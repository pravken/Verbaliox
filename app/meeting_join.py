"""
The link to join a calendar meeting's call (Teams, Zoom, Google Meet, Webex), found in the event's place,
description or meeting URL; a click on the notice before the meeting (app/brief_notice.py) or on
«Подключиться» on the home page opens it.

Only links of these services are opened: an event's text comes from whoever sent the invitation.
A Teams link goes straight to the Teams app when it is installed (msteams:), not through the browser.
"""

import os
import re
import sys
import webbrowser
from typing import Optional

_JOIN_RE = re.compile(
    r"https://(?:"
    r"teams\.microsoft\.com/l/meetup-join/[^\s\"'<>\\]+"
    r"|teams\.microsoft\.com/meet/[^\s\"'<>\\]+"
    r"|teams\.live\.com/meet/[^\s\"'<>\\]+"
    r"|(?:[\w-]+\.)?zoom\.us/[jw]/[^\s\"'<>\\]+"
    r"|meet\.google\.com/[a-z]{3}-[a-z]{4}-[a-z]{3}[^\s\"'<>\\]*"
    r"|[\w-]+\.webex\.com/[^\s\"'<>\\]+"
    r")",
    re.I,
)


def find(text: str) -> str:
    """The first link to a call in the text, "" when there is none."""
    m = _JOIN_RE.search(text or "")
    return m.group(0).rstrip(".,;)>]") if m else ""


def service(url: str) -> str:
    u = (url or "").lower()
    if "teams." in u:
        return "Teams"
    if "zoom.us" in u:
        return "Zoom"
    if "meet.google.com" in u:
        return "Google Meet"
    if "webex.com" in u:
        return "Webex"
    return ""


def _teams_app() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "msteams"):
            return True
    except OSError:
        return False


def launch_target(url: str) -> Optional[str]:
    """What opens the call: msteams:… for a Teams link when the Teams app is there, else the link itself.
    None when it is no link of a call service."""
    link = find(url)
    if not link or link != (url or "").strip().rstrip(".,;)>]"):
        return None
    if service(link) == "Teams" and "teams.microsoft.com" in link.lower() and _teams_app():
        return "msteams:" + link.split("teams.microsoft.com", 1)[1]
    return link


def open_link(url: str) -> Optional[str]:
    """Opens the call. Returns what was opened, None when it is no link of a call service."""
    target = launch_target(url)
    if not target:
        return None
    if target.startswith("msteams:"):
        try:
            os.startfile(target)  # noqa: S606 - the Teams app, with a link of the user's calendar
            return target
        except OSError:
            target = find(url)
    webbrowser.open(target)
    return target
