"""
Windows notifications of calendar meetings (Settings → Календарь, meet_notify), asked by the user:

- a reminder ahead of the meeting, as long ahead as the user chose (meet_notify_before: 30 seconds to
  15 minutes; 0 = none). A meeting that continues a series (or a person met before) tells what is still
  open from last time, and its click opens the brief (app/series.py brief); otherwise «Главная».
- at the meeting's start, a notification whose click joins its call (Teams, Zoom, Meet, Webex:
  app/meeting_join.py; the link of the invitation), so as not to look for the meeting in the calendar.
  A meeting without a link gets none then.

Nothing is sent to the analysis model until the user asks for the brief.
"""

import threading
import time
import traceback
from datetime import datetime, timedelta
from typing import Dict

CHECK_SEC = 5.0        # the notices come within seconds of their time
LATE_SEC = 120         # a notice more than this late (the app was closed, the computer asleep) is not sent
_told: Dict[str, datetime] = {}  # notices sent already ("before|key", "start|key") and the meeting's start


def _lead_sec(settings) -> int:
    try:
        return max(0, min(3600, int(float(settings.get("meet_notify_before", "300") or 0))))
    except ValueError:
        return 300


def _plural(n: int, one: str, few: str, many: str) -> str:
    return one if n % 10 == 1 and n % 100 != 11 else few if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else many


def _ahead_text(sec: float) -> str:
    """«Через 30 секунд», «Через 2 минуты»: the time left, as the reminder is shown."""
    if sec < 60:
        n = max(1, int(round(sec)))
        return f"Через {n} {_plural(n, 'секунду', 'секунды', 'секунд')}"
    n = int(round(sec / 60))
    return f"Через {n} {_plural(n, 'минуту', 'минуты', 'минут')}"


def due(now: datetime, lead: int):
    """[(kind, key, event)]: "before" when the reminder is due, "start" when the meeting begins."""
    from app import calendar_ics

    out = []
    for e in calendar_ics.window(now - timedelta(seconds=LATE_SEC), now + timedelta(seconds=lead + 60)):
        if not calendar_ics.is_meeting(e):  # a long block, or one the user said is no meeting
            continue
        key = f"{e.get('uid') or e['title']}|{e['start'].isoformat(timespec='minutes')}"
        to_start = (e["start"] - now).total_seconds()
        if lead and 0 < to_start <= lead and to_start > lead - LATE_SEC and f"before|{key}" not in _told:
            out.append(("before", key, e))
        if e.get("join") and -LATE_SEC <= to_start <= 0 and f"start|{key}" not in _told:
            out.append(("start", key, e))
    return out


def check(now: datetime = None) -> int:
    from app import app_status, series
    from app.database import get_all_settings
    from app.meeting_join import service

    s = get_all_settings()
    if not (s.get("calendar_ics") or "").strip() or s.get("meet_notify") == "false":
        return 0
    now = now or datetime.now()
    n = 0
    index = None
    for kind, key, e in due(now, _lead_sec(s)):
        _told[f"{kind}|{key}"] = e["start"]
        when = e["start"].strftime("%H:%M")
        title = e["title"][:60]
        join = e.get("join") or ""
        if kind == "start":
            app_status.add_notice(f"Начинается — «{title}»", f"Нажмите — подключиться в {service(join)}", f"join:{join}")
            n += 1
            continue
        index = index or series.EventIndex()  # the library read once for the meetings starting together
        info = series.before_meeting(e["title"], e.get("attendees") or [], index=index)
        parts = [f"{_ahead_text((e['start'] - now).total_seconds())}."]
        if info:
            tasks = info["open_tasks"]
            parts.append((f"Открытых задач с прошлых встреч: {tasks}. " if tasks else "") +
                         f"Прошлый раз: «{info['last']['title']}», {info['last']['date']}. Нажмите — бриф перед встречей")
            target = f"brief:series:{info['series_id']}" if info["series_id"] else f"brief:person:{info['person']}"
        else:
            parts.append("Нажмите — открыть «Главную»")
            target = "dashboard"
        if join:
            parts.append(f"Ссылка на {service(join)} придёт в начале встречи")
        app_status.add_notice(f"В {when} — «{title}»", " ".join(parts), target)
        n += 1
    # meetings started more than a day ago are not asked about again: their notices are forgotten
    for k in [k for k, at in _told.items() if at < now - timedelta(days=1)]:
        del _told[k]
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
