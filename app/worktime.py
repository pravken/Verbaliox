"""
How long the working day lasted (asked by the user): the minutes this computer was in use, kept per day,
and a Windows notification when the hours worked reach the user's norm (8 by default).

A minute counts as work when the keyboard or the mouse was used in the last IDLE_MIN minutes, or a
recording runs, or a call app holds the microphone (a call where one only listens). Teams sets its own
status «Нет на месте» the same way, from the same keyboard and mouse: reading that status itself needs
an account sign-in to Microsoft, this needs nothing and stays on this computer.

A day runs from DAY_START_HOUR (a night past midnight belongs to the day before). The hours worked of a
day are its spans of work: pauses shorter than JOIN_MIN are part of the work, longer ones are breaks.
Settings: worktime_track (on), work_remind_hours (8; 0 = no notification).
"""

import sys
import threading
import time
import traceback
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

IDLE_MIN = 5          # no input for this long: away (Teams' own «Нет на месте» comes after 5 minutes)
JOIN_MIN = 15         # a pause shorter than this is part of the work
DAY_START_HOUR = 4    # the day's first minute; earlier ones belong to the day before
CHECK_SEC = 60.0

_DDL = "CREATE TABLE IF NOT EXISTS work_minutes (day TEXT NOT NULL, minute INTEGER NOT NULL, PRIMARY KEY (day, minute))"


def idle_seconds() -> Optional[float]:
    """Seconds since the last keyboard or mouse input (Windows), None where it cannot be known."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return None
        return ((ctypes.windll.kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000.0
    except Exception:
        return None


def _in_call() -> bool:
    try:
        from app import call_watch

        return bool(call_watch.meeting_app(call_watch.apps_using_microphone()))
    except Exception:
        return False


def _recording() -> bool:
    try:
        from app import app_status

        return bool(app_status._ui.get("recording"))
    except Exception:
        return False


def work_day(at: datetime) -> date:
    """The working day a moment belongs to: before DAY_START_HOUR it is still the day before."""
    return (at - timedelta(hours=DAY_START_HOUR)).date()


@contextmanager
def _conn():
    """A connection with the table there; committed and closed after use."""
    from app.database import _db_lock, get_connection

    with _db_lock:  # the database's own writers take it too: no wait on the busy timeout
        conn = get_connection()
        try:
            conn.execute(_DDL)
            yield conn
            conn.commit()
        finally:
            conn.close()


def mark(at: datetime) -> None:
    """The minute of `at` was worked."""
    d = work_day(at)
    start = datetime.combine(d, datetime.min.time()) + timedelta(hours=DAY_START_HOUR)
    minute = int((at - start).total_seconds() // 60)
    with _conn() as conn:
        conn.execute("INSERT OR IGNORE INTO work_minutes (day, minute) VALUES (?, ?)", (d.isoformat(), minute))


def _sessions(minutes: List[int]) -> List[List[int]]:
    out: List[List[int]] = []
    for m in sorted(minutes):
        if out and m - out[-1][1] <= JOIN_MIN:
            out[-1][1] = m
        else:
            out.append([m, m])
    return out


def summary(d: date, minutes: List[int]) -> Dict[str, Any]:
    """{worked: minutes, start, end ("HH:MM"), breaks: minutes} of a day from its minutes of work."""
    if not minutes:
        return {"worked": 0, "start": "", "end": "", "breaks": 0}
    spans = _sessions(minutes)
    base = datetime.combine(d, datetime.min.time()) + timedelta(hours=DAY_START_HOUR)
    clock = lambda m: (base + timedelta(minutes=m)).strftime("%H:%M")  # noqa: E731
    worked = sum(b - a + 1 for a, b in spans)
    total = spans[-1][1] - spans[0][0] + 1
    return {"worked": worked, "start": clock(spans[0][0]), "end": clock(spans[-1][1] + 1), "breaks": total - worked}


def days(start: date, end: date) -> Dict[str, Dict[str, Any]]:
    """{"YYYY-MM-DD": summary} of the days start…end (end not included) that have work."""
    with _conn() as conn:
        rows = conn.execute("SELECT day, minute FROM work_minutes WHERE day >= ? AND day < ? ORDER BY day, minute",
                            (start.isoformat(), end.isoformat())).fetchall()
    by: Dict[str, List[int]] = {}
    for r in rows:
        by.setdefault(r[0], []).append(int(r[1]))
    return {k: summary(date.fromisoformat(k), v) for k, v in by.items()}


def enabled() -> bool:
    from app.database import get_all_settings

    return get_all_settings().get("worktime_track", "true") != "false"


def remind_hours() -> float:
    from app.database import get_all_settings

    try:
        return max(0.0, float(get_all_settings().get("work_remind_hours") or 0))
    except ValueError:
        return 0.0


def check(now: Optional[datetime] = None, idle: Optional[float] = None) -> bool:
    """One tick: marks the minute when it was worked, and tells once a day that the norm is reached.
    Returns whether the minute counted."""
    if not enabled():
        return False
    now = now or datetime.now()
    idle = idle_seconds() if idle is None else idle
    if idle is None:  # not known here (not Windows): nothing is counted
        return False
    active = idle < IDLE_MIN * 60 or _recording() or _in_call()
    if not active:
        return False
    mark(now)
    hours = remind_hours()
    d = work_day(now).isoformat()
    from app.database import get_all_settings, update_settings

    if hours and get_all_settings().get("work_reminded_day") != d:  # once a day, a restart included
        today = days(work_day(now), work_day(now) + timedelta(days=1)).get(d)
        if today and today["worked"] >= hours * 60:
            update_settings({"work_reminded_day": d})
            from app import app_status

            h = int(hours) if hours == int(hours) else hours
            app_status.add_notice(f"Рабочий день: {h} ч",
                                  f"С {today['start']} отработано {today['worked'] // 60} ч {today['worked'] % 60:02d} мин. Норма рабочего дня выполнена",
                                  "dashboard")
    return True


def loop() -> None:
    while True:
        time.sleep(CHECK_SEC)
        try:
            check()
        except Exception:
            traceback.print_exc()


def start() -> None:
    threading.Thread(target=loop, daemon=True, name="worktime").start()
