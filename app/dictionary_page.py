"""What the section «Словарь» shows beside the words themselves: how many recordings hold each word, and
the words corrections by hand suggest («Предложено из записей»).

A hand edit of the analysis gives pairs of a wrong and a right spelling (app/analysis_edits.word_changes);
the page offers them at once, and the ones not learned there stay here as suggestions until they are added
to the dictionary or hidden."""
import re
from datetime import datetime
from typing import Any, Dict, List

from app.database import _db_lock, get_connection, list_dictionary

OFFERS_MAX = 200  # the newest are kept; an old suggestion nobody answered goes


def _init(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS dictionary_offers (
        wrong_word TEXT NOT NULL, right_word TEXT NOT NULL, meeting_id INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL, hidden INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (wrong_word, right_word))""")


def _conn():
    conn = get_connection()
    _init(conn)
    return conn


def _known() -> Dict[str, set]:
    """Each term of the dictionary (casefolded) and its variants (casefolded)."""
    from app.vocab import split_variants

    return {str(d.get("term") or "").casefold(): {v.casefold() for v in split_variants(d.get("variants") or "")}
            for d in list_dictionary(active_only=False)}


def remember(meeting_id: int, pairs: List[Dict[str, Any]]) -> None:
    """The pairs of a hand edit, kept as suggestions (only those the dictionary could learn, sure ones)."""
    from app.analysis_edits import PHRASE_MAX_WORDS, learnable

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for p in pairs or []:
        wrong, right = " ".join(str(p.get("wrong") or "").split()), " ".join(str(p.get("right") or "").split())
        if p.get("sure") is False or not wrong or not right or wrong.casefold() == right.casefold():
            continue
        if len(wrong.split()) > PHRASE_MAX_WORDS or len(right.split()) > PHRASE_MAX_WORDS or not learnable(wrong):
            continue
        rows.append((wrong, right, int(meeting_id or 0), now))
    if not rows:
        return
    with _db_lock:
        conn = _conn()
        conn.executemany("INSERT INTO dictionary_offers (wrong_word, right_word, meeting_id, created_at) VALUES (?, ?, ?, ?) "
                         "ON CONFLICT(wrong_word, right_word) DO UPDATE SET meeting_id = excluded.meeting_id, created_at = excluded.created_at",
                         rows)
        conn.execute("DELETE FROM dictionary_offers WHERE rowid NOT IN "
                     "(SELECT rowid FROM dictionary_offers ORDER BY created_at DESC LIMIT ?)", (OFFERS_MAX,))
        conn.commit()
        conn.close()


def offers() -> List[Dict[str, Any]]:
    """The suggestions not hidden and not in the dictionary yet, the newest first, with their recording."""
    known = _known()
    with _db_lock:
        conn = _conn()
        rows = conn.execute("SELECT o.wrong_word, o.right_word, o.meeting_id, o.created_at, m.title FROM dictionary_offers o "
                            "LEFT JOIN meetings m ON m.id = o.meeting_id WHERE o.hidden = 0 ORDER BY o.created_at DESC").fetchall()
        conn.close()
    out = []
    for r in rows:
        variants = known.get(r["right_word"].casefold())
        if variants is not None and r["wrong_word"].casefold() in variants:
            continue  # learned already
        out.append({"wrong": r["wrong_word"], "right": r["right_word"], "meeting_id": int(r["meeting_id"] or 0),
                    "title": r["title"] or "", "created_at": r["created_at"]})
    return out


def hide(wrong: str, right: str) -> None:
    with _db_lock:
        conn = _conn()
        conn.execute("UPDATE dictionary_offers SET hidden = 1 WHERE wrong_word = ? AND right_word = ?",
                     (" ".join(str(wrong or "").split()), " ".join(str(right or "").split())))
        conn.commit()
        conn.close()


def usage() -> Dict[int, int]:
    """How many recordings hold each word of the dictionary in their transcript (the word as a phrase of
    the full-text index, any of its forms that start the same way)."""
    terms = list_dictionary(active_only=False)
    out: Dict[int, int] = {}
    with _db_lock:
        conn = get_connection()
        for d in terms:
            tokens = re.findall(r"\w+", str(d.get("term") or "").casefold())[:8]
            if not tokens:
                out[int(d["id"])] = 0
                continue
            phrase = '"' + " ".join(tokens) + '"*'
            try:
                n = conn.execute("SELECT count(DISTINCT meeting_id) FROM segments_fts WHERE segments_fts MATCH ?",
                                 (phrase,)).fetchone()[0]
            except Exception:  # a term the index cannot read as a phrase counts nothing rather than failing the page
                n = 0
            out[int(d["id"])] = int(n or 0)
        conn.close()
    return out
