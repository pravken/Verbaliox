"""
The program's own share of the computer, for the load indicator of the status bar: the memory and the
processor of this process, of the live-caption and dub worker processes and of Ollama, and the video
memory they hold.

No extra package: on Windows OpenProcess, K32GetProcessMemoryInfo, GetProcessTimes and a Toolhelp
snapshot (kernel32, ctypes), elsewhere /proc. The processor share is measured between two calls (the first
one gives None) and is a share of the whole computer, as the total load is. The video memory of each
process comes from NVML (app/vram.nvml_process_memory); where the driver does not tell it (Windows in its
usual WDDM mode), the sizes Ollama reports and the memory torch reserved in this process stand in, and
the figure is marked approximate.
"""

import ctypes
import os
import sys
import threading
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

_lock = threading.Lock()
_last_cpu: Dict[int, tuple] = {}  # pid → (cpu seconds, wall time) at the previous call
_ollama_pids: Dict[str, Any] = {"at": 0.0, "pids": []}
GB = 2**30

if sys.platform == "win32":
    from ctypes import wintypes

    class _MemCounters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    class _ProcessEntry(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    _QUERY = 0x1000  # PROCESS_QUERY_LIMITED_INFORMATION: enough for the memory and the times


def _open(pid: int):
    k32 = ctypes.windll.kernel32
    k32.OpenProcess.restype = wintypes.HANDLE
    h = k32.OpenProcess(_QUERY, False, int(pid))
    return wintypes.HANDLE(h) if h else None


def rss(pid: int) -> Optional[int]:
    """The physical memory a process holds (its working set), in bytes; None when it cannot be read."""
    try:
        if sys.platform == "win32":
            h = _open(pid)
            if not h:
                return None
            try:
                mc = _MemCounters()
                mc.cb = ctypes.sizeof(_MemCounters)
                if not ctypes.windll.kernel32.K32GetProcessMemoryInfo(h, ctypes.byref(mc), mc.cb):
                    return None
                return int(mc.WorkingSetSize)
            finally:
                ctypes.windll.kernel32.CloseHandle(h)
        with open(f"/proc/{int(pid)}/status", encoding="ascii", errors="replace") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
    except Exception:
        return None
    return None


def cpu_seconds(pid: int) -> Optional[float]:
    """The processor time a process used so far (kernel and user), in seconds."""
    try:
        if sys.platform == "win32":
            h = _open(pid)
            if not h:
                return None
            try:
                ft = [wintypes.FILETIME() for _ in range(4)]  # created, exited, kernel, user
                if not ctypes.windll.kernel32.GetProcessTimes(h, *[ctypes.byref(x) for x in ft]):
                    return None
                val = lambda x: (x.dwHighDateTime << 32) | x.dwLowDateTime  # noqa: E731
                return (val(ft[2]) + val(ft[3])) / 1e7
            finally:
                ctypes.windll.kernel32.CloseHandle(h)
        with open(f"/proc/{int(pid)}/stat", encoding="ascii", errors="replace") as f:
            fields = f.read().rsplit(")", 1)[1].split()
        return (int(fields[11]) + int(fields[12])) / os.sysconf("SC_CLK_TCK")
    except Exception:
        return None


_EPOCH_AS_FILETIME = 11644473600  # seconds from 1601-01-01 (FILETIME) to 1970-01-01


def _boot_time() -> Optional[float]:
    try:
        with open("/proc/stat", encoding="ascii", errors="replace") as f:
            for line in f:
                if line.startswith("btime "):
                    return float(line.split()[1])
    except Exception:
        pass
    return None


def _win_times(h) -> Optional[Tuple[float, Optional[float], bool]]:
    """(processor seconds, start time, exited) of an open process handle. GetProcessTimes answers after the
    process ended too, as long as the handle is open."""
    ft = [wintypes.FILETIME() for _ in range(4)]  # created, exited, kernel, user
    if not ctypes.windll.kernel32.GetProcessTimes(h, *[ctypes.byref(x) for x in ft]):
        return None
    val = lambda x: (x.dwHighDateTime << 32) | x.dwLowDateTime  # noqa: E731
    created = val(ft[0]) / 1e7 - _EPOCH_AS_FILETIME if val(ft[0]) else None
    return (val(ft[2]) + val(ft[3])) / 1e7, created, bool(val(ft[1]))


def cpu_times(pid: int) -> Optional[Tuple[float, Optional[float]]]:
    """(processor seconds so far, when the process started — seconds since the epoch, None when unknown)."""
    try:
        if sys.platform == "win32":
            h = _open(pid)
            if not h:
                return None
            try:
                got = _win_times(h)
                return (got[0], got[1]) if got else None
            finally:
                ctypes.windll.kernel32.CloseHandle(h)
        with open(f"/proc/{int(pid)}/stat", encoding="ascii", errors="replace") as f:
            fields = f.read().rsplit(")", 1)[1].split()
        tick = os.sysconf("SC_CLK_TCK")
        boot = _boot_time()
        return (int(fields[11]) + int(fields[12])) / tick, (boot + int(fields[19]) / tick) if boot is not None else None
    except Exception:
        return None


class CpuTracker:
    """The processor time of a set of processes, look after look, without losing a process that ended between
    two looks (ffmpeg, deep-filter): on Windows its handle stays open from one look to the next, so its last
    seconds are still read once it ended (and its pid cannot be reused meanwhile). Elsewhere /proc answers
    until the process is reaped."""

    def __init__(self) -> None:
        self._handles: Dict[int, Any] = {}

    def read(self, pids: Iterable[int]) -> Dict[int, Tuple[float, Optional[float]]]:
        """{pid: (processor seconds, start time)} of pids, and of the processes of the previous look that ended
        since (their final seconds, once)."""
        if sys.platform != "win32":
            out = {}
            for pid in pids:
                got = cpu_times(pid)
                if got is not None:
                    out[int(pid)] = got
            return out
        k32 = ctypes.windll.kernel32
        out = {}
        for pid in set(int(p) for p in pids) - set(self._handles):
            h = _open(pid)
            if h:
                self._handles[pid] = h
        for pid, h in list(self._handles.items()):
            got = None
            try:
                got = _win_times(h)
            except Exception:
                pass
            if got is not None:
                out[pid] = (got[0], got[1])
            if got is None or got[2]:  # ended: its last seconds are read, the handle goes
                k32.CloseHandle(h)
                self._handles.pop(pid, None)
        return out

    def forget(self) -> None:
        if sys.platform == "win32":
            for h in self._handles.values():
                ctypes.windll.kernel32.CloseHandle(h)
        self._handles.clear()


def cpu_percent(pid: int, now: Optional[float] = None) -> Optional[float]:
    """The share of the whole computer's processor a process used since the previous call."""
    sec = cpu_seconds(pid)
    if sec is None:
        return None
    now = time.monotonic() if now is None else now
    with _lock:
        prev = _last_cpu.get(pid)
        _last_cpu[pid] = (sec, now)
    if not prev or now <= prev[1]:
        return None
    share = (sec - prev[0]) / (now - prev[1]) / max(1, os.cpu_count() or 1) * 100
    return round(max(0.0, min(100.0, share)), 1)


def _find_by_name(prefix: str) -> List[int]:
    """The processes whose program file starts with prefix (ollama.exe, ollama_llama_server.exe …)."""
    out: List[int] = []
    try:
        if sys.platform == "win32":
            k32 = ctypes.windll.kernel32
            k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
            snap = k32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
            if not snap or snap == wintypes.HANDLE(-1).value:
                return out
            snap = wintypes.HANDLE(snap)
            try:
                entry = _ProcessEntry()
                entry.dwSize = ctypes.sizeof(_ProcessEntry)
                ok = k32.Process32FirstW(snap, ctypes.byref(entry))
                while ok:
                    if entry.szExeFile.lower().startswith(prefix):
                        out.append(int(entry.th32ProcessID))
                    ok = k32.Process32NextW(snap, ctypes.byref(entry))
            finally:
                k32.CloseHandle(snap)
            return out
        for name in os.listdir("/proc"):
            if not name.isdigit():
                continue
            try:
                with open(f"/proc/{name}/comm", encoding="utf-8", errors="replace") as f:
                    if f.read().strip().lower().startswith(prefix):
                        out.append(int(name))
            except OSError:
                continue
    except Exception:
        pass
    return out


def parent_map() -> Dict[int, int]:
    """{pid: parent pid} of every process (a Toolhelp snapshot on Windows, /proc elsewhere); {} when unknown."""
    out: Dict[int, int] = {}
    try:
        if sys.platform == "win32":
            k32 = ctypes.windll.kernel32
            k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
            snap = k32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
            if not snap or snap == wintypes.HANDLE(-1).value:
                return out
            snap = wintypes.HANDLE(snap)
            try:
                entry = _ProcessEntry()
                entry.dwSize = ctypes.sizeof(_ProcessEntry)
                ok = k32.Process32FirstW(snap, ctypes.byref(entry))
                while ok:
                    out[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
                    ok = k32.Process32NextW(snap, ctypes.byref(entry))
            finally:
                k32.CloseHandle(snap)
            return out
        for name in os.listdir("/proc"):
            if not name.isdigit():
                continue
            try:
                with open(f"/proc/{name}/stat", encoding="ascii", errors="replace") as f:
                    out[int(name)] = int(f.read().rsplit(")", 1)[1].split()[1])
            except (OSError, IndexError, ValueError):
                continue
    except Exception:
        pass
    return out


def descendants(root: int, parents: Dict[int, int]) -> List[int]:
    """root and every process started from it, at any depth (ffmpeg, deep-filter, the workers of the program)."""
    children: Dict[int, List[int]] = {}
    for pid, ppid in parents.items():
        if pid != ppid:
            children.setdefault(ppid, []).append(pid)
    out, todo, seen = [], [int(root)], set()
    while todo:
        pid = todo.pop()
        if pid in seen:
            continue
        seen.add(pid)
        out.append(pid)
        todo.extend(children.get(pid, []))
    return out


def own_pids() -> List[int]:
    """The program's processes: this one, everything it started, and Ollama's (the analysis models)."""
    pids = set(descendants(os.getpid(), parent_map()))
    pids.update(ollama_pids(fresh=True))  # a runner Ollama just started counts from this look on, not 30 s later
    return sorted(pids)


def ollama_pids(fresh: bool = False) -> List[int]:
    """Ollama's processes (the server and its model runners), looked up at most every 30 s (fresh: now)."""
    now = time.monotonic()
    with _lock:
        if not fresh and now - _ollama_pids["at"] < 30 and _ollama_pids["at"]:
            return list(_ollama_pids["pids"])
    pids = _find_by_name("ollama")
    with _lock:
        _ollama_pids.update(at=now, pids=pids)
    return pids


def group(pids: Iterable[int], gpu_by_pid: Optional[Dict[int, int]] = None) -> Optional[Dict[str, Any]]:
    """The memory, processor and video memory of a set of processes together; None when none is readable."""
    ram, cpu, gpu, seen, gpu_known = 0, 0.0, 0, False, False
    for pid in pids:
        r = rss(pid)
        if r is None:
            continue
        seen = True
        ram += r
        cpu += cpu_percent(pid) or 0.0
        if gpu_by_pid and pid in gpu_by_pid:
            gpu += gpu_by_pid[pid]
            gpu_known = True
    if not seen:
        return None
    return {"ram_gb": round(ram / GB, 2), "cpu_percent": round(min(100.0, cpu), 1),
            "gpu_gb": round(gpu / GB, 2) if gpu_known else None}


def _torch_reserved() -> int:
    """The video memory torch reserved in this process (Whisper, the speaker model), without starting CUDA."""
    torch = sys.modules.get("torch")
    try:
        if torch is not None and torch.cuda.is_initialized():
            return int(torch.cuda.memory_reserved())
    except Exception:
        pass
    return 0


def snapshot(workers: Dict[str, List[int]], ollama_vram_gb: float = 0.0,
             gpu_by_pid: Optional[Dict[int, int]] = None) -> Dict[str, Any]:
    """
    {"parts": {"app"|"live"|"dub"|"ollama": {ram_gb, cpu_percent, gpu_gb}}, "ram_gb", "cpu_percent", "gpu_gb",
    "gpu_exact"}: workers names the other processes of the program ({"live": [pid], "dub": [pids]}).
    """
    parts: Dict[str, Any] = {}
    sets = {"app": [os.getpid()], **{k: v for k, v in workers.items() if v}, "ollama": ollama_pids()}
    for name, pids in sets.items():
        g = group(pids, gpu_by_pid)
        if g:
            parts[name] = g
    exact = bool(gpu_by_pid) and any(p.get("gpu_gb") is not None for p in parts.values())
    if exact:
        gpu = sum(p.get("gpu_gb") or 0 for p in parts.values())
    else:  # the driver does not say it per process: what Ollama reports and what torch holds here
        gpu = ollama_vram_gb + _torch_reserved() / GB
    return {"parts": parts, "ram_gb": round(sum(p["ram_gb"] for p in parts.values()), 2),
            "cpu_percent": round(min(100.0, sum(p["cpu_percent"] for p in parts.values())), 1),
            "gpu_gb": round(gpu, 2), "gpu_exact": exact}
