"""
What currently occupies the GPU, for the chips next to the GPU badge: Whisper (cached in this
process), the speaker-embedding model, the model Ollama keeps loaded (/api/ps) and the dub worker
processes. Unloading frees VRAM; preloading saves the load time of the next job.
"""

import ctypes
import sys
import threading
import traceback
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.database import get_all_settings, get_meeting


def _ollama_base() -> str:
    url = get_all_settings().get("ollama_url") or "http://127.0.0.1:11434"
    return url.replace("localhost", "127.0.0.1").rstrip("/")


class _NvmlMemory(ctypes.Structure):
    _fields_ = [("total", ctypes.c_ulonglong), ("free", ctypes.c_ulonglong), ("used", ctypes.c_ulonglong)]


_nvml_lock = threading.Lock()
_ollama_loading = threading.Event()  # set while the preload button loads an Ollama model
_ollama_loading_name: List[Optional[str]] = [None]
_nvml: Dict[str, Any] = {"lib": None, "handle": None, "failed": False}


def _nvml_memory() -> Optional[Tuple[int, int]]:
    """
    (used, total) bytes of GPU 0 from the driver's NVML library, loaded once into this process.
    Faster than starting nvidia-smi on every poll, and nothing is left hanging if the driver stalls.
    """
    with _nvml_lock:
        if _nvml["failed"]:
            return None
        try:
            if _nvml["lib"] is None:
                lib = ctypes.CDLL("nvml.dll") if sys.platform == "win32" else ctypes.CDLL("libnvidia-ml.so.1")
                if lib.nvmlInit_v2() != 0:
                    raise OSError("nvmlInit failed")
                handle = ctypes.c_void_p()
                if lib.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(handle)) != 0:
                    raise OSError("no GPU 0")
                _nvml.update(lib=lib, handle=handle)
            mem = _NvmlMemory()
            if _nvml["lib"].nvmlDeviceGetMemoryInfo(_nvml["handle"], ctypes.byref(mem)) != 0:
                return None
            return int(mem.used), int(mem.total)
        except Exception:
            _nvml["failed"] = True  # no NVIDIA driver: do not try again on every poll
            return None


def nvml_device() -> Optional[Tuple[str, int, int]]:
    """(name, used bytes, total bytes) of GPU 0 from NVML, or None."""
    mem = _nvml_memory()
    if not mem:
        return None
    with _nvml_lock:
        buf = ctypes.create_string_buffer(96)
        try:
            ok = _nvml["lib"].nvmlDeviceGetName(_nvml["handle"], buf, 96) == 0
        except Exception:
            ok = False
    return (buf.value.decode("utf-8", "replace") if ok else "NVIDIA GPU"), mem[0], mem[1]


def gpu_memory() -> Optional[Dict[str, float]]:
    """
    Device-wide used/free/total in GB (all programs), or None without an NVIDIA GPU. NVML is asked
    first: on Windows (WDDM) torch.cuda.mem_get_info misses other programs' memory.
    """
    gb = 2**30
    nv = _nvml_memory()
    if nv:
        used, total = nv
        return {"total_gb": round(total / gb, 1), "free_gb": round((total - used) / gb, 1), "used_gb": round(used / gb, 1)}
    try:
        import torch

        if not torch.cuda.is_available():
            return None
        free, total = torch.cuda.mem_get_info(0)
    except Exception:
        return None
    return {"total_gb": round(total / gb, 1), "free_gb": round(free / gb, 1), "used_gb": round((total - free) / gb, 1)}


def _same_model(a: str, b: str) -> bool:
    norm = lambda n: n if ":" in n else f"{n}:latest"  # noqa: E731
    return norm(a) == norm(b)


def ollama_release_others(keep: Optional[str] = None) -> List[str]:
    """One heavy model at a time: Ollama lets go of every model but `keep` (none: all of them). Asked,
    not waited for; skipped while live captions run (their translation model works next to others).
    Returns the names it asked to unload."""
    from app import live

    if live.has_sessions():
        return []
    names = [m["name"] for m in ollama_loaded() if not (keep and _same_model(m["name"], keep))]
    for name in names:
        try:
            with httpx.Client(timeout=10.0) as client:
                client.post(f"{_ollama_base()}/api/generate", json={"model": name, "keep_alive": 0})
        except Exception as e:
            print(f"[vram] Ollama did not unload {name}: {e}", flush=True)
    return names


def ollama_loaded() -> List[Dict[str, Any]]:
    """Models Ollama keeps in memory. Never starts Ollama."""
    from app.ollama_client import _is_ollama_port_open

    if not _is_ollama_port_open():
        return []
    try:
        with httpx.Client(timeout=0.8) as client:
            resp = client.get(f"{_ollama_base()}/api/ps")
            resp.raise_for_status()
            models = resp.json().get("models") or []
    except Exception:
        return []
    return [
        {"name": m.get("name") or m.get("model") or "?", "size_vram_gb": round((m.get("size_vram") or 0) / 2**30, 1),
         "expires_at": m.get("expires_at")}
        for m in models
    ]


# How long Ollama gets to let a model go by itself before its runner is stopped
OLLAMA_UNLOAD_WAIT_SEC = 8.0


def _stop_ollama_runners() -> None:
    """The processes in which Ollama holds models (its "runner"; ollama_llama_server in older versions).
    Its server stays and starts a new runner at the next request."""
    import subprocess

    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if sys.platform == "win32":
        script = ("Get-CimInstance Win32_Process | Where-Object { ($_.Name -eq 'ollama.exe' -and $_.CommandLine -match ' runner') "
                  "-or $_.Name -eq 'ollama_llama_server.exe' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }")
        subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, timeout=30, creationflags=flags)
    else:
        subprocess.run(["pkill", "-f", "ollama runner"], capture_output=True, timeout=30)
        subprocess.run(["pkill", "-f", "ollama_llama_server"], capture_output=True, timeout=30)


def ollama_unload(names: List[str], force: bool = True) -> List[str]:
    """Asks Ollama to let the models go and waits until they are out of memory: Ollama does it a moment
    later, or only after the answer it is writing. Still there after OLLAMA_UNLOAD_WAIT_SEC (force, Ollama
    on this computer): its runner is stopped. Returns the models still loaded."""
    import time

    from app.ollama_client import _ollama_address

    base = _ollama_base()
    with httpx.Client(timeout=5.0) as client:
        for name in names:
            try:
                client.post(f"{base}/api/generate", json={"model": name, "keep_alive": 0})
            except httpx.HTTPError:
                pass  # busy with an answer: the wait below covers it
    left = list(names)
    end = time.time() + OLLAMA_UNLOAD_WAIT_SEC
    while left and time.time() < end:
        time.sleep(0.5)
        loaded = {m["name"] for m in ollama_loaded()}
        left = [n for n in left if n in loaded]
    if left and force and _ollama_address(base)[0] == "127.0.0.1":
        try:
            _stop_ollama_runners()
        except Exception:
            traceback.print_exc()
        end = time.time() + 4.0
        while left and time.time() < end:
            time.sleep(0.5)
            loaded = {m["name"] for m in ollama_loaded()}
            left = [n for n in left if n in loaded]
    return left


def ollama_installed() -> List[str]:
    """Models downloaded into Ollama (whether loaded or not). Never starts Ollama."""
    from app.ollama_client import _is_ollama_port_open

    if not _is_ollama_port_open():
        return []
    try:
        with httpx.Client(timeout=0.8) as client:
            return [m.get("name") for m in client.get(f"{_ollama_base()}/api/tags").json().get("models") or []]
    except Exception:
        return []


def vram_snapshot() -> Dict[str, Any]:
    """
    Every model the app can use, loaded (in memory) or ready to load (downloaded): all Whisper
    models on disk, the speaker model, every Ollama model, the live-caption worker and the dub
    workers. A click on a chip unloads or loads that model.
    """
    from app import transcriber
    from app.diarizer import ecapa_loaded_on
    from app.dubbing import live_workers
    from app.model_manager import WHISPER_CATALOG, format_whisper_model_name, is_whisper_model_installed
    from app.ollama_client import format_llm_model_name

    settings = get_all_settings()
    busy = transcriber.running_job_kind()
    stage = job_stage()
    asr_busy = stage in _ASR_STAGES
    on_gpu = (settings.get("device") or "cuda") == "cuda"
    chips: List[Dict[str, Any]] = []

    key = transcriber.whisper_cache_key()
    wanted_whisper = settings.get("whisper_model") or "large-v3-turbo"
    loading_whisper = transcriber._preloading_name if transcriber._preloading else (
        wanted_whisper if busy == "transcribe" and not key else None)
    whisper_ids = [m["id"] for m in WHISPER_CATALOG if is_whisper_model_installed(m["id"])]
    if key and key[0] not in whisper_ids:
        whisper_ids.insert(0, key[0])
    for mid in whisper_ids or [wanted_whisper]:
        loaded = bool(key) and key[0] == mid
        chips.append({
            "kind": "whisper", "name": mid, "label": format_whisper_model_name(mid),
            "default": mid == wanted_whisper,
            "loaded": loaded, "loading": not loaded and loading_whisper == mid,
            "device": key[1] if loaded else None,
            # The transcription that uses it must finish first; loading goes through the job queue
            "can_unload": loaded and not asr_busy, "in_use": loaded and asr_busy,
            "can_preload": not loaded and on_gpu and busy is None and not transcriber._preloading,
        })

    ecapa = ecapa_loaded_on()
    if ecapa and ecapa.startswith("cuda"):
        chips.append({"kind": "speakers", "name": "ECAPA", "loaded": True,
                      "can_unload": stage != "diarizing", "in_use": stage == "diarizing", "can_preload": False})

    # Live captions run their own Whisper in a worker process (app/live.py)
    try:
        from app import live

        worker = live._worker
        if worker is not None and worker.proc is not None and worker.proc.poll() is None:
            with live._sessions_lock:
                active = bool(live._sessions)
            cap = worker.model_name or wanted_whisper
            chips.append({"kind": "live", "name": cap, "label": format_whisper_model_name(cap),
                          "loaded": True, "can_unload": not active, "in_use": active, "can_preload": False})
    except Exception:
        pass

    # GigaAM / Parakeet (app/asr_onnx.py) live in this process: in RAM, or on the GPU for a job (app/onnx_gpu.py)
    try:
        from app import asr_onnx, live

        loaded = set(asr_onnx.loaded_models())
        with live._sessions_lock:
            live_onnx = {s.onnx_model for s in live._sessions.values() if s.onnx_model}
        for mid in asr_onnx.ONNX_MODELS:
            if mid in loaded or asr_onnx.is_installed(mid):
                in_use = mid in loaded and (mid in live_onnx or asr_busy)
                chips.append({"kind": "onnx", "name": mid, "label": asr_onnx.ONNX_MODELS[mid]["name"],
                              "default": mid == wanted_whisper, "loaded": mid in loaded,
                              "live": mid in live_onnx, "device": "cuda" if asr_onnx.on_gpu(mid) else "cpu",
                              "can_unload": mid in loaded and not in_use, "in_use": in_use, "can_preload": mid not in loaded})
    except Exception:
        traceback.print_exc()

    loaded_ollama = {m["name"]: m for m in ollama_loaded()}
    installed = ollama_installed()
    wanted_llm = settings.get("ollama_model") or ""
    names = list(dict.fromkeys(list(loaded_ollama) + installed)) or ([wanted_llm] if wanted_llm else [])
    loading_llm = _ollama_loading_name[0] if _ollama_loading.is_set() else None
    for name in names:
        m = loaded_ollama.get(name)
        chips.append({
            "kind": "ollama", "name": name, "label": format_llm_model_name(name), "default": name == wanted_llm,
            "loaded": bool(m), "size_gb": m["size_vram_gb"] if m else None,
            "loading": not m and loading_llm == name,
            "can_unload": bool(m),  # a job asking it meanwhile gets an error and goes on (the switch)
            "can_preload": not m and not _ollama_loading.is_set(),
        })

    workers = [w for w in live_workers() if w["purpose"] == "dub"]
    if workers:
        chips.append({"kind": "dub", "name": "VoxCPM2 / Demucs", "loaded": True, "count": len(workers),
                      "can_unload": False, "can_preload": False})

    from app import idle_unload, sysinfo
    from app.ollama_client import is_embedding_model

    gpu = gpu_memory()
    onnx_gpu = (settings.get("onnx_gpu") or "true").lower() == "true"
    for c in chips:
        # Where the model runs (or will, when it is not loaded): the sidebar shows it under that device
        if not gpu:
            c["where"] = "cpu"
        elif c["kind"] in ("speakers", "dub"):
            c["where"] = "gpu"
        elif c["kind"] == "whisper":
            c["where"] = "gpu" if (c.get("device") or ("cuda" if on_gpu else "cpu")) == "cuda" else "cpu"
        elif c["kind"] == "live":
            c["where"] = "gpu" if on_gpu else "cpu"
        elif c["kind"] == "onnx":
            c["where"] = "gpu" if (c.get("device") == "cuda" or (not c.get("loaded") and onnx_gpu)) else "cpu"
        elif c["kind"] == "ollama":
            c["where"] = "cpu" if c.get("loaded") and not c.get("size_gb") else "gpu"
            c["embedding"] = is_embedding_model(c["name"])  # the model of search by meaning
    return {"gpu": gpu, "chips": chips, "busy": busy, "system": sysinfo.snapshot(), "idle": idle_unload.status()}


# What the running job does now (the status of its recording): a speech model is in use only while
# the job recognizes, the speaker model only while it splits by voices. While the overview is written
# (minutes on Ollama) they are free, and the buttons unload them.
_ASR_STAGES = ("extracting_audio", "transcribing")  # extracting: Whisper may hear the language first


def job_stage() -> Optional[str]:
    from app import transcriber

    if transcriber.running_job_kind() != "transcribe":
        return None
    mid = transcriber.running_meeting_id()
    m = get_meeting(mid) if mid is not None else None
    return (m or {}).get("status") or "transcribing"


def stop_work() -> None:
    """The switch: the jobs are cancelled, the captions of a recording end, and Ollama lets its models
    go (an overview being written breaks off), so nothing loads a model again right after."""
    from app import live, transcriber

    transcriber.stop_all_jobs()
    with live._sessions_lock:
        ids = list(live._sessions)
    for sid in ids:
        live.stop_session(sid)
    try:
        ollama_unload([m["name"] for m in ollama_loaded()])
    except Exception:
        traceback.print_exc()
    transcriber.stop_all_jobs(wait_sec=30.0)


def unload(kind: str, name: str = "", stop: bool = False) -> Dict[str, Any]:
    """stop: the model is in use and the user chose to stop the work that uses it."""
    if stop:
        stop_work()
    stage = job_stage()
    if kind == "whisper":
        if stage in _ASR_STAGES:
            raise RuntimeError("Whisper сейчас распознаёт запись")
        from app import transcriber

        transcriber.release_whisper_model()
    elif kind == "speakers":
        if stage == "diarizing":
            raise RuntimeError("Модель распознавания участников сейчас используется")
        from app.diarizer import unload_diarizer

        unload_diarizer()
    elif kind == "ollama":
        if not name:
            raise ValueError("Не указана модель Ollama")
        if ollama_unload([name]):
            raise RuntimeError(f"Ollama не выгрузила модель {name}")
    elif kind == "live":
        from app import live

        with live._sessions_lock:
            if live._sessions:
                raise RuntimeError("Модель субтитров сейчас используется записью")
        if live._worker is not None:
            with live._worker.lock:
                live._worker._kill()
    elif kind == "onnx":
        from app import asr_onnx, live

        with live._sessions_lock:
            if any(s.onnx_model == name for s in live._sessions.values()):
                raise RuntimeError("Модель сейчас пишет субтитры")
        if stage in _ASR_STAGES:
            raise RuntimeError("Модель сейчас распознаёт запись")
        asr_onnx.release(name)
    elif kind == "dub":
        raise RuntimeError("Процессы дубляжа завершаются вместе с задачей — отмените её в очереди")
    else:
        raise ValueError(f"Неизвестный тип модели {kind!r}")
    return vram_snapshot()


def preload(kind: str, name: str = "") -> Dict[str, Any]:
    from app import idle_unload, transcriber

    idle_unload.touch(name if kind == "ollama" else None)

    if kind == "whisper":
        from app.model_manager import is_whisper_model_installed

        if name and not is_whisper_model_installed(name):
            raise ValueError("Эта модель Whisper не скачана")
        if not transcriber.enqueue_whisper_preload(name or None):
            raise RuntimeError("Очередь занята — модель загрузится вместе со следующей задачей")
    elif kind == "ollama":
        from app.ollama_client import ensure_ollama_running

        model = name or get_all_settings().get("ollama_model") or ""
        if not model:
            raise ValueError("Модель Ollama не выбрана в настройках")
        base = _ollama_base()
        ensure_ollama_running(base)  # explicit user action: starting Ollama is expected here
        _ollama_loading_name[0] = model
        _ollama_loading.set()
        try:
            with httpx.Client(timeout=120.0) as client:
                # An empty prompt only loads the model; it stays for Ollama's usual keep-alive time
                client.post(f"{base}/api/generate", json={"model": model, "keep_alive": idle_unload.ollama_keep_alive() or "10m"}).raise_for_status()
        finally:
            _ollama_loading.clear()
    elif kind == "onnx":
        from app import asr_onnx

        if not asr_onnx.is_onnx_model(name) or not asr_onnx.is_installed(name):
            raise ValueError("Эта модель не скачана")
        threading.Thread(target=asr_onnx.preload, args=(name,), daemon=True).start()
    else:
        raise ValueError(f"Модель {kind!r} нельзя загрузить заранее")
    return vram_snapshot()
