"""The speakers named in the analysis of a recording, kept as references to them.

The analysis (overview, chapters, templates...) is stored with a marker in place of each name of a speaker
of the recording: ⟦spk:SPEAKER_01|Анна⟧ (the speaker's id and its name when the text was written, used only
when the speaker is gone). A reading of the recording (app/database.get_meeting) shows each marker as the
speaker's current name, so a rename reaches the analysis, also after the speakers were merged or split
anew: the markers of a speaker that went over to another follow it (carry_ids).

The model writes names, not markers: a local model copies an unusual token badly (drops a bracket, declines
or translates it), and the text it writes is checked against the transcript by name (app/grounding.py).
The names are turned into markers when the text is saved (mark_text): only a speaker's name written in
full, as it is spelled; the declined forms («Анны») stay text and follow a rename the older way
(app/people.rename_in_text).
"""
import bisect
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

MARK_RE = re.compile(r"⟦spk:([^|⟦⟧\s]{1,64})\|([^⟦⟧\n]{0,160})⟧")
_PREFIX = "⟦spk:"
_CAP_WORD = re.compile(r"[A-ZА-ЯЁ][a-zа-яё]")
_CAP_BEFORE = re.compile(r"(?<![\w-])[A-ZА-ЯЁ][a-zа-яё-]+[ \t]+$")
MIN_NAME = 3  # «Я» of a dictation, «Ян»: too short to tell a name from a word


def has_marks(text: Any) -> bool:
    return isinstance(text, str) and _PREFIX in text


def speaker_name(speakers: Dict[str, Any], sid: str) -> str:
    meta = speakers.get(sid) if isinstance(speakers, dict) else None
    if isinstance(meta, dict):
        return " ".join(str(meta.get("name") or "").split())
    return ""


def mark(sid: str, name: str) -> str:
    safe = re.sub(r"[⟦⟧|\n]", " ", " ".join(str(name or "").split()))[:160].strip()
    return f"{_PREFIX}{sid}|{safe}⟧"


def resolve_text(text: str, speakers: Dict[str, Any]) -> str:
    """The markers of a text as the current names of their speakers (the name they had when the text was
    written, for a speaker the recording no longer has)."""
    if not has_marks(text):
        return text
    return MARK_RE.sub(lambda m: speaker_name(speakers, m.group(1)) or m.group(2), text)


def resolve(summaries: Dict[str, Any], speakers: Dict[str, Any]) -> Dict[str, Any]:
    """The analysis of a recording (key → text) with names in place of the markers."""
    if not isinstance(summaries, dict):
        return summaries
    return {k: resolve_text(v, speakers) if isinstance(v, str) else v for k, v in summaries.items()}


def resolve_raw(summaries_json: Optional[str], speakers_json: Optional[str]) -> Dict[str, Any]:
    """resolve for the stored JSON of both (a reading without get_meeting)."""
    import json

    def load(raw: Optional[str]) -> Dict[str, Any]:
        try:
            v = json.loads(raw or "{}")
        except (TypeError, ValueError):
            return {}
        return v if isinstance(v, dict) else {}

    sums = load(summaries_json)
    if not any(has_marks(v) for v in sums.values()):
        return sums
    return resolve(sums, load(speakers_json))


def _names(speakers: Dict[str, Any]) -> Dict[str, str]:
    """name → id of the speakers whose name is one of theirs alone and long enough to be told from a word."""
    seen: Dict[str, List[str]] = {}
    for sid, meta in (speakers.items() if isinstance(speakers, dict) else ()):
        if not isinstance(meta, dict) or MARK_RE.fullmatch(mark(sid, "")) is None:
            continue
        name = speaker_name(speakers, sid)
        if len(name) >= MIN_NAME and not re.search(r"[⟦⟧|]", name):
            seen.setdefault(name, []).append(sid)
    return {n: ids[0] for n, ids in seen.items() if len(ids) == 1}


def _split_marks(text: str) -> List[Tuple[bool, str]]:
    """The text in pieces: (True, a marker) and (False, the text between them)."""
    out, pos = [], 0
    for m in MARK_RE.finditer(text):
        if m.start() > pos:
            out.append((False, text[pos:m.start()]))
        out.append((True, m.group(0)))
        pos = m.end()
    if pos < len(text):
        out.append((False, text[pos:]))
    return out


def mark_text(text: str, speakers: Dict[str, Any]) -> str:
    """The names of the speakers in a text as markers. A name written in full and spelled as the speaker's;
    a one-word name next to another capitalized word («Анна Петрова» for the speaker «Анна») is someone's
    full name and stays text. The markers there are stay as they are."""
    if not isinstance(text, str) or not text:
        return text
    names = _names(speakers)
    if not names:
        return text
    words = sorted(names, key=len, reverse=True)
    pat = re.compile(r"(?<![\w-])(" + "|".join(re.escape(n).replace(r"\ ", r"[ \t ]+") for n in words) + r")(?![\w-])")

    def piece(chunk: str) -> str:
        def one(m: "re.Match") -> str:
            found = m.group(1)
            key = " ".join(found.split())
            sid = names.get(key)
            if not sid:
                return found
            if " " not in key:
                after = chunk[m.end():m.end() + 40]
                if re.match(r"[ \t]+", after) and _CAP_WORD.match(after.lstrip(" \t")):
                    return found
                if _CAP_BEFORE.search(chunk[max(0, m.start() - 40):m.start()]):
                    return found
            return mark(sid, key)

        return pat.sub(one, chunk)

    return "".join(p if is_mark else piece(p) for is_mark, p in _split_marks(text))


def mark_summaries(updates: Dict[str, Any], speakers: Dict[str, Any]) -> Dict[str, Any]:
    """mark_text for every section of an analysis but its error."""
    return {k: mark_text(v, speakers) if isinstance(v, str) and k != "error" else v for k, v in (updates or {}).items()}


def marked_ids(summaries: Dict[str, Any]) -> set:
    return {m.group(1) for v in (summaries or {}).values() if has_marks(v) for m in MARK_RE.finditer(v)}


def _spans(segments: Iterable[Dict[str, Any]]) -> List[Tuple[float, float, str]]:
    out = []
    for s in segments or []:
        if not isinstance(s, dict):
            continue
        try:
            a, b = float(s.get("start") or 0), float(s.get("end") or 0)
        except (TypeError, ValueError):
            continue
        if b > a and s.get("speaker"):
            out.append((a, b, str(s["speaker"])))
    return out


def assignment(segments: Iterable[Dict[str, Any]]) -> List[Tuple[float, float, str]]:
    """Who says each line, to tell whether an edit of a transcript moved lines between speakers."""
    return _spans(segments)


def carry_ids(old_segments: List[Dict[str, Any]], old_speakers: Dict[str, Any],
              new_segments: List[Dict[str, Any]], new_speakers: Dict[str, Any],
              ids: Optional[Iterable[str]] = None, named_by_time: bool = True) -> Dict[str, Optional[str]]:
    """Which speaker of the new split each earlier speaker is: the one with the same given name, when one
    speaker alone has it; else the one sharing more than half of the earlier speaker's time; None when
    there is none (it is written as its name then). ids: the earlier speakers asked about (all by default).
    named_by_time=False: a speaker with a given name is found by that name only (a new split that did not
    give the name to any voice: the name stays rather than become «Участник N»)."""
    from app.voice_profiles import is_default_name

    wanted = list(ids) if ids is not None else list(old_speakers or {})
    out: Dict[str, Optional[str]] = {}
    by_name: Dict[str, List[str]] = {}
    for sid in new_speakers or {}:
        n = speaker_name(new_speakers, sid).casefold()
        if n:
            by_name.setdefault(n, []).append(sid)
    new = sorted(_spans(new_segments))
    starts = [s[0] for s in new]
    longest = max((b - a for a, b, _ in new), default=0.0)
    old = _spans(old_segments)
    for sid in wanted:
        name = speaker_name(old_speakers, sid)
        same = by_name.get(name.casefold(), []) if name and not is_default_name(name) else []
        if len(same) == 1:
            out[sid] = same[0]
            continue
        if not named_by_time and name and not is_default_name(name):
            out[sid] = None
            continue
        total, shared = 0.0, {}
        for a, b, who in old:
            if who != sid:
                continue
            total += b - a
            i = bisect.bisect_left(starts, b)
            while i > 0:
                i -= 1
                na, nb, nwho = new[i]
                if na < a - longest:
                    break
                ov = min(b, nb) - max(a, na)
                if ov > 0:
                    shared[nwho] = shared.get(nwho, 0.0) + ov
        best = max(shared.items(), key=lambda kv: kv[1], default=None)
        out[sid] = best[0] if best and total > 0 and best[1] > total / 2 and best[0] in (new_speakers or {}) else None
    return out


def remap_text(text: str, mapping: Dict[str, Optional[str]], old_speakers: Dict[str, Any],
               new_speakers: Dict[str, Any]) -> str:
    """The markers of the speakers in mapping pointed at their new speakers, or written as the name they
    had, when there is none. The others stay."""
    if not has_marks(text):
        return text

    def one(m: "re.Match") -> str:
        sid = m.group(1)
        if sid not in mapping:
            return m.group(0)
        to = mapping[sid]
        if to:
            return mark(to, speaker_name(new_speakers, to) or speaker_name(old_speakers, sid) or m.group(2))
        return speaker_name(old_speakers, sid) or m.group(2)

    return MARK_RE.sub(one, text)


def remap_summaries(summaries: Dict[str, Any], mapping: Dict[str, Optional[str]], old_speakers: Dict[str, Any],
                    new_speakers: Dict[str, Any]) -> Dict[str, Any]:
    """The sections remap_text changed (key → text)."""
    out = {}
    for k, v in (summaries or {}).items():
        if has_marks(v):
            new = remap_text(v, mapping, old_speakers, new_speakers)
            if new != v:
                out[k] = new
    return out


def carry(summaries: Dict[str, Any], old_segments: List[Dict[str, Any]], old_speakers: Dict[str, Any],
          new_segments: List[Dict[str, Any]], new_speakers: Dict[str, Any], every: bool) -> Dict[str, Any]:
    """The sections of an analysis with their markers carried over to the speakers after a change of them:
    every=True for a new split (each speaker found anew, its id may now be someone else's; a given name only
    by that name); else only the speakers the recording no longer has (a merge: they went over to the
    speaker that has their time now). Returns the sections changed."""
    ids = marked_ids(summaries)
    if not every:
        ids = {i for i in ids if i not in (new_speakers or {})}
    if not ids:
        return {}
    mapping = carry_ids(old_segments, old_speakers, new_segments, new_speakers, ids, named_by_time=not every)
    return remap_summaries(summaries, mapping, old_speakers, new_speakers)


def name_changes(old_segments: List[Dict[str, Any]], old_speakers: Dict[str, Any],
                 new_segments: List[Dict[str, Any]], new_speakers: Dict[str, Any]) -> Dict[str, str]:
    """old name → new name of the speakers found again in a new split under another name («Участник 2» is
    «Участник 3» now), for what keeps names as text (the tasks of the recording)."""
    out: Dict[str, str] = {}
    for sid, to in carry_ids(old_segments, old_speakers, new_segments, new_speakers, named_by_time=False).items():
        old, new = speaker_name(old_speakers, sid), speaker_name(new_speakers, to) if to else ""
        if old and new and old != new:
            out[old] = new
    return out
