"""
Memory left to the system (Settings → General, asked by the user: the app must not take all of it).

Two reserves: RAM (`mem_reserve_ram`) and video memory (`mem_reserve_vram`), each «auto» (sized by the
computer) or a number of GB. They are kept three ways:
- the work processes (Ollama with its runners, the dubbing and live-caption workers) are in a Windows job
  whose memory is capped at all RAM but the reserve: past it their allocations fail with an error the app
  reports, instead of the computer swapping to a halt;
- Ollama is started with the video-memory reserve kept free (OLLAMA_GPU_OVERHEAD): what does not fit goes
  to the processor, the screen and the other programs keep their part of the card;
- a watch every few seconds: when free RAM falls under the reserve and nothing runs, the models the app
  holds idle are released (they load again on their next use).
"""

import threading
import time
import traceback
from typing import Any, Dict, Optional

RAM_CHOICES = ("auto", "2", "3", "4", "6", "8", "12", "16")
VRAM_CHOICES = ("auto", "0.5", "1", "1.5", "2", "3", "4")
CHECK_EVERY_SEC = 10.0
GB = 2**30

_started = False
_last_release = 0.0


def auto_ram_gb(total_gb: float) -> float:
    """What Windows, a browser and a call need beside the app: a quarter of a small computer, 8 GB at most."""
    if total_gb <= 8:
        return 2.0
    if total_gb <= 16:
        return 4.0
    if total_gb <= 32:
        return 6.0
    return 8.0


def auto_vram_gb(total_gb: float) -> float:
    """The screen, the browser and the call's video keep part of the card; more on a large one, less on
    a small one, where every half gigabyte decides whether a model fits at all."""
    if total_gb <= 0:
        return 0.0
    if total_gb < 12:
        return 0.5
    return 1.0


def _setting(key: str) -> str:
    from app.database import get_all_settings

    return str(get_all_settings().get(key) or "auto").strip().lower()


def _ram_total() -> float:
    from app.sysinfo import memory

    m = memory()
    return float(m["total_gb"]) if m else 0.0


def _vram_total() -> float:
    try:
        from app.vram import gpu_memory

        m = gpu_memory()
        return float(m["total_gb"]) if m else 0.0
    except Exception:
        return 0.0


def ram_reserve_gb(total_gb: Optional[float] = None) -> float:
    v = _setting("mem_reserve_ram")
    total = _ram_total() if total_gb is None else total_gb
    if v != "auto":
        try:
            return max(0.0, min(float(v), max(0.0, total - 2.0) if total else float(v)))
        except ValueError:
            pass
    return auto_ram_gb(total)


def vram_reserve_gb(total_gb: Optional[float] = None) -> float:
    v = _setting("mem_reserve_vram")
    total = _vram_total() if total_gb is None else total_gb
    if v != "auto":
        try:
            return max(0.0, min(float(v), max(0.0, total - 1.0) if total else float(v)))
        except ValueError:
            pass
    return auto_vram_gb(total)


def status() -> Dict[str, Any]:
    """For the settings page: the computer's memory, the reserves chosen and what «auto» means here."""
    ram, vram = _ram_total(), _vram_total()
    return {"ram_total_gb": ram, "ram_auto_gb": auto_ram_gb(ram), "ram_gb": ram_reserve_gb(ram),
            "vram_total_gb": vram, "vram_auto_gb": auto_vram_gb(vram), "vram_gb": vram_reserve_gb(vram)}


def job_limit_bytes() -> int:
    """The cap of the work processes: all RAM but the reserve and what this app's own process holds now,
    never under 2 GB (a model would not load at all)."""
    total = _ram_total()
    if not total:
        return 0
    return int(max(2.0, total - ram_reserve_gb(total) - _own_gb()) * GB)


def _own_gb() -> float:
    """The memory this app's own process holds (its speech models live here, not in the job)."""
    import sys

    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            class Counters(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

            c = Counters()
            c.cb = ctypes.sizeof(c)
            psapi = ctypes.WinDLL("psapi")
            psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
            if psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(c), c.cb):
                return c.WorkingSetSize / GB
        else:
            import resource

            return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**20  # KB on Linux
    except Exception:
        pass
    return 1.0


def apply() -> None:
    """The reserves put in force now (at start and when the settings change)."""
    try:
        from app.shutdown import set_job_memory_limit

        limit = job_limit_bytes()
        if limit:
            set_job_memory_limit(limit)
    except Exception:
        traceback.print_exc()


def ollama_env() -> Dict[str, str]:
    """For the Ollama server this app starts: the video memory it leaves free."""
    gb = vram_reserve_gb()
    return {"OLLAMA_GPU_OVERHEAD": str(int(gb * GB))} if gb > 0 else {}


def low_on_ram() -> Optional[float]:
    """Free RAM in GB when it is under the reserve, else None."""
    from app.sysinfo import memory

    m = memory()
    if not m:
        return None
    free = float(m["free_gb"])
    return free if free < ram_reserve_gb(float(m["total_gb"])) else None


def _loop() -> None:
    global _last_release
    applied = 0
    while True:
        time.sleep(CHECK_EVERY_SEC)
        try:
            limit = job_limit_bytes()  # the app's own process grows and shrinks with its speech models
            if limit and abs(limit - applied) > GB // 2:
                from app.shutdown import set_job_memory_limit

                set_job_memory_limit(limit)
                applied = limit
            free = low_on_ram()
            if free is None or time.time() - _last_release < 60:
                continue
            from app import idle_unload

            if idle_unload._busy():  # a job or an answer is running: its model is needed now
                continue
            res = idle_unload.unload_now()
            _last_release = time.time()
            if res.get("released"):
                print(f"[memory] {free:.1f} GB of RAM free, under the {ram_reserve_gb():.1f} GB left to the system: "
                      f"released {', '.join(res['released'])}", flush=True)
        except Exception:
            traceback.print_exc()


def start() -> None:
    global _started
    if _started:
        return
    _started = True
    apply()
    threading.Thread(target=_loop, daemon=True, name="mem_reserve").start()
