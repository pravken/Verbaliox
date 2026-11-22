"""
Log file of the desktop app.

Launched from Verbaliox.exe the app has no visible console, so everything it prints (uvicorn
messages, tracebacks, warnings) would be lost. `start_file_log()` copies stdout and stderr into
`<data>/logs/verbaliox.log` with a time stamp per line, keeps the last few files, and makes
Python write a stack dump there if the process crashes hard.
"""

import faulthandler
import re
import sys
import threading
import time
from pathlib import Path
from typing import Optional, TextIO

from app.paths import DATA_DIR

LOG_DIR = DATA_DIR / "logs"
LOG_FILE = LOG_DIR / "verbaliox.log"
MAX_BYTES = 2 * 1024 * 1024
KEEP_FILES = 4  # verbaliox.log + .1 ... .3

_lock = threading.Lock()
_file: Optional[TextIO] = None


def _rotate() -> None:
    """verbaliox.log -> .1 -> .2 ...; the oldest is dropped. Call with _lock held."""
    global _file
    if _file is not None:
        _file.close()
    for i in range(KEEP_FILES - 1, 0, -1):
        older = LOG_FILE.with_name(f"{LOG_FILE.name}.{i}")
        newer = LOG_FILE if i == 1 else LOG_FILE.with_name(f"{LOG_FILE.name}.{i - 1}")
        try:
            if newer.exists():
                newer.replace(older)
        except OSError:
            pass
    _file = open(LOG_FILE, "a", encoding="utf-8", buffering=1)


# What never goes into the log, whoever prints it (the log is sent with a problem report): the Windows
# user's name in paths, e-mail addresses, the session token and the links of calls
_SCRUB = [
    (re.compile(r"(?i)([a-z]:[\\/]+(?:users|documents and settings)[\\/]+)[^\\/:*?\"<>|\r\n]+"), r"\1<user>"),
    (re.compile(r"(/(?:home|Users)/)[^/\s'\"]+"), r"\1<user>"),
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "<email>"),
    (re.compile(r"(?i)\b(token|access_token|key|password|pwd|sig|signature)=[^&\s'\"]+"), r"\1=<hidden>"),
    (re.compile(r"(?i)https?://(?:teams\.microsoft\.com|teams\.live\.com|[\w-]+\.zoom\.us|meet\.google\.com|[\w.-]*webex\.com|telemost\.yandex\.ru)/\S*"),
     "<call link>"),
]


def scrub(text: str) -> str:
    for rx, to in _SCRUB:
        text = rx.sub(to, text)
    return text


class _Tee:
    """Writes to the log file and, when there is one, to the original stream."""

    def __init__(self, original: Optional[TextIO], label: str):
        self._original = original
        self._label = label
        self._at_line_start = True

    def write(self, text: str) -> int:
        if not text:
            return 0
        if self._original is not None:
            try:
                self._original.write(text)
            except Exception:
                pass
        with _lock:
            if _file is None:
                return len(text)
            out = []
            for part in text.splitlines(keepends=True):
                if self._at_line_start:
                    out.append(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {self._label} ")
                out.append(scrub(part))
                self._at_line_start = part.endswith("\n")
            try:
                _file.write("".join(out))
                if _file.tell() > MAX_BYTES:
                    _rotate()
            except Exception:
                pass
        return len(text)

    def flush(self) -> None:
        if self._original is not None:
            try:
                self._original.flush()
            except Exception:
                pass
        with _lock:
            if _file is not None:
                try:
                    _file.flush()
                except Exception:
                    pass

    def isatty(self) -> bool:
        return False

    @property
    def encoding(self) -> str:
        return "utf-8"


SIDE_LOG_MAX = 1024 * 1024
SIDE_LOG_KEEP = 256 * 1024


def trim_side_logs() -> None:
    """crash.log (a stack of every thread at each hard crash) and update.log (the installer's output at
    every update of the libraries) are only ever added to: past SIDE_LOG_MAX only their newest part is kept,
    from the start of a line."""
    for name in ("crash.log", "update.log"):
        path = LOG_DIR / name
        try:
            if path.stat().st_size <= SIDE_LOG_MAX:
                continue
            with open(path, "rb") as f:
                f.seek(-SIDE_LOG_KEEP, 2)
                tail = f.read()
            tail = tail[tail.find(b"\n") + 1:]
            tmp = path.with_name(name + ".tmp")
            tmp.write_bytes(tail)
            tmp.replace(path)
        except OSError:
            pass


def start_file_log() -> Path:
    """Starts copying stdout/stderr into the log file. Safe to call once per process."""
    global _file
    with _lock:
        if _file is not None:
            return LOG_FILE
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        trim_side_logs()
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > MAX_BYTES:
            _rotate()
        else:
            _file = open(LOG_FILE, "a", encoding="utf-8", buffering=1)
        _file.write(f"\n===== Verbaliox started {time.strftime('%Y-%m-%d %H:%M:%S')} "
                    f"(Python {sys.version.split()[0]}, {sys.executable}) =====\n")
    sys.stdout = _Tee(sys.__stdout__, "OUT")
    sys.stderr = _Tee(sys.__stderr__, "ERR")
    # Hard crashes (access violation in a native library) still leave a Python stack in the log
    try:
        faulthandler.enable(file=open(LOG_DIR / "crash.log", "a", encoding="utf-8"), all_threads=True)
    except Exception:
        pass
    return LOG_FILE
