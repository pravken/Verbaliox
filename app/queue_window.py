"""
When the automatic work of the queue may start (asked by the user: «работаю — всё зависает»): the transcription
of a recording queued by itself, the analysis that waited, and the mix of the recorded tracks.

Settings → Общие → «Фоновая обработка»:
- queue_when: "always" (as before), "idle" (the computer is free), "schedule" (from queue_from to queue_to, the
  window may cross midnight), "idle_or_schedule" (either);
- the computer is free when the load of the other programs stays below queue_cpu_max % of the processor and queue_gpu_max % of the
  video card for LOW_FOR_SEC in a row. The program's own processes (this one, everything it started — ffmpeg,
  DeepFilterNet, the caption and dub workers — and Ollama) are taken out of the load: its own work is no user's
  load. No video card (no NVML): only the processor counts. The keyboard and the mouse do not count (asked by the
  user: the load is what matters, not whether someone reads or types).

Only the start of the next job waits: a job running goes on when the user comes back. A meeting still holds the
queue as before (app/meeting_guard). What the user starts by hand does not wait (app/transcriber._waits_for_window),
and neither do «Начать сейчас» and «Свести сейчас».

A light look every SAMPLE_SEC on a thread of its own (no package: app/sysinfo, app/procstat, app/vram NVML);
the queue asks hold() under its lock, which reads only what was measured. Where the load cannot be measured,
the computer is taken for free.
"""

import threading
import time
import traceback
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

SAMPLE_SEC = 15.0
LOW_FOR_SEC = 120.0  # the load below the thresholds this long in a row: the computer is free
MODES = ("always", "idle", "schedule", "idle_or_schedule")
DEFAULTS = {"queue_when": "always", "queue_cpu_max": "30", "queue_gpu_max": "30",
            "queue_from": "19:00", "queue_to": "08:00"}

_lock = threading.Lock()
# what the last look measured: the load of the other programs (None: not known), since when it is low
# sampled_at: when the last look was taken (0: none since the mode needs them)
_state: Dict[str, Any] = {"cpu": None, "gpu": None, "low_since": 0.0, "measured": False, "held": False,
                          "started": False, "sampled_at": 0.0}
STALE_SEC = 2 * SAMPLE_SEC  # the last look older than this (the computer slept): what it measured holds no more
_prev: Dict[str, Any] = {"sys": None, "own": {}, "at": 0.0, "wall": 0.0}


# --- the settings ---
def _setting(settings: Dict[str, str], key: str) -> str:
    return str(settings.get(key) or DEFAULTS[key]).strip()


def mode(settings: Optional[Dict[str, str]] = None) -> str:
    if settings is None:
        settings = _settings()
    m = _setting(settings, "queue_when")
    return m if m in MODES else "always"


def _int(settings: Dict[str, str], key: str, lo: int, hi: int) -> int:
    try:
        return min(hi, max(lo, int(float(_setting(settings, key)))))
    except (TypeError, ValueError):
        return int(DEFAULTS[key])


def _minutes(text: str, default: str) -> int:
    """"HH:MM" → minutes of the day."""
    for value in (text, default):
        try:
            h, m = str(value).split(":")
            h, m = int(h), int(m)
            if 0 <= h < 24 and 0 <= m < 60:
                return h * 60 + m
        except (TypeError, ValueError):
            continue
    return 0


def _settings() -> Dict[str, str]:
    try:
        from app.database import get_all_settings

        return get_all_settings()
    except Exception:
        return dict(DEFAULTS)


# --- the schedule ---
def in_schedule(at: datetime, start: int, end: int) -> bool:
    """at falls in the window from start to end (minutes of the day); end before start crosses midnight,
    and start equal to end is the whole day."""
    m = at.hour * 60 + at.minute
    if start == end:
        return True
    if start < end:
        return start <= m < end
    return m >= start or m < end


def next_start(at: datetime, start: int) -> datetime:
    """The next beginning of the window after at (today's, or tomorrow's)."""
    day = at.replace(hour=start // 60, minute=start % 60, second=0, microsecond=0)
    return day if day > at else day + timedelta(days=1)


# --- the computer free ---


def is_free(settings: Dict[str, str], now: float, low_since: float, measured: bool) -> bool:
    """The other programs' load stayed below the thresholds LOW_FOR_SEC. The load not measured: free, as before
    the setting."""
    if low_since and now - low_since >= LOW_FOR_SEC:
        return True
    return not measured


def decide(settings: Dict[str, str], now: float, low_since: float, measured: bool = True) -> Dict[str, Any]:
    """What holds the automatic work: {} — nothing; {"kind": "idle"} — waits for the computer to be free;
    {"kind": "schedule", "from": "HH:MM", "until": time} — waits for the start of the schedule;
    {"kind": "idle", "from", "until"} — waits for either."""
    m = mode(settings)
    if m == "always":
        return {}
    want_idle = m in ("idle", "idle_or_schedule")
    want_time = m in ("schedule", "idle_or_schedule")
    if want_idle and is_free(settings, now, low_since, measured):
        return {}
    out: Dict[str, Any] = {"kind": "idle" if want_idle else "schedule"}
    if want_time:
        start = _minutes(_setting(settings, "queue_from"), DEFAULTS["queue_from"])
        end = _minutes(_setting(settings, "queue_to"), DEFAULTS["queue_to"])
        at = datetime.fromtimestamp(now)
        if in_schedule(at, start, end):
            return {}
        out["from"] = f"{start // 60:02d}:{start % 60:02d}"
        out["until"] = next_start(at, start).timestamp()
    return out


def hold(now: Optional[float] = None, settings: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """What holds the automatic work now ({} — nothing). Fast: what the last look measured."""
    now = time.time() if now is None else now
    settings = _settings() if settings is None else settings
    if mode(settings) == "always":
        return {}
    with _lock:
        low_since, measured = float(_state["low_since"]), bool(_state["measured"])
        sampled_at, sampling = float(_state["sampled_at"]), bool(_state["started"])
    if sampling and mode(settings) in ("idle", "idle_or_schedule") and not (0 <= now - sampled_at <= STALE_SEC):
        # no look yet since the mode was chosen (it was «always» a moment ago), or the last one is old (after
        # sleep): not taken for free until a fresh look — «not measured» is free only where nothing can be measured
        low_since, measured = 0.0, True
    out = decide(settings, now, low_since, measured)
    if "until" in out:
        out["left"] = max(0, int(round(out["until"] - now)))
    return out


# --- the load of the other programs ---
def _own_busy_on_gpu() -> bool:
    """The program itself works on the video card now (a job, live captions, an analysis)."""
    try:
        from app import live, transcriber
        from app.ollama_client import analysis_running

        return bool(transcriber.running_job_kind() or live.has_sessions() or analysis_running())
    except Exception:
        return False


def _cpu_other(own_pids) -> Optional[float]:
    """The processor load of the other programs since the last look, %: the whole computer's less the program's.
    None at the first look, or where it cannot be read. A process of the program that began since the last look
    counts all its seconds as the program's (ffmpeg, deep-filter started by a job), and one that ended since is
    counted to its end (app/procstat.CpuTracker): else each counted as the other programs' load for a part of the
    look, and almost every job broke the run of low looks."""
    import os

    from app import sysinfo

    mono, wall = time.monotonic(), time.time()
    times = sysinfo._cpu_times()
    own = _tracker().read(own_pids)
    prev_sys, prev_own, prev_at, prev_wall = _prev["sys"], _prev["own"], _prev.get("at") or 0.0, _prev.get("wall") or 0.0
    _prev.update(sys=times, own={pid: sec for pid, (sec, _started) in own.items()}, at=mono, wall=wall)
    if times is None or prev_sys is None or mono <= prev_at:
        return None
    d_idle, d_total = times[0] - prev_sys[0], times[1] - prev_sys[1]
    if d_total <= 0:
        return None
    total = 100.0 * (1 - d_idle / d_total)
    used = 0.0
    for pid, (sec, started) in own.items():
        if pid in prev_own:
            used += max(0.0, sec - prev_own[pid])
        elif started is not None and started >= prev_wall - 1.0:
            used += max(0.0, sec)  # began since the last look: all of it in this one
        # else: an older process that has just become the program's (Ollama found now): its past is not this look's
    mine = used / (mono - prev_at) / max(1, os.cpu_count() or 1) * 100
    return round(max(0.0, min(100.0, total - mine)), 1)


_cpu_tracker: List[Any] = []


def _tracker():
    from app import procstat

    if not _cpu_tracker:
        _cpu_tracker.append(procstat.CpuTracker())
    return _cpu_tracker[0]


def _ollama_on_gpu() -> bool:
    """Ollama keeps a model on the video card: its work there is the program's (the rule «Ollama is own»), and
    the driver does not say its share."""
    try:
        from app import vram

        return any(float(m.get("size_vram") or 0) > 0 for m in (vram._ollama_ps(timeout=0.5) or []))
    except Exception:
        return False


def _gpu_other(own_pids) -> Optional[float]:
    """The video card load of the other programs, %; None without NVML, or when the program itself works on it and
    the driver does not tell its share (then this look counts the processor only)."""
    from app import vram

    total = vram.gpu_utilization()
    if total is None:
        return None
    per = vram.gpu_process_utilization(int((time.time() - SAMPLE_SEC) * 1e6))  # the last look's span
    if per is None:
        return None if (_own_busy_on_gpu() or _ollama_on_gpu()) else float(total)
    mine = sum(v for pid, v in per.items() if pid in own_pids)
    return float(max(0, min(100, total - mine)))


def sample(settings: Optional[Dict[str, str]] = None, now: Optional[float] = None) -> Dict[str, Any]:
    """One look at the load; updates since when it is low. Returns what it measured."""
    from app import procstat

    settings = _settings() if settings is None else settings
    now = time.time() if now is None else now
    with _lock:
        stale = bool(_state["sampled_at"]) and not (0 <= now - _state["sampled_at"] <= STALE_SEC)
        if stale:  # the computer slept since the last look: the run of low looks starts again, as the figures do
            _state["low_since"] = 0.0
    if stale:
        _prev.update(sys=None, own={}, at=0.0, wall=0.0)
    try:
        pids = set(procstat.own_pids())
    except Exception:
        pids = set()
    cpu = _cpu_other(pids)
    try:
        gpu = _gpu_other(pids)
    except Exception:
        gpu = None
    # the processor's times readable: the load can be measured (the first look gives no figure yet)
    out = note(settings, now, cpu, gpu, readable=_prev["sys"] is not None)
    with _lock:
        _state["sampled_at"] = now
    return out


def note(settings: Dict[str, str], now: float, cpu: Optional[float], gpu: Optional[float],
         readable: bool = True) -> Dict[str, Any]:
    """Takes one measurement: the load is low while the processor (and the video card, where known) of the other
    programs stay below their thresholds; an unknown processor breaks no run of low looks."""
    cpu_max = _int(settings, "queue_cpu_max", 5, 95)
    gpu_max = _int(settings, "queue_gpu_max", 5, 95)
    with _lock:
        _state.update(cpu=cpu, gpu=gpu)
        _state["measured"] = bool(_state["measured"] or readable or cpu is not None)
        if cpu is None:
            return dict(_state)
        low = cpu < cpu_max and (gpu is None or gpu < gpu_max)
        if not low:
            _state["low_since"] = 0.0
        elif not _state["low_since"]:
            _state["low_since"] = now
        return dict(_state)


def status() -> Dict[str, Any]:
    """For the settings page: the mode, what holds the queue now, and the load measured."""
    settings = _settings()
    with _lock:
        cpu, gpu = _state["cpu"], _state["gpu"]
    return {"mode": mode(settings), "hold": hold(settings=settings), "cpu": cpu, "gpu": gpu}


def tick(now: Optional[float] = None) -> Dict[str, Any]:
    """One look: the load measured (only when the mode needs it) and the queue woken when it may go on."""
    settings = _settings()
    if mode(settings) in ("idle", "idle_or_schedule"):
        sample(settings, now)
    else:  # not measured meanwhile: a run of low looks from before does not count when the mode comes back
        with _lock:
            _state.update(low_since=0.0, measured=False, cpu=None, gpu=None, sampled_at=0.0)
        _prev.update(sys=None, own={}, at=0.0, wall=0.0)
        if _cpu_tracker:
            _cpu_tracker[0].forget()
    held = hold(now, settings)
    with _lock:
        was, _state["held"] = _state["held"], bool(held)
    if was and not held:
        print("[queue_window] the computer is free (or the schedule began): the automatic jobs go on", flush=True)
        try:
            from app import meeting_guard, transcriber

            transcriber.wake_queue()
            meeting_guard.kick()  # the analyses marked meanwhile go to the queue now, not at its next look
        except Exception:
            traceback.print_exc()
    elif held and not was:
        print(f"[queue_window] the automatic jobs wait: {held.get('kind')}", flush=True)
    return held


def settings_changed() -> None:
    """The settings of «Фоновая обработка» saved: a look now, so the page and the queue do not wait for the next one."""
    def run() -> None:
        try:
            tick()
        except Exception:
            traceback.print_exc()

    threading.Thread(target=run, daemon=True, name="queue_window_now").start()


def _loop() -> None:
    while True:
        try:
            tick()
        except Exception:
            traceback.print_exc()
        time.sleep(SAMPLE_SEC)


def start() -> None:
    with _lock:
        if _state["started"]:
            return
        _state["started"] = True
    threading.Thread(target=_loop, daemon=True, name="queue_window").start()
