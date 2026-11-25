"""
The calendar of the classic Outlook installed on this computer (Microsoft 365 / Exchange / Outlook.com:
the same calendar Teams shows its meetings in). Read through Outlook's own automation interface with
the PowerShell that comes with Windows: no link to publish, no sign-in, nothing leaves the computer.

The new Outlook ("Outlook (new)") and Outlook on the web have no such interface: for them the calendar
is added by its published .ics link (app/calendar_ics.py).

Selected in Settings -> Integrations -> Calendar as the source "outlook". Recurring meetings come
already expanded by Outlook; cancelled ones and all-day events are left out.
"""

import json
import subprocess
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

SOURCE = "outlook"
NO_PROFILE = ("Классический Outlook не настроен: в нём нет почтового профиля. Для нового Outlook и Outlook в браузере "
              "добавьте опубликованную ссылку .ics")
DAYS_BACK = 1
DAYS_AHEAD = 14
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Outlook's Restrict wants the dates in the user's own short format, which PowerShell's ToString('g') gives.
# MeetingStatus 5 / 7: the meeting was cancelled (by the organizer / received cancelled).
# Sorted by start before IncludeRecurrences, as Outlook's documentation asks: the other way round the occurrences
# of a recurring meeting are not expanded reliably (found in an audit). One appointment Outlook cannot read (a
# property refused by its security prompt) is left out, not the whole calendar.
_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ol = New-Object -ComObject Outlook.Application
$ns = $ol.GetNamespace('MAPI')
$me = ''
try { $me = $ns.CurrentUser.Name } catch {}
$items = $ns.GetDefaultFolder(9).Items
$items.Sort('[Start]')
$items.IncludeRecurrences = $true
$from = (Get-Date).Date.AddDays(-__BACK__).ToString('g')
$to = (Get-Date).Date.AddDays(__AHEAD__).ToString('g')
$found = $items.Restrict("[Start] >= '$from' AND [Start] <= '$to'")
$out = @()
foreach ($a in $found) {
  try {
  if ($a.AllDayEvent) { continue }
  if ($a.MeetingStatus -eq 5 -or $a.MeetingStatus -eq 7) { continue }
  $people = @()
  foreach ($r in @($a.RequiredAttendees, $a.OptionalAttendees)) {
    if ($r) { $people += ($r -split ';' | ForEach-Object { $_.Trim() } | Where-Object { $_ -and $_ -ne $me }) }
  }
  $out += [pscustomobject]@{
    uid = [string]$a.GlobalAppointmentID
    title = [string]$a.Subject
    start = $a.Start.ToString('yyyy-MM-ddTHH:mm:ss')
    end = $a.End.ToString('yyyy-MM-ddTHH:mm:ss')
    location = [string]$a.Location
    join = ([regex]::Match(([string]$a.Location + ' ' + [string]$a.Body), 'https://(teams\.microsoft\.com/l/meetup-join|teams\.microsoft\.com/meet|teams\.live\.com/meet|([\w-]+\.)?zoom\.us/[jw]/|meet\.google\.com/|[\w-]+\.webex\.com/)[^\s<>]*')).Value  # no double quote here: the script is a command-line argument
    attendees = @($people)
  }
  } catch { continue }
  if ($out.Count -ge 300) { break }
}
ConvertTo-Json -InputObject @($out) -Depth 4 -Compress
"""


# Where classic Outlook keeps its mail profiles: 2013 and later per Office version, before it the
# Windows Messaging Subsystem. With none, starting Outlook opens its first-run wizard («Welcome to
# Outlook») instead of the calendar, and every new read opened it again (found by the user: the
# wizard kept coming back after the calendar source was set to Outlook).
_PROFILE_KEYS = (r"Software\Microsoft\Office\16.0\Outlook\Profiles", r"Software\Microsoft\Office\15.0\Outlook\Profiles",
                 r"Software\Microsoft\Windows NT\CurrentVersion\Windows Messaging Subsystem\Profiles")


def supported() -> bool:
    """Classic Outlook is registered for automation on this computer."""
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Outlook.Application\CLSID"):
            return True
    except OSError:
        return False


def has_profile() -> bool:
    """Classic Outlook has a mail profile set up: it opens without its first-run wizard."""
    if sys.platform != "win32":
        return False
    import winreg

    for key in _PROFILE_KEYS:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
                if winreg.QueryInfoKey(k)[0] > 0:  # at least one profile
                    return True
        except OSError:
            continue
    return False


def _outlook_pids() -> Optional[Set[int]]:
    """The process ids of the Outlook running now; None when not known."""
    try:
        res = subprocess.run(["tasklist", "/FI", "IMAGENAME eq OUTLOOK.EXE", "/FO", "CSV", "/NH"], capture_output=True,
                             text=True, errors="replace", timeout=15, creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return None
    pids = set()
    for line in (res.stdout or "").splitlines():
        cells = [c.strip().strip('"') for c in line.split('","')]
        if len(cells) >= 2 and cells[0].strip('"').lower() == "outlook.exe" and cells[1].isdigit():
            pids.add(int(cells[1]))
    return pids


def _has_visible_window(pid: int) -> bool:
    """The process shows a window (the main window, a password or profile prompt): someone may be using it.
    Not known counts as shown."""
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        found = []
        proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def look(hwnd, _):
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value == pid and user32.IsWindowVisible(hwnd):
                found.append(hwnd)
                return False
            return True

        user32.EnumWindows(proc(look), 0)
        return bool(found)
    except Exception:  # noqa: BLE001 - not known: treated as in use
        return True


def _close_started_outlook(before: Optional[Set[int]]) -> None:
    """The Outlook this read started, left hanging with no window, is asked to close. Outlook runs as one
    instance, so the one the user opened (or opened meanwhile, or is typing a password in) must stay: only
    a process that was not there before the read and shows no window, and never forced (no /F)."""
    if before is None:
        return
    now = _outlook_pids()
    if not now:
        return
    for pid in sorted(now - before):
        if _has_visible_window(pid):
            continue
        try:
            subprocess.run(["taskkill", "/PID", str(pid)], capture_output=True, timeout=15, creationflags=_NO_WINDOW)
        except (OSError, subprocess.SubprocessError):
            pass


def fetch() -> List[Dict[str, Any]]:
    """Meetings from yesterday to two weeks ahead, as app/calendar_ics.py events."""
    if not supported():
        raise RuntimeError("Классический Outlook на этом компьютере не найден. Для нового Outlook и Outlook в браузере "
                           "добавьте опубликованную ссылку .ics")
    if not has_profile():
        raise RuntimeError(NO_PROFILE)
    before = _outlook_pids()
    script = _SCRIPT.replace("__BACK__", str(DAYS_BACK)).replace("__AHEAD__", str(DAYS_AHEAD))
    from app.paths import powershell_exe

    try:
        res = subprocess.run([powershell_exe(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
                             capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90,
                             creationflags=_NO_WINDOW)
    except subprocess.TimeoutExpired:
        _close_started_outlook(before)
        raise RuntimeError("Outlook не ответил за 90 секунд (возможно, ждёт выбора профиля или пароля)")
    if res.returncode != 0:
        raise RuntimeError("Outlook: " + ((res.stderr or res.stdout or "").strip().splitlines() or ["ошибка"])[-1][:200])
    return parse(res.stdout)


def parse(text: str) -> List[Dict[str, Any]]:
    data = json.loads((text or "").strip() or "[]")
    if isinstance(data, dict):  # PowerShell 5 gives one object instead of a list of one
        data = [data]
    out = []
    for it in data or []:
        try:
            start = datetime.fromisoformat(str(it["start"]))
            end = datetime.fromisoformat(str(it["end"]))
        except (KeyError, ValueError):
            continue
        from app.meeting_join import find

        join = find(str(it.get("join") or ""))  # checked again: only a link of a call service
        attendees = it.get("attendees") or []
        if isinstance(attendees, str):
            attendees = [attendees]
        out.append({"uid": str(it.get("uid") or ""), "title": str(it.get("title") or "").strip(), "start": start,
                    "end": end if end > start else start, "attendees": [str(a) for a in attendees if str(a).strip()],
                    "rrule": "", "exdates": [], "all_day": False, "status": "",
                    "location": str(it.get("location") or "")[:200], "join": join,
                    "online": bool(join) or "://" in str(it.get("location") or "")})
    return out
