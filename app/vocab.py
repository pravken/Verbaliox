"""
The dictionary applied to recognized text, for every speech model.

Whisper also gets the terms as a hint while it decodes (`hotwords`); GigaAM and Parakeet take no hint,
so a term heard wrong ("klot", "клод" for Claude) is put right after recognition:

1. variants: what the user wrote down as "may be recognized as" is replaced by the term exactly;
2. similar sound (setting dictionary_fuzzy): a word, or two or three words written together, that
   sounds like a term is replaced by it. Words are compared by a rough sound key that is the same for
   Latin and Cyrillic spelling ("Claude", "klot", "клод" -> "klat"); short keys must match exactly.
"""

import re
import threading
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

CACHE_SEC = 10.0
MIN_FUZZY_KEY = 4          # a term with a shorter key ("ИИ", "Code") is replaced only by its variants
MAX_WINDOW = 3             # a term heard as up to three words ("Open AI", "кубер нетис")
# Russian endings dropped from a Cyrillic word heard for a Latin term ("в кубернетисе" -> "в Kubernetes")
_RU_ENDINGS = ("ами", "ями", "ом", "ем", "ой", "ей", "ов", "ев", "ах", "ях", "ам", "ям", "а", "я", "у", "ю", "е", "ы")

_CYR = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "o", "ж": "J", "з": "z", "и": "i",
    "й": "i", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t",
    "у": "u", "ф": "f", "х": "h", "ц": "ts", "ч": "C", "ш": "S", "щ": "S", "ъ": "", "ы": "i", "ь": "",
    "э": "e", "ю": "iu", "я": "ia",
}
# English spellings first (longest first), then single letters
_LAT = [
    ("sch", "S"), ("tch", "C"), ("dzh", "J"), ("sh", "S"), ("ch", "C"), ("zh", "J"), ("kh", "h"),
    ("ph", "f"), ("th", "t"), ("ck", "k"), ("qu", "kv"), ("au", "o"), ("aw", "o"), ("ou", "u"),
    ("oo", "u"), ("ee", "i"), ("ea", "i"), ("ie", "i"), ("ey", "i"), ("ay", "ei"),
    ("ce", "se"), ("ci", "si"), ("cy", "si"), ("ge", "Je"), ("gi", "Ji"),
    ("c", "k"), ("q", "k"), ("x", "ks"), ("w", "v"), ("y", "i"), ("j", "J"),
]
# Voiced and voiceless sounds, and e/i, are told apart badly by ear. "o" and "a" stay apart: else
# "клад" would sound like "клод" (Claude)
_FOLD = str.maketrans({"b": "p", "d": "t", "g": "k", "v": "f", "z": "s", "J": "S", "e": "i", "y": "i"})
_WORD_CORE = re.compile(r"^(\W*)(.*?)(\W*)$", re.S)


def _latin(word: str) -> str:
    w = word.lower().replace("ё", "е")
    if any("а" <= ch <= "я" for ch in w):
        w = w.replace("дж", "J")
        return "".join(_CYR.get(ch, ch if ch.isascii() and ch.isalnum() else "") for ch in w)
    w = "".join(ch for ch in w if ch.isascii() and ch.isalnum())
    if len(w) > 3 and w.endswith("e") and w[-2] not in "aeiouy":
        w = w[:-1]  # a silent final e: "Claude", "Kubernete"
    out, i = [], 0
    while i < len(w):
        for src, dst in _LAT:
            if w.startswith(src, i):
                out.append(dst)
                i += len(src)
                break
        else:
            out.append(w[i])
            i += 1
    return "".join(out)


def sound_key(text: str) -> str:
    """A rough sound of a word or phrase, the same for Latin and Cyrillic spelling."""
    s = "".join(_latin(w) for w in text.split()).translate(_FOLD)
    s = s.replace("h", "")  # "Claude" is never "Clhaude", and х/h are dropped by both models alike
    out: List[str] = []
    for ch in s:
        if out and out[-1] == ch:
            continue  # doubled letters: "Verbaliox" / "Вербаллиокс"
        out.append(ch)
    return "".join(out)


def _distance(a: str, b: str, limit: int) -> int:
    """Edit distance, stopping once it is over the limit."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if min(cur) > limit:
            return limit + 1
        prev = cur
    return prev[-1]


def _allowed_edits(key_len: int) -> int:
    return 0 if key_len <= 5 else 1 if key_len <= 9 else 2


def _norm(word: str) -> str:
    return word.lower().replace("ё", "е")


def _is_cyr(s: str) -> bool:
    return any("а" <= ch <= "я" or ch == "ё" for ch in s.lower())


class Rules:
    def __init__(self, items: Sequence[Dict[str, Any]], fuzzy: bool = True):
        self.exact: Dict[Tuple[str, ...], str] = {}
        self.terms: List[Tuple[str, int, str, bool]] = []  # term, its word count, sound key, Latin term
        self.fuzzy = fuzzy
        known = set()
        for it in items:
            term = " ".join(str(it.get("term") or "").split())
            if not term:
                continue
            words = tuple(_norm(w) for w in term.split())
            known.add(words)
            for v in split_variants(it.get("variants") or ""):
                vw = tuple(_norm(w) for w in v.split())
                if vw and vw != words:
                    self.exact[vw] = term
            key = sound_key(term)
            if len(key) >= MIN_FUZZY_KEY:
                self.terms.append((term, len(words), key, not _is_cyr(term)))
        self.known = known
        self.longest = max([len(k) for k in self.exact] + [MAX_WINDOW], default=MAX_WINDOW)

    def __bool__(self) -> bool:
        return bool(self.exact or (self.fuzzy and self.terms))

    def _fuzzy(self, cores: List[str]) -> Optional[str]:
        joined = " ".join(cores)
        # the same for every term: worked out once per window (it was per term, the bulk of the time)
        k = sound_key(joined)
        cyr = _is_cyr(joined)
        stems_of_word: Optional[List[str]] = None  # "кубернетисе" without its Russian ending, made when needed
        for term, n, key, latin_term in self.terms:
            if abs(len(cores) - n) > 1:
                continue
            if len(cores) != n and (len(key) < 6 or min(len(c) for c in cores) < 2):
                continue  # split or joined words only for a long term, and never a preposition ("в", "и")
            # Russian words for a Russian term: only the same sound, so "Максима" stays "Максима"
            # and is not made "Максим"; another script ("Maksim") may differ a little
            limit = 0 if cyr and not latin_term else _allowed_edits(len(key))
            if len(cores) != n:
                limit = max(0, limit - 1)
            if abs(len(k) - len(key)) <= limit and _distance(k, key, limit) <= limit:
                return term
            # "кубернетисе": a Russian ending on a Latin term is dropped
            if latin_term and len(cores) == 1 and cyr:
                if stems_of_word is None:
                    low = _norm(joined)
                    stems_of_word = [sound_key(low[: -len(end)]) for end in _RU_ENDINGS
                                     if low.endswith(end) and len(low) - len(end) >= 3]
                # "Джире": the ending took the place of the term's last vowel
                stems = (key, key[:-1]) if key[-1] in "aiu" else (key,)
                for ks in stems_of_word:
                    if len(ks) >= 3 and any(_distance(ks, k2, limit) <= limit for k2 in stems if len(k2) >= 3):
                        return term
        return None

    def match(self, cores: List[str]) -> Optional[Tuple[int, str]]:
        """(how many words, the term) for the words starting at cores[0], or None."""
        norm = [_norm(c) for c in cores]
        for n in range(min(self.longest, len(norm)), 0, -1):
            term = self.exact.get(tuple(norm[:n]))
            if term:
                return n, term
        if not self.fuzzy or not self.terms:
            return None
        for n in range(min(MAX_WINDOW, len(norm)), 0, -1):
            window = norm[:n]
            if not all(window) or tuple(window) in self.known:
                continue
            # A word that is a term itself is left as it is ("Claude Code" is not "Claude"+"Code")
            if any((w,) in self.known for w in window) and n > 1:
                continue
            term = self._fuzzy(cores[:n])
            if term and _norm(term) != " ".join(window):
                return n, term
        return None


def split_variants(raw: str) -> List[str]:
    return [" ".join(v.split()) for line in str(raw).splitlines() for v in line.split(",") if v.strip()]


def _split(token: str) -> Tuple[str, str, str]:
    m = _WORD_CORE.match(token)
    return m.group(1), m.group(2), m.group(3)


def fix_text(text: str, rules: Optional[Rules]) -> str:
    if not rules or not text:
        return text
    tokens = text.split()
    parts = [_split(t) for t in tokens]
    out: List[str] = []
    i = 0
    changed = False
    while i < len(parts):
        # A phrase does not run over a sentence end or a comma: "...клод. Код..." stays two words
        span = [parts[i][1]]
        for p in parts[i + 1: i + rules.longest]:
            if parts[i + len(span) - 1][2] or p[0]:
                break
            span.append(p[1])
        hit = rules.match(span)
        if hit:
            n, term = hit
            out.append(parts[i][0] + term + parts[i + n - 1][2])
            i += n
            changed = True
        else:
            out.append(tokens[i])
            i += 1
    return " ".join(out) if changed else text


def fix_words(words: List[Dict[str, Any]], rules: Optional[Rules]) -> List[Dict[str, Any]]:
    """The same for the word timings: the words heard for one term become one word."""
    if not rules or not words:
        return words
    parts = [_split((w.get("word") or "").strip()) for w in words]
    out: List[Dict[str, Any]] = []
    i = 0
    while i < len(words):
        span = [parts[i][1]]
        for p in parts[i + 1: i + rules.longest]:
            if parts[i + len(span) - 1][2] or p[0]:
                break
            span.append(p[1])
        hit = rules.match(span)
        if hit:
            n, term = hit
            first, last = words[i], words[i + n - 1]
            lead = (first.get("word") or "")[: len(first.get("word") or "") - len((first.get("word") or "").lstrip())]
            merged = {**first, "end": last.get("end", first.get("end")),
                      "word": lead + parts[i][0] + term + parts[i + n - 1][2]}
            probs = [w.get("prob") for w in words[i:i + n] if isinstance(w.get("prob"), (int, float))]
            if probs:
                merged["prob"] = min(probs)
            out.append(merged)
            i += n
        else:
            out.append(words[i])
            i += 1
    return out


def fix_segments(segments: List[Dict[str, Any]], rules: Optional[Rules] = None) -> List[Dict[str, Any]]:
    rules = current() if rules is None else rules
    if not rules:
        return segments
    for seg in segments:
        seg["text"] = fix_text(seg.get("text") or "", rules)
        if seg.get("words"):
            seg["words"] = fix_words(seg["words"], rules)
    return segments


_cache: Dict[str, Any] = {"at": 0.0, "rules": None, "hotwords": ""}
_lock = threading.Lock()


def invalidate() -> None:
    with _lock:
        _cache["at"] = 0.0


def _load() -> None:
    from app.database import get_all_settings, list_dictionary

    items = list_dictionary(active_only=True)
    fuzzy = (get_all_settings().get("dictionary_fuzzy") or "true").lower() == "true"
    _cache.update(at=time.time(), rules=Rules(items, fuzzy=fuzzy),
                  hotwords=", ".join(it["term"] for it in items))


def current() -> Optional[Rules]:
    """The active dictionary, read again at most every CACHE_SEC (captions ask for it every window)."""
    with _lock:
        if time.time() - _cache["at"] > CACHE_SEC:
            try:
                _load()
            except Exception as e:  # the dictionary must never stop recognition
                print(f"[vocab] dictionary not loaded: {e}", flush=True)
                _cache.update(at=time.time(), rules=None, hotwords="")
        return _cache["rules"]


def hotwords() -> str:
    current()
    return _cache["hotwords"]
