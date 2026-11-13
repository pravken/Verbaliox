"""
Which Teams meeting is open now, by the titles of the Teams windows (Windows only).

A recording started for one meeting went on through the next one: Teams keeps the microphone when you
go from one meeting into another, so the call watcher (app/call_watch.py) saw one long call. The
meeting's own window has the meeting's name in its title («Планёрка | Microsoft Teams»); the main
window has the name of a section («Чат | …», «Календарь | …»). The page asks this while it records and
starts a new recording when the meeting changes, and stops it when the meeting's window is gone
(static/js/studio.js meetingFollowTick).
"""

import re
import sys
import time
from typing import Any, Dict, List

TEAMS_PROCESSES = {"ms-teams.exe", "teams.exe", "msteams.exe"}
_SUFFIX_RE = re.compile(r"\s*[|\-–—]\s*Microsoft Teams(?:\s*\([^)]*\))?\s*$", re.I)
# The sections of the main window, in the languages of Teams the app is used with: not a meeting
SECTIONS = {
    "microsoft teams", "teams", "chat", "чат", "activity", "действия", "лента действий", "calendar", "календарь",
    "calls", "звонки", "files", "файлы", "apps", "приложения", "onedrive", "communities", "сообщества",
    "assignments", "задания", "approvals", "утверждения", "notification", "уведомление", "уведомления",
    "settings", "параметры", "настройки", "help", "справка", "search", "поиск", "команды", "copilot",
}
_LAST: List[str] = [""]
_HAS_LEAVE: Dict[tuple, tuple] = {}  # (window, title) -> (holds «Покинуть» / «Leave», when looked)
RECHECK_SEC = 20.0  # a window without the button is looked at again: the lobby has none until you join
LEAVE_IDS = {"hangup-button", "hangup-btn", "leave-call-button"}
LEAVE_NAMES = {"leave", "покинуть", "выйти", "hang up", "завершить"}


def meeting_title(titles: List[str]) -> str:
    """The meeting among the titles of Teams windows: its name without « | Microsoft Teams», or "".
    A window titled after a section of the main window (or with nothing but the app's name) is not
    one; «Чат | Анна | Microsoft Teams» is the chat, not a meeting."""
    for raw in titles:
        if not raw or "teams" not in raw.lower():
            continue
        name = _SUFFIX_RE.sub("", raw).strip()
        if not name:
            continue
        first = re.split(r"\s*\|\s*", name)[0].strip().lower()
        if first in SECTIONS or name.lower() in SECTIONS:
            continue
        return name[:200]
    return ""


def teams_windows() -> List[tuple]:
    """(window handle, title) of the visible windows of Teams (new and classic). Empty outside Windows."""
    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes

    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    out: List[tuple] = []
    names: Dict[int, str] = {}

    def process_name(pid: int) -> str:
        if pid not in names:
            name = ""
            h = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if h:
                try:
                    buf = ctypes.create_unicode_buffer(1024)
                    size = wintypes.DWORD(1024)
                    if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                        name = buf.value.replace("/", "\\").rsplit("\\", 1)[-1].lower()
                finally:
                    kernel32.CloseHandle(h)
            names[pid] = name
        return names[pid]

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def on_window(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if process_name(pid.value) not in TEAMS_PROCESSES:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        if buf.value.strip():
            out.append((int(hwnd or 0), buf.value.strip()))
        return True

    user32.EnumWindows(on_window, 0)
    return out


def _has_leave_button(hwnd: int) -> bool:
    """The window holds the button that leaves a call: it is a meeting, not the main window. None when
    UI Automation cannot be used (the title alone decides then)."""
    try:
        from app.teams_captions import load_uia

        load_uia()
        from System import IntPtr
        from System.Windows.Automation import AutomationElement, ControlType, PropertyCondition, TreeScope

        root = AutomationElement.FromHandle(IntPtr(hwnd))
        buttons = root.FindAll(TreeScope.Descendants,
                               PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.Button))
        for b in buttons:
            c = b.Current
            if (c.AutomationId or "").lower() in LEAVE_IDS or (c.Name or "").strip().lower() in LEAVE_NAMES:
                return True
        return False
    except Exception as e:
        print(f"[meeting] no UI Automation, the title alone decides: {e}", flush=True)
        return None  # type: ignore[return-value]


def current() -> Dict[str, Any]:
    """{"title": the meeting open now or "", "windows": the Teams window titles}. A change is written
    to the log: the titles of Teams are not documented, the log shows what was seen."""
    try:
        wins = teams_windows()
    except Exception as e:  # never in the way of a recording
        return {"title": "", "windows": [], "error": str(e)[:200]}
    titles = [t for _, t in wins]
    title = ""
    for hwnd, t in wins:
        name = meeting_title([t])
        if not name:
            continue
        key = (hwnd, t)
        seen = _HAS_LEAVE.get(key)
        if seen is None or (seen[0] is False and time.time() - seen[1] > RECHECK_SEC):
            if len(_HAS_LEAVE) > 200:
                _HAS_LEAVE.clear()
            seen = _HAS_LEAVE[key] = (_has_leave_button(hwnd), time.time())
        if seen[0] is False:
            continue  # the main window with a chat or a channel open: not a meeting
        title = name
        break
    if title != _LAST[0]:
        _LAST[0] = title
        print(f"[meeting] Teams meeting: {title or 'none'}; windows: {titles[:6]!r}", flush=True)
    return {"title": title, "windows": titles[:12]}
