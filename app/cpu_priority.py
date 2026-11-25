"""
Lower scheduling priority for speech recognition on the processor (bench-report/asr-2026-11.md, item 7).

Windows gives the call app, the video and the page the processor first when the speech work runs «below
normal»: in the measurement on 8 logical processors fewer threads and the lowered priority together cut the
worst wake-up delay of the system from 31 to 17 ms. The main process of the app (the server and the page) keeps its normal
priority, so only two things are lowered:

- a separate process doing nothing but speech recognition (the Whisper caption worker, app/live_worker.py):
  the whole process, BELOW_NORMAL_PRIORITY_CLASS on Windows, nice +5 elsewhere;
- in this process, the thread that runs a transcription job or a caption step on the processor, for the time
  it runs (Windows only: elsewhere a thread's nice value cannot be raised back without privileges).

ONNX Runtime's own worker threads keep the normal priority: Windows does not pass a thread's priority on to
the threads it starts, and the Python API of ONNX Runtime has no hook for it. The thread budget
(app/asr_onnx.queue_threads) and spinning off (app/asr_onnx.NO_SPINNING) are what keeps them in check.
"""

import contextlib
import os
from typing import Any, Iterator

BELOW_NORMAL_PRIORITY_CLASS = 0x4000
THREAD_PRIORITY_BELOW_NORMAL = -1
THREAD_PRIORITY_ERROR_RETURN = 0x7FFFFFFF
NICE = 5

_WINDOWS = os.name == "nt"


def _kernel32() -> Any:
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.GetCurrentThread.restype = wintypes.HANDLE
    k32.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k32.SetPriorityClass.restype = wintypes.BOOL
    k32.GetThreadPriority.argtypes = [wintypes.HANDLE]
    k32.GetThreadPriority.restype = ctypes.c_int
    k32.SetThreadPriority.argtypes = [wintypes.HANDLE, ctypes.c_int]
    k32.SetThreadPriority.restype = wintypes.BOOL
    return k32


def lower_process() -> bool:
    """The calling process (a worker for speech recognition, never the app itself) at «below normal»."""
    try:
        if _WINDOWS:
            k32 = _kernel32()
            return bool(k32.SetPriorityClass(k32.GetCurrentProcess(), BELOW_NORMAL_PRIORITY_CLASS))
        os.nice(NICE)
        return True
    except (OSError, AttributeError):
        return False


@contextlib.contextmanager
def below_normal_thread() -> Iterator[None]:
    """The calling thread at «below normal» while the block runs, then back to what it was (Windows)."""
    if not _WINDOWS:
        yield
        return
    k32 = None
    old = THREAD_PRIORITY_ERROR_RETURN
    try:
        k32 = _kernel32()
        old = k32.GetThreadPriority(k32.GetCurrentThread())
        if old == THREAD_PRIORITY_ERROR_RETURN or old <= THREAD_PRIORITY_BELOW_NORMAL or \
                not k32.SetThreadPriority(k32.GetCurrentThread(), THREAD_PRIORITY_BELOW_NORMAL):
            old = THREAD_PRIORITY_ERROR_RETURN  # already low, or not changed: nothing to give back
    except (OSError, AttributeError):
        old = THREAD_PRIORITY_ERROR_RETURN
    try:
        yield
    finally:
        if k32 is not None and old != THREAD_PRIORITY_ERROR_RETURN:
            try:
                k32.SetThreadPriority(k32.GetCurrentThread(), old)
            except OSError:
                pass
