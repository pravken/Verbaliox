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
    if sample[:1].isupper() and right == right.lower():  # «iPhone», «macOS» keep their own case
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
    A rewritten sentence is not a typo: only short replacements (up to 4 words each side) count. The lines
    are compared first and only the changed ones word by word (a long section diffed word by word at once
    took seconds: found by an audit)."""
    out: List[Dict[str, str]] = []
    seen = set()
    old_lines, new_lines = str(old or "").splitlines(), str(new or "").splitlines()
    by_line = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
    for tag, i1, i2, j1, j2 in by_line.get_opcodes():
        if tag != "replace":
            continue
        a, b = _words("\n".join(old_lines[i1:i2])), _words("\n".join(new_lines[j1:j2]))
        sm = difflib.SequenceMatcher(a=[w.casefold() for w in a], b=[w.casefold() for w in b], autojunk=False)
        for wtag, x1, x2, y1, y2 in sm.get_opcodes():
            if wtag != "replace":
                continue
            if not (1 <= x2 - x1 <= PHRASE_MAX_WORDS and 1 <= y2 - y1 <= PHRASE_MAX_WORDS):
                continue
            wrong, right = " ".join(a[x1:x2]), " ".join(b[y1:y2])
            if not (_has_letters(wrong) and _has_letters(right)) or wrong.casefold() == right.casefold():
                continue
            # «обсудили» → «согласовали» is a reworded thought, not a word heard wrong: the two must look
            # alike, or the right one must be a name or a term (Latin letters, a capital not of a sentence start)
            alike = difflib.SequenceMatcher(a=wrong.casefold(), b=right.casefold()).ratio() >= 0.5
            termish = (any("a" <= ch.lower() <= "z" for ch in right) or any(ch.isupper() for ch in right[1:])
                       or (right[:1].isupper() and not wrong[:1].isupper()))
            if not (alike or termish) or not learnable(wrong):
                continue
            key = (wrong.casefold(), right)
            if key in seen:
                continue
            seen.add(key)
            # «принял» → «приняли» is grammar, not a word heard wrong: offered, but not ticked (an exact
            # variant would change every «принял» after it); a term or a name is ticked
            out.append({"wrong": wrong, "right": right, "sure": termish})
            if len(out) >= CHANGES_MAX:
                return out
    return out


_SPEAKER_LABEL = re.compile(r"^(участник|speaker|спикер|говорящий)[ _]?\d+$|^speaker_\d+$", re.I)


def learnable(wrong: str) -> bool:
    """Whether a wrong spelling may become a dictionary variant: not a speaker's label («Участник 2» renamed
    by hand would rename someone else in the next meeting), no digits, no comma (variants are comma
    separated: «Ромашка, Москва» would make «Москва» one on its own). Found by the audits."""
    w = " ".join(str(wrong or "").split())
    return bool(w) and not _SPEAKER_LABEL.match(w) and not any(ch.isdigit() for ch in w) and "," not in w and ";" not in w


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
        if not learnable(wrong):
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
        body = line.strip()
        fixed = fix_text(body, rules) if body else body
        if fixed == body:
            out.append(line)
            continue
        lead, tail = line[: len(line) - len(line.lstrip())], line[len(line.rstrip()):]
        out.append(lead + fixed + tail)  # a Markdown line break («  » at the end) stays
    return "\n".join(out)


# ---------------------------------------------------------------- doubtful words of the analysis
UNSURE_PROB = 0.45  # a word Whisper heard with less certainty than this is doubtful
SUSPECTS_MAX = 60
CHECK_TEXT_MAX = 6000
CHECK_MAX = 20


def analysis_text(meeting: Dict[str, Any]) -> str:
    """The text of the analysis sections (Markdown ones; the chapters are a list with times)."""
    out = []
    for key, value in (meeting.get("summaries") or {}).items():
        if key in ("error", "chapters") or not isinstance(value, str) or not value.strip():
            continue
        out.append(value)
    return "\n\n".join(out)


def _found(text: str, word: str) -> bool:
    return bool(word) and re.search(_boundary(word), text, re.I | re.U) is not None


def _clean_word(text: str) -> str:
    return re.sub(r"^[^\w]+|[^\w]+$", "", " ".join(str(text or "").split()), flags=re.U)


def suspects(meeting: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The words of the analysis the recognition was not sure of: a place the models of a merged
    transcript heard differently (with what the others heard) or a word Whisper was unsure of.
    [{"word": "кубер", "options": ["Kubernetes"], "source": "dispute"|"unsure", "start": 12.3}]"""
    text = analysis_text(meeting)
    if not text:
        return []
    out: List[Dict[str, Any]] = []
    seen = set()
    # the analysis's words once: a word not among them is not searched for (a regex per unsure word over the
    # whole analysis took seconds on a long recording: found by the audits)
    vocabulary = {w.casefold() for w in _WORD.findall(text)}

    def add(word: str, options: List[str], source: str, start: Any) -> None:
        word = _clean_word(word)
        key = word.casefold()
        if not word or key in seen:
            return
        seen.add(key)  # a miss too: the same word is not looked for again
        if not _has_letters(word) or any(w.casefold() not in vocabulary for w in _WORD.findall(word)) \
                or not _found(text, word):
            return
        opts = []
        for o in options:
            o = _clean_word(o)
            if o and o.casefold() != key and o not in opts:
                opts.append(o)
        out.append({"word": word, "options": opts[:4], "source": source, "start": float(start or 0)})

    # A word Whisper was surely sure of elsewhere in the recording is not doubtful in one place: «проект»
    # heard unsurely once was underlined everywhere (found by an audit)
    sure = set()
    for seg in meeting.get("segments") or []:
        for w in seg.get("words") or []:
            if isinstance(w.get("prob"), (int, float)) and w["prob"] >= 0.8 and not w.get("alts"):
                sure.add(_clean_word(w.get("word")).casefold())

    for seg in meeting.get("segments") or []:
        words = seg.get("words") or []
        for i, w in enumerate(words):
            if len(out) >= SUSPECTS_MAX:
                return out
            if w.get("alts"):
                span = max(1, int(w.get("span") or 1))
                shown = " ".join(str(x.get("word") or "").strip() for x in words[i:i + span])
                add(shown, [a.get("text") or "" for a in w["alts"]], "dispute", w.get("start"))
            elif isinstance(w.get("prob"), (int, float)) and w["prob"] < UNSURE_PROB:
                word = _clean_word(w.get("word"))
                if sum(ch.isalpha() for ch in word) >= 3 and word.casefold() not in sure:
                    add(word, [], "unsure", w.get("start"))
    return out


_CHECK_SYSTEM = (
    "Ты корректор. Тебе дан текст анализа встречи, составленный по автоматической расшифровке речи. "
    "Распознавание речи иногда пишет слова неверно: искажает термины, названия продуктов и сервисов, имена "
    "и фамилии, склеивает или разрывает слова. Найди в тексте только такие слова и опечатки. Не меняй стиль, "
    "формулировки, падежи и порядок слов; обычные правильные слова не трогай. Пиши правильное написание так, "
    "как его пишут в работе (латиницей для продуктов и сервисов, если так принято). "
    "Ответь только JSON-массивом без пояснений вокруг: "
    '[{"wrong": "как написано в тексте", "right": "как правильно", "reason": "коротко, почему"}]. '
    "Если исправлять нечего, ответь []."
)


def _parse_check(answer: str, text: str) -> List[Dict[str, str]]:
    raw = str(answer or "")
    a, b = raw.find("["), raw.rfind("]")
    if a < 0 or b <= a:
        return []
    try:
        items = json.loads(raw[a:b + 1])
    except ValueError:
        return []
    out: List[Dict[str, str]] = []
    seen = set()
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        wrong, right = _clean_word(it.get("wrong")), _clean_word(it.get("right"))
        if not wrong or not right or wrong.casefold() == right.casefold() or wrong.casefold() in seen:
            continue
        if len(wrong.split()) > PHRASE_MAX_WORDS or len(right.split()) > PHRASE_MAX_WORDS or not _found(text, wrong):
            continue  # a word the text does not have is the model's invention
        seen.add(wrong.casefold())
        out.append({"wrong": wrong, "right": right, "reason": " ".join(str(it.get("reason") or "").split())[:160]})
        if len(out) >= CHECK_MAX:
            break
    return out


def check_with_model(meeting: Dict[str, Any], local_only: bool = False) -> List[Dict[str, str]]:
    """A small model reads the analysis for words heard wrong. Uses the small installed model of live
    translation when the analysis runs locally (seconds instead of a minute), else the analysis model."""
    from app import llm

    text = analysis_text(meeting)[:CHECK_TEXT_MAX]
    if not text.strip():
        return []
    model = None
    if not llm.uses_cloud() or local_only:
        try:
            from app.live_translate import model_choices

            model = model_choices().get("fast")
        except Exception:
            model = None
    tgt = llm.target(model, local_only=local_only)
    parts = []
    try:
        from app.people import meeting_roster

        names = meeting_roster(meeting)
        if names:
            parts.append("Участники встречи (так пишутся их имена):\n" + "\n".join(f"- {n}" for n in names[:40]))
    except Exception:
        pass
    try:
        from app.database import list_dictionary

        terms = [d["term"] for d in list_dictionary(active_only=True)][:120]
        if terms:
            parts.append("Термины из словаря пользователя (пишутся именно так): " + ", ".join(terms))
    except Exception:
        pass
    parts.append(f"Текст:\n```\n{text}\n```")
    answer = tgt.chat(_CHECK_SYSTEM, "\n\n".join(parts), short=True)
    return _parse_check(answer, text)
