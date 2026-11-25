"""
Frees the models the app keeps in memory once it no longer uses them (Settings → General,
`idle_unload_minutes`; 0 turns the automatic unload off). Asked by the user: a recording with live caption
translation that began within the 10 minutes after the last processing found the analysis model still in the
video memory, beside the caption models (0.4 GB left on a card of 10 GB).

The rules:

* **After the processing: AFTER_WORK_SEC (60 s).** When the queue has nothing running or waiting (a
  transcription with its automatic analysis — overview, tasks, title, note — is one job, so there is no moment
  between them), or the last caption session ends, a mark is set (`work_done`). If nothing uses the app for
  AFTER_WORK_SEC after it, everything this app loaded is released: Whisper, GigaAM / Parakeet, the speaker
  models, the caption worker, the Ollama models this app asked for. A model the user asked by hand (a question
  to the assistant, the «Анализ» button, a preload in the memory panel) within the idle limit stays until that
  limit: a follow-up question does not wait for it to load again. Caption sessions still open: only what they
  do not use goes (see below).
* **Interactive use: the idle limit (`idle_unload_minutes`).** Every use calls `touch()`; a use other than the
  captions' own cancels the mark above. When nothing runs and the last use is older than the limit,
  everything is released as before.
* **Captions start (or their translation is turned on):** the Ollama models of this app the captions do not
  translate with (the analysis model) are unloaded, and so are the speech models of the queue when no job runs
  (`captions_started`). Not while an analysis is running (app/meeting_guard.py normally breaks an automatic one
  off). Done whatever the idle limit: it is about room on the card, not about idleness.
* **The captions' translator changes** («Качество» ↔ «Быстро», a model chosen in the studio): the previous one
  is unloaded unless another caption session or a running analysis uses it (`translator_switched`).
* **Ollama's own keep_alive**: the idle limit for the user's requests; for the requests of a queued job at most
  BACKGROUND_KEEP_ALIVE_MIN, so Ollama lets the model go by itself even when the unload above is skipped.

Every unload writes one line in the log with its reason (model names only, never a recording's title).
Models other programs loaded into Ollama are left alone. The models load again on their next use.
"""

import threading
import time
import traceback
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import httpx

CHECK_EVERY_SEC = 15.0
AFTER_WORK_SEC = 60.0  # after the processing: a new job or question within this keeps the models
BACKGROUND_KEEP_ALIVE_MIN = 2  # Ollama's keep_alive for a queued job's requests (minutes)

_lock = threading.Lock()
_last_used = time.time()
_unloaded_after: Optional[float] = None  # _last_used value the last unload happened for
_ollama_used: Set[str] = set()
_interactive: Dict[str, float] = {}  # Ollama model -> when the user last asked it (not from a queued job)
_after_work: Optional[Tuple[float, str]] = None  # (when the processing ended, why): see work_done
_started = False


def _in_job_thread() -> bool:
    """This thread runs a queued job (a transcription and its analysis, a translation, a deferred analysis)."""
    try:
        from app import transcriber

        return transcriber._running_id is not None and threading.get_ident() == transcriber._running_thread
    except Exception:
        return False


def touch(ollama_model: Optional[str] = None, captions: bool = False) -> None:
    """A use of the app. captions: the live captions' own use (audio, their translator): it keeps the idle
    time from running out but does not cancel the unload after the processing, which leaves their models."""
    global _last_used, _after_work
    now = time.time()
    in_job = _in_job_thread() if ollama_model and not captions else True
    with _lock:
        _last_used = now
        if ollama_model:
            _ollama_used.add(ollama_model)
        if captions:
            return
        _after_work = None
        if ollama_model and not in_job:
            _interactive[ollama_model] = now


def _bump() -> None:
    """In use right now (seen by the check): the idle time counts from the end of it; the mark stays."""
    global _last_used
    with _lock:
        _last_used = time.time()


def work_done(reason: str) -> None:
    """The processing ended (the queue is empty) or the captions did: everything goes AFTER_WORK_SEC later
    unless something uses the app meanwhile (touch)."""
    global _after_work
    if not limit_minutes():
        return
    with _lock:
        _after_work = (time.time(), reason)


def limit_minutes() -> int:
    from app.database import get_all_settings

    try:
        return max(0, int(float(get_all_settings().get("idle_unload_minutes") or 0)))
    except ValueError:
        return 0


def ollama_keep_alive(background: Optional[bool] = None) -> Optional[str]:
    """keep_alive for this app's Ollama requests: the idle limit, so Ollama unloads by itself too; for a
    queued job's requests (background; None: whether this thread runs one) at most BACKGROUND_KEEP_ALIVE_MIN."""
    minutes = limit_minutes()
    if not minutes:
        return None
    if background is None:
        background = _in_job_thread()
    return f"{min(minutes, BACKGROUND_KEEP_ALIVE_MIN) if background else minutes}m"


def status() -> Dict[str, Any]:
    minutes = limit_minutes()
    now = time.time()
    with _lock:
        idle = now - _last_used
        mark = _after_work
    if not minutes:
        return {"minutes": minutes, "idle_sec": round(idle), "unload_in_sec": None}
    left = minutes * 60 - idle
    if mark:
        left = min(left, AFTER_WORK_SEC - (now - mark[0]))
    return {"minutes": minutes, "idle_sec": round(idle), "unload_in_sec": max(0, round(left))}


def _busy() -> bool:
    from app import live, transcriber

    if transcriber.running_job_kind():
        return True
    from app.ollama_client import analysis_running

    if analysis_running():  # an overview or an answer asked on the page is being written
        return True
    return live.has_sessions()


def _analysis_busy() -> bool:
    """An analysis is being written, or its job runs (between two of its answers too)."""
    try:
        from app import meeting_guard, transcriber
        from app.ollama_client import analysis_running

        if analysis_running():
            return True
        with meeting_guard._lock:
            if meeting_guard._running:  # the automatic analysis after a transcription
                return True
        return transcriber.running_job_kind() in ("analysis", "complete", "translate")
    except Exception:
        traceback.print_exc()
        return True  # not known: left alone


def _same(a: str, b: str) -> bool:
    norm = lambda n: n if ":" in n else f"{n}:latest"  # noqa: E731
    return norm(a) == norm(b)


def _among(name: str, names: Iterable[Optional[str]]) -> bool:
    return any(n and _same(name, n) for n in names)


def release_speech_models() -> List[str]:
    """The models of transcription out of memory: Whisper, GigaAM / Parakeet, the speaker models (ECAPA and
    Nemotron, which no unload reached before: it stayed until the app ended). Returns what was released.
    While live captions run, the processor's copy of GigaAM / Parakeet they recognize with stays."""
    from app import asr_onnx, live, nemotron_diar, transcriber
    from app.vram import ecapa_loaded_on

    released = []
    if transcriber.whisper_cache_key():
        transcriber.release_whisper_model()
        released.append("whisper")
    if ecapa_loaded_on():
        from app.diarizer import unload_diarizer

        unload_diarizer()
        released.append("speakers")
    if nemotron_diar.loaded():
        nemotron_diar.unload()
        released.append("nemotron")
    loaded = asr_onnx.loaded_models()
    if loaded:
        captions = live.onnx_models_in_use() if live.has_sessions() else set()
        if captions:
            before = asr_onnx.copies()
            for model in loaded:  # only the captions' own copies stay (app/asr_onnx._key)
                asr_onnx.release(model, keep_live=model in captions)
            if asr_onnx.copies() != before:
                released.append("onnx")
        else:
            asr_onnx.release()  # GigaAM / Parakeet: up to 3 GB of RAM or VRAM
            released.append("onnx")
    return released


def _ollama_unload_ours(keep: Iterable[Optional[str]] = ()) -> List[str]:
    """The Ollama models this app asked for, but `keep`, unloaded (asked, then waited for: app/vram)."""
    from app.vram import ollama_loaded, ollama_unload

    with _lock:
        ours = set(_ollama_used)
    keep = list(keep)
    names = [m["name"] for m in ollama_loaded() if _among(m["name"], ours) and not _among(m["name"], keep)]
    if names:
        ollama_unload(names, force=False)
    return names


def unload_now(force: bool = False, keep: Iterable[str] = ()) -> Dict[str, Any]:
    """Releases everything the app holds; returns what was released. force (the button): every model
    Ollama has in memory too, also one loaded before this start or by another program, waiting until it
    is really gone (app/vram.ollama_unload). keep: Ollama models left in memory (the user's recent ones)."""
    from app import live

    released = release_speech_models()
    worker = live._worker
    if worker is not None and worker.proc is not None:
        with worker.lock:
            worker._kill()
        released.append("live")
    try:
        from app.vram import _ollama_base, ollama_loaded, ollama_unload

        with _lock:
            ours = set(_ollama_used)
        keep = list(keep)
        names = [m["name"] for m in ollama_loaded() if force or (m["name"] in ours and not _among(m["name"], keep))]
        if force:
            left = ollama_unload(names)
            released += [n for n in names if n not in left]
            if left:
                return {"released": released, "left": left}
        else:
            for name in names:
                with httpx.Client(timeout=15.0) as client:
                    client.post(f"{_ollama_base()}/api/generate", json={"model": name, "keep_alive": 0})
                released.append(name)
    except Exception:
        traceback.print_exc()
    return {"released": released}


def free_for_captions(reason: str) -> List[str]:
    """What live captions do not use leaves the memory: the speech models of the queue (when no job runs) and
    the Ollama models of this app but the captions' translators (not while an analysis runs)."""
    from app import live, transcriber

    released: List[str] = []
    try:
        if not transcriber.running_job_kind():
            released += release_speech_models()
    except Exception:
        traceback.print_exc()
    try:
        if not _analysis_busy():
            released += _ollama_unload_ours(keep=live.translator_models())
    except Exception:
        traceback.print_exc()
    if released:
        print(f"[idle] {reason}: released {', '.join(released)}", flush=True)
    return released


def captions_started() -> None:
    """A caption session began, or its translation was turned on: the card is freed for its models (in a
    thread: the session's request does not wait for Ollama)."""
    threading.Thread(target=free_for_captions, args=("live captions started",), daemon=True,
                     name="idle_captions").start()


def translator_switched(previous: Optional[str], current: Optional[str]) -> bool:
    """The captions' translator changed from `previous` to `current`: the previous one is unloaded, unless
    another caption session translates with it or a running analysis uses it. True when it was unloaded."""
    if not previous or (current and _same(previous, current)):
        return False
    try:
        from app import live
        from app.ollama_client import analysis_running

        if _among(previous, live.translator_models()):
            return False
        if _among(previous, analysis_running()) or (_analysis_busy() and _is_analysis_model(previous)):
            return False
        from app.vram import ollama_loaded, ollama_unload

        if not _among(previous, [m["name"] for m in ollama_loaded()]):
            return False
        ollama_unload([previous], force=False)
        print(f"[idle] the caption translator changed: released {previous}", flush=True)
        return True
    except Exception:
        traceback.print_exc()
        return False


def _is_analysis_model(name: str) -> bool:
    try:
        from app.database import get_all_settings

        chosen = get_all_settings().get("ollama_model") or ""
        return bool(chosen) and _same(name, chosen)
    except Exception:
        return True


def _after_work_unload(mark: Tuple[float, str], now: float, minutes: int) -> Optional[Dict[str, Any]]:
    global _after_work
    from app import live, transcriber
    from app.ollama_client import analysis_running

    if transcriber.running_job_kind() or analysis_running():
        touch()  # in use again: the idle limit counts from the end of it
        return None
    with _lock:
        if _after_work is not mark:  # a use came meanwhile
            return None
        _after_work = None
        keep = sorted(m for m, at in _interactive.items() if now - at < minutes * 60)
    reason = f"{mark[1]}, nothing else for {int(AFTER_WORK_SEC)} s"
    if live.has_sessions():
        return {"released": free_for_captions(reason)}
    res = unload_now(keep=keep)
    if res["released"]:
        print(f"[idle] {reason}: released {', '.join(res['released'])}"
              + (f"; kept until the idle limit: {', '.join(keep)}" if keep else ""), flush=True)
    return res


def tick(now: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """One look (the thread runs it every CHECK_EVERY_SEC). Returns what was released, or None."""
    global _unloaded_after
    now = time.time() if now is None else now
    minutes = limit_minutes()
    if not minutes:
        return None
    with _lock:
        last = _last_used
        mark = _after_work
    if mark and now - mark[0] >= AFTER_WORK_SEC:
        return _after_work_unload(mark, now, minutes)
    if _unloaded_after == last or now - last < minutes * 60:
        return None
    if _busy():
        _bump()  # in use right now: count the idle time from the end of it
        return None
    res = unload_now()
    _unloaded_after = last
    if res["released"]:
        print(f"[idle] {minutes} min without use: released {', '.join(res['released'])}", flush=True)
    return res


def _loop() -> None:
    while True:
        time.sleep(CHECK_EVERY_SEC)
        try:
            tick()
        except Exception:
            traceback.print_exc()


def start() -> None:
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, daemon=True, name="idle_unload").start()
