"""
The transcript Teams makes of a meeting (Download → .vtt), imported into a recording: a transcript
version of its own («Субтитры Teams»), and the names it gives each line name the voices.

The captions read during a recording (app/teams_captions.py) depend on the caption panel being open and
on the layout of Teams; the downloaded transcript has every line with its speaker and its exact time.
Its lines look like:

    00:00:03.120 --> 00:00:07.840
    <v Анна Петрова>Добрый день, начнём.</v>

(older files: «Анна Петрова: Добрый день» without the <v> tag; a cue id may come before the times).
"""

import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

_TIME = r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})"
_CUE_RE = re.compile(rf"^\s*{_TIME}\s*-->\s*{_TIME}")
_VOICE_RE = re.compile(r"<v(?:\.[^ >]*)?\s+([^>]+)>(.*?)(?:</v>|$)", re.S)
_TAG_RE = re.compile(r"</?[^>]+>")
_NAME_PREFIX_RE = re.compile(r"^([^:]{2,60}):\s+(.+)$", re.S)
MAX_BYTES = 20 * 1024 * 1024


def _seconds(h: Optional[str], m: str, s: str, frac: str) -> float:
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(frac.ljust(3, "0")[:3]) / 1000.0


def parse_vtt(text: str) -> List[Dict[str, Any]]:
    """Cues as {"start", "end", "name", "text"}, in order; lines without a speaker keep name ""."""
    cues: List[Dict[str, Any]] = []
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    i = 0
    while i < len(lines):
        m = _CUE_RE.match(lines[i])
        if not m:
            i += 1
            continue
        g = m.groups()
        start, end = _seconds(*g[0:4]), _seconds(*g[4:8])
        i += 1
        body: List[str] = []
        while i < len(lines) and lines[i].strip():
            body.append(lines[i])
            i += 1
        raw = "\n".join(body).strip()
        if not raw:
            continue
        name, said = "", raw
        voices = _VOICE_RE.findall(raw)
        if voices:
            name = voices[0][0].strip()
            said = " ".join(v[1] for v in voices)
        said = " ".join(_TAG_RE.sub("", said).split())
        if not name:
            p = _NAME_PREFIX_RE.match(said)
            if p:
                name, said = p.group(1).strip(), p.group(2).strip()
        if said:
            cues.append({"start": start, "end": max(end, start + 0.2), "name": name[:80], "text": said})
    cues.sort(key=lambda c: c["start"])
    return cues


def as_version(cues: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The cues as a transcript version: each a phrase of its speaker, its words spread over its time."""
    if not cues:
        return None
    try:
        from app.diarizer import SPEAKER_COLORS
    except Exception:
        SPEAKER_COLORS = ["#0A84FF"]
    ids: Dict[str, str] = {}
    speakers: Dict[str, Dict[str, Any]] = {}
    segments: List[Dict[str, Any]] = []
    for i, c in enumerate(cues):
        name = c["name"] or "Teams"
        if name not in ids:
            sid = f"SPEAKER_{len(ids):02d}"
            ids[name] = sid
            speakers[sid] = {"id": sid, "name": name, "color": SPEAKER_COLORS[(len(ids) - 1) % len(SPEAKER_COLORS)]}
        words = c["text"].split()
        step = (c["end"] - c["start"]) / max(1, len(words))
        segments.append({"id": i, "start": round(c["start"], 2), "end": round(c["end"], 2), "speaker": ids[name],
                         "text": c["text"],
                         "words": [{"word": " " + w, "start": round(c["start"] + k * step, 2),
                                    "end": round(c["start"] + (k + 1) * step, 2), "prob": 1.0} for k, w in enumerate(words)]})
    return {"segments": segments, "speakers": speakers, "language": "", "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}


def import_into(meeting_id: int, text: str) -> Tuple[int, int]:
    """Files the transcript as the «Субтитры Teams» version and names the voices of the recording's
    transcript by it (only voices still named «Участник N»: a name the user gave stays). (lines, voices
    named)."""
    from app import database
    from app.teams_captions import TEAMS
    from app.transcriber import apply_speaker_marks
    from app.voice_profiles import is_default_name

    cues = parse_vtt(text)
    version = as_version(cues)
    if not version:
        raise ValueError("В файле нет реплик расшифровки Teams (нужен файл .vtt из «Скачать расшифровку»)")
    database.save_transcript_version(meeting_id, TEAMS, version)
    marks = [{"at": c["start"], "name": c["name"], "text": c["text"]} for c in cues if c["name"]]
    m = database.get_meeting(meeting_id) or {}
    kept = [mk for mk in m.get("speaker_marks") or [] if not mk.get("text")]  # the studio's own clicks stay
    database.set_speaker_marks(meeting_id, kept + marks)
    named = [0]

    def rename(meeting: Dict[str, Any]):
        speakers = meeting.get("speakers") or {}
        if not speakers or not meeting.get("segments"):
            return ()
        trial = {k: dict(v) for k, v in speakers.items()}
        apply_speaker_marks(trial, meeting["segments"], marks)
        taken = {str(v.get("name") or "").strip().lower() for v in speakers.values() if not is_default_name(str(v.get("name") or ""))}
        for sid, v in trial.items():
            new = str(v.get("name") or "").strip()
            if new and new != speakers[sid].get("name") and is_default_name(str(speakers[sid].get("name") or "")) \
                    and new.lower() not in taken:
                speakers[sid]["name"] = new
                taken.add(new.lower())
                named[0] += 1
        return ("speakers",) if named[0] else ()

    database.edit_meeting(meeting_id, rename)
    print(f"[teams] transcript imported into meeting {meeting_id}: {len(cues)} line(s), {named[0]} voice(s) named", flush=True)
    return len(cues), named[0]
