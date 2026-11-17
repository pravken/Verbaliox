"""
The people directory ("Все люди"): everyone the library knows of — the named speakers of the
recordings, the people invited to the calendar meetings the recordings were made in, the ones
promises name — and the people and departments added by hand.

Two spellings of one person can be merged: the first name stays, the others become its variants
(aliases), so a later recording, an invitation or a promise with a variant still finds the person.
"Это я" marks the user (one person at most). A person may have a role ("руководитель проекта").
Who the user is lives in the setting my_name (names separated by commas), which the home page and
the tasks read too; the directory's own mark is only a fallback for databases from before it.

Only the hand-made part is stored (table people_directory: added entries, variants, roles, "me");
the rest is read from the library each time, so it never goes stale.
"""

import base64
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.database import _db_lock, get_all_settings, get_connection, update_settings

KINDS = ("person", "dept")
PHOTO_MAX_BYTES = 600_000  # the page sends a 256 px square (a few tens of KB)
MAX_NAME = 120
# The calendar's participants of a recording, as app/calendar_ics.apply_to_recording writes them
_CAL_HEAD_RE = re.compile(r"^(?:Участники по календарю|Participants \(calendar\))\s*:\s*(.+)$", re.M)


def my_names() -> List[str]:
    """The user's names from the setting my_name, lower case."""
    return [n.strip().lower() for n in str(get_all_settings().get("my_name") or "").split(",") if n.strip()]


def _set_me(name: str, on: bool) -> None:
    """"Это я" for name: it becomes the user's name, or stops being one of them."""
    names = [n.strip() for n in str(get_all_settings().get("my_name") or "").split(",") if n.strip()]
    if on:
        update_settings({"my_name": name})
    elif any(n.lower() == name.lower() for n in names):
        update_settings({"my_name": ", ".join(n for n in names if n.lower() != name.lower())})


def init_table() -> None:
    with _db_lock:
        conn = get_connection()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS people_directory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                kind TEXT NOT NULL DEFAULT 'person',
                role TEXT NOT NULL DEFAULT '',
                aliases TEXT NOT NULL DEFAULT '[]',
                is_me INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
        conn.close()


def _clean(name: Any) -> str:
    return re.sub(r"\s+", " ", str(name or "")).strip()[:MAX_NAME]


def _rows() -> List[Dict[str, Any]]:
    init_table()
    with _db_lock:
        conn = get_connection()
        rows = conn.execute("SELECT * FROM people_directory ORDER BY id").fetchall()
        conn.close()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["aliases"] = [a for a in json.loads(d.get("aliases") or "[]") if isinstance(a, str)]
        except ValueError:
            d["aliases"] = []
        d["is_me"] = bool(d["is_me"])
        out.append(d)
    return out


def calendar_attendees(meeting: Dict[str, Any]) -> List[str]:
    """The people invited to the calendar meeting a recording was made in (from its notes)."""
    m = _CAL_HEAD_RE.search(meeting.get("user_notes") or "")
    if not m:
        return []
    names = []
    for part in m.group(1).split(","):
        name = _clean(re.sub(r"<[^>]*>", "", part))  # "Имя <почта>" keeps the name
        if name and name.lower() not in {n.lower() for n in names}:
            names.append(name)
    return names[:30]


def _alias_map(rows: List[Dict[str, Any]]) -> Dict[str, str]:
    """A variant (lower case) → the name it was merged into."""
    out: Dict[str, str] = {}
    for r in rows:
        for a in r["aliases"]:
            out[a.lower()] = r["name"]
    return out


def canonical(name: str, rows: Optional[List[Dict[str, Any]]] = None) -> str:
    """The directory's name for a spelling (itself when it is not a merged variant)."""
    name = _clean(name)
    return _alias_map(rows if rows is not None else _rows()).get(name.lower(), name)


def _library_people() -> Iterable[Dict[str, Any]]:
    from app.voice_profiles import people

    return people()


def _library_meetings() -> List[Dict[str, Any]]:
    with _db_lock:
        conn = get_connection()
        rows = conn.execute("SELECT id, user_notes FROM meetings WHERE status = 'completed'").fetchall()
        conn.close()
    return [dict(r) for r in rows]


def _commitment_names() -> List[str]:
    from app.commitments import _init

    _init()
    with _db_lock:
        conn = get_connection()
        rows = conn.execute("SELECT who, to_whom FROM commitments").fetchall()
        conn.close()
    names: List[str] = []
    for r in rows:
        names.extend([r["who"], r["to_whom"]])
    return [n for n in (_clean(x) for x in names) if n]


def directory() -> List[Dict[str, Any]]:
    """Everyone, most present first: [{id, name, kind, role, aliases, is_me, recordings, seconds,
    voice, tasks, calendar, sources}]. id is None for a person nobody edited yet."""
    rows = _rows()
    alias = _alias_map(rows)
    by_key: Dict[str, Dict[str, Any]] = {}

    def entry(name: str) -> Dict[str, Any]:
        name = alias.get(name.lower(), name)
        key = name.lower()
        if key not in by_key:
            by_key[key] = {"id": None, "name": name, "kind": "person", "role": "", "aliases": [], "is_me": False,
                           "recordings": 0, "seconds": 0.0, "voice": False, "tasks": 0, "calendar": 0, "sources": []}
        return by_key[key]

    def source(e: Dict[str, Any], s: str) -> None:
        if s not in e["sources"]:
            e["sources"].append(s)

    for r in rows:
        e = entry(r["name"])
        e.update(id=r["id"], name=r["name"], kind=r["kind"] if r["kind"] in KINDS else "person", role=r["role"] or "",
                 aliases=list(r["aliases"]), is_me=r["is_me"])
        source(e, "manual")
    for p in _library_people():
        e = entry(p["name"])
        e["recordings"] += len(p.get("recordings") or [])
        e["seconds"] = round(e["seconds"] + float(p.get("total_seconds") or 0), 1)
        e["voice"] = e["voice"] or bool(p.get("profile"))
        source(e, "records")
    for m in _library_meetings():
        for name in calendar_attendees(m):
            e = entry(name)
            e["calendar"] += 1
            source(e, "calendar")
    for name in _commitment_names():
        e = entry(name)
        e["tasks"] += 1
        source(e, "tasks")
    me = my_names()
    if me:  # the setting decides; the stored mark only counts while it is empty
        for e in by_key.values():
            e["is_me"] = any(n.lower() in me for n in [e["name"], *e["aliases"]])
    return sorted(by_key.values(), key=lambda e: (not e["is_me"], -(e["recordings"] + e["calendar"] + e["tasks"]), e["name"].lower()))


def _find(conn, name: str) -> Optional[Dict[str, Any]]:
    row = conn.execute("SELECT * FROM people_directory WHERE name = ?", (name,)).fetchone()
    return dict(row) if row else None


def _ensure(conn, name: str, kind: str = "person") -> int:
    row = _find(conn, name)
    if row:
        return int(row["id"])
    cur = conn.execute("INSERT INTO people_directory (name, kind, created_at) VALUES (?, ?, ?)",
                       (name, kind, datetime.now().isoformat(timespec="seconds")))
    return int(cur.lastrowid)


def add(name: str, kind: str = "person") -> Dict[str, Any]:
    """A person or a department added by hand (an existing one is returned as it is)."""
    name = _clean(name)
    if not name:
        raise ValueError("Укажите имя")
    if kind not in KINDS:
        raise ValueError("Неизвестный вид записи справочника")
    init_table()
    rows = _rows()
    name = canonical(name, rows)
    with _db_lock:
        conn = get_connection()
        try:
            _ensure(conn, name, kind)
            conn.commit()
        finally:
            conn.close()
    return next(e for e in directory() if e["name"].lower() == name.lower())


def update(name: str, role: Optional[str] = None, kind: Optional[str] = None, is_me: Optional[bool] = None,
           new_name: Optional[str] = None) -> Dict[str, Any]:
    """Role, kind, "это я" or a new spelling of a person (the old one stays as a variant)."""
    name = _clean(name)
    if not name:
        raise ValueError("Укажите имя")
    if kind is not None and kind not in KINDS:
        raise ValueError("Неизвестный вид записи справочника")
    init_table()
    name = canonical(name)
    target = name
    with _db_lock:
        conn = get_connection()
        try:
            pid = _ensure(conn, name)
            if role is not None:
                conn.execute("UPDATE people_directory SET role = ? WHERE id = ?", (_clean(role), pid))
            if kind is not None:
                conn.execute("UPDATE people_directory SET kind = ? WHERE id = ?", (kind, pid))
            if is_me is not None:
                if is_me:
                    conn.execute("UPDATE people_directory SET is_me = 0")
                conn.execute("UPDATE people_directory SET is_me = ? WHERE id = ?", (1 if is_me else 0, pid))
            nn = _clean(new_name) if new_name is not None else ""
            if nn and nn.lower() != name.lower():
                if _find(conn, nn):
                    raise ValueError("Такое имя уже есть в справочнике: объедините записи")
                row = _find(conn, name)
                aliases = [a for a in json.loads(row["aliases"] or "[]") if a.lower() != nn.lower()]
                aliases.append(name)
                conn.execute("UPDATE people_directory SET name = ?, aliases = ? WHERE id = ?",
                             (nn, json.dumps(aliases, ensure_ascii=False), pid))
                target = nn
            conn.commit()
        finally:
            conn.close()
    if target.lower() != name.lower():
        _move_photo(name, target)
    if is_me is not None:
        _set_me(target, is_me)
    elif target.lower() != name.lower() and name.lower() in my_names():  # the user renamed themselves
        _set_me(target, True)
    return next(e for e in directory() if e["name"].lower() == target.lower())


def merge(names: List[str]) -> Dict[str, Any]:
    """The first name stays; the others become its variants (with their own variants and role)."""
    names = [n for n in (_clean(x) for x in names) if n]
    if len(names) < 2:
        raise ValueError("Выберите хотя бы двоих, чтобы объединить")
    init_table()
    rows = _rows()
    names = [canonical(n, rows) for n in names]
    keep = names[0]
    others = [n for n in dict.fromkeys(n.lower() for n in names[1:]) if n != keep.lower()]
    with _db_lock:
        conn = get_connection()
        try:
            pid = _ensure(conn, keep)
            row = _find(conn, keep)
            aliases = list(json.loads(row["aliases"] or "[]"))
            role, me = row["role"], bool(row["is_me"])
            for low in others:
                other = next((n for n in names if n.lower() == low), low)
                orow = _find(conn, other)
                if orow:
                    aliases.extend(json.loads(orow["aliases"] or "[]"))
                    role = role or orow["role"]
                    me = me or bool(orow["is_me"])
                    conn.execute("DELETE FROM people_directory WHERE id = ?", (orow["id"],))
                aliases.append(other)
            seen, clean = set(), []
            for a in aliases:
                if a.lower() not in seen and a.lower() != keep.lower():
                    seen.add(a.lower())
                    clean.append(a)
            conn.execute("UPDATE people_directory SET aliases = ?, role = ?, is_me = ? WHERE id = ?",
                         (json.dumps(clean, ensure_ascii=False), role, 1 if me else 0, pid))
            conn.commit()
        finally:
            conn.close()
    for low in others:
        _move_photo(low, keep)
    return next(e for e in directory() if e["name"].lower() == keep.lower())


def remove(name: str) -> bool:
    """Forget what was added by hand about a person (the library's own mentions stay)."""
    init_table()
    with _db_lock:
        conn = get_connection()
        cur = conn.execute("DELETE FROM people_directory WHERE name = ?", (_clean(name),))
        conn.commit()
        conn.close()
    return cur.rowcount > 0


def mentions(meeting: Dict[str, Any], people: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """People and departments of the directory named in a recording's text who do not speak in it:
    [{name, kind, count, first_at}], most mentioned first."""
    people = people if people is not None else directory()
    speaking = {_clean((s or {}).get("name")).lower() for s in (meeting.get("speakers") or {}).values()}
    found: Dict[str, Dict[str, Any]] = {}
    for p in people:
        if p["name"].lower() in speaking:
            continue
        spellings = [p["name"]] + list(p.get("aliases") or [])
        # a name as a whole word: "Анна" is not found in "Аннотация"; Russian endings are allowed
        pats = _name_patterns(spellings)
        for seg in meeting.get("segments") or []:
            text = seg.get("text") or ""
            n = sum(len(p_.findall(text)) for p_ in pats)
            if not n:
                continue
            e = found.setdefault(p["name"].lower(), {"name": p["name"], "kind": p["kind"], "count": 0,
                                                     "first_at": float(seg.get("start") or 0)})
            e["count"] += n
    return sorted(found.values(), key=lambda e: (-e["count"], e["first_at"]))


# --- The speakers of one recording: merge two into one, split one in two, role and "это я" ---
_SPK_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
_PALETTE = ["#64D2FF", "#FFB340", "#C9A2FF", "#7EE787", "#FF8A80", "#FFD60A", "#5AC8FA", "#FF9F0A"]


def _check_spk(speaker_id: str) -> None:
    if not _SPK_ID_RE.match(speaker_id or ""):
        raise ValueError("Некорректный идентификатор участника")


def merge_speakers(meeting_id: int, source: str, target: str) -> Optional[Dict[str, Any]]:
    """Every line of `source` becomes a line of `target` (one person counted as two); `source` goes."""
    from app.database import edit_meeting

    _check_spk(source)
    _check_spk(target)
    if source == target:
        raise ValueError("Выберите другого участника")

    def change(m: Dict[str, Any]) -> tuple:
        speakers = m.get("speakers") or {}
        if source not in speakers or target not in speakers:
            raise ValueError("Участник не найден")
        for seg in m.get("segments") or []:
            if seg.get("speaker") == source:
                seg["speaker"] = target
        speakers.pop(source, None)
        m["speakers"] = speakers
        return ("segments", "speakers")

    return edit_meeting(meeting_id, change)


def split_speaker(meeting_id: int, speaker_id: str, positions: List[int], new_name: str) -> Optional[Dict[str, Any]]:
    """The chosen lines (positions in the transcript) of a speaker go to a new person (two people
    counted as one); the others stay."""
    from app.database import edit_meeting

    _check_spk(speaker_id)
    name = _clean(new_name)
    wanted = {int(p) for p in positions}
    if not wanted:
        raise ValueError("Отметьте реплики другого человека")

    def change(m: Dict[str, Any]) -> tuple:
        speakers = m.get("speakers") or {}
        segs = m.get("segments") or []
        if speaker_id not in speakers:
            raise ValueError("Участник не найден")
        own = [i for i, s in enumerate(segs) if s.get("speaker") == speaker_id]
        moved = [i for i in own if i in wanted]
        if not moved:
            raise ValueError("Отметьте реплики другого человека")
        if len(moved) == len(own):
            raise ValueError("У участника должна остаться хотя бы одна реплика")
        n = 1
        while f"SPEAKER_{n:02d}" in speakers:
            n += 1
        new_id = f"SPEAKER_{n:02d}"
        used = {(s or {}).get("color") for s in speakers.values()}
        color = next((c for c in _PALETTE if c not in used), _PALETTE[n % len(_PALETTE)])
        first = segs[moved[0]]
        speakers[new_id] = {"id": new_id, "name": canonical(name) if name else f"Участник {len(speakers) + 1}",
                            "color": color, "sample_start": float(first.get("start") or 0),
                            "sample_end": float(first.get("end") or 0)}
        for i in moved:
            segs[i]["speaker"] = new_id
        m["speakers"] = speakers
        return ("segments", "speakers")

    return edit_meeting(meeting_id, change)


def set_speaker_meta(meeting_id: int, speaker_id: str, role: Optional[str] = None,
                     is_me: Optional[bool] = None) -> Optional[Dict[str, Any]]:
    """A speaker's role in this recording and "это я" (one speaker of a recording at most; the
    directory remembers the user's name)."""
    from app.database import edit_meeting

    _check_spk(speaker_id)
    named: List[str] = []

    def change(m: Dict[str, Any]) -> tuple:
        speakers = m.get("speakers") or {}
        spk = speakers.get(speaker_id)
        if spk is None:
            raise ValueError("Участник не найден")
        if role is not None:
            spk["role"] = _clean(role)
        if is_me is not None:
            for s in speakers.values():
                s.pop("is_me", None)
            if is_me:
                spk["is_me"] = True
                named.append(str(spk.get("name") or ""))
        m["speakers"] = speakers
        return ("speakers",)

    m = edit_meeting(meeting_id, change)
    from app.voice_profiles import is_default_name

    if m is not None and named and not is_default_name(named[0]):
        update(named[0], is_me=True)
    return m


# --- A person's own photo (given in «Участники» / «Все люди»): one per name of the directory, shown
# instead of the initials on the speaker cards, in the directory and on the studio's captions. Kept
# in the data folder under a hash of the name, so a rename or a merge moves it with the person.
def _photo_dir() -> Path:
    from app.paths import DATA_DIR

    return Path(DATA_DIR) / "people_photos"


def photo_path(name: str) -> Path:
    key = hashlib.sha1(canonical(name).lower().encode("utf-8")).hexdigest()[:20]
    return _photo_dir() / f"{key}.img"


def photo_kind(data: bytes) -> str:
    """image/jpeg or image/png by the file's first bytes; "" for anything else."""
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    return ""


def set_photo(name: str, data_b64: str) -> None:
    name = _clean(name)
    if not name:
        raise ValueError("Укажите имя")
    try:
        data = base64.b64decode(str(data_b64 or "").split(",")[-1], validate=True)
    except (ValueError, TypeError):
        raise ValueError("Нужна картинка JPEG или PNG")
    if not photo_kind(data):
        raise ValueError("Нужна картинка JPEG или PNG")
    if len(data) > PHOTO_MAX_BYTES:
        raise ValueError("Картинка слишком большая")
    init_table()
    with _db_lock:  # the person is in the directory from now on (a rename then moves the photo)
        conn = get_connection()
        try:
            _ensure(conn, canonical(name))
            conn.commit()
        finally:
            conn.close()
    path = photo_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    tmp.write_bytes(data)
    tmp.replace(path)


def remove_photo(name: str) -> bool:
    path = photo_path(name)
    if path.is_file():
        path.unlink()
        return True
    return False


def photos() -> Dict[str, int]:
    """Every name with a photo, its variants too (lower case) → a version for the page's cache."""
    if not _photo_dir().is_dir():
        return {}
    out: Dict[str, int] = {}
    for e in directory():
        path = photo_path(e["name"])
        if path.is_file():
            v = int(path.stat().st_mtime)
            for n in [e["name"], *e["aliases"]]:
                out[n.lower()] = v
    return out


def _move_photo(old: str, new: str) -> None:
    """A rename or a merge: the photo goes with the person (one already there stays)."""
    src = _photo_dir() / f"{hashlib.sha1(old.lower().encode('utf-8')).hexdigest()[:20]}.img"
    dst = _photo_dir() / f"{hashlib.sha1(new.lower().encode('utf-8')).hexdigest()[:20]}.img"
    if src.is_file() and src != dst:
        if dst.is_file():
            src.unlink()
        else:
            src.replace(dst)


# --- The participants of a meeting, for the analysis model: their names written right ---
def meeting_roster(meeting: Dict[str, Any]) -> List[str]:
    """Who was in the meeting, as the directory writes them: the speakers named, the names marked in
    the studio and in the Teams captions, the calendar's invitees; with a role when the directory
    has one («Анна Петрова — дизайнер»)."""
    from app.voice_profiles import is_default_name

    names: List[str] = []
    for sp in (meeting.get("speakers") or {}).values():
        n = _clean((sp or {}).get("name") if isinstance(sp, dict) else "")
        if n and not is_default_name(n):
            names.append(n)
    names += [_clean(mk.get("name")) for mk in meeting.get("speaker_marks") or [] if isinstance(mk, dict)]
    names += calendar_attendees(meeting)
    try:
        rows = _rows()
    except Exception:
        rows = []
    roles = {r["name"].lower(): r["role"] for r in rows if r.get("role")}
    out, seen = [], set()
    for n in names:
        if not n:
            continue
        n = canonical(n, rows)
        if n.lower() in seen:
            continue
        seen.add(n.lower())
        out.append(f"{n} — {roles[n.lower()]}" if roles.get(n.lower()) else n)
    return out[:40]


def name_regex(spelling: str) -> str:
    """A name in any case form: «Олег» → «Олега», «Олегу»; a name ending in а/я/й/ь changes it: «Ксения» →
    «Ксении», «Ксению», «Игорь» → «Игоря». The same rule as the page's links (app.js markPeople)."""
    s = " ".join(spelling.split())
    body = r"\s+".join(re.escape(w) for w in s.split(" "))
    if len(s) >= 4 and s[-1].lower() in "аяйь":
        return body[:-1] + r"(?:а|я|у|ю|ой|ей|ою|ею|ы|и|е|й|ь|ем|ём|ом)"
    return body + r"(?:а|у|ой|ом|е|ы|ю|ем|и|я|ей|ов|ым)?"


_CASES = ("nom", "gen", "dat", "ins", "prep", "acc")


def _name_type(word: str) -> Tuple[str, str]:
    """(type, stem) of a word of a Russian name, for declining it; ("", word) for one that is not declined here."""
    w = word.lower()
    if not re.fullmatch(r"[а-яё-]+", w) or len(w) < 3:
        return "", word
    if re.search(r"(ова|ева|ёва|ина|ына)$", w):
        return "sur_f", word[:-1]
    if re.search(r"(ов|ев|ёв|ин|ын)$", w):
        return "sur_m", word
    if w.endswith(("ская", "цкая", "ский", "цкий", "ая", "яя", "ой", "ый")):
        return "", word  # an adjective-like surname («Толстой», «Вишневская»): written as it is
    if w.endswith("ия"):
        return "f_iya", word[:-1]
    if w.endswith("ий"):
        return "m_iy", word[:-1]
    if w[-1] in "й":
        return "m_y", word[:-1]
    if w[-1] == "ь":
        return "m_soft", word[:-1]
    if w[-1] == "я":
        return "f_ya", word[:-1]
    if w[-1] == "а":
        return "f_a", word[:-1]
    if w[-1] in "бвгдзклмнпрстфхжшчщц":
        return "m_hard", word
    return "", word


def _endings(kind: str, stem: str) -> Dict[str, str]:
    hush = stem[-1:].lower() in "гкхжшчщ"
    return {
        "m_hard": {"nom": "", "gen": "а", "dat": "у", "ins": "ем" if stem[-1:].lower() in "жшчщц" else "ом", "prep": "е", "acc": "а"},
        "sur_m": {"nom": "", "gen": "а", "dat": "у", "ins": "ым", "prep": "е", "acc": "а"},
        "m_y": {"nom": "й", "gen": "я", "dat": "ю", "ins": "ем", "prep": "е", "acc": "я"},
        "m_iy": {"nom": "й", "gen": "я", "dat": "ю", "ins": "ем", "prep": "и", "acc": "я"},
        "m_soft": {"nom": "ь", "gen": "я", "dat": "ю", "ins": "ем", "prep": "е", "acc": "я"},
        "f_a": {"nom": "а", "gen": "и" if hush else "ы", "dat": "е", "ins": "ой", "prep": "е", "acc": "у"},
        "f_ya": {"nom": "я", "gen": "и", "dat": "е", "ins": "ей", "prep": "е", "acc": "ю"},
        "f_iya": {"nom": "я", "gen": "и", "dat": "и", "ins": "ей", "prep": "и", "acc": "ю"},
        "sur_f": {"nom": "а", "gen": "ой", "dat": "ой", "ins": "ой", "prep": "ой", "acc": "у"},
    }.get(kind, {})


def _case_of(word: str, seen: str) -> Optional[str]:
    """The case a word of a name was seen in («Олега» of «Олег» → genitive); None when it cannot be told."""
    if seen.lower() == word.lower():
        return "nom"
    kind, stem = _name_type(word)
    if not kind or not seen.lower().startswith(stem.lower()):
        return None
    tail = seen[len(stem):].lower()
    ends = _endings(kind, stem)
    return next((c for c in _CASES if ends.get(c) == tail), None)


def _decline(word: str, case: Optional[str]) -> str:
    kind, stem = _name_type(word)
    if not case or case == "nom" or not kind:
        return word
    return stem + _endings(kind, stem).get(case, word[len(stem):])


def _word_form(old_word: str, new_word: str, seen: str) -> str:
    """The new spelling of one word of a name in the case the old one was seen in: «Мельника» (of
    «Мельник») → «Мельникова» (of «Мельников»), «Алле» (of «Алла») → «Марии» (of «Мария»)."""
    return _decline(new_word, _case_of(old_word, seen))


def rename_in_text(text: str, old: str, new: str) -> str:
    """A person's name written again in a text (the analysis of a recording) after its spelling was put right
    or the person was said to be someone else: every case form of the old name («Ярослава Мельника») becomes
    the same form of the new one, word by word when both have the same number of words; otherwise the
    nominative only («Ярослав Мельник» → «Ярослав Мельников-Петров»). A surname or given name written alone
    follows too when it is long enough to be the person's."""
    old, new = " ".join((old or "").split()), " ".join((new or "").split())
    if not text or not old or not new or old == new:
        return text
    ow, nw = old.split(" "), new.split(" ")
    word = lambda w: "(" + name_regex(w) + ")"  # noqa: E731
    full = re.compile(r"(?<![\w-])" + r"\s+".join(word(w) for w in ow) + r"(?![\w-])", re.I)

    def whole(m: "re.Match") -> str:
        if len(ow) == len(nw):
            return " ".join(_word_form(o, n, m.group(i + 1)) for i, (o, n) in enumerate(zip(ow, nw)))
        # «Олега» → «Дмитрия Орлова»: the case of the old name, told by its words, for every new word
        case = next((c for c in (_case_of(o, m.group(i + 1)) for i, o in enumerate(ow)) if c), None)
        return " ".join(_decline(n, case) for n in nw)

    done: List[str] = []  # what was written already stays out of the next pass («Мельников» is not «Мельник»+«ов»)

    def keep(value: str) -> str:
        done.append(value)
        return f"\x00{len(done) - 1}\x00"

    text = full.sub(lambda m: keep(whole(m)), text)
    if 1 < len(ow) == len(nw):  # «Мельник сказал»: a word of the name alone, when it changed and is not a common short word
        for o, n in zip(ow, nw):
            if o.lower() == n.lower() or len(o) < 4:
                continue
            one = re.compile(r"(?<![\w-])(" + name_regex(o) + r")(?![\w-])", re.I)
            text = one.sub(lambda m, o=o, n=n: keep(_word_form(o, n, m.group(1))), text)
    return re.sub("\x00(\\d+)\x00", lambda m: done[int(m.group(1))], text)


def rename_in_analysis(meeting_id: int, old: str, new: str) -> List[str]:
    """The analysis of a recording with a person's name written anew (rename_in_text); the sections changed."""
    from app.database import get_meeting, merge_summaries

    m = get_meeting(meeting_id)
    if not m:
        return []
    changed = {}
    for key, value in (m.get("summaries") or {}).items():
        if key != "error" and isinstance(value, str) and value.strip():
            fixed = rename_in_text(value, old, new)
            if fixed != value:
                changed[key] = fixed
    if changed:
        merge_summaries(meeting_id, changed)
    return sorted(changed)


def rename_everywhere(old: str, new: str) -> int:
    """A contact's name put right in «Контакты»: the analyses that name them and their tasks follow
    (the recordings whose analysis has the old name, found by its start in the database first)."""
    old, new = _clean(old), _clean(new)
    if not old or not new or old.lower() == new.lower():
        return 0
    from app import commitments

    with _db_lock:
        conn = get_connection()
        ids = [int(r["id"]) for r in conn.execute(
            "SELECT id FROM meetings WHERE summaries_json LIKE ?", (f"%{old.split()[-1][:4]}%",)).fetchall()]
        task_ids = [int(r["meeting_id"]) for r in conn.execute(
            "SELECT DISTINCT meeting_id FROM commitments WHERE meeting_id IS NOT NULL").fetchall()] \
            if conn.execute("SELECT name FROM sqlite_master WHERE name = 'commitments'").fetchone() else []
        conn.close()
    n = 0
    for mid in ids:
        if rename_in_analysis(mid, old, new):
            n += 1
    for mid in task_ids:
        commitments.rename_person(mid, old, new)
    return n


def _name_patterns(spellings: List[str]) -> List["re.Pattern"]:
    """A name as a whole word in any case form; short spellings are left out."""
    return [re.compile(r"(?<![\w-])" + name_regex(s) + r"(?![\w-])", re.I) for s in spellings if len(s) >= 3]


def card(name: str) -> Optional[Dict[str, Any]]:
    """One person of «Контакты»: the directory's entry, the recordings they speak in, were invited to or
    are named in, and their tasks. {person, spoke, invited, mentioned, tasks}; None for a name nobody knows."""
    rows = _rows()
    want = canonical(name, rows).lower()
    person = next((p for p in directory() if p["name"].lower() == want), None)
    if person is None:
        return None
    spellings = [person["name"], *person.get("aliases", [])]
    keys = {s.lower() for s in spellings}
    spoke = []
    for p in _library_people():
        if p["name"].lower() in keys:
            spoke += p.get("recordings") or []
    spoke_ids = {r["meeting_id"] for r in spoke}
    with _db_lock:
        conn = get_connection()
        meetings = {int(r["id"]): dict(r) for r in conn.execute(
            "SELECT id, title, recorded_at, created_at, user_notes FROM meetings WHERE status = 'completed'").fetchall()}
        # the transcripts that may name the person: the database narrows by the name's start, Python checks
        likes = sorted({s[:4] for s in spellings if len(s) >= 3})
        found_rows = conn.execute(
            "SELECT meeting_id, data FROM segments WHERE " + " OR ".join(["data LIKE ?"] * len(likes)),
            tuple(f"%{x}%" for x in likes)).fetchall() if likes else []
        conn.close()

    def brief(mid: int) -> Dict[str, Any]:
        m = meetings[mid]
        return {"meeting_id": mid, "title": m["title"], "date": str(m["recorded_at"] or m["created_at"] or "")[:10]}

    invited = [brief(mid) for mid, m in meetings.items()
               if mid not in spoke_ids and keys & {n.lower() for n in calendar_attendees(m)}]
    pats = _name_patterns(spellings)
    named: Dict[int, Dict[str, Any]] = {}
    for r in found_rows:
        mid = int(r["meeting_id"])
        if mid not in meetings or mid in spoke_ids:
            continue
        try:
            seg = json.loads(r["data"] or "{}")
        except ValueError:
            continue
        text = str(seg.get("text") or "")
        if any(p.search(text) for p in pats):
            e = named.setdefault(mid, {**brief(mid), "count": 0, "first_at": float(seg.get("start") or 0)})
            e["count"] += 1
            e["first_at"] = min(e["first_at"], float(seg.get("start") or 0))
    from app import commitments

    tasks = [t for t in commitments.all_tasks()
             if canonical(t.get("who") or "", rows).lower() == want or canonical(t.get("to_whom") or "", rows).lower() == want]
    by_date = lambda x: x.get("date") or ""  # noqa: E731
    return {"person": person, "spoke": sorted(spoke, key=by_date, reverse=True)[:50],
            "invited": sorted(invited, key=by_date, reverse=True)[:50],
            "mentioned": sorted(named.values(), key=by_date, reverse=True)[:50],
            "tasks": tasks[:100]}


def expand_names(text: str, rows: Optional[List[Dict[str, Any]]] = None) -> str:
    """A contact's other spelling written for them («Дима» merged into «Дмитрий Орлов») becomes the full name
    (asked by the user: the analysis names people as in the contacts, the short form only when it is unclear
    who that is). As written (the nominative), with the surname beside it too («Дима Орлов»); another case
    form («Диме») stays, a declined full name is not made up. Spellings shorter than 3 letters are left."""
    if not text:
        return text
    try:
        rows = rows if rows is not None else _rows()
    except Exception:
        return text
    for r in rows:
        name = r["name"]
        if r.get("kind", "person") != "person":
            continue
        surname = name.split()[-1] if len(name.split()) > 1 else ""
        for alias in sorted(r["aliases"], key=len, reverse=True):
            if len(alias) < 3 or alias.lower() == name.lower() or alias.lower() in name.lower().split():
                continue
            tail = r"(?:\s+" + re.escape(surname) + r")?" if surname and surname.lower() not in alias.lower() else ""
            text = re.sub(r"(?<![\w-])" + r"\s+".join(re.escape(w) for w in alias.split()) + tail + r"(?![\w-])",
                          lambda _m: name, text)
    return text


def known_people(meeting: Dict[str, Any], exclude: Optional[List[str]] = None, cloud: bool = False,
                 limit: int = 60) -> List[str]:
    """The contacts the analysis model is told of besides the participants («Контакты», asked by the user: a
    person named in the talk but not in the meeting was written as heard, not as in the contacts). The ones
    the transcript names come first; on a local model the rest follow (most present first), so a name the
    recognition misheard can still be matched. A cloud service gets only the ones the transcript names: it
    already has the transcript, not the user's whole address book. People only, with their role and the other
    spellings: «Дмитрий Орлов — тимлид (также: Дима)»."""
    try:
        people = [p for p in directory() if p.get("kind") == "person"]
    except Exception:
        return []
    skip = {_clean(n.split(" — ")[0]).lower() for n in (exclude or [])}
    try:
        named = {e["name"].lower() for e in mentions(meeting, people)}
    except Exception:
        named = set()
    ordered = [p for p in people if p["name"].lower() in named] + \
        ([] if cloud else [p for p in people if p["name"].lower() not in named])
    out: List[str] = []
    for p in ordered:
        if p["name"].lower() in skip or p.get("is_me") and p["name"].lower() not in named:
            continue
        line = p["name"] + (f" — {p['role']}" if p.get("role") else "")
        if p.get("aliases"):
            line += f" (также: {', '.join(p['aliases'][:4])})"
        out.append(line)
        if len(out) >= limit:
            break
    return out


_WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё'-]*")
_NAME_ENDINGS = ("ами", "ями", "ого", "его", "ому", "ему", "ой", "ей", "ом", "ем", "ую", "юю", "ая", "яя",
                 "ов", "ев", "ах", "ях", "ам", "ям", "а", "я", "у", "ю", "е", "ы", "и", "ь", "s")


def _dist(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _stem(word: str) -> tuple:
    low = word.lower()
    for end in _NAME_ENDINGS:
        if low.endswith(end) and len(low) - len(end) >= 3:
            return word[: len(word) - len(end)], word[len(word) - len(end):]
    return word, ""


def fix_name_typos(text: str, roster: List[str]) -> str:
    """A participant's name or surname written by the analysis model with a letter or two wrong
    («Мацлевич» for «Мацулевич») is written as in the roster; its case ending stays («Мацлевичу» →
    «Мацулевичу»). Only capitalised words, only names whose stem has 6 letters or more (surnames,
    long names: a short one is too like other words), one letter off, two for 8 letters or more."""
    parts = {}
    for entry in roster or []:
        for w in _WORD_RE.findall(entry.split(" — ")[0]):
            if len(w) >= 4 and w[0].isupper():
                st, _ = _stem(w)
                parts[st.lower()] = (w, st)
    if not parts or not text:
        return text

    def fix(m: "re.Match") -> str:
        word = m.group(0)
        if not word[0].isupper() or len(word) < 4:
            return word
        stem, end = _stem(word)
        low = stem.lower()
        if low in parts:
            return word  # written right (in any case form)
        best, best_d = None, 9
        for key, (name, name_stem) in parts.items():
            # short names are left alone: «Марс» or «Марина» are not a misspelt «Мария»
            if len(key) < 6 or abs(len(key) - len(low)) > 2 or key[0] != low[0]:
                continue
            allowed = 1 if len(key) < 8 else 2
            d = _dist(low, key)
            if d <= allowed and d < best_d:
                best, best_d = (name, name_stem), d
        if best is None:
            return word
        name, name_stem = best
        return (name if not end else name_stem + end) if word[1:].islower() or not word[1:].isupper() else word

    return _WORD_RE.sub(fix, text)


# --- Who a task is for, as the roster writes them: «Макс» said in the meeting is «Maksim Orlov» of
# the Teams captions or the invitation; a surname alone, a short name, a Latin or Cyrillic spelling and
# a letter wrong all find the participant ---
# Short names said in a meeting and the full names they stand for (Russian and English)
_SHORT_NAMES = {
    "макс": ["максим"], "максик": ["максим"], "саша": ["александр", "александра"], "шура": ["александр", "александра"],
    "дима": ["дмитрий"], "митя": ["дмитрий"], "миша": ["михаил"], "женя": ["евгений", "евгения"],
    "лёша": ["алексей"], "леша": ["алексей"], "алёша": ["алексей"], "алеша": ["алексей"], "серёжа": ["сергей"],
    "сережа": ["сергей"], "серёга": ["сергей"], "серега": ["сергей"], "коля": ["николай"], "вова": ["владимир"],
    "володя": ["владимир"], "петя": ["пётр", "петр"], "ваня": ["иван"], "катя": ["екатерина"], "маша": ["мария"],
    "настя": ["анастасия"], "лена": ["елена"], "оля": ["ольга"], "таня": ["татьяна"], "наташа": ["наталья", "наталия"],
    "юля": ["юлия"], "света": ["светлана"], "ира": ["ирина"], "аня": ["анна"], "даша": ["дарья"], "костя": ["константин"],
    "андрюша": ["андрей"], "паша": ["павел"], "гоша": ["георгий"], "жора": ["георгий"], "слава": ["вячеслав", "ярослав", "станислав"],
    "витя": ["виктор"], "толя": ["анатолий"], "рома": ["роман"], "стас": ["станислав"], "влад": ["владислав", "владимир"],
    "гена": ["геннадий"], "лиза": ["елизавета"], "вика": ["виктория"], "ксюша": ["ксения"], "галя": ["галина"],
    "люба": ["любовь"], "надя": ["надежда"], "тёма": ["артём", "артем"], "тема": ["артём", "артем"], "игорёк": ["игорь"],
    "миля": ["эмилия"], "кирюша": ["кирилл"], "никита": ["никита"], "лёва": ["лев"], "боря": ["борис"], "гриша": ["григорий"],
    "max": ["maxim", "maksim", "maximilian"], "alex": ["alexander", "alexandra", "alexey", "aleksei"], "mike": ["michael"],
    "kate": ["katherine", "catherine", "ekaterina"], "dan": ["daniel"], "nick": ["nicholas", "nikolai"], "tom": ["thomas"],
    "bob": ["robert"], "rob": ["robert"], "bill": ["william"], "will": ["william"], "jim": ["james"], "liz": ["elizabeth"],
    "sam": ["samuel", "samantha"], "ben": ["benjamin"], "chris": ["christopher", "christina"], "andy": ["andrew"],
    "dima": ["dmitry", "dmitrii"], "sasha": ["alexander", "aleksandr"], "misha": ["mikhail"], "vova": ["vladimir"],
}


def _name_keys(word: str) -> List[str]:
    """The sound keys a spoken word may stand for: its own and its full names'."""
    from app.vocab import sound_key

    w = word.lower().strip(".,:;!?«»\"'")
    keys = [sound_key(w)]
    for full in _SHORT_NAMES.get(w, []) + _SHORT_NAMES.get(w.replace("ё", "е"), []):
        keys.append(sound_key(full))
    return [k for k in dict.fromkeys(keys) if k]


_SEVERAL_RE = re.compile(r"(\s(и|или|and|or)\s|[,/&+;])", re.I)
_MALE_OBLIQUE = ("ому", "ему", "ом", "ем", "у", "ю", "е")  # Иванову, Петром: the name itself plus an ending
_FEMALE_OBLIQUE = ("ой", "ей", "у", "ю")                    # Ивановой, Марию: the -а/-я of the name changed


def _word_fits(word: str, part: str) -> bool:
    """Whether a word said for a person is this part of a participant's name: the same (in any script, or
    a short name of it), the same in another case, or one letter off in a long word (a surname)."""
    from app.vocab import sound_key

    w, p = word.lower(), part.lower()
    pk = sound_key(p)
    if pk in _name_keys(w):
        return True
    for end in _MALE_OBLIQUE:  # a man's name in another case: the name is the word without its ending
        if w.endswith(end) and len(w) - len(end) >= 3 and sound_key(w[: -len(end)]) == pk:
            return True
    for end in _FEMALE_OBLIQUE:  # a woman's: the name ends in -а/-я where the word has the ending
        if w.endswith(end) and len(w) - len(end) >= 3 and pk in (sound_key(w[: -len(end)] + "а"), sound_key(w[: -len(end)] + "я")):
            return True
    # A misspelt surname or long name: the same first and last letter (so «Александра» is not «Александр»,
    # «Максимов» not «Максим»), a letter off, two in a word of 9 letters or more
    wk = sound_key(w)
    return (len(wk) >= 6 and len(pk) >= 6 and wk[0] == pk[0] and wk[-1] == pk[-1]
            and _dist(wk, pk) <= (1 if len(pk) < 9 else 2))


def resolve_person(who: str, roster: List[str]) -> str:
    """The roster's name for a task's person when exactly one participant fits every word said: by a full
    or short name, by the surname, in Latin or Cyrillic, in another case, a surname a letter off. Who
    stays as said when nobody or several fit, when it names several people («Иван и Олег»), or when a
    word fits no part of the name («Анна Каренина» is not «Анна Сидорова»)."""
    said = re.sub(r"\([^)]*\)", " ", who or "")
    if _SEVERAL_RE.search(f" {said} "):
        return who
    words = [w for w in _WORD_RE.findall(said) if len(w) >= 2]
    if not words or not roster:
        return who
    names = [entry.split(" — ")[0].strip() for entry in roster if entry.strip()]
    hits = []
    for name in names:
        parts = [w for w in _WORD_RE.findall(name) if len(w) >= 2]
        if not parts or len(words) > len(parts):
            continue
        free = list(parts)
        for w in words:
            fit = next((p for p in free if _word_fits(w, p)), None)
            if fit is None:
                break
            free.remove(fit)
        else:
            hits.append(name)
    hits = list(dict.fromkeys(hits))
    return hits[0] if len(hits) == 1 else who
