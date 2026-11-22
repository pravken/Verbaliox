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

«Мои программы» (asked by the user, off until turned on: apps_track): a worked minute also notes the
program in front, by its file name only (Teams, outlook.exe). Nothing else: no window titles (they hold the
names of documents, letters and sites), no keys, no screen. Only a minute with input goes to a program (asked by
the user: count what is really used; the time of meetings comes from the recordings). «meeting» rows of earlier
versions are still shown. A game controller counts as input (only whether its state changed). It stays in this computer's database and goes nowhere.
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
_DDL_APPS = "CREATE TABLE IF NOT EXISTS app_minutes (day TEXT NOT NULL, minute INTEGER NOT NULL, app TEXT NOT NULL, PRIMARY KEY (day, minute))"
MEETING = "meeting"  # a minute of a recording or a call in earlier versions (no longer noted)

# the names people know for the usual programs; any other one is its file name without «.exe»
# The names in Russian are said in English by the page (static/i18n.js appName_<key>)
APP_NAMES = {
    "ms-teams": "Teams", "teams": "Teams", "outlook": "Outlook", "olk": "Outlook", "chrome": "Chrome", "msedge": "Edge",
    "firefox": "Firefox", "browser": "Яндекс Браузер", "opera": "Opera", "code": "Visual Studio Code", "devenv": "Visual Studio",
    "excel": "Excel", "winword": "Word", "powerpnt": "PowerPoint", "onenote": "OneNote", "explorer": "Проводник",
    "telegram": "Telegram", "slack": "Slack", "zoom": "Zoom", "notepad": "Блокнот", "acrord32": "Acrobat Reader",
    "acrobat": "Acrobat", "obsidian": "Obsidian", "notion": "Notion", "figma": "Figma", "verbaliox": "Verbaliox",
    "windowsterminal": "Терминал", "cmd": "Командная строка", "powershell": "PowerShell", "pycharm64": "PyCharm",
    "idea64": "IntelliJ IDEA", "1cv8": "1С:Предприятие", "1cv8c": "1С:Предприятие",
    "claude": "Claude", "parsecd": "Parsec", "steam": "Steam", "discord": "Discord", "skype": "Skype", "whatsapp": "WhatsApp",
    "spotify": "Spotify", "webex": "Webex", "ciscowebex": "Webex", "atmgr": "Webex", "vlc": "VLC", "photoshop": "Photoshop",
    "datagrip64": "DataGrip", "webstorm64": "WebStorm", "rider64": "Rider", "cursor": "Cursor", "postman": "Postman",
}



def foreground_app() -> Optional[str]:
    """The file name of the program in front («outlook»), None where it cannot be known. Only the name:
    the window's title is never read."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        # own instances: the types set below stay off the shared ctypes.windll the other watchers use
        user32, kernel32 = ctypes.WinDLL("user32"), ctypes.WinDLL("kernel32")
        # handles are pointer-sized: without these a 64-bit handle would be cut to an int
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        import os

        if pid.value == os.getpid():  # the window of this program: its process is python, not Verbaliox.exe
            return "verbaliox"
        h = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return None
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(len(buf))
            if not kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return None
        finally:
            kernel32.CloseHandle(h)
        name = buf.value.replace("/", "\\").rsplit("\\", 1)[-1]
        return (name[:-4] if name.lower().endswith(".exe") else name).lower()[:64] or None
    except Exception:
        return None


def app_name(app: str) -> str:
    """The name people know; another program's file name with its first letter capital («parsecd» → «Parsecd»)."""
    return APP_NAMES.get(app) or (app[:1].upper() + app[1:])


def idle_seconds(pad: bool = True) -> Optional[float]:
    """Seconds since the last keyboard, mouse or game controller input (Windows), None where it cannot be known.
    pad=False: without the game controller, whose changes are seen by one caller only (the minute loop): the
    page's look at it would take them away."""
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
        idle = ((ctypes.windll.kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000.0
    except Exception:
        return None
    return 0.0 if pad and gamepad_used() else idle


def supported() -> bool:
    """The time at the computer can be counted here (Windows tells the last input)."""
    return idle_seconds(pad=False) is not None


# XInput: a resting stick is never exactly at 0 and drifts (its packet number changes with no one touching it);
# a move counts beyond these, as XInput's own dead zones; a trigger beyond its threshold
LEFT_THUMB_DEADZONE = 7849
RIGHT_THUMB_DEADZONE = 8689
TRIGGER_THRESHOLD = 30

_pad_lock = threading.Lock()
_pad_states: Dict[int, tuple] = {}  # controller → (buttons, lt, rt, lx, ly, rx, ry) seen last


def _pad_changed(before: Optional[tuple], now: tuple) -> bool:
    """Whether someone used the controller between two looks: a button, a trigger, or a stick moved beyond its
    dead zone. A drifting stick alone is no use."""
    if before is None:
        return False
    if before[0] != now[0]:
        return True
    if abs(before[1] - now[1]) > TRIGGER_THRESHOLD or abs(before[2] - now[2]) > TRIGGER_THRESHOLD:
        return True
    left = max(abs(before[3] - now[3]), abs(before[4] - now[4]))
    right = max(abs(before[5] - now[5]), abs(before[6] - now[6]))
    return left > LEFT_THUMB_DEADZONE or right > RIGHT_THUMB_DEADZONE


def gamepad_used() -> bool:
    """A game controller (XInput) used since the last check: Windows does not count it as input, so a game
    played with one looked like time away. Only whether it was used is kept, never what was pressed."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        class XINPUT_STATE(ctypes.Structure):
            _fields_ = [("dwPacketNumber", ctypes.c_uint), ("buttons", ctypes.c_ushort), ("lt", ctypes.c_ubyte),
                        ("rt", ctypes.c_ubyte), ("lx", ctypes.c_short), ("ly", ctypes.c_short), ("rx", ctypes.c_short),
                        ("ry", ctypes.c_short)]

        dll = None
        for name in ("xinput1_4", "xinput9_1_0", "xinput1_3"):
            try:
                dll = ctypes.WinDLL(name)
                break
            except OSError:
                continue
        if dll is None:
            return False
        used = False
        with _pad_lock:
            for pad in range(4):
                st = XINPUT_STATE()
                if dll.XInputGetState(pad, ctypes.byref(st)) != 0:  # not connected
                    _pad_states.pop(pad, None)
                    continue
                now = (st.buttons, st.lt, st.rt, st.lx, st.ly, st.rx, st.ry)
                used = _pad_changed(_pad_states.get(pad), now) or used
                _pad_states[pad] = now
        return used
    except Exception:
        return False


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


def _day_minute(at: datetime):
    d = work_day(at)
    start = datetime.combine(d, datetime.min.time()) + timedelta(hours=DAY_START_HOUR)
    return d.isoformat(), int((at - start).total_seconds() // 60)


def mark(at: datetime, app: Optional[str] = None) -> None:
    """The minute of `at` was worked (in the program `app`, when «Мои программы» are on)."""
    d, minute = _day_minute(at)
    with _conn() as conn:
        conn.execute("INSERT OR IGNORE INTO work_minutes (day, minute) VALUES (?, ?)", (d, minute))
        if app:
            conn.execute(_DDL_APPS)
            conn.execute("INSERT OR IGNORE INTO app_minutes (day, minute, app) VALUES (?, ?, ?)", (d, minute, app))


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


def apps(start: date, end: date) -> Dict[str, int]:
    """{program: minutes} of the days start…end (end not included)."""
    with _conn() as conn:
        conn.execute(_DDL_APPS)
        rows = conn.execute("SELECT app, COUNT(*) FROM app_minutes WHERE day >= ? AND day < ? GROUP BY app",
                            (start.isoformat(), end.isoformat())).fetchall()
    return {r[0]: int(r[1]) for r in rows}


def apps_since() -> str:
    """The first day «Мои программы» counted (YYYY-MM-DD), '' with no minute noted: a period that begins earlier
    holds the days since then only."""
    with _conn() as conn:
        conn.execute(_DDL_APPS)
        row = conn.execute("SELECT MIN(day) FROM app_minutes").fetchone()
    return (row[0] or "") if row else ""


def clear_apps() -> None:
    """«Удалить историю»: every minute noted by «Мои программы»."""
    with _conn() as conn:
        conn.execute(_DDL_APPS)
        conn.execute("DELETE FROM app_minutes")


def apps_enabled() -> bool:
    from app.database import get_all_settings

    return get_all_settings().get("apps_track", "false") == "true"


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
    meeting = _recording() or _in_call()
    if not (idle < IDLE_MIN * 60 or meeting):
        return False
    # «Мои программы»: the program actually used, with input in the last minutes; a recording or a call alone
    # (only listening) counts the minute as work, not as a program's (the meetings' time is counted from the
    # recordings, «Время во встречах»)
    app = foreground_app() if apps_enabled() and idle < IDLE_MIN * 60 else None
    mark(now, app)
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
