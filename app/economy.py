"""
«Режим экономии» (asked by the user, from the tray icon's menu or Settings → Общие): only recording works,
no model takes the processor or the memory. While it is on:
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
    return (settings.get("economy_mode") or "false").lower() == "true"


def set_mode(enabled: bool) -> bool:
    from app.database import update_settings

    update_settings({"economy_mode": "true" if enabled else "false"})
    applied(enabled)
    return bool(enabled)


def applied(enabled: bool) -> None:
    """What turning it on or off does at once (the setting is already saved)."""
    print(f"[economy] {'on: recording only' if enabled else 'off'}", flush=True)
    from app import events, meeting_guard, transcriber

    events.publish({"type": "economy", "on": bool(enabled)})  # the page: the status bar, the captions
    transcriber.wake_queue()  # off: the waiting jobs start
    meeting_guard.kick()  # on: the analysis is broken off and its models unloaded; off: it follows
    if enabled:
        def unload() -> None:
            try:
                from app import idle_unload, live

                live.stop_all()  # the captions of a recording going on stop (its sound is still recorded)

                idle_unload.unload_now()
            except Exception:
                traceback.print_exc()

        threading.Thread(target=unload, daemon=True, name="economy_unload").start()
