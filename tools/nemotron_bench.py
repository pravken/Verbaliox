# Bench tool of 2026-11-14 (bench-report/llm-profiles.md, embeddings.md, diarization.md). Paths point to the
# benchmark workspace C:s-llm (data copy, separate Ollama, downloads); adjust them to rerun.
"""Nemotron 3 Diarization (OpenMDW-1.1) on the AMI test meetings, through transformers on the GPU.
Offline mode first; if the whole meeting does not fit, streaming mode ("low_latency") chunk by chunk.
Appends hypothesis segments to results/diar-hyp.jsonl (encoder "nemotron3", mode "model")."""
import json, sys, time, threading, subprocess
import torch
from transformers import AutoModelForAudioFrameClassification, AutoProcessor
from transformers.audio_utils import load_audio

MID = "nvidia/Nemotron-3-Diarization"
REV = "52a4326727"


def gpu_used():
    return int(subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                              capture_output=True, text=True).stdout.split()[0])


class Peak(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True); self.peak = 0; self.go = True
    def run(self):
        while self.go:
            try: self.peak = max(self.peak, gpu_used())
            except Exception: pass
            time.sleep(0.3)


def main():
    proc = AutoProcessor.from_pretrained(MID, revision=REV)
    model = AutoModelForAudioFrameClassification.from_pretrained(MID, revision=REV, device_map="cuda")
    sr = proc.feature_extractor.sampling_rate
    out = open(r"C:\vs-llm\results\diar-hyp.jsonl", "a", encoding="utf-8")
    for ami in sys.argv[1:]:
        audio = load_audio(rf"C:\vs-llm\ami\{ami}.wav", sampling_rate=sr)
        for attempt in (1, 2):
            torch.cuda.empty_cache(); base = gpu_used(); pk = Peak(); pk.start(); t0 = time.time()
            mode = "offline"
            try:
                inputs = proc(audio, sampling_rate=sr).to(model.device, dtype=model.dtype)
                with torch.inference_mode():
                    logits = model(**inputs).logits
                segs = proc.extract_speaker_dict(logits, inputs.attention_mask)[0]
            except torch.cuda.OutOfMemoryError:
                torch.cuda.empty_cache(); mode = "streaming"
                raise
            sec = time.time() - t0; pk.go = False; pk.join()
        rec = {"ami": ami, "encoder": "nemotron3", "mode": mode, "sec": round(sec, 1), "gpu_extra_mb": max(0, pk.peak - base),
               "speakers": len({s["Speaker"] for s in segs}),
               "segments": [[round(float(s["Start"]), 2), round(float(s["End"]), 2), f"S{s['Speaker']}"] for s in segs]}
        out.write(json.dumps(rec) + "\n"); out.flush()
        print(ami, mode, rec["sec"], "s", rec["speakers"], "speakers", rec["gpu_extra_mb"], "MB", flush=True)


if __name__ == "__main__":
    main()
