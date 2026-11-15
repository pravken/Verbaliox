"""
Nemotron 3 Diarization (NVIDIA, OpenMDW-1.1): who speaks when, for the whole recording at once, up to
8 people. Measured on the PC (bench-report/diarization.md): on AMI 2 % of the time to the wrong person
against 6 % for ECAPA with clustering, and the number of people right in all 4 meetings; on the owner's
Russian recordings the same people as the program's own separation, and on a 55-minute Teams meeting
5 people where ECAPA found 6.

It is a choice in the settings (diarizer_engine = "nemotron"), downloaded on request. ECAPA still
computes the voice prints (voice profiles across recordings) and places the phrases Nemotron leaves
unmarked; any failure of Nemotron falls back to ECAPA's clustering (app/diarizer.py).

The license (OpenMDW-1.1) asks to keep its text and the notices: the downloaded folder keeps the model
card (README.md) and the license text (licenses/OpenMDW-1.1.txt), and README and the About window
name the model and its license.
"""

import shutil
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.database import MODELS_DIR, get_all_settings

REPO = "nvidia/Nemotron-3-Diarization"
# A fixed commit, as the PC measurement used (52a43267): a changed repository reaches no one until this changes
REVISION = "52a432672732425e4c19765b9fec9b5810e6f4ba"
# What transformers needs (378 MB) and the model card with its notices; not the .nemo and .gguf
# copies of the same model (290 MB) nor the demo videos
FILES = ["config.json", "processor_config.json", "model.safetensors", "README.md"]
LICENSE_TEXT = Path(__file__).resolve().parent.parent / "licenses" / "OpenMDW-1.1.txt"
LICENSE = "OpenMDW-1.1"
MAX_SPEAKERS = 8
COMPLETE_MARK = ".complete"

Turn = Tuple[float, float, int]  # start, end (seconds), speaker number

_state: Dict[str, Any] = {"installing": False, "error": ""}
_lock = threading.Lock()
_model: Dict[str, Any] = {"processor": None, "model": None, "device": None}


def model_dir() -> Path:
    return MODELS_DIR / "nemotron-3-diarization"


def library_ready() -> bool:
    """transformers with the model's class (5.23 measured; Python 3.11 needed)."""
    import importlib.util

    try:
        return importlib.util.find_spec("transformers.models.nemotron3_diarization") is not None
    except (ImportError, ValueError):
        return False


def installed() -> bool:
    d = model_dir()
    return (d / COMPLETE_MARK).exists() and (d / "config.json").exists()


def chosen(settings: Optional[Dict[str, str]] = None) -> bool:
    s = settings if settings is not None else get_all_settings()
    return (s.get("diarizer_engine") or "ecapa") == "nemotron"


def usable(settings: Optional[Dict[str, str]] = None) -> bool:
    return chosen(settings) and installed() and library_ready()


def status() -> Dict[str, Any]:
    from app.model_manager import dir_size_mb

    with _lock:
        st = dict(_state)
    ready = installed()
    return {**st, "installed": ready, "library": library_ready(), "chosen": chosen(),
            "disk_mb": dir_size_mb(model_dir()) if ready else 0, "license": LICENSE}


def install_async() -> Dict[str, Any]:
    with _lock:
        if _state["installing"]:
            return status()
        _state.update(installing=True, error="")

    def work() -> None:
        try:
            if not library_ready():
                raise RuntimeError("Для Nemotron нужна библиотека transformers: обновите программу до последней версии")
            from huggingface_hub import snapshot_download

            d = model_dir()
            d.mkdir(parents=True, exist_ok=True)
            print(f"[nemotron] downloading {REPO}@{REVISION}", flush=True)
            snapshot_download(REPO, revision=REVISION, local_dir=str(d), allow_patterns=FILES)
            if LICENSE_TEXT.exists():  # the repository has no license file: its text kept with the model
                shutil.copyfile(LICENSE_TEXT, d / "LICENSE-OpenMDW-1.1.txt")
            (d / COMPLETE_MARK).write_text(f"{REPO}@{REVISION}", encoding="utf-8")
        except Exception as e:
            print(f"[nemotron] not downloaded: {e}", flush=True)
            with _lock:
                _state["error"] = str(e)[:300]
        finally:
            with _lock:
                _state["installing"] = False

    threading.Thread(target=work, daemon=True, name="nemotron-install").start()
    return status()


def remove() -> None:
    unload()
    shutil.rmtree(model_dir(), ignore_errors=True)


def unload() -> None:
    with _lock:
        was = _model["model"] is not None
        _model.update(processor=None, model=None, device=None)
    if was:
        try:
            from app.hardware import clear_vram

            clear_vram()
        except Exception:
            pass


def _load(device: str):
    with _lock:
        if _model["model"] is not None and _model["device"] == device:
            return _model["processor"], _model["model"]
    from transformers import AutoModelForAudioFrameClassification, AutoProcessor

    path = str(model_dir())
    processor = AutoProcessor.from_pretrained(path)
    model = AutoModelForAudioFrameClassification.from_pretrained(path).to(device).eval()
    with _lock:
        _model.update(processor=processor, model=model, device=device)
    return processor, model


def _run(audio, device: str) -> List[Turn]:
    import torch

    processor, model = _load(device)
    sr = processor.feature_extractor.sampling_rate
    inputs = processor(audio, sampling_rate=sr).to(model.device, dtype=model.dtype)
    with torch.inference_mode():
        logits = model(**inputs).logits
    found = processor.extract_speaker_dict(logits, inputs.attention_mask)[0]
    return [(float(t["Start"]), float(t["End"]), int(t["Speaker"])) for t in found if float(t["End"]) > float(t["Start"])]


def turns(wav_path: str | Path, device: str = "cuda") -> List[Turn]:
    """Who speaks when in a 16 kHz mono WAV: the whole recording in one pass (the model goes through it
    in parts with a cache of the voices, so memory does not grow with its length). The video card first,
    the processor when it is not there or runs out of memory."""
    import numpy as np
    import soundfile as sf

    audio, sr = sf.read(str(wav_path), dtype="float32")
    if audio.ndim > 1:
        audio = np.mean(audio, axis=1)
    if sr != 16000:
        raise RuntimeError(f"Nemotron ждёт звук 16 кГц, а в файле {sr} Гц")
    use_cuda = device == "cuda"
    if use_cuda:
        try:
            import torch

            use_cuda = torch.cuda.is_available()
        except Exception:
            use_cuda = False
    try:
        if use_cuda:
            try:
                return _run(audio, "cuda")
            except Exception as e:  # out of memory, a failing card: the processor does it
                if type(e).__name__ == "JobCancelled":
                    raise
                print(f"[nemotron] the video card failed ({str(e).splitlines()[0][:160]}): on the processor", flush=True)
                unload()
        return _run(audio, "cpu")
    finally:
        unload()
