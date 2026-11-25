"""
Speech recognition with GigaAM v3 (Sber, MIT licence) and NVIDIA Parakeet TDT 0.6B v3 (CC-BY-4.0),
both free for commercial use, run on ONNX Runtime through onnx-asr (MIT).

GigaAM is the most accurate model for Russian; Parakeet is several times faster than Whisper and
covers 25 European languages. Neither needs PyTorch. The audio is cut into phrases by the Silero
VAD (MIT), each phrase is recognized with token timestamps, and the tokens are joined into words,
so the result has the same shape as the Whisper segments (start, end, text, words) and the rest of
the pipeline (speakers, translation, subtitles) does not change.

Models are downloaded from Hugging Face (the ONNX exports in istupakov/*) into <models>/onnx.
"""

import re
import threading
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from app.paths import MODELS_DIR

ONNX_MODELS: Dict[str, Dict[str, Any]] = {
    "gigaam-v3": {
        "onnx_name": "gigaam-v3-e2e-rnnt",
        # Other files of the same repository for some copies (_key), each with the files it needs; until they
        # are downloaded (_complete_async: an installation made before they were added) the copy is the main one.
        # live: live captions by VAD phrases (app/live_phrases.py): the e2e-CTC int8 recognizes a phrase in
        # 0.1 s with the WER of the RNN-T (bench-report/asr-2026-11.md, item 3)
        # cpu: a job on the processor takes the e2e-RNN-T int8: the same WER, 1.6 times faster, 0.46 GB of memory
        # instead of 1.1 (item 5); the video card keeps the main fp32 model
        "variants": {
            "live": {"onnx_name": "gigaam-v3-e2e-ctc", "quantization": "int8", "phrases": True,
                     "files": ["v3_e2e_ctc.int8.onnx", "v3_e2e_ctc_vocab.txt"]},
            "cpu": {"onnx_name": "gigaam-v3-e2e-rnnt", "quantization": "int8",
                    "files": ["v3_e2e_rnnt_encoder.int8.onnx", "v3_e2e_rnnt_decoder.int8.onnx",
                              "v3_e2e_rnnt_joint.int8.onnx", "v3_e2e_rnnt_vocab.txt"]},
        },
        "name": "GigaAM v3",
        "size_mb": 1285,  # MiB as _dir_mb counts them: 1281 for the model folder downloaded on 2026-11-25
        "license": "MIT",
        "vram_gb": 1.5,  # on the GPU (app/onnx_gpu.py)
        "languages": ["ru"],
        "desc_ru": "Модель Сбера (Conformer, ONNX), обученная на русской речи. Сразу расставляет пунктуацию и регистр, числа пишет цифрами. WER на FLEURS: 3,5 % — лучший результат для русского среди моделей программы (у Whisper Pro 3,8 %). Быстрая и на процессоре (≈30× реального времени), на видеокарте ≈50×. Только русский язык.",
        "desc_en": "Sber's model (Conformer, ONNX) trained on Russian speech. Writes punctuation and capital letters itself, numbers as digits. WER on FLEURS: 3.5%, the best for Russian among the app's models (Whisper Pro: 3.8%). Fast on the CPU too (≈30× real time), ≈50× on a GPU. Russian only.",
    },
    "parakeet-v3": {
        "onnx_name": "nemo-parakeet-tdt-0.6b-v3",
        "name": "Parakeet TDT v3",
        "size_mb": 2600,
        "license": "CC-BY-4.0 (NVIDIA)",
        "vram_gb": 3.0,
        "languages": ["en", "ru", "de", "fr", "es", "it", "pt", "nl", "pl", "uk", "cs", "sk", "bg", "hr", "da",
                      "fi", "el", "hu", "lv", "lt", "mt", "ro", "sl", "sv", "et"],
        "desc_ru": "NVIDIA Parakeet TDT 0.6B v3 (FastConformer, ONNX): 25 европейских языков, включая русский и английский, с пунктуацией и регистром. WER на FLEURS: 5,5 % — русский, 7,8 % — английский. Быстрая на процессоре (≈23× реального времени), на видеокарте 56–72×.",
        "desc_en": "NVIDIA Parakeet TDT 0.6B v3 (FastConformer, ONNX): 25 European languages including Russian and English, with punctuation and capitals. WER on FLEURS: 5.5% Russian, 7.8% English. Fast on the CPU (≈23× real time), 56–72× on a GPU.",
    },
}
VAD_NAME = "silero"
MAX_PHRASE_SEC = 20.0

_lock = threading.Lock()
_fetch_lock = threading.Lock()
_loaded: Dict[str, Any] = {}
_downloads: Dict[str, Dict[str, Any]] = {}


# Removed models: what a setting or a recording that still names one now uses
REPLACED = {"gigaam-v2": "gigaam-v3", "canary-v2": "parakeet-v3"}  # Canary: slower and less accurate in Russian (bench-report/)


def is_onnx_model(model_id: str) -> bool:
    return model_id in ONNX_MODELS


def model_dir(model_id: str) -> Path:
    return MODELS_DIR / "onnx" / model_id


def _vad_dir() -> Path:
    return MODELS_DIR / "onnx" / "silero-vad"


def is_installed(model_id: str) -> bool:
    d = model_dir(model_id)
    return d.is_dir() and any(d.glob("*.onnx")) and any(_vad_dir().glob("*.onnx"))


def supports_language(model_id: str, lang: Optional[str]) -> bool:
    return not lang or lang == "auto" or lang[:2] in ONNX_MODELS[model_id]["languages"]


def _dir_mb(d: Path) -> float:
    """Size of a folder, including the partial files Hugging Face writes while downloading."""
    from app.paths import dir_size

    return dir_size(d) / 2**20


def download_progress(model_id: str) -> int:
    return max(1, min(99, int(_dir_mb(model_dir(model_id)) * 100 / ONNX_MODELS[model_id]["size_mb"])))


def catalog() -> List[Dict[str, Any]]:
    out = []
    for mid, m in ONNX_MODELS.items():
        dl = _downloads.get(mid) or {}
        out.append({"id": mid, "engine": "onnx", "name": m["name"], "size_mb": m["size_mb"], "license": m["license"],
                    "languages": m["languages"], "desc_ru": m["desc_ru"], "desc_en": m["desc_en"],
                    "installed": is_installed(mid), "downloading": bool(dl.get("active")),
                    "progress": download_progress(mid) if dl.get("active") else 0, "error": dl.get("error", "")})
    return out


ONNX_ASR_PIN = "onnx-asr==0.12.0"
# Packages the app installs by itself when they are missing: the exact files (PyPI wheels), so a
# replaced package or index installs nothing (requirements.txt is checked the same way). Their
# dependencies are in requirements.txt already, hence --no-deps.
PINNED = {
    "onnx-asr": ("0.12.0", "5e7ceca454609819ea7833f61e2302e0c8f6ece4f8a78b66c5daba53cb51de4a"),
    "yt-dlp": ("2026.8.19", "1d57897e94c6665a0a6f9bc54b34e584284e32c034ffab3a7df25d8f7b24eedf"),
}


def pinned_args(package: str, folder: Path) -> List[str]:
    """pip / uv arguments that install exactly PINNED[package] (a requirements file with its hash)."""
    version, sha = PINNED[package]
    req = folder / f"{package}.requirements.txt"
    req.write_text(f"{package}=={version} --hash=sha256:{sha}\n", encoding="utf-8")
    return ["-r", str(req), "--require-hashes", "--no-deps"]


def install_pinned(package: str) -> None:
    """Installs PINNED[package] into the program's Python (uv first, then pip); RuntimeError if it fails."""
    import importlib
    import tempfile

    print(f"[setup] installing {package}=={PINNED[package][0]}", flush=True)
    errors = []
    with tempfile.TemporaryDirectory(prefix="vs_pkg_") as tmp:
        for cmd in _install_commands(pinned_args(package, Path(tmp))):
            proc = _run(cmd)
            if proc.returncode == 0:
                importlib.invalidate_caches()
                return
            errors.append((proc.stderr or proc.stdout or "").strip()[-300:])
    raise RuntimeError(f"Не удалось установить {package}: " + (errors[-1] if errors else "нет uv и pip"))


def ensure_package() -> None:
    """Installs onnx-asr into the program's Python when it is missing (an update copied over an old
    installation brings the code but not the new library)."""
    import importlib

    try:
        importlib.import_module("onnx_asr")
        return
    except ImportError:
        pass
    install_pinned("onnx-asr")


def _run(cmd):
    import subprocess

    try:
        return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError as e:
        return subprocess.CompletedProcess(cmd, 1, "", str(e))


def _install_commands(args=None):
    """uv first (setup.bat makes the venv with uv, which has no pip in it), then pip, bootstrapping it
    with ensurepip when the venv has none. `args`: what to install (onnx-asr by default)."""
    import sys

    from app.pyenv import ensure_pip, find_uv

    uv = find_uv()
    if uv:
        yield [uv, "pip", "install", "--python", sys.executable, *(args or [ONNX_ASR_PIN])]
    ensure_pip(sys.executable)
    yield [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", *(args or [ONNX_ASR_PIN])]


CPU_BATCH = 8   # phrases recognized at once (onnx-asr's default)
GPU_BATCH = 32  # a GPU is faster with more at once; settings "onnx_gpu_batch" / "onnx_gpu_vad" to tune


def gpu_tuning() -> Tuple[int, bool]:
    """(phrases per batch, VAD on the GPU too) for jobs on the GPU."""
    try:
        from app.database import get_all_settings

        st = get_all_settings()
        batch = int(st.get("onnx_gpu_batch") or GPU_BATCH)
        return max(1, min(128, batch)), str(st.get("onnx_gpu_vad", "false")).lower() == "true"
    except Exception:
        return GPU_BATCH, False


# Each model has up to three copies in memory, each a session of its own (ONNX Runtime fixes the threads of a
# session when it is made): "<id>@gpu" for a job on the video card, "<id>" for a job on the processor (its threads
# from the budget below) and "<id>@live" for live captions and dictation (live_threads)
def _key(model_id: str, gpu: bool, live: bool = False) -> str:
    return f"{model_id}@gpu" if gpu else f"{model_id}@live" if live else model_id


def _settings() -> Dict[str, str]:
    try:
        from app.database import get_all_settings

        return get_all_settings()
    except Exception:
        return {}


def cpu_threads(settings: Optional[Dict[str, str]] = None) -> int:
    """Threads a model on the processor may use (Settings → Запись → «Потоки процессора»). Left alone, ONNX
    Runtime takes every core: the live captions of Parakeet kept a 20-thread processor at 100 % (reported by
    the user). «auto»: half of them, 2 to 8."""
    import os

    if settings is None:
        settings = _settings()
    cores = os.cpu_count() or 4
    value = str(settings.get("cpu_threads") or "auto").lower()
    if value == "all":
        return cores
    if value.isdigit():
        return max(1, min(int(value), cores))
    return max(2, min(8, cores // 2))


# One budget of threads for the whole program (bench-report/asr-2026-11.md, item 2): live captions by VAD phrases
# recognize one phrase of a few seconds at a time and need 2 threads; by the sliding window (Parakeet) they
# recognize up to 20 s again every 1.2 s and need 4: on 2 a step took 1 s in the median, the window fell behind
# and the WER rose from 5.6 % to 8-9 % (bench-report/asr-2026-11-check.md). While captions run, a transcription
# job on the processor takes at most what is left once they and RESERVED_THREADS (the call app, the video, the
# page) have theirs.
LIVE_THREADS = 2
WINDOW_THREADS = 4
RESERVED_THREADS = 2


def live_threads(settings: Optional[Dict[str, str]] = None, model_id: Optional[str] = None) -> int:
    """Threads of the copy for live captions and dictation of this model: by VAD phrases LIVE_THREADS, by the
    window WINDOW_THREADS (never more than the user's setting allows)."""
    want = WINDOW_THREADS if model_id in ONNX_MODELS and not live_phrases(model_id) else LIVE_THREADS
    return max(1, min(want, cpu_threads(settings)))


def _captions_running() -> bool:
    try:
        from app import live

        return live.has_sessions()
    except Exception:
        return False


def _captions_threads(settings: Dict[str, str]) -> int:
    """Threads the running captions take: the most of their models' copies (the Whisper captions: LIVE_THREADS)."""
    try:
        from app import live

        models = live.onnx_models_in_use()
    except Exception:
        models = set()
    return max([live_threads(settings, m) for m in models] or [live_threads(settings)])


def queue_threads(settings: Optional[Dict[str, str]] = None, captions: Optional[bool] = None) -> int:
    """Threads of a transcription job on the processor: the user's setting (cpu_threads) and, while live captions
    run, at most «logical processors − caption threads − RESERVED_THREADS» (at least 1). A session keeps its
    threads to its end: a job that started before the captions finishes with what it had, the next job's session
    is made with the budget of its start (_load)."""
    import os

    if settings is None:
        settings = _settings()
    limit = cpu_threads(settings)
    if captions is None:
        captions = _captions_running()
    if captions:
        cores = os.cpu_count() or 4
        limit = min(limit, max(1, cores - _captions_threads(settings) - RESERVED_THREADS))
    return limit


# ONNX Runtime's threads wait for work actively by default (spinning): two such pools on a 4-core / 8-thread
# laptop (live captions and the queue) froze the whole PC for up to 0.1 s hundreds of times in five minutes,
# with no gain in speed (bench-report/asr-2026-11.md, «созвон»). Without it the queue is even faster.
NO_SPINNING = {"session.intra_op.allow_spinning": "0", "session.inter_op.allow_spinning": "0"}


def _no_spinning(so: Any) -> Any:
    for key, value in NO_SPINNING.items():
        so.add_session_config_entry(key, value)
    return so


def _cpu_options(threads: Optional[int] = None):
    """Session options of a model on the processor: its threads limited (cpu_threads by default), not spinning."""
    try:
        import onnxruntime as ort
    except ImportError:
        return None
    so = ort.SessionOptions()
    so.intra_op_num_threads = threads or cpu_threads()
    so.inter_op_num_threads = 1
    return _no_spinning(so)


def _gpu_options():
    """Session options of a model on the video card: the operators left on the processor do not spin either."""
    try:
        import onnxruntime as ort
    except ImportError:
        return None
    return _no_spinning(ort.SessionOptions())


def release_cpu() -> None:
    """The copies on the processor go (the number of threads changed): loaded again when next needed."""
    with _lock:
        for key in [k for k in _loaded if not k.endswith("@gpu")]:
            _drop(key)


_made: Dict[str, Tuple[str, Optional[str], int]] = {}  # copy -> (onnx-asr model, quantization, threads) it was made with
_plain: Dict[str, Any] = {}  # copy of live captions -> the same model without the VAD (app/live_phrases.py)


def _drop(key: str) -> None:
    """A copy out of memory (call with _lock held)."""
    _loaded.pop(key, None)
    _plain.pop(key, None)
    _made.pop(key, None)


def _any_copy(model_id: str) -> bool:
    return any(k.split("@")[0] == model_id for k in list(_loaded))


def _variant(model_id: str, kind: str) -> Dict[str, Any]:
    """What the copy of this kind ("gpu", "cpu" or "live") is made from: {"onnx_name", "quantization", "phrases"}.
    A variant whose files are not downloaded yet gives way to the main model, and its files are fetched in the
    background (an installation made before the variant was added): the next copy made uses it."""
    m = ONNX_MODELS[model_id]
    v = (m.get("variants") or {}).get(kind)
    if v and _has_files(model_id, v):
        return v
    if v:
        _complete_async(model_id)
    return {"onnx_name": m["onnx_name"], "quantization": None, "phrases": False}


_present: set = set()  # (model, file) found on disk


def _has_files(model_id: str, variant: Dict[str, Any]) -> bool:
    d = model_dir(model_id)
    for name in variant.get("files") or []:
        if (model_id, name) not in _present:
            if not (d / name).is_file():
                return False
            _present.add((model_id, name))
    return True


def live_phrases(model_id: Optional[str]) -> bool:
    """Live captions with this model go by VAD phrases (app/live_phrases.py), not by the sliding window."""
    return bool(model_id) and model_id in ONNX_MODELS and bool(_variant(model_id, "live").get("phrases"))


_completing: Dict[str, float] = {}  # model -> when its missing files were last fetched in the background
COMPLETE_RETRY_SEC = 600.0


def _complete_async(model_id: str) -> None:
    """The files of the variants of an installed model, downloaded in the background (once; again after
    COMPLETE_RETRY_SEC when it failed)."""
    import time

    if not is_installed(model_id):
        return  # not installed: «Download» fetches everything
    with _lock:
        if time.time() - _completing.get(model_id, 0.0) < COMPLETE_RETRY_SEC:
            return
        _completing[model_id] = time.time()

    def work() -> None:
        try:
            with _fetch_lock:
                fetch(model_id)
            print(f"[asr_onnx] {model_id}: the files of its variants are downloaded", flush=True)
        except Exception as e:
            print(f"[asr_onnx] {model_id}: its variants were not downloaded: {e}", flush=True)

    threading.Thread(target=work, daemon=True, name=f"onnx_complete_{model_id}").start()


def _load(model_id: str, gpu: bool = False, live: bool = False):
    """The model and the VAD, loaded once (installing the library and downloading what is missing).
    gpu: on the video card (app/onnx_gpu.py); live: the copy for live captions and dictation (live_threads);
    otherwise the copy of a job on the processor, made again when the thread budget (queue_threads) has
    changed since it was made. Each copy is made from its variant (_variant), and again once a variant
    downloaded later is there. The VAD stays on the CPU: it is tiny, and the GPU would only add copies."""
    ensure_package()
    import onnx_asr

    from app import onnx_gpu

    if not _any_copy(model_id):
        with _fetch_lock:  # the download (gigabytes) must not hold the lock live captions wait on
            fetch(model_id)
    key = _key(model_id, gpu, live)
    variant = _variant(model_id, "gpu" if gpu else "live" if live else "cpu")
    threads = 0 if live else queue_threads()  # a job on the video card: its VAD on the processor
    cpu_n = live_threads(model_id=model_id) if live else threads
    made = (variant["onnx_name"], variant.get("quantization"), 0 if gpu else cpu_n)
    with _lock:
        if key in _loaded and key in _made and _made[key] != made:
            _drop(key)  # the budget changed (captions started or ended) or a variant was downloaded
        if key not in _loaded:
            if gpu:
                onnx_gpu.prepare_cuda()
            batch, vad_gpu = gpu_tuning() if gpu else (CPU_BATCH, False)
            opts = _gpu_options() if gpu else _cpu_options(cpu_n)
            asr = onnx_asr.load_model(variant["onnx_name"], model_dir(model_id), quantization=variant.get("quantization"),
                                      providers=onnx_gpu.providers(gpu), sess_options=opts)
            vad = onnx_asr.load_vad(VAD_NAME, _vad_dir(), providers=onnx_gpu.providers(vad_gpu),
                                    sess_options=_gpu_options() if vad_gpu else _cpu_options(cpu_n))
            _loaded[key] = asr.with_vad(vad, max_speech_duration_s=MAX_PHRASE_SEC, min_silence_duration_ms=300,
                                        speech_pad_ms=120, batch_size=batch).with_timestamps()
            if live:
                _plain[key] = asr.with_timestamps()
            _made[key] = made
        return _loaded[key]


# The commit each repository is downloaded from (onnx-asr itself always takes main): a rewritten or
# replaced repository does not reach anyone until the commit here is changed and its license checked
REVISIONS = {
    "istupakov/gigaam-v3-onnx": "322c3b29492673eb7d0b434bfa9dfb8653e34d02",  # MIT
    "istupakov/parakeet-tdt-0.6b-v3-onnx": "8f23f0c03c8761650bdb5b40aaf3e40d2c15f1ce",  # CC-BY-4.0
    "istupakov/silero-vad-onnx": "b3e3ee3cce4c11ceb63b1a0b229d916069c1ddf6",  # MIT
}


def _pinned(resolver: Any) -> Any:
    """onnx-asr's resolver, downloading from the commit in REVISIONS: its download steps are the
    library's own (onnx-asr 0.12, resolver.py) with revision= added."""
    from huggingface_hub import hf_hub_download, snapshot_download

    rev = REVISIONS[resolver.repo_id]

    def download_config(*, local_files_only: bool) -> Path:
        return Path(hf_hub_download(resolver.repo_id, "config.json", revision=rev, local_dir=resolver.local_dir,
                                    local_files_only=local_files_only))

    def download_model(quantization: Optional[str], *, local_files_only: bool) -> Path:
        files = list(resolver.model_type._get_model_files(quantization).values())
        files = [*files, *(f.removeprefix("**/") for f in files if f.startswith("**/"))]
        files = ["config.json", "config.yaml", *files,
                 *(str(Path(f).with_suffix(".onnx?data")) for f in files if Path(f).suffix == ".onnx")]
        return Path(snapshot_download(resolver.repo_id, revision=rev, local_dir=resolver.local_dir,
                                      local_files_only=local_files_only, allow_patterns=files))

    resolver._download_config = download_config
    resolver._download_model = download_model
    return resolver


def fetch(model_id: str) -> None:
    """Downloads the missing model files into our models folder. onnx_asr.load_model with a path that
    already exists only looks there and never downloads, so the files are fetched with its resolver
    (offline=False: look in the folder, download from Hugging Face what is not there)."""
    from onnx_asr.loader import create_asr_resolver, create_vad_resolver

    m = ONNX_MODELS[model_id]
    _pinned(create_asr_resolver(m["onnx_name"], model_dir(model_id), offline=False)).resolve_model()
    for v in (m.get("variants") or {}).values():  # the files of its other copies (_variant)
        _pinned(create_asr_resolver(v["onnx_name"], model_dir(model_id), offline=False)).resolve_model(
            quantization=v.get("quantization"))
    _pinned(create_vad_resolver(VAD_NAME, _vad_dir(), offline=False)).resolve_model()


def release(model_id: Optional[str] = None, gpu: Optional[bool] = None, keep_live: bool = False) -> None:
    """The copies of a model (of every model without model_id): gpu None — all of them, True — the one on the
    video card, False — those on the processor. keep_live: the copy of live captions stays."""
    with _lock:
        for key in list(_loaded):
            mid, _, kind = key.partition("@")
            if model_id and mid != model_id:
                continue
            if gpu is not None and (kind == "gpu") != gpu:
                continue
            if keep_live and kind == "live":
                continue
            _drop(key)


def shares_live_copy(model_id: str) -> bool:
    """A job on the processor would load the same files as the copy of live captions: Parakeet (both fp32, about
    3 GB each; 6 GB with the two at once, bench-report/asr-2026-11-check.md). GigaAM takes different files for
    each (CTC int8 by phrases, RNN-T int8 in the queue) and shares nothing once they are downloaded."""
    if model_id not in ONNX_MODELS:
        return False
    live, cpu = _variant(model_id, "live"), _variant(model_id, "cpu")
    return (live["onnx_name"], live.get("quantization")) == (cpu["onnx_name"], cpu.get("quantization"))


def release_live(model_id: str) -> bool:
    """The copy of live captions of this model out of memory (the captions ended and a job on the processor loads
    its own): True when it was there. Loaded again when captions or dictation next need it."""
    with _lock:
        key = _key(model_id, False, live=True)
        there = key in _loaded
        _drop(key)
    return there


def copies() -> List[str]:
    """The copies in memory, as keys of _key ("gigaam-v3", "gigaam-v3@gpu", "gigaam-v3@live")."""
    with _lock:
        return sorted(_loaded)


def on_gpu(model_id: str) -> bool:
    return _key(model_id, True) in _loaded


def release_gpu() -> None:
    """Frees the video memory of the models a transcription job loaded there."""
    with _lock:
        for k in [k for k in _loaded if k.endswith("@gpu")]:
            _drop(k)


def preload(model_id: str) -> None:
    try:
        _load(model_id)
    except Exception:
        traceback.print_exc()


_preloading: Dict[str, threading.Thread] = {}
_preload_errors: Dict[str, Tuple[float, str]] = {}  # model -> (when, why) of the last failed load
PRELOAD_RETRY_SEC = 60.0


def is_loaded(model_id: str) -> bool:
    """The copy of live captions is in memory, made from the variant it should be (a variant downloaded since
    is loaded in the background too): recognizing with it starts at once."""
    key = _key(model_id, False, live=True)
    if key not in _loaded:
        return False
    made, v = _made.get(key), _variant(model_id, "live")
    return made is None or made[:2] == (v["onnx_name"], v.get("quantization"))


def preload_async(model_id: str) -> str:
    """Loads the copy of live captions in the background (installing onnx-asr or downloading missing files can take
    minutes: never in a request). Returns why the last try failed, '' while none did; a failed load
    is tried again after PRELOAD_RETRY_SEC."""
    import time

    with _lock:
        running = _preloading.get(model_id)
        if running and running.is_alive() or is_loaded(model_id):
            return ""
        failed = _preload_errors.get(model_id)
        if failed and time.time() - failed[0] < PRELOAD_RETRY_SEC:
            return failed[1]

        def _run() -> None:
            try:
                _load(model_id, live=True)
                _preload_errors.pop(model_id, None)
            except Exception as e:
                traceback.print_exc()
                _preload_errors[model_id] = (time.time(), str(e)[:200])

        t = threading.Thread(target=_run, daemon=True, name=f"onnx_preload_{model_id}")
        _preloading[model_id] = t
        t.start()
    return failed[1] if failed else ""


def loaded_models() -> List[str]:
    with _lock:  # a load or release in another thread changed the dict while it was read
        keys = list(_loaded)
    return list(dict.fromkeys(k.split("@")[0] for k in keys))


# Frequent short words of the Latin-script languages Parakeet hears most: enough to tell them apart in a
# transcript (a German meeting is not taken for English)
_STOPWORDS = {
    "en": {"the", "and", "is", "are", "you", "that", "this", "with", "for", "have", "not", "what", "we"},
    "de": {"und", "der", "die", "das", "ist", "nicht", "ich", "wir", "sie", "mit", "auf", "ein", "eine"},
    "fr": {"le", "la", "les", "et", "est", "pas", "nous", "vous", "une", "des", "que", "pour", "dans"},
    "es": {"el", "los", "las", "y", "es", "que", "no", "una", "por", "para", "con", "pero", "muy"},
    "it": {"il", "che", "non", "per", "una", "sono", "della", "come", "anche", "questo", "gli", "ma"},
    "pt": {"o", "os", "que", "não", "uma", "para", "com", "por", "mais", "isso", "você", "são"},
    "nl": {"de", "het", "een", "en", "is", "niet", "dat", "wij", "ik", "met", "voor", "maar"},
    "pl": {"nie", "się", "jest", "że", "to", "na", "jak", "ale", "tak", "czy", "jestem", "już"},
}


def guess_language(text: str) -> str:
    """The language of a transcript by its letters (Cyrillic: Russian or Ukrainian) and, for Latin
    script, by its most frequent short words; English when nothing tells."""
    cyr = sum(1 for ch in text if "\u0400" <= ch <= "\u04ff")
    if cyr > len(text) * 0.3:
        return "uk" if any(ch in "іїєґІЇЄҐ" for ch in text) else "ru"
    words = re.findall(r"[^\W\d_]+", text.lower())
    counts = {lang: sum(1 for w in words if w in sw) for lang, sw in _STOPWORDS.items()}
    best = max(counts, key=counts.get)
    return best if counts[best] >= 3 and counts[best] > counts["en"] else "en"


_UNK_IN_WORD = re.compile(r"(?<=[а-яё])<unk>(?=[а-яё])", re.IGNORECASE)


def clean_text(text: str) -> str:
    """GigaAM writes "ё", which its vocabulary lacks, as "<unk>" ("ид<unk>т"): "е" inside a Russian
    word, nothing elsewhere."""
    if "<unk>" not in text:
        return text
    return " ".join(_UNK_IN_WORD.sub("е", text).replace("<unk>", "").split())


def _clean_words(words: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for w in words:
        word = clean_text(w["word"])
        if word.strip():
            out.append({**w, "word": " " + word.strip()})
    return out


QUIET_PEAK = 0.3     # below this the sound is raised, so the VAD does not take quiet speech for silence
SILENT_PEAK = 0.002  # nothing but noise: left as it is
MAX_GAIN = 30.0
LEVEL_WINDOW_SEC = 10.0
NOISE_SHARE = 0.03   # a window this much quieter than the loudest one is a pause: not raised


def _peak(a: Any) -> float:
    import numpy as np

    return float(np.percentile(np.abs(a), 99.9)) if a.size else 0.0  # not one click


def level(audio: Any, sr: int = 16000) -> Any:
    """Quiet speech brought to a normal level, so the VAD of GigaAM / Parakeet does not drop it
    (bench-report/gpu-report.md): the whole recording when it is quiet, and then each 10 s part on its
    own, so a far, quiet speaker next to a loud one is raised too. The gain changes smoothly between
    parts; pauses and noise are not raised."""
    import numpy as np

    a = np.asarray(audio, dtype=np.float32)
    if a.size == 0:
        return a
    peak = _peak(a)
    if SILENT_PEAK < peak < QUIET_PEAK:
        a = np.clip(a * min(0.9 / peak, MAX_GAIN), -1.0, 1.0)
        peak = _peak(a)
    win = int(LEVEL_WINDOW_SEC * sr)
    n = a.size // win
    if n < 2 or peak <= SILENT_PEAK:
        return a
    # part by part: the whole recording was copied five or six times over (2 GB for an hour and a half)
    peaks = np.array([np.percentile(np.abs(a[i * win:(i + 1) * win]), 99.9) for i in range(n)])
    floor = max(SILENT_PEAK, peak * NOISE_SHARE)
    gains = np.where((peaks > floor) & (peaks < QUIET_PEAK), np.minimum(0.9 / np.maximum(peaks, 1e-6), MAX_GAIN), 1.0)
    if np.all(gains == 1.0):
        return a
    centers = (np.arange(n) + 0.5) * win
    out = np.empty_like(a)
    step = 1 << 20
    for s in range(0, a.size, step):
        e = min(a.size, s + step)
        g = np.interp(np.arange(s, e, dtype=np.float64), centers, gains).astype(np.float32)
        np.clip(a[s:e] * g, -1.0, 1.0, out=out[s:e])
    return out


def recognize_array(model_id: str, audio: Any) -> List[Tuple[float, float, str]]:
    """Sentences of a short 16 kHz float32 window (live captions): [(start, end, text)], cut at the
    word timings, so a sentence ends exactly where the next one starts. The copy of live captions does it."""
    from app.cpu_priority import below_normal_thread

    asr = _load(model_id, live=True)
    out = []
    with below_normal_thread():  # the call app and the page first (app/cpu_priority.py)
        results = list(asr.recognize(level(audio), sample_rate=16000))
    for res in results:
        text = clean_text(" ".join((res.text or "").split()))
        if not text:
            continue
        start, end = float(res.start), float(res.end)
        if res.tokens and res.timestamps:
            seg = {"start": start, "end": end, "text": text,
                   "words": _clean_words(words_from_text(" ".join((res.text or "").split()), res.tokens, res.timestamps,
                                                         start, end))}
            out.extend((p["start"], p["end"], p["text"]) for p in split_sentences_words(seg))
        else:
            out.extend(split_sentences_text(start, end, text))
    return out


def recognize_phrase(model_id: str, audio: Any) -> List[Tuple[float, float, str]]:
    """Sentences of one phrase the live captions cut by the VAD themselves (app/live_phrases.py), already
    levelled: [(start, end, text)] from the phrase's start, cut at the word timings. No VAD inside."""
    import numpy as np

    from app.cpu_priority import below_normal_thread

    _load(model_id, live=True)
    plain = _plain.get(_key(model_id, False, live=True))
    if plain is None:  # unloaded meanwhile
        return []
    a = np.asarray(audio, dtype=np.float32)
    if a.size < 1600:  # under 0.1 s: nothing to hear
        return []
    with below_normal_thread():  # the call app and the page first (app/cpu_priority.py)
        res = plain.recognize(a, sample_rate=16000)
    raw = " ".join((getattr(res, "text", "") or "").split())
    text = clean_text(raw)
    if not text:
        return []
    end = a.size / 16000
    if getattr(res, "tokens", None) and getattr(res, "timestamps", None):
        words = _clean_words(words_from_text(raw, res.tokens, res.timestamps, 0.0, end))
        if words:
            seg = {"start": words[0]["start"], "end": end, "text": text, "words": words}
            return [(p["start"], p["end"], p["text"]) for p in split_sentences_words(seg)]
    return split_sentences_text(0.0, end, text)


def start_download(model_id: str) -> Dict[str, Any]:
    """Downloads the model in the background (loading it once fetches every file it needs)."""
    if model_id not in ONNX_MODELS:
        raise ValueError("Неизвестная модель")
    if (_downloads.get(model_id) or {}).get("active"):
        return _downloads[model_id]
    _downloads[model_id] = {"active": True, "error": ""}

    def work() -> None:
        try:
            _load(model_id)
            _downloads[model_id] = {"active": False, "error": ""}
        except Exception as e:
            traceback.print_exc()
            _downloads[model_id] = {"active": False, "error": str(e)[:300]}

    threading.Thread(target=work, daemon=True, name=f"onnx_dl_{model_id}").start()
    return _downloads[model_id]


def ensure_downloaded(model_id: str, on_progress: Callable[[int], None]) -> None:
    """A recording processed with a model that is not downloaded yet: its files first, with the
    percentage (of the folder's size) every second; the settings show the same download."""
    if is_installed(model_id):
        return
    ensure_package()
    stop = threading.Event()

    def watch() -> None:
        while not stop.wait(1.0):
            on_progress(download_progress(model_id))

    _downloads[model_id] = {"active": True, "error": ""}
    threading.Thread(target=watch, daemon=True, name=f"onnx_dl_watch_{model_id}").start()
    try:
        with _fetch_lock:
            fetch(model_id)
        _downloads[model_id] = {"active": False, "error": ""}
    except Exception as e:
        _downloads[model_id] = {"active": False, "error": str(e)[:300]}
        raise
    finally:
        stop.set()


def delete_model(model_id: str) -> bool:
    import shutil

    release(model_id)  # only this one: the other model may be giving live captions right now
    d = model_dir(model_id)
    if d.is_dir():
        shutil.rmtree(d, ignore_errors=True)
        return True
    return False


def words_from_text(text: str, tokens: List[str], timestamps: List[float], offset: float, end: float) -> List[Dict[str, Any]]:
    """Words exactly as in the model's text (its spaces), each starting at the time of the token that
    holds its first letter: tokens are matched to the text by their non-space characters."""
    starts: List[float] = []  # time of every non-space character of the token stream
    for tok, ts in zip(tokens, timestamps):
        starts.extend([float(ts)] * sum(1 for ch in tok.replace("▁", " ") if not ch.isspace()))
    words: List[Dict[str, Any]] = []
    last: List[float] = []  # time of the last token of each word
    pos = 0
    for w in text.split():
        if pos >= len(starts):
            return words_from_tokens(tokens, timestamps, offset, end)  # text and tokens differ
        words.append({"word": " " + w, "start": round(offset + starts[pos], 2)})
        last.append(offset + starts[min(len(starts), pos + len(w)) - 1])
        pos += len(w)
    if pos != len(starts):
        return words_from_tokens(tokens, timestamps, offset, end)
    _set_ends(words, last, end)
    return words


WORD_TAIL_SEC = 0.25  # a word goes on this long after its last token is emitted


def _set_ends(words: List[Dict[str, Any]], last: List[float], end: float) -> None:
    """A word ends a little after its last token, not where the next one starts: the pauses between
    words stay visible, and speaker separation cuts long phrases there (app/diarizer.py)."""
    for i, w in enumerate(words):
        if i + 1 < len(words):
            stop = min(words[i + 1]["start"], last[i] + WORD_TAIL_SEC)
        else:
            stop = end  # the phrase ends where the VAD heard the speech end
        w["end"] = round(max(w["start"] + 0.05, min(stop, w["start"] + 2.0)), 2)
        w["prob"] = 1.0


def words_from_tokens(tokens: List[str], timestamps: List[float], offset: float, end: float) -> List[Dict[str, Any]]:
    """Joins sub-word tokens into words: a token starting with a space (or "▁") starts a new word.
    A word lasts until the next word starts (the last one until the end of the phrase)."""
    words: List[Dict[str, Any]] = []
    last: List[float] = []
    space = True  # a space before the next piece (GigaAM v3 gives it as a separate "▁" token)
    for tok, ts in zip(tokens, timestamps):
        piece = tok.replace("▁", " ")
        if not piece:
            continue
        if not piece.strip():
            space = True
            continue
        if space or piece[0].isspace() or not words:
            words.append({"word": " " + piece.strip(), "start": round(offset + float(ts), 2)})
            last.append(offset + float(ts))
        else:
            words[-1]["word"] += piece.rstrip()
            last[-1] = offset + float(ts)
        space = piece[-1].isspace()
    _set_ends(words, last, end)
    return words


_SENT_END = (".", "?", "!", "…")


def split_sentences_words(seg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """A phrase of several sentences as one segment per sentence (cut at words that end one)."""
    words = seg.get("words") or []
    if len(words) < 2:
        return [seg]
    out, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        if w["word"].strip().endswith(_SENT_END) and i < len(words) - 1:
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    if len(out) == 1:
        return [seg]
    return [{"start": ws[0]["start"], "end": ws[-1]["end"], "text": "".join(w["word"] for w in ws).strip(), "words": ws}
            for ws in out]


def split_sentences_text(start: float, end: float, text: str) -> List[Tuple[float, float, str]]:
    """The same without word timings: times shared by the length of each sentence."""
    import re

    parts = [p.strip() for p in re.split(r"(?<=[.?!…])\s+", text) if p.strip()]
    if len(parts) < 2:
        return [(start, end, text)]
    total = sum(len(p) for p in parts)
    out, t = [], start
    for p in parts:
        d = (end - start) * len(p) / total
        out.append((round(t, 2), round(t + d, 2), p))
        t += d
    return out


def transcribe(model_id: str, wav_path: Path, total_dur: float, on_progress: Callable[[float], None],
               check_cancel: Callable[[], None], out: Optional[List[Dict[str, Any]]] = None,
               gpu: bool = False, leveling: bool = True) -> List[Dict[str, Any]]:
    """Segments like faster-whisper's: [{start, end, text, words: [{word, start, end, prob}]}].
    `out` (optional) receives them as they come, for showing the text while it is recognized."""
    import contextlib

    from app.cpu_priority import below_normal_thread

    asr = _load(model_id, gpu)
    # on the processor the job's thread runs «below normal»: the call app and the page first (app/cpu_priority.py)
    with contextlib.nullcontext() if gpu else below_normal_thread():
        return _transcribe_with(asr, wav_path, total_dur, on_progress, check_cancel, out, leveling)


def _transcribe_with(asr: Any, wav_path: Path, total_dur: float, on_progress: Callable[[float], None],
                     check_cancel: Callable[[], None], out: Optional[List[Dict[str, Any]]],
                     leveling: bool) -> List[Dict[str, Any]]:
    import soundfile as sf

    audio, sr = sf.read(str(wav_path), dtype="float32")  # 16 kHz mono (app/audio_utils.py)
    if getattr(audio, "ndim", 1) > 1:
        audio = audio.mean(axis=1)
    # leveling: quiet parts raised first (chosen per recording, on by default)
    results: Iterator[Any] = asr.recognize(level(audio, sr) if leveling else audio, sample_rate=sr)
    segments: List[Dict[str, Any]] = out if out is not None else []
    for res in results:
        check_cancel()
        raw = " ".join((res.text or "").split())
        text = clean_text(raw)
        if not text:
            continue
        start, end = float(res.start), float(res.end)
        words = _clean_words(words_from_text(raw, res.tokens, res.timestamps, start, end)) if res.tokens and res.timestamps else []
        seg = {"start": round(start, 2), "end": round(end, 2), "text": text, "words": words}
        segments.extend(split_sentences_words(seg) if words else
                        [{"start": a, "end": b, "text": t, "words": []} for a, b, t in split_sentences_text(start, end, text)])
        on_progress(min(1.0, end / max(1.0, total_dur)))
    return segments
