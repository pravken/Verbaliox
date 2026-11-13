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
    p = exe_path()
    if p.is_file():
        return str(p)
    return shutil.which("deep-filter")


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


def clean(ffmpeg: str, source: Path, out: Path, atten_db: int = ATTEN_DB) -> bool:
    """The voice in `source` (any sound or video file) without its noise, written to `out` (WAV,
    48 kHz mono, the same length and timing). False when the filter is not there or did not work:
    the recording is then mixed with the microphone as it was."""
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
            res = subprocess.run([exe, "-D", "-a", str(int(atten_db)), "-o", str(Path(tmp) / "out"), str(raw)],
                                 capture_output=True, creationflags=flags, timeout=6 * 3600)
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
