"""
The analysis model waits for the end of a meeting (asked by the user: meeting after meeting, the analysis of
the last one slowed the whole computer during the next).

A meeting is going on while this app records, or while the calendar has one now or within 10 minutes
(app/calendar_ics.current_meeting): the calendar alone is not always right, the recording is the sure sign.
Then:
- the automatic analysis after a transcription does not start: the recording is marked to be analysed later
  (the table deferred_analysis, so it survives a restart);
- an analysis that runs is broken off (app/cancel_scope) and marked the same way, and the analysis models
  are unloaded from memory (Ollama: keep_alive 0), once, when the meeting begins;
- after QUIET_SEC without a meeting, the marked recordings are analysed one by one in the queue.

What the user starts by hand (the «Анализ» button, a question) is never held back.
Settings → ИИ-анализ → «Анализ — после встречи» (analysis_after_meetings, on by default).
"""

import threading
import time
import traceback
from contextlib import contextmanager
from typing import Dict, Iterator, List, Optional, Set

POLL_SEC = 20.0
QUIET_SEC = 120.0  # without a meeting this long: the next one did not start right after, the analysis can go
RECORDING_STALE_SEC = 10 * 3600  # «recording» reported this long ago: the page did not say it stopped

_lock = threading.Lock()
_running: Dict[int, int] = {}  # recording → the thread its automatic analysis runs on
_interrupted: Set[int] = set()  # recordings whose analysis a meeting broke off
_state = {"busy": "", "quiet_since": 0.0, "started": False}


def enabled(settings: Optional[Dict[str, str]] = None) -> bool:
    if settings is None:
        from app.database import get_all_settings

        settings = get_all_settings()
    return (settings.get("analysis_after_meetings") or "true").lower() == "true"


def busy(settings: Optional[Dict[str, str]] = None) -> str:
    """Why the analysis waits: "recording", "calendar", or "" (no meeting, or the setting is off)."""
    if not enabled(settings):
        return ""
    from app.app_status import _ui

    if _ui.get("recording") and time.time() - float(_ui.get("since") or 0) < RECORDING_STALE_SEC:
        return "recording"
    try:
        from app import calendar_ics

        if calendar_ics.current_meeting():
            return "calendar"
    except Exception:
        pass
    return ""


# --- the recordings to analyse later ---
def _table(conn) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS deferred_analysis (meeting_id INTEGER PRIMARY KEY, since TEXT NOT NULL)")


def defer(meeting_id: int) -> None:
    from app.database import _db_lock, get_connection

    with _db_lock:
        conn = get_connection()
        _table(conn)
        conn.execute("INSERT OR IGNORE INTO deferred_analysis (meeting_id, since) VALUES (?, datetime('now'))", (int(meeting_id),))
        conn.commit()
        conn.close()
    print(f"[meeting_guard] meeting {meeting_id}: the analysis waits for the end of the meeting", flush=True)


def done(meeting_id: int) -> None:
    from app.database import _db_lock, get_connection

    with _db_lock:
        conn = get_connection()
        _table(conn)
        conn.execute("DELETE FROM deferred_analysis WHERE meeting_id = ?", (int(meeting_id),))
        conn.commit()
        conn.close()


def pending() -> List[int]:
    """The marked recordings that still exist, oldest first (a deleted one is forgotten)."""
    from app.database import _db_lock, get_connection

    with _db_lock:
        conn = get_connection()
        _table(conn)
        ids = [int(r[0]) for r in conn.execute(
            "SELECT d.meeting_id FROM deferred_analysis d JOIN meetings m ON m.id = d.meeting_id ORDER BY d.since, d.meeting_id")]
        conn.execute("DELETE FROM deferred_analysis WHERE meeting_id NOT IN (SELECT id FROM meetings)")
        conn.commit()
        conn.close()
    return ids


# --- the analysis running now ---
@contextmanager
def guard(meeting_id: int) -> Iterator[None]:
    """Around an automatic analysis: a meeting that begins meanwhile breaks it off (see interrupted())."""
    with _lock:
        _running[meeting_id] = threading.get_ident()
        _interrupted.discard(meeting_id)
    try:
        yield
    finally:
        with _lock:
            _running.pop(meeting_id, None)


def interrupted(meeting_id: int) -> bool:
    with _lock:
        return meeting_id in _interrupted


def clear_interrupted(meeting_id: int) -> None:
    with _lock:
        _interrupted.discard(meeting_id)


def _break_off() -> List[int]:
    from app import cancel_scope

    with _lock:
        running = dict(_running)
        _interrupted.update(running)
    for thread_id in running.values():
        cancel_scope.abort(thread_id)
    return list(running)


def _unload_models() -> List[str]:
    """The analysis models out of memory (a model Ollama keeps on this computer)."""
    try:
        from app.vram import ollama_loaded, ollama_unload

        names = [m["name"] for m in ollama_loaded()]
        if names:
            ollama_unload(names)
        return names
    except Exception:
        traceback.print_exc()
        return []


def check(now: Optional[float] = None) -> str:
    """One look: a meeting begins → the analysis is broken off and its model unloaded; no meeting for
    QUIET_SEC → the marked recordings go to the queue. Returns the reason the analysis waits ("" = none)."""
    now = time.time() if now is None else now
    reason = busy()
    with _lock:
        was = _state["busy"]
        _state["busy"] = reason
        if reason:
            _state["quiet_since"] = 0.0
        elif was or not _state["quiet_since"]:
            _state["quiet_since"] = now
        quiet_for = now - _state["quiet_since"] if not reason else 0.0
    if reason and not was:
        broken = _break_off()
        unloaded = _unload_models()
        print(f"[meeting_guard] a meeting began ({reason}): analysis broken off {broken or '-'}, "
              f"unloaded {unloaded or '-'}", flush=True)
    if not reason and quiet_for >= QUIET_SEC:
        from app import transcriber

        for meeting_id in pending():
            if not transcriber.is_job_active(meeting_id):
                transcriber.enqueue_analysis_job(meeting_id)
    return reason


def kick() -> None:
    """The page said a recording began or ended: looked at now, not at the next poll."""
    threading.Thread(target=_safe_check, daemon=True, name="meeting_guard_kick").start()


def _safe_check() -> None:
    try:
        check()
    except Exception:
        traceback.print_exc()


def _loop() -> None:
    while True:
        _safe_check()
        time.sleep(POLL_SEC)


def start() -> None:
    with _lock:
        if _state["started"]:
            return
        _state["started"] = True
    threading.Thread(target=_loop, daemon=True, name="meeting_guard").start()
