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


def _clean(name: str) -> str:
    return re.sub(r"\s+", " ", str(name or "")).strip()[:NAME_MAX]


def _by_name(conn, name: str) -> Optional[Dict[str, Any]]:
    key = name.casefold()
    return next((dict(r) for r in conn.execute("SELECT id, name, color FROM features").fetchall() if r["name"].casefold() == key), None)


def list_features() -> List[Dict[str, Any]]:
    """Every feature with how many recordings are about it, by name."""
    with _db_lock:
        conn = _conn()
        rows = conn.execute(
            "SELECT f.id, f.name, f.color, COUNT(m.id) AS count FROM features f "
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


def update_feature(feature_id: int, name: Optional[str] = None, color: Optional[str] = None) -> None:
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


def feature_map(meeting_ids: Optional[Iterable[int]] = None) -> Dict[int, List[int]]:
    """{meeting id: [feature ids]} of the given recordings (all of them when None), one query."""
    with _db_lock:
        conn = _conn()
        rows = conn.execute("SELECT meeting_id, feature_id FROM meeting_features ORDER BY rowid").fetchall()
        conn.close()
    wanted = None if meeting_ids is None else {int(i) for i in meeting_ids}
    out: Dict[int, List[int]] = {}
    for r in rows:
        if wanted is None or r["meeting_id"] in wanted:
            out.setdefault(r["meeting_id"], []).append(r["feature_id"])
    return out


def suggestion_map(meeting_ids: Optional[Iterable[int]] = None) -> Dict[int, List[int]]:
    with _db_lock:
        conn = _conn()
        rows = conn.execute("SELECT meeting_id, feature_id FROM feature_suggestions").fetchall()
        conn.close()
    wanted = None if meeting_ids is None else {int(i) for i in meeting_ids}
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
        conn.execute("DELETE FROM feature_suggestions WHERE meeting_id = ?", (meeting_id,))
        if for_series:
            row = conn.execute("SELECT series_id FROM meetings WHERE id = ?", (meeting_id,)).fetchone()
            if row and row["series_id"]:
                conn.execute("DELETE FROM series_features WHERE series_id = ?", (row["series_id"],))
                conn.executemany("INSERT INTO series_features (series_id, feature_id) VALUES (?, ?)",
                                 [(row["series_id"], f) for f in ids])
        conn.commit()
        conn.close()
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
    listing = "Фичи: " + "; ".join(f["name"] for f in features)
    ids = parse_names(llm.chat(_SUGGEST, listing + "\n\n" + text), features)
    with _db_lock:
        conn = _conn()
        declined = {r[0] for r in conn.execute("SELECT feature_id FROM feature_declined WHERE meeting_id = ?", (meeting_id,)).fetchall()}
        ids = [f for f in ids if f not in declined]
        conn.execute("DELETE FROM feature_suggestions WHERE meeting_id = ?", (meeting_id,))
        conn.executemany("INSERT INTO feature_suggestions (meeting_id, feature_id) VALUES (?, ?)", [(meeting_id, f) for f in ids])
        conn.commit()
        conn.close()
    return ids
