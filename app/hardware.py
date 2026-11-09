import os
import sys
import gc
from pathlib import Path
from typing import Dict, Any

# Suppress symlink warnings and force UTF-8 output on Windows
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ["PYTHONUTF8"] = "1"
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def register_cuda_dlls() -> None:
    """
    Automatically locates and registers NVIDIA cuBLAS and cuDNN DLLs installed inside
    the Python virtual environment so CTranslate2 (faster-whisper) and PyTorch (SpeechBrain)
    coexist on Windows without DLL symbol conflicts (such as cudnnGetLibConfig Error 127).
    """
    if sys.platform != "win32":
        return

    import ctypes

    site_packages_candidates = [
        Path(sys.prefix) / "Lib" / "site-packages" / "nvidia",
        Path(__file__).resolve().parent.parent / ".venv" / "Lib" / "site-packages" / "nvidia",
    ]

    dll_dirs = []
    # Prioritize torch/lib first so its newer cuDNN 9 DLLs take precedence over older shims
    for base in site_packages_candidates:
        torch_lib = base.parent / "torch" / "lib"
        if torch_lib.exists():
            dll_dirs.append(str(torch_lib.resolve()))
            for cudnn_dll in (
                "cudnn64_9.dll",
                "cudnn_graph64_9.dll",
                "cudnn_ops64_9.dll",
                "cudnn_cnn64_9.dll",
            ):
                dll_file = torch_lib / cudnn_dll
                if dll_file.exists():
                    try:
                        ctypes.WinDLL(str(dll_file))
                    except Exception:
                        pass

    for base in site_packages_candidates:
        if base.exists():
            for bin_dir in base.glob("*/bin"):
                if bin_dir.is_dir():
                    dll_dirs.append(str(bin_dir.resolve()))

    current_path = os.environ.get("PATH", "")
    for d in reversed(dll_dirs):
        if d not in current_path:
            os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
        if hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(d)
            except Exception:
                pass


# Register DLL directories immediately on import
register_cuda_dlls()


_gpu_cache: Dict[str, Any] = {"at": 0.0, "value": None}


def _gpu_probe():
    """(name, total GB, free GB) of GPU 0, or None. The NVIDIA driver (NVML) is asked first: it
    needs no torch, which would slow the start and keep a CUDA context with VRAM in this process.
    Cached for a few seconds (the page asks often)."""
    import time

    if time.time() - _gpu_cache["at"] < 5.0:
        return _gpu_cache["value"]
    value = None
    try:
        from app.vram import nvml_device

        dev = nvml_device()
        if dev:
            name, used, total = dev
            value = (name, round(total / 2**30, 1), round((total - used) / 2**30, 1))
    except Exception:
        value = None
    if value is None:
        try:
            import torch

            if torch.cuda.is_available():
                props = torch.cuda.get_device_properties(0)
                total = props.total_memory
                try:
                    free, _ = torch.cuda.mem_get_info(0)
                except Exception:
                    free = total
                value = (props.name, round(total / 2**30, 1), round(free / 2**30, 1))
        except Exception:
            value = None
    _gpu_cache.update(at=time.time(), value=value)
    return value


_torch_cuda: Dict[str, Any] = {"checked": False, "ok": False, "why": ""}


def _arch_supported(cap: tuple, arch_list: list) -> bool:
    """Whether the kernels of this PyTorch build run on a card of compute capability `cap`: a binary
    for the same major version and a minor one not newer, or PTX of a version not newer (compiled for
    the card when loaded)."""
    major, minor = cap
    for a in arch_list:
        kind, _, num = a.partition("_")
        if not num.isdigit() or len(num) < 2:
            continue
        a_major, a_minor = int(num[:-1]), int(num[-1])
        if kind == "sm" and a_major == major and a_minor <= minor:
            return True
        if kind == "compute" and (a_major, a_minor) <= (major, minor):
            return True
    return False


def torch_cuda_works() -> bool:
    """PyTorch can run on this video card: CUDA is there, the build has kernels for the card's
    architecture (a card newer than the build, an RTX 50 for a CUDA 12.6 build, or one older than it
    supports fails with "no kernel image is available"), and a small operation runs. Checked once;
    else the parts on PyTorch (the speaker model) run on the processor."""
    if _torch_cuda["checked"]:
        return _torch_cuda["ok"]
    ok, why = False, ""
    try:
        import torch

        if torch.cuda.is_available():
            cap = torch.cuda.get_device_capability(0)
            arch = list(torch.cuda.get_arch_list() or [])
            if arch and not _arch_supported(cap, arch):
                why = f"sm_{cap[0]}{cap[1]} not in {' '.join(arch)}"
            else:
                x = torch.nn.functional.pad(torch.ones(1, 1, 4, device="cuda:0"), [1, 1], mode="reflect")
                torch.cuda.synchronize()
                ok = float(x.sum()) > 0
    except Exception as e:  # torch.AcceleratorError: no kernel image, a broken driver...
        why = str(e).splitlines()[0][:200]
    if why:
        print(f"[hardware] PyTorch cannot use the video card ({why}): its models run on the processor", flush=True)
    _torch_cuda.update(checked=True, ok=ok, why=why)
    return ok


def torch_cuda_problem() -> str:
    """Why PyTorch cannot use the video card ('' when it can or was not checked)."""
    return _torch_cuda["why"]


def get_hardware_info() -> Dict[str, Any]:
    """
    Detects available GPU/CPU resources and recommends optimal Whisper model and compute_type
    for any user's hardware (NVIDIA high-VRAM, NVIDIA low-VRAM, or AMD/Intel/CPU fallback).
    """
    info: Dict[str, Any] = {
        "cuda_available": False,
        "device_name": "Процессор (CPU)",
        "vram_total_gb": 0.0,
        "vram_free_gb": 0.0,
        "recommended_device": "cpu",
        "recommended_compute_type": "int8",
        "recommended_whisper_model": "large-v3-turbo",
        "recommended_ollama_model": "qwen3.5:4b",
        "tier": "cpu",
        "tier_description": "Работа на процессоре: быстрее всего GigaAM v3 (русский) и Parakeet; Whisper Turbo — в режиме int8",
    }

    try:
        gpu = _gpu_probe()
        if gpu:
            name, total_gb, free_gb = gpu
            info["cuda_available"] = True
            info["device_name"] = name
            info["vram_total_gb"] = total_gb
            info["vram_free_gb"] = free_gb
            info["recommended_device"] = "cuda"

            if total_gb >= 10.0:
                info["tier"] = "high_vram"
                info["recommended_compute_type"] = "float16"
                info["recommended_whisper_model"] = "large-v3"
                info["recommended_ollama_model"] = "qwen3:8b"
                info["tier_description"] = (
                    f"Максимальная производительность ({name}, {total_gb} ГБ VRAM). "
                    "Доступны самые точные модели large-v3 и large-v3-turbo в режиме float16."
                )
            elif total_gb >= 5.5:
                info["tier"] = "mid_vram"
                info["recommended_compute_type"] = "int8_float16"
                info["recommended_whisper_model"] = "large-v3-turbo"
                info["recommended_ollama_model"] = "qwen3.5:4b"
                info["tier_description"] = (
                    f"Средний объём видеопамяти ({name}, {total_gb} ГБ VRAM). "
                    "Рекомендуется модель large-v3-turbo в гибридном режиме int8_float16."
                )
            else:
                info["tier"] = "low_vram"
                info["recommended_compute_type"] = "int8"
                info["recommended_whisper_model"] = "large-v3-turbo"
                info["recommended_ollama_model"] = "qwen3.5:4b"
                info["tier_description"] = (
                    f"Компактный режим видеопамяти ({name}, {total_gb} ГБ VRAM). "
                    "Модели загружаются по очереди в сжатом формате int8."
                )
    except Exception as e:
        info["error"] = str(e)

    return info


def clear_vram() -> None:
    """
    Explicitly releases GPU memory between pipeline stages (e.g. after Whisper and before
    Diarization or Ollama LLM summary) so even 4-6 GB GPUs never run out of memory.
    """
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
    except Exception:
        pass
