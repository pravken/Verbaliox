"""
Features (a product's features, «фичи»): a tag across the library, the meetings about one feature
together, whatever folder they are in. A meeting may be about several features (most often one); its
tasks belong to its features (they are not tagged one by one).

Two ways a feature comes to a meeting besides the user's own choice:
- a series rule: the features of a series of recurring meetings, set by the user, go to every new
  meeting of the series (app/series.py puts a recording into its series);
- a suggestion of the analysis model, out of the existing features only, shown greyed with ✓ / ✕:
  nothing is put on a meeting until the user accepts it.
"""

import json
import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from app.database import _db_lock, get_connection, get_meeting

# Colours given in turn to new features (the user can change them)
COLORS = ["#64B5FF", "#BF5AF2", "#30D158", "#FF9F0A", "#FF6482", "#5AC8FA", "#FFD60A", "#AC8E68"]
NAME_MAX = 60


def _init(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS features (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, color TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL)""")
    # what a feature is about (Словарь → Фичи): each field has a use, none is required
    have = {r["name"] for r in conn.execute("PRAGMA table_info(features)").fetchall()}
    for column in ("description", "keywords", "terms"):
        if column not in have:
            conn.execute(f"ALTER TABLE features ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
    conn.execute("CREATE TABLE IF NOT EXISTS meeting_features (meeting_id INTEGER NOT NULL, feature_id INTEGER NOT NULL, "
                 "PRIMARY KEY (meeting_id, feature_id))")
    conn.execute("CREATE TABLE IF NOT EXISTS series_features (series_id INTEGER NOT NULL, feature_id INTEGER NOT NULL, "
                 "PRIMARY KEY (series_id, feature_id))")
    conn.execute("CREATE TABLE IF NOT EXISTS feature_suggestions (meeting_id INTEGER NOT NULL, feature_id INTEGER NOT NULL, "
                 "PRIMARY KEY (meeting_id, feature_id))")
    # a suggestion the user turned down is not made again for that meeting
    conn.execute("CREATE TABLE IF NOT EXISTS feature_declined (meeting_id INTEGER NOT NULL, feature_id INTEGER NOT NULL, "
                 "PRIMARY KEY (meeting_id, feature_id))")


def _conn():
    conn = get_connection()
    _init(conn)
    return conn


# Direction overrides and other invisible characters: a name that reads differently from what it is
_INVISIBLE = re.compile("[\x00-\x1f\x7f\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]")


def _clean(name: str) -> str:
    return re.sub(r"\s+", " ", _INVISIBLE.sub("", str(name or ""))).strip()[:NAME_MAX]


def _by_name(conn, name: str) -> Optional[Dict[str, Any]]:
    key = name.casefold()
    return next((dict(r) for r in conn.execute("SELECT id, name, color FROM features").fetchall() if r["name"].casefold() == key), None)


def list_features() -> List[Dict[str, Any]]:
    """Every feature with how many recordings are about it, by name."""
    with _db_lock:
        conn = _conn()
        rows = conn.execute(
            "SELECT f.id, f.name, f.color, f.description, f.keywords, f.terms, COUNT(m.id) AS count FROM features f "
            "LEFT JOIN meeting_features mf ON mf.feature_id = f.id LEFT JOIN meetings m ON m.id = mf.meeting_id "
            "GROUP BY f.id ORDER BY f.name COLLATE NOCASE").fetchall()
        conn.close()
    return [dict(r) for r in rows]


def create_feature(name: str, color: str = "") -> Dict[str, Any]:
    """A new feature; a name there is already (in any letter case) gives that one."""
    name = _clean(name)
    if not name:
        raise ValueError("Название фичи пустое")
    with _db_lock:
        conn = _conn()
        row = _by_name(conn, name)  # SQLite's lower() leaves Cyrillic as it is: compared here
        if row:
            conn.close()
            return row
        n = conn.execute("SELECT COUNT(*) FROM features").fetchone()[0]
        color = color if re.fullmatch(r"#[0-9A-Fa-f]{6}", color or "") else COLORS[n % len(COLORS)]
        cur = conn.execute("INSERT INTO features (name, color, created_at) VALUES (?, ?, ?)",
                           (name, color, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        fid = int(cur.lastrowid)
        conn.close()
    return {"id": fid, "name": name, "color": color}


DESCRIPTION_MAX = 400
LIST_MAX = 400  # keywords: comma-separated
TERMS_MAX = 1200  # terms: about a hundred (400 characters held 40, the PC check of 0.8.7-beta.2)


def _clean_list(text: Optional[str], limit: int = LIST_MAX) -> str:
    """«возвраты, эквайринг ,payments» -> «возвраты, эквайринг, payments» (each once, in order)."""
    items: List[str] = []
    size = 0
    for x in re.split(r"[,;\n]", str(text or "")):  # split first: a line break separates too
        x = " ".join(_INVISIBLE.sub("", x).split())[:NAME_MAX]
        if not x or x.casefold() in {i.casefold() for i in items}:
            continue
        size += len(x) + (2 if items else 0)
        if size > limit:  # whole items only: a cut one would reach recognition and the glossary
            break
        items.append(x)
    return ", ".join(items)


def split_list(text: Optional[str]) -> List[str]:
    return [x.strip() for x in str(text or "").split(",") if x.strip()]


def update_feature(feature_id: int, name: Optional[str] = None, color: Optional[str] = None,
                   description: Optional[str] = None, keywords: Optional[str] = None, terms: Optional[str] = None) -> None:
    with _db_lock:
        conn = _conn()
        if name is not None:
            name = _clean(name)
            if not name:
                conn.close()
                raise ValueError("Название фичи пустое")
            other = _by_name(conn, name)
            if other and other["id"] != feature_id:
                conn.close()
                raise ValueError("Фича с таким названием уже есть")
            conn.execute("UPDATE features SET name = ? WHERE id = ?", (name, feature_id))
        if color is not None and re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
            conn.execute("UPDATE features SET color = ? WHERE id = ?", (color, feature_id))
        if description is not None:
            text = " ".join(_INVISIBLE.sub("", description).split())[:DESCRIPTION_MAX]
            conn.execute("UPDATE features SET description = ? WHERE id = ?", (text, feature_id))
        if keywords is not None:
            conn.execute("UPDATE features SET keywords = ? WHERE id = ?", (_clean_list(keywords), feature_id))
        if terms is not None:
            conn.execute("UPDATE features SET terms = ? WHERE id = ?", (_clean_list(terms, TERMS_MAX), feature_id))
        conn.commit()
        conn.close()


def delete_feature(feature_id: int) -> None:
    """The feature and its tags go; the recordings and their tasks stay."""
    with _db_lock:
        conn = _conn()
        for table in ("meeting_features", "series_features", "feature_suggestions", "feature_declined"):
            conn.execute(f"DELETE FROM {table} WHERE feature_id = ?", (feature_id,))
        conn.execute("DELETE FROM features WHERE id = ?", (feature_id,))
        conn.commit()
        conn.close()


def _pairs(table: str, meeting_ids: Optional[Iterable[int]]):
    """(meeting_id, feature_id) rows of a table, of the given recordings only when they are few."""
    wanted = None if meeting_ids is None else sorted({int(i) for i in meeting_ids})
    with _db_lock:
        conn = _conn()
        if wanted is not None and len(wanted) <= 500:  # SQLite's limit on parameters
            rows = conn.execute(f"SELECT meeting_id, feature_id FROM {table} WHERE meeting_id IN ({','.join('?' * len(wanted))}) "
                                "ORDER BY rowid", wanted).fetchall() if wanted else []
        else:
            rows = conn.execute(f"SELECT meeting_id, feature_id FROM {table} ORDER BY rowid").fetchall()
        conn.close()
    return rows, (None if wanted is None else set(wanted))


def feature_map(meeting_ids: Optional[Iterable[int]] = None) -> Dict[int, List[int]]:
    """{meeting id: [feature ids]} of the given recordings (all of them when None), one query."""
    rows, wanted = _pairs("meeting_features", meeting_ids)
    out: Dict[int, List[int]] = {}
    for r in rows:
        if wanted is None or r["meeting_id"] in wanted:
            out.setdefault(r["meeting_id"], []).append(r["feature_id"])
    return out


def suggestion_map(meeting_ids: Optional[Iterable[int]] = None) -> Dict[int, List[int]]:
    rows, wanted = _pairs("feature_suggestions", meeting_ids)
    out: Dict[int, List[int]] = {}
    for r in rows:
        if wanted is None or r["meeting_id"] in wanted:
            out.setdefault(r["meeting_id"], []).append(r["feature_id"])
    return out


def set_meeting_features(meeting_id: int, feature_ids: List[int], for_series: bool = False) -> List[int]:
    """The features of a recording, as chosen (the earlier ones replaced). for_series: the same
    features for every new meeting of its series too. A suggestion is settled by the choice."""
    with _db_lock:
        conn = _conn()
        known = {r[0] for r in conn.execute("SELECT id FROM features").fetchall()}
        ids = [int(f) for f in dict.fromkeys(feature_ids) if int(f) in known]
        conn.execute("DELETE FROM meeting_features WHERE meeting_id = ?", (meeting_id,))
        conn.executemany("INSERT INTO meeting_features (meeting_id, feature_id) VALUES (?, ?)", [(meeting_id, f) for f in ids])
        # a suggestion of a feature now chosen is settled; the others stay to be answered
        conn.executemany("DELETE FROM feature_suggestions WHERE meeting_id = ? AND feature_id = ?", [(meeting_id, f) for f in ids])
        if for_series:
            row = conn.execute("SELECT series_id FROM meetings WHERE id = ?", (meeting_id,)).fetchone()
            if row and row["series_id"]:
                conn.execute("DELETE FROM series_features WHERE series_id = ?", (row["series_id"],))
                conn.executemany("INSERT INTO series_features (series_id, feature_id) VALUES (?, ?)",
                                 [(row["series_id"], f) for f in ids])
        conn.commit()
        conn.close()
    try:  # its Obsidian note goes to the feature's folder (app/obsidian.follow)
        from app import obsidian

        obsidian.follow(meeting_id)
    except Exception:
        pass
    return ids


def series_rule(series_id: Optional[int]) -> List[int]:
    if not series_id:
        return []
    with _db_lock:
        conn = _conn()
        rows = conn.execute("SELECT feature_id FROM series_features WHERE series_id = ?", (series_id,)).fetchall()
        conn.close()
    return [r[0] for r in rows]


def apply_series_rule(meeting_id: int) -> List[int]:
    """A new meeting of a series the user gave features to gets them, when it has none of its own."""
    m = get_meeting(meeting_id)
    if not m or feature_map([meeting_id]).get(meeting_id):
        return []
    ids = series_rule(m.get("series_id"))
    return set_meeting_features(meeting_id, ids) if ids else []


def decline_suggestion(meeting_id: int, feature_id: int) -> None:
    with _db_lock:
        conn = _conn()
        conn.execute("DELETE FROM feature_suggestions WHERE meeting_id = ? AND feature_id = ?", (meeting_id, feature_id))
        conn.execute("INSERT OR IGNORE INTO feature_declined (meeting_id, feature_id) VALUES (?, ?)", (meeting_id, feature_id))
        conn.commit()
        conn.close()


def accept_suggestion(meeting_id: int, feature_id: int) -> List[int]:
    ids = feature_map([meeting_id]).get(meeting_id, [])
    return set_meeting_features(meeting_id, ids + [feature_id])


def _mentions(text: str, phrase: str) -> bool:
    """The phrase as whole words of the text, any letter case («Платежи» in «Синк: платежи и возвраты»)."""
    phrase = phrase.strip()
    if len(phrase) < 2:
        return False
    return re.search(r"(?<!\w)" + re.escape(phrase.casefold()) + r"(?!\w)", text.casefold()) is not None


def suggest_by_title(meeting_id: int) -> List[int]:
    """The features whose name or a keyword is in the meeting's title (a Teams meeting is often named
    after its feature): kept as suggestions, for ✓ / ✕ like the model's. Not for a meeting that has
    features; one the user turned down for it is not suggested again."""
    m = get_meeting(meeting_id)
    if not m or feature_map([meeting_id]).get(meeting_id):
        return []
    title = str(m.get("title") or "")
    ids = [f["id"] for f in list_features()
           if any(_mentions(title, p) for p in [f["name"], *split_list(f.get("keywords"))])]
    return _keep_suggestions(meeting_id, ids)


def _keep_suggestions(meeting_id: int, ids: List[int]) -> List[int]:
    with _db_lock:
        conn = _conn()
        declined = {r[0] for r in conn.execute("SELECT feature_id FROM feature_declined WHERE meeting_id = ?", (meeting_id,)).fetchall()}
        ids = [f for f in ids if f not in declined]
        conn.execute("DELETE FROM feature_suggestions WHERE meeting_id = ?", (meeting_id,))
        conn.executemany("INSERT INTO feature_suggestions (meeting_id, feature_id) VALUES (?, ?)", [(meeting_id, f) for f in ids])
        conn.commit()
        conn.close()
    return ids


def describe(feature_ids: Iterable[int]) -> str:
    """What the given features are, for a model's request: name, description, keywords and terms."""
    by_id = {f["id"]: f for f in list_features()}
    lines = []
    for fid in feature_ids:
        f = by_id.get(int(fid))
        if not f:
            continue
        extra = [x for x in (f.get("description") or "",
                             ("ключевые слова: " + f["keywords"]) if f.get("keywords") else "",
                             ("термины: " + f["terms"]) if f.get("terms") else "") if x]
        lines.append(f"- {f['name']}" + (": " + "; ".join(extra) if extra else ""))
    return "\n".join(lines)


def note_for(meeting: Dict[str, Any]) -> str:
    """describe() of a recording's own features ('' when it has none)."""
    try:
        return describe(meeting.get("features") or [])
    except Exception:
        return ""


def all_terms() -> List[str]:
    """The terms of every feature (for recognition and the models' glossary)."""
    out: List[str] = []
    for f in list_features():
        for t in split_list(f.get("terms")):
            if t.casefold() not in {x.casefold() for x in out}:
                out.append(t)
    return out


_SUGGEST = (
    "Тебе дан список фич продукта и материалы встречи. Выбери из списка фичи, которым посвящена встреча: обычно "
    "одну, реже две-три. Только если о фиче на встрече действительно говорили по существу; не выбирай по одному "
    "упоминанию. Новых названий не придумывай. Ответ — только JSON-массив названий из списка, например "
    '["Платежи"]; если ни одна не подходит — [].'
)
SUGGEST_TEXT_CHARS = 12000


def parse_names(answer: str, features: List[Dict[str, Any]]) -> List[int]:
    """The ids of the features the model named (only names of the list, in any letter case)."""
    by_name = {f["name"].casefold(): f["id"] for f in features}
    m = re.search(r"\[[^\[\]]*\]", answer or "")
    try:
        names = json.loads(m.group(0)) if m else []
    except ValueError:
        names = []
    out = []
    for n in names if isinstance(names, list) else []:
        fid = by_name.get(str(n).strip().casefold())
        if fid and fid not in out:
            out.append(fid)
    return out[:3]


def suggest(meeting_id: int, model_name: Optional[str] = None) -> List[int]:
    """The analysis model's guess which existing features the meeting is about, kept as suggestions
    (shown with ✓ / ✕). Not for a meeting that has features, nor when there are none to choose from;
    a feature the user turned down for this meeting is not suggested again."""
    from app.database import is_local_only
    from app.llm import target
    from app.ollama_client import build_transcript_lines

    features = list_features()
    m = get_meeting(meeting_id)
    if not features or not m or feature_map([meeting_id]).get(meeting_id):
        return []
    sums = m.get("summaries") or {}
    body = "\n\n".join(x for x in (sums.get("tldr"), sums.get("protocol")) if (x or "").strip())
    if not body.strip():
        body = "\n".join(build_transcript_lines(m.get("segments") or [], m.get("speakers") or {}))
    text = (f"Название встречи: {m.get('title') or ''}\n\n" + (f"MFU:\n{m['mfu']}\n\n" if (m.get("mfu") or "").strip() else "")
            + body)[:SUGGEST_TEXT_CHARS]
    llm = target(model_name, local_only=is_local_only(m))
    listing = "Фичи:\n" + describe(f["id"] for f in features)  # with what each is about, when written
    ids = parse_names(llm.chat(_SUGGEST, listing + "\n\n" + text, short=True), features)
    return _keep_suggestions(meeting_id, ids)


# --- The page of a feature: its meetings, the decisions written in their summaries, its tasks ---
_DECISION_HEAD = re.compile(r"^\s{0,3}(#{1,6}\s*|\*\*).*(решени|договор|decision|agreed)", re.I)
_ANY_HEAD = re.compile(r"^\s{0,3}(#{1,6}\s|\*\*[^*]+\*\*:?\s*$)")  # «## Решения» or a line «**Решения**»
_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*\S)")
DECISIONS_PER_MEETING = 12


def decisions_of(summary_md: str) -> List[str]:
    """The points under a «Решения» / «Договорённости» / «Decisions» heading of a summary."""
    out: List[str] = []
    inside = False
    for line in str(summary_md or "").splitlines():
        if _ANY_HEAD.match(line):
            inside = bool(_DECISION_HEAD.match(line))
            continue
        m = _BULLET.match(line) if inside else None
        if m:
            out.append(m.group(1).strip())
    return out[:DECISIONS_PER_MEETING]


def overview(feature_id: int, today=None) -> Optional[Dict[str, Any]]:
    """Everything of one feature: its meetings (newest first) with the decisions of their summaries,
    and the tasks of those meetings; the card (asked by the user) adds the people met in them, the
    meetings and hours of each of the last WEEKS weeks, the hours in all. None when there is no such feature."""
    from app import commitments
    from app.database import _loads_dict

    f = next((x for x in list_features() if x["id"] == int(feature_id)), None)
    if not f:
        return None
    with _db_lock:
        conn = _conn()
        rows = conn.execute(
            "SELECT m.id, m.title, m.recorded_at, m.created_at, m.duration, m.summaries_json, m.speakers_json FROM meetings m "
            "JOIN meeting_features mf ON mf.meeting_id = m.id WHERE mf.feature_id = ?", (int(feature_id),)).fetchall()
        conn.close()
    meetings = []
    for r in rows:
        sums = _loads_dict(r["summaries_json"])
        meetings.append({"id": r["id"], "title": r["title"] or "", "date": str(r["recorded_at"] or r["created_at"] or "")[:16],
                         "duration": r["duration"] or 0, "tldr": str(sums.get("tldr") or "")[:400],
                         "decisions": decisions_of(sums.get("protocol") or "")})
    meetings.sort(key=lambda m: m["date"], reverse=True)
    tasks = commitments.for_meetings([m["id"] for m in meetings]) if meetings else []
    return {"feature": f, "meetings": meetings, "tasks": tasks, **_card(rows, meetings, today)}


WEEKS = 12


def _card(rows, meetings: List[Dict[str, Any]], today=None) -> Dict[str, Any]:
    """The people met in the feature's meetings (most first; not the user), each of the last WEEKS weeks
    (from Monday: meetings and hours), the hours in all and the last meeting's date."""
    from datetime import date, timedelta

    from app.database import _loads_dict
    from app.people import _rows, canonical, my_names
    from app.voice_profiles import is_default_name

    today = today or date.today()
    week0 = today - timedelta(days=today.weekday())
    weeks = [{"start": (week0 - timedelta(days=7 * k)).isoformat(), "meetings": 0, "hours": 0.0} for k in range(WEEKS - 1, -1, -1)]
    try:
        directory = _rows()
    except Exception:
        directory = []
    me = set(my_names())
    met: Dict[str, Dict[str, Any]] = {}
    speakers = {r["id"]: r["speakers_json"] for r in rows}
    for m in meetings:
        try:
            day = date.fromisoformat(m["date"][:10])
        except ValueError:
            day = None
        if day:
            for w in weeks:
                a = date.fromisoformat(w["start"])
                if a <= day < a + timedelta(days=7):
                    w["meetings"] += 1
                    w["hours"] = round(w["hours"] + float(m["duration"] or 0) / 3600, 2)
        seen = set()
        for sp in _loads_dict(speakers.get(m["id"])).values():
            n = (sp or {}).get("name") if isinstance(sp, dict) else ""
            if not n or is_default_name(n):
                continue
            n = canonical(n, directory)
            if n.lower() in seen or n.lower() in me:
                continue
            seen.add(n.lower())
            e = met.setdefault(n.lower(), {"name": n, "color": (sp or {}).get("color") or "", "meetings": 0, "last": ""})
            e["meetings"] += 1
            e["last"] = max(e["last"], m["date"][:10])
    people = sorted(met.values(), key=lambda x: (-x["meetings"], x["name"].lower()))[:12]
    return {"people": people, "weeks": weeks, "hours": round(sum(float(m["duration"] or 0) for m in meetings) / 3600, 1),
            "last": meetings[0]["date"][:10] if meetings else ""}
