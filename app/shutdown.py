"""
What the app stops before its process ends (the window closed, "Quit" in the tray, an update).

The process ends with os._exit (a hanging WebView2 must not keep it alive), and on Windows a child
process outlives its parent: FFmpeg recording the screen would go on writing until the disk is full,
a worker would keep its gigabytes of VRAM. So recordings are finished properly first (the screen
file closed by FFmpeg itself, the system sound file closed), then every child process the app
started for its work (track()) is ended with its own children.

That needs the app to end normally. For a crash or a forced end (Task Manager, taskkill /F), every
tracked process is also put in a Windows job that ends with the app's process (kill on close); its
own children (FFmpeg started by a worker) belong to the job too. Only the work processes: a browser
or a folder window the app opened is the user's and stays open.
"""

import subprocess
import sys
import threading
import weakref
from typing import Any

_procs: "weakref.WeakSet[subprocess.Popen]" = weakref.WeakSet()
_lock = threading.Lock()
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0


_job = None  # the Windows job of the work processes; its handle closes with the process
_job_lock = threading.Lock()


def _structs():
    import ctypes
    from ctypes import wintypes

    class BASIC(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class EXTENDED(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BASIC), ("IoInfo", ctypes.c_uint64 * 6),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    return EXTENDED


def _EXTENDED():  # noqa: N802 - a structure made on first use (ctypes.wintypes exists on Windows only)
    global _extended_cls
    if _extended_cls is None:
        _extended_cls = _structs()
    return _extended_cls()


_extended_cls = None


def _job_handle():
    global _job
    with _job_lock:
        if _job is not None:
            return _job
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = ctypes.c_void_p
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            raise OSError(ctypes.get_last_error(), "CreateJobObjectW")
        _set_limits(kernel32, job)  # ends with the app; the memory cap of app/mem_reserve.py when set
        _job = (kernel32, job)
        return _job


_job_memory_limit = 0  # bytes; 0: none


def set_job_memory_limit(limit: int) -> None:
    """Caps the memory all the work processes together may commit (app/mem_reserve.py: the RAM left to the
    system). Past it their allocations fail (Ollama reports it) instead of the computer swapping to a halt.
    Kept for the job made later too; Windows only, never raises."""
    global _job_memory_limit
    _job_memory_limit = max(0, int(limit))
    if sys.platform != "win32" or _job is None:
        return
    try:
        _set_limits(*_job)
    except Exception as e:
        print(f"[shutdown] memory limit of the work processes not set: {e}", flush=True)


def _set_limits(kernel32: Any, job: Any) -> None:
    import ctypes

    JobObjectExtendedLimitInformation, KILL_ON_CLOSE, JOB_MEMORY = 9, 0x2000, 0x200
    info = _EXTENDED()
    info.BasicLimitInformation.LimitFlags = KILL_ON_CLOSE | (JOB_MEMORY if _job_memory_limit else 0)
    info.JobMemoryLimit = _job_memory_limit
    if not kernel32.SetInformationJobObject(ctypes.c_void_p(job), JobObjectExtendedLimitInformation,
                                            ctypes.byref(info), ctypes.sizeof(info)):
        raise OSError(ctypes.get_last_error(), "SetInformationJobObject")


def _bind_to_app(proc: Any) -> None:
    """Puts a child process in the job that ends with the app (Windows); never raises."""
    handle = getattr(proc, "_handle", None)
    if sys.platform != "win32" or handle is None:
        return
    try:
        import ctypes

        kernel32, job = _job_handle()
        if not kernel32.AssignProcessToJobObject(ctypes.c_void_p(job), ctypes.c_void_p(int(handle))):
            print(f"[shutdown] child {proc.pid} not bound to the app: error {ctypes.get_last_error()}", flush=True)
    except Exception as e:
        print(f"[shutdown] child {getattr(proc, 'pid', '?')} not bound to the app: {e}", flush=True)


def track(proc: Any) -> Any:
    """A child process to end when the app ends (returns it, for Popen(...) chains)."""
    with _lock:
        _procs.add(proc)
    _bind_to_app(proc)
    return proc


def _kill_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        if sys.platform == "win32":  # uv and FFmpeg start processes of their own
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, timeout=10,
                           creationflags=_NO_WINDOW)
        else:
            proc.kill()
    except (OSError, subprocess.SubprocessError):
        try:
            proc.kill()
        except OSError:
            pass


def stop_all() -> None:
    """Finishes recordings and ends the work processes; never raises."""
    try:
        from app import screen_capture

        with screen_capture._lock:
            caps = list(screen_capture._captures.values())
        for cap in caps:
            try:
                cap.stop()  # "q": FFmpeg writes the end of the file, which stays playable
            except Exception:
                pass
    except Exception:
        pass
    try:
        from app import system_audio

        with system_audio._lock:
            caps = list(system_audio._captures.values())
        for cap in caps:
            try:
                cap.stop()
            except Exception:
                pass
    except Exception:
        pass
    try:  # an Ollama the user started stays, without the models the app loaded into it
        from app.ollama_client import release_on_exit

        release_on_exit()
    except Exception:
        pass
    with _lock:
        procs = list(_procs)
    for proc in procs:
        _kill_tree(proc)
