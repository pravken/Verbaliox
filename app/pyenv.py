"""
uv and pip for installing packages into a Python environment. setup.bat makes .venv with uv, which
puts no pip in it, so pip is bootstrapped with ensurepip when uv is not found.
"""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# The requirements.txt the environment was installed from (its SHA-256). The launcher compares it with
# the requirements.txt next to it: the installer or an archive unpacked over an older version brings new
# libraries, and the setup window then installs them into the existing .venv
REQUIREMENTS_MARK = Path(".venv") / "verbaliox-requirements.sha256"


def requirements_hash(app_dir: Path) -> str:
    import hashlib

    try:
        return hashlib.sha256((app_dir / "requirements.txt").read_bytes()).hexdigest()
    except OSError:
        return ""


def mark_requirements(app_dir: Path, only_if_missing: bool = False) -> None:
    """Records requirements.txt as installed in .venv: after setup.bat and the updater install it, and
    at start for an environment made before the mark existed (it is taken as current then)."""
    mark = app_dir / REQUIREMENTS_MARK
    digest = requirements_hash(app_dir)
    if not digest or not mark.parent.is_dir() or (only_if_missing and mark.exists()):
        return
    try:
        mark.write_text(digest, encoding="ascii")
    except OSError:
        pass


def find_uv() -> Optional[str]:
    """A uv that runs: on PATH or where its installers put it (the app may start without the updated
    PATH). The shortcut winget leaves may point nowhere, or a policy may block programs in AppData:
    such a uv is skipped (setup.bat :try_uv)."""
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    local = Path(os.environ.get("LOCALAPPDATA") or home)
    on_path = shutil.which("uv")  # found by which: it exists
    files = [home / ".local" / "bin" / "uv.exe", home / ".cargo" / "bin" / "uv.exe",
             local / "Microsoft" / "WinGet" / "Links" / "uv.exe",
             *sorted((local / "Microsoft" / "WinGet" / "Packages").glob("astral-sh.uv*/uv.exe"))]
    candidates = ([on_path] if on_path else []) + [str(f) for f in files if f.is_file()]
    for c in dict.fromkeys(candidates):
        if _runs(c):
            return c
    return None


def _runs(exe: str) -> bool:
    try:
        return subprocess.run([exe, "--version"], capture_output=True, creationflags=_NO_WINDOW,
                              timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _ok(cmd) -> bool:
    try:
        return subprocess.run(cmd, capture_output=True, creationflags=_NO_WINDOW, timeout=300).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def ensure_pip(python: str) -> bool:
    """True when `python -m pip` works, installing pip with ensurepip if the environment has none."""
    if _ok([python, "-m", "pip", "--version"]):
        return True
    _ok([python, "-m", "ensurepip", "--upgrade"])
    return _ok([python, "-m", "pip", "--version"])
