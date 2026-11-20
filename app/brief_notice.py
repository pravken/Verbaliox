"""
A few minutes before a calendar meeting: a Windows notification (Settings → Календарь, meet_notify).
Every meeting (a reminder); a meeting with a link to its call: the click joins it (Teams, Zoom, Meet, Webex: app/meeting_join.py),
asked by the user so as not to look for the meeting in the calendar. Without one, a meeting that
continues a series (or a person met before) tells what is still open from last time and the click opens
the brief (app/series.py brief). Nothing is sent to the analysis model until the user asks for the brief.
"""

import threading
import time
import traceback
from datetime import datetime, timedelta
from typing import Set

AHEAD_MIN = 5          # minutes before the meeting
CHECK_SEC = 60.0
_told: Set[str] = set()  # meetings told about already (uid|start)


def due(now: datetime):
    """The calendar meetings that start in AHEAD_MIN minutes (± a check), not told about yet."""
    from app import calendar_ics

    out = []
    for e in calendar_ics.window(now + timedelta(minutes=AHEAD_MIN - 1), now + timedelta(minutes=AHEAD_MIN + 1)):
        if not calendar_ics.is_meeting(e):  # a long block, or one the user said is no meeting
            continue
        key = f"{e.get('uid') or e['title']}|{e['start'].isoformat(timespec='minutes')}"
        if key in _told or e["start"] <= now:
            continue
        out.append((key, e))
    return out


def check(now: datetime = None) -> int:
    from app import app_status, series
    from app.database import get_all_settings

    from app.meeting_join import service

    s = get_all_settings()
    if not (s.get("calendar_ics") or "").strip() or s.get("meet_notify") == "false":
        return 0
    n = 0
    for key, e in due(now or datetime.now()):
        _told.add(key)
        info = series.before_meeting(e["title"], e.get("attendees") or [])
        join = e.get("join") or ""
        when = e["start"].strftime("%H:%M")
        parts = []
        if info:
            tasks = info["open_tasks"]
            parts.append((f"Открытых задач с прошлых встреч: {tasks}. " if tasks else "") +
                         f"Прошлый раз: «{info['last']['title']}», {info['last']['date']}.")
        if join:
            parts.append(f"Нажмите — подключиться в {service(join)}")
            target = f"join:{join}"
        elif info:
            parts.append("Нажмите — бриф перед встречей")
            target = f"brief:series:{info['series_id']}" if info["series_id"] else f"brief:person:{info['person']}"
        else:  # a meeting with nothing to tell but itself: a reminder, the click opens «Главная»
            parts.append(f"Через {AHEAD_MIN} минут. Нажмите — открыть «Главную»")
            target = "dashboard"
        app_status.add_notice(f"В {when} — «{e['title'][:60]}»", " ".join(parts), target)
        n += 1
    if len(_told) > 500:
        _told.clear()
    return n


def loop() -> None:
    while True:
        time.sleep(CHECK_SEC)
        try:
            check()
        except Exception:
            traceback.print_exc()


def start() -> None:
    threading.Thread(target=loop, daemon=True, name="brief_notice").start()
