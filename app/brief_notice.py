"""
Windows notifications of calendar meetings (Settings → Календарь, meet_notify), asked by the user:

- a reminder ahead of the meeting, as long ahead as the user chose (meet_notify_before: 30 seconds to
  15 minutes; 0 = none). A meeting that continues a series (or a person met before) tells what is still
  open from last time, and its click opens the brief (app/series.py brief); otherwise «Главная».
- at the meeting's start, a notification whose click joins its call (Teams, Zoom, Meet, Webex:
  app/meeting_join.py; the link of the invitation), so as not to look for the meeting in the calendar.
  A meeting without a link gets none then.

Nothing is sent to the analysis model until the user asks for the brief.

A meeting moved or cancelled in the calendar is not reminded of at its old time (reported by the user): the
calendar is read afresh shortly before each notice and before each meeting's start (keep_fresh: PREFETCH_SEC
ahead, in a thread of its own, as Outlook may take up to 90 s), and a notice waits for that read up to
WAIT_SEC. The read finds the meeting gone or at another time: no notice now (the new time has its own). The
read failed or took longer: the notice comes by the calendar read before, and the log says so (no titles).
"""

import threading
import time
import traceback
from datetime import datetime, timedelta
from typing import Dict, List

from app.ui_lang import count, tr

CHECK_SEC = 5.0        # the notices come within seconds of their time
LATE_SEC = 120         # a notice more than this late (the app was closed, the computer asleep) is not sent
FRESH_SEC = 180       # a calendar read this long before a notice (or a meeting's start) is fresh enough for it
PREFETCH_SEC = 120    # the fresh read starts this long before
WAIT_SEC = 60         # a notice waits this long past its time for a read still running
TRY_SEC = 30          # keep_fresh asks for a read at most this often (a failed Outlook is not read again: calendar_ics)
_told: Dict[str, datetime] = {}  # notices sent already ("before|key", "start|key") and the meeting's start
_tried = {"at": 0.0}


def _lead_sec(settings) -> int:
    try:
        return max(0, min(3600, int(float(settings.get("meet_notify_before", "300") or 0))))
    except ValueError:
        return 300


def _ahead_text(sec: float) -> str:
    """«Через 30 секунд», «Через 2 минуты» ("In 2 minutes"): the time left, as the reminder is shown."""
    if sec < 60:
        left = count(max(1, int(round(sec))), "секунду", "секунды", "секунд", "second", "seconds")
    else:
        left = count(int(round(sec / 60)), "минуту", "минуты", "минут", "minute", "minutes")
    return tr(f"Через {left}", f"In {left}")


def due(now: datetime, lead: int):
    """[(kind, key, event)]: "before" when the reminder is due, "start" when the meeting begins."""
    from app import calendar_ics

    out = []
    # what was read already: the reads themselves come from keep_fresh, in a thread of their own
    for e in calendar_ics.window(now - timedelta(seconds=LATE_SEC), now + timedelta(seconds=lead + 60), cached=True):
        if not calendar_ics.is_meeting(e):  # a long block, or one the user said is no meeting
            continue
        key = f"{e.get('uid') or e['title']}|{e['start'].isoformat(timespec='minutes')}"
        to_start = (e["start"] - now).total_seconds()
        if lead and 0 < to_start <= lead and to_start > lead - LATE_SEC and f"before|{key}" not in _told:
            out.append(("before", key, e))
        if e.get("join") and -LATE_SEC <= to_start <= 0 and f"start|{key}" not in _told:
            out.append(("start", key, e))
    return out


def _points(now: datetime, lead: int, notify: bool) -> List[datetime]:
    """The times the calendar must be fresh at: the meetings' starts (the notice with the call's link, the
    recording of the page by itself, app/meeting_guard.py) and the reminders before them."""
    from app import calendar_ics

    out = []
    for e in calendar_ics.window(now - timedelta(seconds=LATE_SEC), now + timedelta(seconds=lead + PREFETCH_SEC + 60), cached=True):
        if not calendar_ics.is_meeting(e):
            continue
        out.append(e["start"])
        if notify and lead:
            out.append(e["start"] - timedelta(seconds=lead))
    return out


def keep_fresh(now: datetime = None) -> bool:
    """Starts a calendar read when one is due (True): PREFETCH_SEC before a notice or a meeting's start, and
    every SOON_CACHE_SEC while a meeting starts within the hour (CACHE_SEC otherwise). Never waits for it."""
    from app import calendar_ics
    from app.database import get_all_settings

    s = get_all_settings()
    if not (s.get("calendar_ics") or "").strip():
        return False
    now = now or datetime.now()
    state = calendar_ics.read_state()
    if state["reading"] or time.time() - _tried["at"] < TRY_SEC:
        return False
    lead = _lead_sec(s)
    age = None
    for t in _points(now, lead, s.get("meet_notify") != "false"):
        if t - timedelta(seconds=PREFETCH_SEC) <= now < t + timedelta(seconds=WAIT_SEC) \
                and state["at"] < (t - timedelta(seconds=FRESH_SEC)).timestamp():
            age = 0.0
            break
    if age is None:
        soon = [e for e in calendar_ics.window(now, now + timedelta(hours=calendar_ics.SOON_HOURS), cached=True)
                if calendar_ics.is_meeting(e)]
        age = calendar_ics.SOON_CACHE_SEC if soon else calendar_ics.CACHE_SEC
        if time.time() - state["at"] < age:
            return False
    _tried["at"] = time.time()
    return calendar_ics.refresh_async(age)


def _fresh_for(at: datetime, now: datetime) -> str:
    """"" when the calendar was read afresh for a notice due at `at`; "wait" while its read runs; otherwise why
    not (for the log, the notice then comes by the calendar read before)."""
    from app import calendar_ics

    state = calendar_ics.read_state()
    since = (at - timedelta(seconds=FRESH_SEC)).timestamp()
    if state["ok_at"] >= since:
        return ""
    if state["reading"]:
        return "wait" if now < at + timedelta(seconds=WAIT_SEC) else f"no answer within {WAIT_SEC} s"
    return "the read failed" if state["at"] >= since else "not read"


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
    lead = _lead_sec(s)
    for kind, key, e in due(now, lead):
        why = _fresh_for(e["start"] - timedelta(seconds=lead if kind == "before" else 0), now)
        if why == "wait":  # the calendar is being read: the meeting may have moved
            continue
        if why:
            print(f"[brief_notice] the calendar was not read afresh before a notice ({why}): sent by the calendar read before",
                  flush=True)
        _told[f"{kind}|{key}"] = e["start"]
        when = e["start"].strftime("%H:%M")
        title = e["title"][:60]
        join = e.get("join") or ""
        if kind == "start":
            svc = service(join)
            app_status.add_notice(tr(f"Начинается — «{title}»", f"Starting now: “{title}”"),
                                  tr(f"Нажмите — подключиться в {svc}", f"Click to join in {svc}" if svc else "Click to join"),
                                  f"join:{join}")
            n += 1
            continue
        index = index or series.EventIndex()  # the library read once for the meetings starting together
        info = series.before_meeting(e["title"], e.get("attendees") or [], index=index)
        parts = [f"{_ahead_text((e['start'] - now).total_seconds())}."]
        if info:
            tasks = info["open_tasks"]
            last, date = info["last"]["title"], info["last"]["date"]
            parts.append(tr((f"Открытых задач с прошлых встреч: {tasks}. " if tasks else "") +
                            f"Прошлая встреча: «{last}», {date}. Нажмите — бриф перед встречей",
                            (f"Open tasks from previous meetings: {tasks}. " if tasks else "") +
                            f"Previous meeting: “{last}”, {date}. Click to open the brief before the meeting"))
            target = f"brief:series:{info['series_id']}" if info["series_id"] else f"brief:person:{info['person']}"
        else:
            parts.append(tr("Нажмите — открыть «Главную»", "Click to open Home"))
            target = "dashboard"
        if join:
            parts.append(tr(f"Ссылка на {service(join)} придёт в начале встречи",
                            f"The {service(join)} link will come when the meeting starts" if service(join)
                            else "The call link will come when the meeting starts"))
        app_status.add_notice(tr(f"В {when} — «{title}»", f"At {when}: “{title}”"), " ".join(parts), target)
        n += 1
    # meetings started more than a day ago are not asked about again: their notices are forgotten
    for k in [k for k, at in _told.items() if at < now - timedelta(days=1)]:
        del _told[k]
    return n


def loop() -> None:
    while True:
        time.sleep(CHECK_SEC)
        try:
            keep_fresh()
            check()
        except Exception:
            traceback.print_exc()


def start() -> None:
    threading.Thread(target=loop, daemon=True, name="brief_notice").start()
