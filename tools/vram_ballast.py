"""
Holds video memory so that a big card behaves like a smaller one (bench of LLMs for weak cards).

    python tools/vram_ballast.py --card 10            # leaves what a 10 GB card has free (9.5 GB)
    python tools/vram_ballast.py --card 10 --asr      # the same plus GigaAM on CUDA, as during a recording
    python tools/vram_ballast.py --hold 12.5          # holds exactly this much

The free memory is read the way Ollama reads it (NVML, as nvidia-smi shows it), and the ballast grows
until that is the size of the card minus what the desktop takes on a real one (0.5 GB). Whatever other
programs already hold on this card is counted, so the result does not depend on them. With --asr the
speech model is loaded from VERBALIOX_MODELS_DIR the way the app loads it (app/asr_onnx.py), inside the
emulated card. The memory is held until the process is closed (Ctrl+C or killed).
"""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

RESERVE_GB = 0.5  # the desktop and the driver take some memory on a real card as well
STEP_GB = 0.125


def nvml_free_gb() -> float:
    out = subprocess.run(["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
                         capture_output=True, text=True, timeout=20).stdout
    return int(out.split()[0]) / 1024


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--card", type=float, help="emulate a card with this many GB")
    ap.add_argument("--hold", type=float, help="hold exactly this many GB")
    ap.add_argument("--asr", action="store_true", help="also load GigaAM v3 on CUDA, as during a recording")
    args = ap.parse_args()
    if (args.card is None) == (args.hold is None):
        ap.error("give --card or --hold")

    import torch

    if not torch.cuda.is_available():
        print("no CUDA device", file=sys.stderr)
        return 1
    asr_gb = 0.0
    if args.asr:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from app import asr_onnx

        before = nvml_free_gb()
        asr_onnx._load("gigaam-v3", True)
        time.sleep(1.0)
        asr_gb = max(0.0, before - nvml_free_gb())  # it is on the emulated card, not on top of it
    torch.zeros(1, device="cuda")  # the CUDA context first: it takes memory of its own
    torch.cuda.synchronize()

    def block():
        # Written, not just allocated: under Windows (WDDM) an untouched allocation is not resident, and
        # NVML (what Ollama and nvidia-smi read) still reports that memory as free
        return torch.ones(int(STEP_GB * 2**30), dtype=torch.uint8, device="cuda")

    blocks = []
    if args.hold is not None:
        while len(blocks) * STEP_GB + 1e-9 < args.hold:
            blocks.append(block())
    else:
        target = args.card - RESERVE_GB - asr_gb
        # Big steps first, then step by step while NVML catches up
        first = max(0.0, nvml_free_gb() - target - 0.5)
        while len(blocks) * STEP_GB + 1e-9 < first:
            blocks.append(block())
        torch.cuda.synchronize()
        time.sleep(1.0)
        while nvml_free_gb() > target + STEP_GB / 2:
            blocks.append(block())
            torch.cuda.synchronize()
            time.sleep(0.3)
    torch.cuda.synchronize()
    time.sleep(1.0)
    print(f"ballast {len(blocks) * STEP_GB:.2f} GB held, asr={f'{asr_gb:.2f} GB' if args.asr else 'off'}, "
          f"NVML free now {nvml_free_gb():.2f} GB (pid {os.getpid()})", flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
