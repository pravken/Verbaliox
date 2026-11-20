"""
Recordings whose transcription the user cancelled and that were never transcribed after (asked by the user:
remind of them and offer to transcribe). Shown on the dashboard with «Расшифровать» and «Не напоминать»,
and once a day as a Windows notification, never during a meeting (app/meeting_guard.py).

Only a cancel: a failed job has its own error and «Повторить»; a recording imported without recognition
(«added») was meant so. The file must still be there (a cancelled download by link has none).
"""

import time
from pathlib import Path
from typing import Any, Dict, List

NOTICE_EVERY_SEC = 24 * 3600
CHECK_EVERY_SEC = 30 * 60
_state = {"checked": 0.0, "noticed": 0.0}


def _dismissed(conn) -> set:
    conn.execute("CREATE TABLE IF NOT EXISTS untranscribed_dismissed (meeting_id INTEGER PRIMARY KEY)")
    return {int(r[0]) for r in conn.execute("SELECT meeting_id FROM untranscribed_dismissed")}


def items() -> List[Dict[str, Any]]:
    """The recordings to remind of, newest first: {id, title, recorded_at, duration}."""
    from app.database import _db_lock, get_connection

    with _db_lock:
        conn = get_connection()
        hidden = _dismissed(conn)
        conn.commit()
        rows = conn.execute(
            "SELECT id, title, media_path, recorded_at, created_at, duration FROM meetings "
            # never finished: a cancel mid-recognition keeps the phrases saved so far (has_transcript is 1),
            # but no transcript was made (its model is set when one is)
            "WHERE status = 'cancelled' AND COALESCE(transcript_model, '') = '' "
            "ORDER BY COALESCE(recorded_at, created_at) DESC").fetchall()
        conn.close()
    out = []
    for r in rows:
        if int(r["id"]) in hidden or not r["media_path"] or not Path(r["media_path"]).is_file():
            continue
        out.append({"id": int(r["id"]), "title": r["title"] or "", "recorded_at": r["recorded_at"] or r["created_at"] or "",
                    "duration": float(r["duration"] or 0)})
    return out


def dismiss(ids: List[int]) -> int:
    """«Не напоминать»: these recordings are not shown again (they stay in the library as they are)."""
    from app.database import _db_lock, get_connection

    with _db_lock:
        conn = get_connection()
        _dismissed(conn)
        conn.executemany("INSERT OR IGNORE INTO untranscribed_dismissed (meeting_id) VALUES (?)", [(int(i),) for i in ids])
        conn.commit()
        conn.close()
    return len(ids)


def transcribe(ids: List[int]) -> int:
    """«Расшифровать»: each of them to the queue, as «Повторить» does. Returns how many went."""
    from app.database import update_meeting_progress
    from app.transcriber import enqueue_meeting_job, is_job_active

    wanted = {int(i) for i in ids}
    n = 0
    for it in items():
        if it["id"] not in wanted or is_job_active(it["id"]):
            continue
        update_meeting_progress(it["id"], status="queued", progress=0, stage_text="В очереди на распознавание", error_message="")
        if enqueue_meeting_job(it["id"]):
            n += 1
    return n


def notice_tick(now: float = 0.0) -> bool:
    """Called by the meeting watch (app/meeting_guard): a Windows notification at most once a day, when
    there are such recordings and no meeting is going on. True when one was given."""
    now = now or time.time()
    if now < _state["checked"] or now < _state["noticed"]:  # the clock was set back: not silent until it catches up
        _state["checked"] = _state["noticed"] = 0.0
    if now - _state["checked"] < CHECK_EVERY_SEC or now - _state["noticed"] < NOTICE_EVERY_SEC:
        return False
    _state["checked"] = now
    from app import meeting_guard

    if meeting_guard.busy():
        return False
    found = items()
    if not found:
        return False
    _state["noticed"] = now
    from app import app_status

    n = len(found)
    title = "Есть нерасшифрованные записи" if n > 1 else "Есть нерасшифрованная запись"
    text = f"«{found[0]['title'][:60]}»" + (f" и ещё {n - 1}" if n > 1 else "") + " — расшифровка была отменена. Нажмите, чтобы расшифровать"
    app_status.add_notice(title, text, "dashboard")
    return True
