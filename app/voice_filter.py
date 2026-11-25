"""
The microphone of a studio recording cleaned by a neural network: noise (a fan, the keyboard, the
street, the room's hum) taken out, the voice kept — as Discord's or NVIDIA Broadcast's filters do.

DeepFilterNet 3 (github.com/Rikorose/DeepFilterNet, code and weights MIT or Apache-2.0) runs as its own
program, deep-filter.exe (27 MB, the model inside), downloaded on request in Settings → Recording and
checked against a pinned SHA-256 like FFmpeg (app/ffmpeg_manager.py). After «Стоп», while the tracks
are mixed in the background, the microphone (already without the speakers' echo, app/echo_cancel.py)
goes through it; the mix uses the cleaned one. The noise is lowered by ATTEN_DB at most, so a voice
never sounds cut off. The system sound is not touched: it is clean already.
"""

import hashlib
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from app.paths import BIN_DIR

VERSION = "0.5.6"
URL = f"https://github.com/Rikorose/DeepFilterNet/releases/download/v{VERSION}/deep-filter-{VERSION}-x86_64-pc-windows-msvc.exe"
SHA256 = "75e11fa16445f560cb6b021521ddb89e89270d13b83089705d98776f58fd7915"
SIZE = 26912256
ATTEN_DB = 30  # noise lowered by this much at most: the voice keeps its breath and room
_EXE = ".exe" if sys.platform == "win32" else ""

_lock = threading.Lock()
_state: Dict[str, Any] = {"active": False, "progress": 0, "error": "", "done": False}


def exe_path() -> Path:
    return BIN_DIR / f"deep-filter{_EXE}"


def find_exe() -> Optional[str]:
    """Only the file the app downloaded and checked (SHA256): a deep-filter found on PATH or in the current
    folder is not run with the user's microphone."""
    p = exe_path()
    return str(p) if p.is_file() else None


def status() -> Dict[str, Any]:
    with _lock:
        download = dict(_state)
    return {"installed": bool(find_exe()), "can_download": sys.platform == "win32", "version": VERSION,
            "size_mb": round(SIZE / 1e6), "download": download}


def _download() -> None:
    import httpx

    BIN_DIR.mkdir(parents=True, exist_ok=True)
    part = BIN_DIR / "deep-filter.download.part"
    try:
        digest, done = hashlib.sha256(), 0
        with httpx.stream("GET", URL, follow_redirects=True, timeout=60.0) as resp:
            resp.raise_for_status()
            with part.open("wb") as f:
                for chunk in resp.iter_bytes(1024 * 256):
                    f.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    with _lock:
                        _state["progress"] = min(99, int(done * 100 / SIZE))
        if digest.hexdigest() != SHA256:
            raise RuntimeError("Контрольная сумма фильтра голоса не совпала — файл отклонён")
        part.replace(exe_path())
        with _lock:
            _state.update(active=False, progress=100, done=True, error="")
    except Exception as e:
        with _lock:
            _state.update(active=False, error=str(e)[:300])
    finally:
        part.unlink(missing_ok=True)


def start_download() -> Dict[str, Any]:
    if sys.platform != "win32":
        return {**status(), "error": "Фильтр голоса скачивается только в Windows"}
    with _lock:
        if not _state["active"]:
            _state.update(active=True, progress=0, error="", done=False)
            threading.Thread(target=_download, daemon=True, name="voice_filter_download").start()
    return status()


RATE_KEY = "voice_filter_rate"  # seconds of sound the filter cleaned per second on this computer, last time


def _run_with_progress(cmd: list, flags: int, seconds: float, progress) -> "subprocess.CompletedProcess":
    """The filter run, telling `progress(fraction or None, elapsed)` every 2 s: an hour of a microphone takes
    about ten minutes, and a stage that stays at one number that long looked stuck (asked by the user).
    The fraction is estimated from the speed of the last run on this computer; None the first time."""
    import time

    from app.database import get_all_settings, update_settings

    try:
        rate = float(get_all_settings().get(RATE_KEY) or 0)
    except ValueError:
        rate = 0.0
    start = time.monotonic()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags)
    while True:
        try:
            out, err = proc.communicate(timeout=2.0)
            break
        except subprocess.TimeoutExpired:
            elapsed = time.monotonic() - start
            if elapsed > 6 * 3600:
                proc.kill()
                out, err = proc.communicate()
                break
            if progress:
                progress(min(0.97, elapsed * rate / seconds) if rate > 0 and seconds > 0 else None, elapsed)
    took = time.monotonic() - start
    if proc.returncode == 0 and seconds > 30 and took > 1:
        update_settings({RATE_KEY: f"{seconds / took:.2f}"})
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)


def clean(ffmpeg: str, source: Path, out: Path, atten_db: int = ATTEN_DB, progress=None) -> bool:
    """The voice in `source` (any sound or video file) without its noise, written to `out` (WAV,
    48 kHz mono, the same length and timing). False when the filter is not there or did not work:
    the recording is then mixed with the microphone as it was. `progress(fraction or None, elapsed)`
    is told while it runs."""
    exe = find_exe()
    if not exe:
        return False
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        with tempfile.TemporaryDirectory(dir=str(out.parent)) as tmp:
            raw = Path(tmp) / "voice.wav"
            res = subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(source), "-vn",
                                  "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", str(raw)],
                                 capture_output=True, creationflags=flags)
            if res.returncode != 0 or not raw.is_file():
                raise RuntimeError((res.stderr or b"").decode("utf-8", "replace")[-300:])
            # -D: the delay of the network made up for, so the voice stays where the system sound is
            seconds = max(0.0, (raw.stat().st_size - 44) / (48000 * 2))
            res = _run_with_progress([exe, "-D", "-a", str(int(atten_db)), "-o", str(Path(tmp) / "out"), str(raw)],
                                     flags, seconds, progress)
            done = Path(tmp) / "out" / raw.name
            if res.returncode != 0 or not done.is_file():
                raise RuntimeError((res.stderr or res.stdout or b"").decode("utf-8", "replace")[-300:])
            shutil.move(str(done), str(out))
        print(f"[voice] microphone cleaned by DeepFilterNet (noise down to -{atten_db} dB)", flush=True)
        return True
    except Exception as e:  # the recording is saved anyway, with its noise
        print(f"[voice] not cleaned: {e}", flush=True)
        out.unlink(missing_ok=True)
        return False
