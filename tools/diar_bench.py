# Bench tool of 2026-11-14 (bench-report/llm-profiles.md, embeddings.md, diarization.md). Paths point to the
# benchmark workspace C:s-llm (data copy, separate Ollama, downloads); adjust them to rerun.
"""Speaker splitting on AMI test meetings inside the app's own pipeline: the transcript lines of the data copy
(resplit_input) go through app.diarizer.diarize_and_merge_segments with the voice encoder swapped:
ECAPA (current), WeSpeaker ResNet34-LM / ResNet293-LM and CAM++-LM (official ONNX, CC-BY-4.0 / Apache-2.0).
Writes hypothesis segments per (meeting, encoder, mode) to results/diar-hyp.jsonl.

usage: python diar_bench.py <AMI_ID>=<meeting_id> ...   (run with the clone's .venv, VERBALIOX_DATA_DIR set)
"""
import json, os, subprocess, sys, threading, time
from pathlib import Path

sys.path.insert(0, r"D:\src\VerbaScribe-pc")
import numpy as np, torch, torchaudio
import onnxruntime as ort
from huggingface_hub import hf_hub_download

from app import diarizer
from app.audio_utils import extract_audio_16k_mono
from app.database import get_meeting
from app.transcriber import resplit_input

ONNX = {
    "wespeaker-resnet34-LM": ("Wespeaker/wespeaker-voxceleb-resnet34-LM", "voxceleb_resnet34_LM.onnx", "f0c48c298f"),
    "wespeaker-resnet293-LM": ("Wespeaker/wespeaker-voxceleb-resnet293-LM", "voxceleb_resnet293_LM.onnx", "6e6bffe5bf"),
    "campplus-LM": ("Wespeaker/wespeaker-voxceleb-campplus-LM", "voxceleb_CAM++_LM.onnx", "c5e01c6fcf"),
}


class OnnxEncoder:
    """The ECAPA encoder's encode_batch interface over a WeSpeaker ONNX model: 80-dim Kaldi fbank of the
    int16-scaled waveform, mean-normalised per slice, one slice at a time (no padding)."""

    def __init__(self, repo, fname):
        path = hf_hub_download(repo, fname)
        prov = ["CUDAExecutionProvider", "CPUExecutionProvider"] if "CUDAExecutionProvider" in ort.get_available_providers() else ["CPUExecutionProvider"]
        self.s = ort.InferenceSession(path, providers=prov)
        self.inp = self.s.get_inputs()[0].name
        self.provider = self.s.get_providers()[0]

    def encode_batch(self, wavs, wav_lens):
        out = []
        for row in range(wavs.shape[0]):
            n = int(round(float(wav_lens[row]) * wavs.shape[1]))
            w = wavs[row, :n].unsqueeze(0) * 32768.0
            f = torchaudio.compliance.kaldi.fbank(w, num_mel_bins=80, frame_length=25, frame_shift=10, dither=0.0,
                                                  sample_frequency=16000, window_type="hamming")
            f = f - f.mean(dim=0, keepdim=True)
            e = self.s.run(None, {self.inp: f.unsqueeze(0).numpy().astype(np.float32)})[0]
            out.append(torch.from_numpy(np.asarray(e, dtype=np.float32).reshape(1, -1)))
        return torch.stack(out)  # (B, 1, D)


class GpuPeak(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True); self.peak = 0; self.go = True
    def run(self):
        while self.go:
            try:
                v = int(subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                                       capture_output=True, text=True, timeout=5).stdout.split()[0])
                self.peak = max(self.peak, v)
            except Exception:
                pass
            time.sleep(0.3)


def main():
    pairs = [a.split("=") for a in sys.argv[1:]]
    out = open(r"C:\vs-llm\results\diar-hyp.jsonl", "a", encoding="utf-8")
    encoders = {"ecapa": None, **ONNX}
    for ami, mid in pairs:
        m = get_meeting(int(mid))
        raw = resplit_input(m["segments"])
        wav = Path(rf"C:\vs-llm\ami\{ami}.16k.wav")
        if not wav.exists():
            p = m.get("processing") or {}
            extract_audio_16k_mono(rf"C:\vs-llm\ami\{ami}.wav", wav, denoise=p.get("denoise", True), loudnorm=p.get("loudnorm", True))
        for name, spec in encoders.items():
            if spec is None:
                diarizer._get_ecapa_encoder = ORIG_GET
                diarizer.unload_diarizer()
            else:
                enc = OnnxEncoder(spec[0], spec[1])
                diarizer._get_ecapa_encoder = lambda device="cpu", enc=enc: enc
            for mode, hint in (("auto", 0), ("oracle", 4)):
                for attempt in (1, 2):  # the second pass is reported: the first warms caches
                    torch.cuda.empty_cache()
                    base = int(subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                                              capture_output=True, text=True).stdout.split()[0])
                    pk = GpuPeak(); pk.start()
                    t0 = time.time()
                    speakers, segs = diarizer.diarize_and_merge_segments(wav, raw, device="cuda", num_speakers_hint=hint)
                    sec = time.time() - t0
                    pk.go = False; pk.join()
                rec = {"ami": ami, "meeting": int(mid), "encoder": name, "mode": mode, "sec": round(sec, 1),
                       "gpu_extra_mb": max(0, pk.peak - base), "speakers": len(speakers),
                       "segments": [[round(s["start"], 2), round(s["end"], 2), s["speaker"]] for s in segs]}
                out.write(json.dumps(rec) + "\n"); out.flush()
                print(ami, name, mode, rec["sec"], "s", rec["speakers"], "speakers", rec["gpu_extra_mb"], "MB", flush=True)
            diarizer.unload_diarizer()


ORIG_GET = diarizer._get_ecapa_encoder
if __name__ == "__main__":
    main()
