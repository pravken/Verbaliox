"""
A Windows toast with buttons (asked by the user: «Подключиться» right in the notification of a meeting's
start). The tray's balloon (app/tray.py) has no buttons; a toast has, and a button that opens a link
(protocol activation) needs nothing from the app when it is pressed.

The toast is shown under the app's AppUserModelID (the one of its window and its Start menu shortcut,
registered here with its name and icon for a copy without the installer's shortcut), by Windows
PowerShell through the WinRT notification API. Where that fails, the caller falls back to the balloon.
"""

import base64
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple
from xml.sax.saxutils import quoteattr, escape

APP_ID = "Verbaliox.Desktop.Studio.1"  # run.py set_app_user_model_id, installer/verbaliox.iss
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# Characters XML 1.0 does not allow: one in a meeting's title (an invitation's text) made the toast's XML invalid,
# and Windows showed nothing (found in an audit)
_NOT_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")


def _xml_text(value: str) -> str:
    return _NOT_XML.sub("", str(value or ""))


def toast_xml(title: str, text: str, buttons: List[Tuple[str, str]], launch: str = "", stay: bool = False) -> str:
    """The toast: its click opens `launch`, each button (label, link) opens its link, the last one is
    «Закрыть» (in the UI language). stay: it stays on the screen until answered (a meeting starting now)."""
    title, text, launch = _xml_text(title), _xml_text(text), _xml_text(launch)
    buttons = [(_xml_text(label), _xml_text(link)) for label, link in buttons]
    acts = "".join(f"<action content={quoteattr(label)} activationType=\"protocol\" arguments={quoteattr(link)}/>"
                   for label, link in buttons)
    from app.ui_lang import tr

    acts += f"<action content={quoteattr(tr('Закрыть', 'Close'))} activationType=\"system\" arguments=\"dismiss\"/>"
    head = "<toast" + (f" activationType=\"protocol\" launch={quoteattr(launch)}" if launch else "") + \
        (" scenario=\"reminder\"" if stay and buttons else "") + ">"
    return (f"{head}<visual><binding template=\"ToastGeneric\"><text>{escape(title)}</text><text>{escape(text)}</text>"
            f"</binding></visual><actions>{acts}</actions><audio src=\"ms-winsoundevent:Notification.Reminder\"/></toast>")


def _register(icon: Optional[Path]) -> None:
    """The app's name and icon for its toasts (HKCU\\Software\\Classes\\AppUserModelId)."""
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\AppUserModelId\{APP_ID}") as k:
        winreg.SetValueEx(k, "DisplayName", 0, winreg.REG_SZ, "Verbaliox")
        if icon and icon.exists():
            winreg.SetValueEx(k, "IconUri", 0, winreg.REG_SZ, str(icon))


def script(xml: str) -> str:
    """The script that shows the toast. The XML (an invitation's title and link are untrusted text) goes
    in as base64 and is decoded by the script: no quote of any kind in it can end a string and run code
    (PowerShell takes the typographic ‘ ’ for quotes as well)."""
    data = base64.b64encode(xml.encode("utf-8")).decode("ascii")
    return (
        "$ErrorActionPreference = 'Stop'\n"  # an error ends the script with an exit code: the balloon then
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null\n"
        "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null\n"
        "$x = New-Object Windows.Data.Xml.Dom.XmlDocument\n"
        f"$x.LoadXml([System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String('{data}')))\n"
        "$t = New-Object Windows.UI.Notifications.ToastNotification $x\n"
        f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{APP_ID}').Show($t)\n"
    )


def show(title: str, text: str, buttons: List[Tuple[str, str]], launch: str = "", stay: bool = False,
         icon: Optional[Path] = None) -> bool:
    """Shows the toast. False where it cannot be (not Windows, PowerShell refused): the balloon then."""
    if sys.platform != "win32":
        return False
    try:
        _register(icon)
        encoded = base64.b64encode(script(toast_xml(title, text, buttons, launch, stay)).encode("utf-16-le")).decode()
        res = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                              "-EncodedCommand", encoded], capture_output=True, timeout=20, creationflags=_NO_WINDOW)
        return res.returncode == 0
    except Exception:
        return False
