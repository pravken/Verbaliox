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

The transcription waits the same way (reported by the user: a recording finished as the next meeting began,
and its transcription loaded Parakeet and the speaker models during the call — the computer froze and the
screen could not be shared): the queue holds the automatic transcriptions while a meeting goes on and
QUIET_SEC after it (holds_queue), and the speech models loaded are released when a meeting begins, unless
a job is running. What the user starts by hand in the queue (a translation, a dub, a new split) goes on.

What the user starts by hand (the «Анализ» button, a question) is never held back.
Settings → «Не мешать на встречах» (analysis_after_meetings, on by default).
"""

import threading
import time
import traceback
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional, Set

POLL_SEC = 20.0
QUIET_SEC = 120.0  # without a meeting this long: the next one did not start right after, the analysis can go
RECORDING_STALE_SEC = 10 * 3600  # «recording» reported this long ago: the page did not say it stopped

_lock = threading.Lock()
_running: Dict[int, int] = {}  # recording → the thread its automatic analysis runs on
_interrupted: Set[int] = set()  # recordings whose analysis a meeting broke off
_state = {"busy": "", "quiet_since": 0.0, "started": False, "ended": 0.0, "looked": False}
_sent: Set[int] = set()  # marked recordings sent to the queue since the last meeting: once each, not every poll


def enabled(settings: Optional[Dict[str, str]] = None) -> bool:
    if settings is None:
        from app.database import get_all_settings

        settings = get_all_settings()
    return (settings.get("analysis_after_meetings") or "true").lower() == "true"


# The calendar's meetings the user left early: its recording was stopped during it (asked by the user: the mix
# waited for the end of a meeting the calendar still showed). Such a meeting holds nothing any more while no call app
# holds the microphone. event key → when its recording stopped
_left: Dict[str, float] = {}


def recording_ended(now: Optional[float] = None) -> None:
    """Called when the app's own recording stops: the calendar's meeting going on now is taken for left."""
    now = time.time() if now is None else now
    try:
        from app import calendar_ics

        e = calendar_ics.current_meeting(cached=True)
        if e:
            with _lock:
                for k in [k for k, at in _left.items() if now - at > 24 * 3600]:
                    _left.pop(k, None)
                _left[_event_key(e)] = now
            print("[meeting_guard] the recording stopped during a calendar meeting: it holds nothing while no call goes on", flush=True)
    except Exception:
        traceback.print_exc()


def _event_key(e: Dict[str, Any]) -> str:
    try:
        from app import calendar_ics

        return calendar_ics.event_key(e)
    except Exception:
        return str(e.get("uid") or e.get("title") or "")


def _in_call() -> bool:
    """A call app or a browser holds the microphone: the user is still in a meeting (Windows; elsewhere not known)."""
    try:
        from app import call_watch

        return bool(call_watch.meeting_app(call_watch.apps_using_microphone()))
    except Exception:
        return False


def busy(settings: Optional[Dict[str, str]] = None, cached_calendar: bool = False) -> str:
    """Why the analysis waits: "economy" (recording only, app/economy.py), "recording", "calendar", or ""
    (no meeting, or the setting is off). cached_calendar: the calendar as read already, never read now."""
    from app import economy

    if economy.on(settings):
        return "economy"
    if not enabled(settings):
        return ""
    from app.app_status import _ui

    if _ui.get("recording") and time.time() - float(_ui.get("since") or 0) < RECORDING_STALE_SEC:
        return "recording"
    try:
        from app import calendar_ics

        e = calendar_ics.current_meeting(cached=True) if cached_calendar else calendar_ics.current_meeting()
        if e:
            with _lock:
                left = _event_key(e) in _left
            if not (left and not _in_call()):
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

    # under the lock: guard() leaves _running under it too, so a thread is aborted only while its analysis
    # still runs (not after it reset the abort, nor once the next job took the thread)
    with _lock:
        running = dict(_running)
        _interrupted.update(running)
        for thread_id in running.values():
            cancel_scope.abort(thread_id)
    return list(running)


def _unload_models() -> List[str]:
    """The analysis models this app loaded out of memory, gently (no runner is killed). Not while the user's
    own analysis or question is being answered, nor while live captions run (their translation may use
    Ollama): what the user started by hand is never held back. Other programs' models are left alone."""
    try:
        from app import idle_unload, live
        from app.ollama_client import analysis_running
        from app.vram import ollama_loaded, ollama_unload

        if analysis_running() or live.has_sessions():
            return []
        with idle_unload._lock:
            ours = set(idle_unload._ollama_used)
        names = [m["name"] for m in ollama_loaded() if m["name"] in ours]
        if names:
            ollama_unload(names, force=False)
        return names
    except Exception:
        traceback.print_exc()
        return []


def holds_queue(now: Optional[float] = None) -> bool:
    """Whether the automatic transcriptions wait: a meeting goes on, or one ended less than QUIET_SEC ago
    (the next one often starts right after). «Только запись» holds the whole queue by itself (app/economy)."""
    now = time.time() if now is None else now
    with _lock:
        looked = _state["looked"]
    if not looked:  # just started (a recording recovered, jobs resumed): asked now, not after the first poll
        # The calendar only as read already: the queue asks under its lock, and a read now (Outlook up to 90 s,
        # a link up to 60 s) held every new job meanwhile (found in the review)
        try:
            return busy(cached_calendar=True) not in ("", "economy")
        except Exception:
            return False
    with _lock:
        if _state["busy"] and _state["busy"] != "economy":
            return True
        return bool(_state["ended"]) and now - _state["ended"] < QUIET_SEC


def hold_reason() -> Dict[str, str]:
    """What holds the queue now, for the page (asked by the user: «откуда эта пауза»): an own recording, or the
    calendar's meeting with its title and end. {} when nothing, or not known."""
    with _lock:
        kind = _state["busy"]
    if kind == "recording":
        return {"kind": "recording"}
    if kind == "calendar":
        try:
            from app import calendar_ics

            e = calendar_ics.current_meeting(cached=True)
            if e:
                return {"kind": "calendar", "title": str(e.get("title") or "")[:120], "end": e["end"].strftime("%H:%M")}
        except Exception:
            pass
        return {"kind": "calendar"}
    return {}


def hold_until(now: Optional[float] = None) -> Optional[float]:
    """What holds_queue() says, with when it ends: None — nothing is held; 0.0 — a meeting goes on (its end
    is not known); a time — QUIET_SEC after the end of the last meeting. The page counts down to it."""
    now = time.time() if now is None else now
    with _lock:
        looked = _state["looked"]
    if not looked:
        try:
            return 0.0 if busy(cached_calendar=True) not in ("", "economy") else None
        except Exception:
            return None
    with _lock:
        if _state["busy"] and _state["busy"] != "economy":
            return 0.0
        if _state["ended"] and now - _state["ended"] < QUIET_SEC:
            return float(_state["ended"]) + QUIET_SEC
    return None


def _release_speech() -> List[str]:
    """The speech models out of memory as a meeting begins, when no job uses them (one running finishes)."""
    try:
        from app import idle_unload, transcriber

        if transcriber.running_job_kind():
            return []
        return idle_unload.release_speech_models()
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
        _state["looked"] = True
        if reason:
            _state["quiet_since"] = 0.0
            _sent.clear()  # after this meeting they are tried again
        elif was or not _state["quiet_since"]:
            _state["quiet_since"] = now
        if was and not reason:
            _state["ended"] = now
        quiet_for = now - _state["quiet_since"] if not reason else 0.0
    if reason and not was:
        broken = _break_off()
        # only when an analysis was broken off, or recording only was asked for: a calendar event coming
        # does not take the model from the user's own work
        unloaded = _unload_models() if (broken or reason == "economy") else []
        unloaded += _release_speech()
        print(f"[meeting_guard] a meeting began ({reason}): analysis broken off {broken or '-'}, "
              f"unloaded {unloaded or '-'}", flush=True)
    if was and not reason:
        from app import transcriber

        transcriber.wake_queue()  # the transcriptions held back start after QUIET_SEC (the queue looks every 5 s)
    if not reason and quiet_for >= QUIET_SEC:
        from app import transcriber

        for meeting_id in pending():
            with _lock:
                if meeting_id in _sent:
                    continue
            if not transcriber.is_job_active(meeting_id) and transcriber.enqueue_analysis_job(meeting_id):
                with _lock:
                    _sent.add(meeting_id)
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
        try:  # «Только запись» for a time: turned off when it is over
            from app import economy

            economy.tick()
        except Exception:
            traceback.print_exc()
        try:  # recordings whose transcription was cancelled: a reminder, never during a meeting
            from app import untranscribed

            untranscribed.notice_tick()
        except Exception:
            traceback.print_exc()
        time.sleep(POLL_SEC)


def start() -> None:
    with _lock:
        if _state["started"]:
            return
        _state["started"] = True
    threading.Thread(target=_loop, daemon=True, name="meeting_guard").start()
