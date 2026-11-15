"""
Hand corrections of a recording's analysis, and the dictionary learning from them.

- `replace_word`: «Кубернетис» → «Kubernetes» in every analysis section of a recording (whole words only);
- `word_changes`: after a section was edited by hand, the words that were replaced by others (a typo,
  a term written wrong) — offered to the user for the dictionary;
- `learn`: the right spelling becomes a dictionary term and the wrong one its variant, so recognition
  writes it right next time and the next analysis does too;
- `fix_with_dictionary`: what an analysis model writes goes through the dictionary's variants
  (only the exact ones: the sound-alike guess is for recognition, not for a model's text).
"""

import difflib
import json
import re
from typing import Any, Dict, List, Optional, Tuple

PHRASE_MAX_WORDS = 4
CHANGES_MAX = 12
_WORD = re.compile(r"[\w][\w'’\-+.#]*[\w+#]|\w", re.U)


def _boundary(text: str) -> str:
    """A regex for the text as a whole word or phrase (spaces may differ)."""
    parts = [re.escape(p) for p in text.split()]
    return r"(?<![\w-])" + r"\s+".join(parts) + r"(?![\w-])"


def _cased(sample: str, right: str) -> str:
    """The right word in the case of the one it replaces: «кубер»→«Kubernetes» stays as typed; an
    upper-cased first letter of a sentence is kept."""
    if sample[:1].isupper() and right[:1].islower():
        return right[:1].upper() + right[1:]
    return right


def replace_word(text: str, wrong: str, right: str) -> Tuple[str, int]:
    """Every whole-word «wrong» in the text (case aside) is «right». Returns (text, how many)."""
    wrong, right = " ".join(str(wrong).split()), " ".join(str(right).split())
    if not text or not wrong or not right or wrong == right:
        return text, 0
    rx = re.compile(_boundary(wrong), re.I | re.U)
    count = 0

    def sub(m: "re.Match[str]") -> str:
        nonlocal count
        count += 1
        found = m.group(0)
        # the word as written (case aside) is the one asked: a different case of the same word keeps
        # the user's spelling, only a sentence start gets its capital
        return right if found == wrong else _cased(found, right)

    return rx.sub(sub, text), count


def _replace_in_value(value: Any, wrong: str, right: str) -> Tuple[Any, int]:
    """A section is Markdown, or JSON (the chapters): in JSON only the texts change, not the keys."""
    if isinstance(value, str):
        s = value.strip()
        if s[:1] in "[{":
            try:
                data = json.loads(s)
            except ValueError:
                data = None
            if data is not None:
                new, n = _replace_in_json(data, wrong, right)
                return (json.dumps(new, ensure_ascii=False), n) if n else (value, 0)
        return replace_word(value, wrong, right)
    return value, 0


def _replace_in_json(data: Any, wrong: str, right: str) -> Tuple[Any, int]:
    if isinstance(data, str):
        return replace_word(data, wrong, right)
    if isinstance(data, list):
        total, out = 0, []
        for x in data:
            y, n = _replace_in_json(x, wrong, right)
            out.append(y)
            total += n
        return out, total
    if isinstance(data, dict):
        total, out = 0, {}
        for k, x in data.items():
            y, n = _replace_in_json(x, wrong, right)
            out[k] = y
            total += n
        return out, total
    return data, 0


def replace_in_summaries(summaries: Dict[str, Any], wrong: str, right: str,
                         keys: Optional[List[str]] = None) -> Tuple[Dict[str, Any], int]:
    """The changed sections only ({key: new text}) and how many words changed."""
    changed: Dict[str, Any] = {}
    total = 0
    for key, value in (summaries or {}).items():
        if key == "error" or (keys and key not in keys):
            continue
        new, n = _replace_in_value(value, wrong, right)
        if n:
            changed[key] = new
            total += n
    return changed, total


def _words(text: str) -> List[str]:
    return _WORD.findall(str(text or ""))


def _has_letters(s: str) -> bool:
    return any(ch.isalpha() for ch in s)


def word_changes(old: str, new: str) -> List[Dict[str, str]]:
    """The words a hand edit replaced by others: [{"wrong": "кубернетис", "right": "Kubernetes"}].
    A rewritten sentence is not a typo: only short replacements (up to 4 words each side) count."""
    a, b = _words(old), _words(new)
    out: List[Dict[str, str]] = []
    seen = set()
    sm = difflib.SequenceMatcher(a=[w.casefold() for w in a], b=[w.casefold() for w in b], autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "replace":
            continue
        if not (1 <= i2 - i1 <= PHRASE_MAX_WORDS and 1 <= j2 - j1 <= PHRASE_MAX_WORDS):
            continue
        wrong, right = " ".join(a[i1:i2]), " ".join(b[j1:j2])
        if not (_has_letters(wrong) and _has_letters(right)) or wrong.casefold() == right.casefold():
            continue
        # «обсудили» → «согласовали» is a reworded thought, not a word heard wrong: the two must look
        # alike, or the right one must be a name or a term (Latin letters, a capital not of a sentence start)
        alike = difflib.SequenceMatcher(a=wrong.casefold(), b=right.casefold()).ratio() >= 0.5
        termish = (any("a" <= ch.lower() <= "z" for ch in right) or any(ch.isupper() for ch in right[1:])
                   or (right[:1].isupper() and not wrong[:1].isupper()))
        if not (alike or termish):
            continue
        key = (wrong.casefold(), right)
        if key in seen:
            continue
        seen.add(key)
        out.append({"wrong": wrong, "right": right})
        if len(out) >= CHANGES_MAX:
            break
    return out


def learn(pairs: List[Dict[str, str]]) -> List[str]:
    """Each right spelling becomes a term (or stays one) with the wrong one added to its variants.
    Returns the terms learned."""
    from app.database import add_dictionary_term, list_dictionary
    from app.vocab import invalidate, split_variants

    known = {str(d.get("term") or "").casefold(): d for d in list_dictionary(active_only=False)}
    learned: List[str] = []
    for p in pairs or []:
        wrong = " ".join(str(p.get("wrong") or "").split())
        right = " ".join(str(p.get("right") or "").split())
        if not wrong or not right or wrong.casefold() == right.casefold():
            continue
        if len(right.split()) > PHRASE_MAX_WORDS or len(wrong.split()) > PHRASE_MAX_WORDS:
            continue
        have = known.get(right.casefold())
        variants = split_variants((have or {}).get("variants") or "")
        if wrong.casefold() not in {v.casefold() for v in variants}:
            variants.append(wrong)
        term = (have or {}).get("term") or right
        item = add_dictionary_term(term, (have or {}).get("category") or "Термин", ", ".join(variants))
        known[right.casefold()] = item
        learned.append(term)
    if learned:
        invalidate()
    return learned


def fix_with_dictionary(text: str) -> str:
    """An analysis model's answer with the dictionary's exact variants put right, line by line (the
    Markdown keeps its lines and indents)."""
    if not text:
        return text
    try:
        from app.database import list_dictionary
        from app.vocab import Rules, fix_text

        rules = Rules(list_dictionary(active_only=True), fuzzy=False)
    except Exception as e:  # the dictionary must never stop an analysis
        print(f"[analysis_edits] dictionary not applied: {e}", flush=True)
        return text
    if not rules:
        return text
    out = []
    for line in text.split("\n"):
        body = line.lstrip()
        fixed = fix_text(body, rules) if body else body
        out.append(line[: len(line) - len(body)] + fixed if fixed != body else line)
    return "\n".join(out)
