"""
«Только запись» (the setting economy_mode; asked by the user, from the tray icon's menu or Settings → Общие):
only recording works, no model takes the processor or the memory, until it is turned off or for a time
(economy_until: 30 minutes, an hour, two, four, the end of the day). While it is on:
- the job queue does not start the next job (a transcription, a translation...): they wait for the mode to end;
  the job running when it was turned on finishes;
- the analysis waits as during a meeting (app/meeting_guard.busy says "economy"): one running is broken off,
  the analysis models are unloaded;
- the speech models are unloaded, the live captions are not started (the page asks /api/system),
  the microphone is not cleaned by DeepFilterNet when a recording is saved (the echo is still removed);
- the Teams captions are still read: they are no model, and the names and the text go with the recording.
Turned off: the queue goes on, the waiting analyses follow two minutes later.
"""

import threading
import traceback
from typing import Dict, Optional


def on(settings: Optional[Dict[str, str]] = None) -> bool:
    if settings is None:
        try:
            from app.database import get_all_settings

            settings = get_all_settings()
        except Exception:
            return False
    if (settings.get("economy_mode") or "false").lower() != "true":
        return False
    return not expired(settings)


DURATIONS = {"0": 0, "30": 30, "60": 60, "120": 120, "240": 240, "day": -1}


def until_for(choice: str, now: Optional[float] = None) -> float:
    """The moment «Только запись» ends for a choice of its time ("0": when turned off; "day": midnight)."""
    import time
    from datetime import datetime, timedelta

    now = time.time() if now is None else now
    minutes = DURATIONS.get(str(choice or "0"), 0)
    if minutes == 0:
        return 0.0
    if minutes < 0:
        d = datetime.fromtimestamp(now)
        return (datetime(d.year, d.month, d.day) + timedelta(days=1)).timestamp()
    return now + minutes * 60


def until(settings: Optional[Dict[str, str]] = None) -> float:
    if settings is None:
        from app.database import get_all_settings

        settings = get_all_settings()
    try:
        return float(settings.get("economy_until") or 0)
    except ValueError:
        return 0.0


def expired(settings: Optional[Dict[str, str]] = None) -> bool:
    import time

    end = until(settings)
    return bool(end) and time.time() >= end


def set_mode(enabled: bool, choice: str = "0") -> bool:
    """On (for a time: DURATIONS) or off."""
    from app.database import update_settings

    end = until_for(choice) if enabled else 0.0
    update_settings({"economy_mode": "true" if enabled else "false", "economy_until": f"{end:.0f}" if end else ""})
    applied(enabled)
    return bool(enabled)


def tick() -> None:
    """Its time is over: turned off, the queue and the analysis go on (app/meeting_guard's loop)."""
    from app.database import get_all_settings

    settings = get_all_settings()
    if (settings.get("economy_mode") or "false").lower() == "true" and expired(settings):
        print("[economy] its time is over", flush=True)
        set_mode(False)


def applied(enabled: bool) -> None:
    """What turning it on or off does at once (the setting is already saved)."""
    print(f"[economy] {'on: recording only' if enabled else 'off'}", flush=True)
    from app import events, meeting_guard, transcriber

    events.publish({"type": "economy", "on": bool(enabled), "until": until() if enabled else 0})  # the page: the status bar, the captions
    transcriber.wake_queue()  # off: the waiting jobs start
    meeting_guard.kick()  # on: the analysis is broken off and its models unloaded; off: it follows
    if enabled:
        def unload() -> None:
            import time

            try:
                from app import dictation, idle_unload, live

                live.stop_all()  # the captions of a recording going on stop (its sound is still recorded)
                # the job running finishes with its models (unloading them now frees nothing and makes it
                # load them again), and a dictation the user is speaking keeps its model: unloaded after
                while on() and (transcriber.running_job_kind() or dictation._state.get("active")
                                or dictation._state.get("busy")):
                    time.sleep(5)
                if on():
                    idle_unload.unload_now()
            except Exception:
                traceback.print_exc()

        threading.Thread(target=unload, daemon=True, name="economy_unload").start()
