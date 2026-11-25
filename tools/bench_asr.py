"""
Bench of speech recognition models for live captions and for the transcription of recordings: accuracy (WER, CER),
speed (RTFx), caption latency, processor load and, above all, how responsive the computer stays while captions run
next to a transcription and a video call (bench-report/asr-2026-11.md; the task: docs/pc-session-asr-bench.md).

    <venv>\\Scripts\\python tools\\bench_asr.py prepare --root D:\\bench-asr                  # data and models
    <venv>\\Scripts\\python tools\\bench_asr.py offline --root D:\\bench-asr --models parakeet-int8 gigaam-ctc-int8
    <venv>\\Scripts\\python tools\\bench_asr.py live --root D:\\bench-asr --model nemotron-560 --scheme stream --lang ru
    <venv>\\Scripts\\python tools\\bench_asr.py call --root D:\\bench-asr --model parakeet-int8 --scheme vad --lang ru \\
        --queue parakeet-int8 --threads 4 --spin off --prio below
    <venv>\\Scripts\\python tools\\bench_asr.py report --root D:\\bench-asr --out bench-report\\asr-2026-11

Every model runs in a process of its own (the "worker" subcommand), so its memory and threads are measured alone;
this process only starts the workers, samples their processor and memory use (psutil) and writes the results to
--root\\results\\*.json.

Modes:
  * offline: every FLEURS phrase recognized whole. WER / CER (jiwer; one normalization for every model: lower case,
    no punctuation, ё -> е, numbers as they are), RTFx, load time, peak memory.
  * live: a ~10 min file of FLEURS phrases joined with pauses of 0.3-1.5 s is fed in real time, as from a microphone.
    Schemes: "window" - the app's own code (app.live.LiveSession: every page post of ~1 s of audio, the window of up
    to 20 s is recognized again; run with the app's Python, see --app-python); "vad" - only the current phrase (from
    the speech start by the Silero VAD) is recognized, at most every --draft-sec, and once more when a pause of
    >= 500 ms ends it; "stream" - a streaming model (sherpa-onnx: Nemotron 3.5, T-one) gets every piece of audio once.
    WER of the final text, latency "phrase end in the audio -> final text" (median, p90), latency of the first draft,
    processor load of the process and of the system, peak memory.
  * call: live, and at the same time a transcription of a 10 min file in a second process (--queue), a video call's
    load (ffmpeg encodes 1080p30 x264 veryfast in real time) and a probe process of normal priority that sleeps for
    10 ms in a loop and records how late it wakes up: p99, maximum and the number of stalls over 50 and 200 ms. That
    is the direct measure of a stuttering mouse. --cpus N keeps every process of the run on the first N logical
    processors (a smaller computer on this one).

Switches (live and call): --threads (number, or "app" for app.asr_onnx.cpu_threads() - half of the logical
processors, 2 to 8), --spin on/off (ONNX Runtime threads waiting actively or not: session.intra_op.allow_spinning and
inter_op; for sherpa-onnx through provider="cpu:<config file>"), --prio normal/below/idle, and the model's
quantization by its name (parakeet-fp32 / parakeet-int8 ...).

Data: FLEURS (google/fleurs, CC-BY-4.0), test split, 100 phrases each of ru_ru, en_us, de_de, picked with a fixed
seed. Downloads, extracted audio and models go to --root (nothing goes into the repository). Nothing of the user's
data is read: the app's code (scheme "window") runs with its data and models folders in --root.
"""

import argparse
import json
import os
import random
import re
import statistics
import subprocess
import sys
import tarfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
SR = 16000
SEED = 2026
LANGS = {"ru": "ru_ru", "en": "en_us", "de": "de_de"}
LONG_SEC = 600.0
SHERPA_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/{}.tar.bz2"

# Models: key -> how to get and load it. "rev": the commit the files come from (checked licence: "license")
MODELS: Dict[str, Dict[str, Any]] = {
    "parakeet-fp32": {"kind": "onnx", "name": "nemo-parakeet-tdt-0.6b-v3", "repo": "istupakov/parakeet-tdt-0.6b-v3-onnx",
                      "rev": "8f23f0c03c8761650bdb5b40aaf3e40d2c15f1ce", "quant": None, "license": "CC-BY-4.0",
                      "langs": ["ru", "en", "de"]},
    "parakeet-int8": {"kind": "onnx", "name": "nemo-parakeet-tdt-0.6b-v3", "repo": "istupakov/parakeet-tdt-0.6b-v3-onnx",
                      "rev": "8f23f0c03c8761650bdb5b40aaf3e40d2c15f1ce", "quant": "int8", "license": "CC-BY-4.0",
                      "langs": ["ru", "en", "de"]},
    "ultra-int8": {"kind": "onnx", "name": "nemo-parakeet-tdt-0.6b-v3", "repo": "Masterx/parakeet-tdt-0.6b-ultra-onnx",
                   "rev": "99b09f030a", "quant": "int8", "license": "CC-BY-4.0", "langs": ["ru", "en", "de"]},
    "ultra-fp32": {"kind": "onnx", "name": "nemo-parakeet-tdt-0.6b-v3", "repo": "Masterx/parakeet-tdt-0.6b-ultra-onnx",
                   "rev": "99b09f030a", "quant": None, "license": "CC-BY-4.0", "langs": ["ru", "en", "de"]},
    "ultra-fp16": {"kind": "onnx", "name": "nemo-parakeet-tdt-0.6b-v3", "repo": "Masterx/parakeet-tdt-0.6b-ultra-onnx",
                   "rev": "99b09f030a", "quant": "fp16", "license": "CC-BY-4.0", "langs": ["ru", "en", "de"]},
    "gigaam-ctc-int8": {"kind": "onnx", "name": "gigaam-v3-e2e-ctc", "repo": "istupakov/gigaam-v3-onnx",
                        "rev": "322c3b29492673eb7d0b434bfa9dfb8653e34d02", "quant": "int8", "license": "MIT",
                        "langs": ["ru"]},
    "gigaam-rnnt": {"kind": "onnx", "name": "gigaam-v3-e2e-rnnt", "repo": "istupakov/gigaam-v3-onnx",
                    "rev": "322c3b29492673eb7d0b434bfa9dfb8653e34d02", "quant": None, "license": "MIT", "langs": ["ru"]},
    "gigaam-rnnt-int8": {"kind": "onnx", "name": "gigaam-v3-e2e-rnnt", "repo": "istupakov/gigaam-v3-onnx",
                         "rev": "322c3b29492673eb7d0b434bfa9dfb8653e34d02", "quant": "int8", "license": "MIT",
                         "langs": ["ru"]},
    "canary-int8": {"kind": "onnx", "name": "nemo-canary-1b-v2", "repo": "istupakov/canary-1b-v2-onnx",
                    "rev": "5ebc1520ce", "quant": "int8", "license": "CC-BY-4.0", "langs": ["ru", "en", "de"]},
    "nemotron-160": {"kind": "sherpa-nemotron", "archive": "sherpa-onnx-nemotron-3.5-asr-streaming-0.6b-160ms-int8-2026-06-11",
                     "license": "OpenMDW-1.1", "langs": ["ru", "en", "de"]},
    "nemotron-560": {"kind": "sherpa-nemotron", "archive": "sherpa-onnx-nemotron-3.5-asr-streaming-0.6b-560ms-int8-2026-06-11",
                     "license": "OpenMDW-1.1", "langs": ["ru", "en", "de"]},
    "nemotron-1120": {"kind": "sherpa-nemotron", "archive": "sherpa-onnx-nemotron-3.5-asr-streaming-0.6b-1120ms-int8-2026-06-11",
                      "license": "OpenMDW-1.1", "langs": ["ru", "en", "de"]},
    "tone": {"kind": "sherpa-tone", "archive": "sherpa-onnx-streaming-t-one-russian-2025-09-08", "license": "Apache-2.0",
             "langs": ["ru"]},
    "whisper-turbo": {"kind": "whisper", "name": "large-v3-turbo", "license": "MIT", "langs": ["ru", "en", "de"]},
    "qwen3-1.7b": {"kind": "qwen", "name": "Qwen/Qwen3-ASR-1.7B", "license": "Apache-2.0", "langs": ["ru", "en", "de"]},
    "qwen3-0.6b": {"kind": "qwen", "name": "Qwen/Qwen3-ASR-0.6B", "license": "Apache-2.0", "langs": ["ru", "en", "de"]},
}
VAD_REPO = ("istupakov/silero-vad-onnx", "b3e3ee3cce4c11ceb63b1a0b229d916069c1ddf6")
NEMOTRON_LANG = {"ru": "ru-RU", "en": "en-US", "de": "de-DE"}
QWEN_LANG = {"ru": "Russian", "en": "English", "de": "German"}


def say(msg: str) -> None:
    print(msg, flush=True)


def paths(root: Path) -> Dict[str, Path]:
    return {"cache": root / "cache", "data": root / "data", "models": root / "models", "results": root / "results",
            "tmp": root / "tmp"}


# ---------------------------------------------------------------- text

_PUNCT = re.compile(r"[^\w\s]|_", re.UNICODE)


def normalize(text: str) -> str:
    t = text.lower().replace("ё", "е")
    t = _PUNCT.sub(" ", t)
    return " ".join(t.split())


def wer_cer(refs: List[str], hyps: List[str]) -> Tuple[float, float]:
    import jiwer

    pairs = [(normalize(r), normalize(h)) for r, h in zip(refs, hyps)]
    pairs = [(r, h) for r, h in pairs if r]
    r = [p[0] for p in pairs]
    h = [p[1] for p in pairs]
    return 100 * jiwer.wer(r, h), 100 * jiwer.cer(r, h)


# ---------------------------------------------------------------- data

def _fleurs_rows(cache: Path, lang: str) -> List[List[str]]:
    from huggingface_hub import hf_hub_download

    code = LANGS[lang]
    tsv = hf_hub_download("google/fleurs", f"data/{code}/test.tsv", repo_type="dataset", local_dir=cache / "fleurs")
    return [line.split("\t") for line in Path(tsv).read_text(encoding="utf-8").splitlines() if line.strip()]


def prepare_data(root: Path, n: int) -> None:
    """FLEURS test: n phrases per language (distinct sentences, fixed seed) and a ~10 min file of other phrases."""
    import numpy as np
    import soundfile as sf
    from huggingface_hub import hf_hub_download

    p = paths(root)
    for lang, code in LANGS.items():
        out = p["data"] / "fleurs" / lang
        if (out / "long.json").exists():
            continue
        out.mkdir(parents=True, exist_ok=True)
        rows = _fleurs_rows(p["cache"], lang)
        say(f"FLEURS {code}: {len(rows)} rows, downloading the audio ...")
        tar_path = hf_hub_download("google/fleurs", f"data/{code}/audio/test.tar.gz", repo_type="dataset",
                                   local_dir=p["cache"] / "fleurs")
        by_sentence: Dict[str, List[List[str]]] = {}
        for r in rows:
            by_sentence.setdefault(r[0], []).append(r)
        ids = sorted(by_sentence)
        rnd = random.Random(SEED)
        rnd.shuffle(ids)
        picked = [rnd.choice(by_sentence[i]) for i in ids[:n]]
        pool = [rnd.choice(by_sentence[i]) for i in ids[n:]]
        want = {r[1] for r in picked} | {r[1] for r in pool}
        audio: Dict[str, Any] = {}
        with tarfile.open(tar_path, "r:gz") as tf:
            for m in tf:
                name = m.name.rsplit("/", 1)[-1]
                if m.isfile() and name in want:
                    import io

                    data, sr = sf.read(io.BytesIO(tf.extractfile(m).read()), dtype="float32")
                    assert sr == SR, sr
                    audio[name] = data
        phrases = []
        for r in picked:
            sf.write(out / r[1], audio[r[1]], SR)
            phrases.append({"file": r[1], "text": r[2], "sec": round(len(audio[r[1]]) / SR, 2)})
        (out / "phrases.json").write_text(json.dumps(phrases, ensure_ascii=False, indent=1), encoding="utf-8")
        # the "meeting": phrases with pauses of 0.3-1.5 s, ~LONG_SEC long
        parts, segs, t = [np.zeros(int(0.5 * SR), dtype=np.float32)], [], 0.5
        for r in pool:
            if t >= LONG_SEC:
                break
            a = audio.get(r[1])
            if a is None:
                continue
            segs.append({"start": round(t, 3), "end": round(t + len(a) / SR, 3), "text": r[2]})
            parts.append(a)
            t += len(a) / SR
            gap = rnd.uniform(0.3, 1.5)
            parts.append(np.zeros(int(gap * SR), dtype=np.float32))
            t += gap
        sf.write(out / "long.wav", np.concatenate(parts), SR)
        (out / "long.json").write_text(json.dumps(segs, ensure_ascii=False, indent=1), encoding="utf-8")
        say(f"  {len(phrases)} phrases, long.wav {t / 60:.1f} min of {len(segs)} phrases")


def model_dir(root: Path, key: str) -> Path:
    m = MODELS[key]
    if m["kind"] == "onnx":
        return paths(root)["models"] / "hf" / m["repo"].replace("/", "--")
    if m["kind"].startswith("sherpa"):
        return paths(root)["models"] / "sherpa" / m["archive"]
    return paths(root)["models"] / key


def vad_path(root: Path) -> Path:
    return paths(root)["models"] / "hf" / VAD_REPO[0].replace("/", "--")


def fetch_model(root: Path, key: str) -> None:
    m = MODELS[key]
    d = model_dir(root, key)
    if m["kind"] == "onnx":
        from huggingface_hub import snapshot_download

        q = m["quant"]
        pats = ["config.json", "*.txt", "*.yaml"]
        if q is None:
            pats += ["*-model.onnx", "*-model.onnx.data", "*_encoder.onnx", "*_decoder.onnx", "*_joint.onnx",
                     "v3_e2e_ctc.onnx", "nemo128.onnx"]
        else:
            pats += [f"*.{q}.onnx", "nemo128.onnx"]
        say(f"{key}: {m['repo']} -> {d}")
        snapshot_download(m["repo"], revision=m["rev"], local_dir=d, allow_patterns=pats)
    elif m["kind"].startswith("sherpa"):
        if d.is_dir() and any(d.glob("*.onnx")):
            return
        import urllib.request

        arc = paths(root)["cache"] / (m["archive"] + ".tar.bz2")
        arc.parent.mkdir(parents=True, exist_ok=True)
        if not arc.exists():
            say(f"{key}: downloading {m['archive']} ...")
            urllib.request.urlretrieve(SHERPA_URL.format(m["archive"]), str(arc) + ".part")
            os.replace(str(arc) + ".part", arc)
        with tarfile.open(arc, "r:bz2") as tf:
            tf.extractall(d.parent, filter="data")
    elif m["kind"] == "whisper":
        from huggingface_hub import snapshot_download

        snapshot_download("mobiuslabsgmbh/faster-whisper-large-v3-turbo", local_dir=d)


def prepare_meetings(root: Path) -> None:
    """Public long recordings with human transcripts (kept in --root\\meetings for later benches too): <name>.wav
    (16 kHz mono) and <name>.txt (the reference). Nothing of them goes into the repository."""
    import io
    import zipfile
    import xml.etree.ElementTree as ET

    import numpy as np
    import soundfile as sf
    from huggingface_hub import hf_hub_download

    out = root / "meetings"
    out.mkdir(parents=True, exist_ok=True)
    cache = paths(root)["cache"] / "meetings"

    def save_audio(name: str, data, sr: int) -> None:
        if data.ndim > 1:
            data = data.mean(axis=1)
        if sr != SR:
            import soxr

            data = soxr.resample(data, sr, SR)
        sf.write(out / f"{name}.wav", data.astype(np.float32), SR)

    # en: AMI ES2004a (CC-BY-4.0), 4 speakers, a design meeting; headset mix; words from the manual annotation
    if not (out / "en-ami-ES2004a.txt").exists():
        repo = "FluidInference/ami-corpus-mirror"
        wav = hf_hub_download(repo, "sdm/ES2004a.Mix-Headset.wav", repo_type="dataset", local_dir=cache)
        ann = hf_hub_download(repo, "annotations/ami_public_manual_1.6.2.zip", repo_type="dataset", local_dir=cache)
        words = []
        with zipfile.ZipFile(ann) as z:
            for n in z.namelist():
                if re.match(r"words/ES2004a\.[A-Z]\.words\.xml$", n):
                    for el in ET.fromstring(z.read(n)).iter():
                        if el.tag == "w" and el.text and el.get("punc") != "true" and el.get("starttime"):
                            words.append((float(el.get("starttime")), el.text))
        words.sort()
        a, sr = sf.read(wav, dtype="float32")
        save_audio("en-ami-ES2004a", a, sr)
        (out / "en-ami-ES2004a.txt").write_text(" ".join(w for _, w in words), encoding="utf-8")
        say(f"en-ami-ES2004a: {len(a) / sr / 60:.1f} min, {len(words)} words")
    # en: NOTSOFAR-1 MTG_32000 (CC-BY-4.0), a natural office meeting, one far-field device
    if not (out / "en-notsofar-MTG32000.txt").exists():
        base = "benchmark-datasets/eval_set/240825.1_eval_full_with_GT/MTG/MTG_32000/"
        gt = hf_hub_download("microsoft/NOTSOFAR", base + "gt_transcription.json", repo_type="dataset", local_dir=cache)
        wav = hf_hub_download("microsoft/NOTSOFAR", base + "sc_plaza_0/ch0.wav", repo_type="dataset", local_dir=cache)
        rows = json.loads(Path(gt).read_text(encoding="utf-8"))
        rows.sort(key=lambda r: float(r.get("start_time", 0)))
        a, sr = sf.read(wav, dtype="float32")
        save_audio("en-notsofar-MTG32000", a, sr)
        (out / "en-notsofar-MTG32000.txt").write_text(" ".join(r["text"] for r in rows), encoding="utf-8")
        say(f"en-notsofar-MTG32000: {len(a) / sr / 60:.1f} min")
    # ru: a webinar from YODAS2 ru000 (CC-BY-3.0 videos; captions uploaded by the author, punctuated - not checked
    # word by word: a rough reference)
    if not (out / "ru-yodas-webinar.txt").exists():
        from huggingface_hub import HfFileSystem

        repo, shard, vid = "espnet/yodas2", "00000000", "Y35nnzaDLRA"
        tj = hf_hub_download(repo, f"data/ru000/text/{shard}.json", repo_type="dataset", local_dir=cache)
        text = next(e["text"] for e in json.loads(Path(tj).read_text(encoding="utf-8")) if e["audio_id"] == vid)
        with HfFileSystem().open(f"datasets/{repo}/data/ru000/audio/{shard}.tar.gz", "rb") as f, \
                tarfile.open(fileobj=f, mode="r|gz") as t:
            for m in t:
                if m.isfile() and m.name.rsplit("/", 1)[-1].split(".")[0] == vid:
                    raw = t.extractfile(m).read()
                    break
        import av

        frames = []
        with av.open(io.BytesIO(raw)) as c:
            rs = av.AudioResampler(format="flt", layout="mono", rate=SR)
            for fr in c.decode(audio=0):
                for x in rs.resample(fr):
                    frames.append(x.to_ndarray().reshape(-1))
        save_audio("ru-yodas-webinar", np.concatenate(frames), SR)
        (out / "ru-yodas-webinar.txt").write_text(" ".join(text[k] for k in sorted(text)), encoding="utf-8")
        say(f"ru-yodas-webinar: {sum(len(x) for x in frames) / SR / 60:.1f} min")
    # ru: one talk of Multilingual TEDx ru test (CC BY-NC-ND 4.0: evaluation only), human subtitles, one speaker
    if not (out / "ru-mtedx-talk.txt").exists():
        import pyarrow.parquet as pq
        from huggingface_hub import list_repo_files

        files = [f for f in list_repo_files("deepdml/mtedx", repo_type="dataset") if f.startswith("ru/test")]
        pqf = hf_hub_download("deepdml/mtedx", files[0], repo_type="dataset", local_dir=cache)
        tbl = pq.read_table(pqf).to_pylist()
        talks: Dict[str, List[Dict[str, Any]]] = {}
        for r in tbl:
            talks.setdefault(r["talk_id"], []).append(r)
        # the talk closest to 12 minutes
        dur = {k: sum(float(r["end"]) - float(r["start"]) for r in v) for k, v in talks.items()}
        tid = min(dur, key=lambda k: abs(dur[k] - 720))
        rows = sorted(talks[tid], key=lambda r: float(r["start"]))
        parts, texts = [], []
        for r in rows:
            au = r["audio"]
            data, sr = sf.read(io.BytesIO(au["bytes"]), dtype="float32")
            if sr != SR:
                import soxr

                data = soxr.resample(data, sr, SR)
            parts += [data, np.zeros(int(0.4 * SR), dtype=np.float32)]
            texts.append(r["transcript"])
        save_audio("ru-mtedx-talk", np.concatenate(parts), SR)
        (out / "ru-mtedx-talk.txt").write_text(" ".join(texts), encoding="utf-8")
        say(f"ru-mtedx-talk: {dur[tid] / 60:.1f} min of speech, {len(rows)} segments")


def fetch_vad(root: Path) -> None:
    from huggingface_hub import snapshot_download

    snapshot_download(VAD_REPO[0], revision=VAD_REPO[1], local_dir=vad_path(root))


# ---------------------------------------------------------------- loudness, as the app evens it

QUIET_PEAK, SILENT_PEAK, MAX_GAIN, LEVEL_SEC = 0.3, 0.002, 30.0, 10.0  # app.asr_onnx.level()


def level(audio):
    """Quiet speech raised the way app.asr_onnx.level() does it before every recognition (a whole recording, then
    each 10 s part on its own): many FLEURS phrases peak at 0.005, which the Silero VAD takes for silence."""
    import numpy as np

    a = np.asarray(audio, dtype=np.float32)
    if not a.size:
        return a

    def peak(x):
        return float(np.percentile(np.abs(x), 99.9)) if x.size else 0.0

    p = peak(a)
    if SILENT_PEAK < p < QUIET_PEAK:
        a = np.clip(a * min(0.9 / p, MAX_GAIN), -1, 1)
        p = peak(a)
    win = int(LEVEL_SEC * SR)
    n = a.size // win
    if n < 2 or p <= SILENT_PEAK:
        return a
    peaks = np.array([peak(a[i * win:(i + 1) * win]) for i in range(n)])
    floor = max(SILENT_PEAK, p * 0.03)
    gains = np.where((peaks > floor) & (peaks < QUIET_PEAK), np.minimum(0.9 / np.maximum(peaks, 1e-6), MAX_GAIN), 1.0)
    g = np.interp(np.arange(a.size), (np.arange(n) + 0.5) * win, gains).astype(np.float32)
    return np.clip(a * g, -1, 1)


class StreamLevel:
    """The same while the audio arrives: the gain follows the loudest part of the last 10 s (it drops at once, so
    nothing clips, and rises over a few pieces)."""

    def __init__(self):
        from collections import deque

        self.peaks = deque()
        self.gain = 1.0

    def __call__(self, piece):
        import numpy as np

        if not piece.size:
            return piece
        self.peaks.append((piece.size, float(np.percentile(np.abs(piece), 99.9))))
        while sum(n for n, _ in self.peaks) > LEVEL_SEC * SR and len(self.peaks) > 1:
            self.peaks.popleft()
        p = max(x for _, x in self.peaks)
        target = min(0.9 / p, MAX_GAIN) if SILENT_PEAK < p < QUIET_PEAK else 1.0
        self.gain = target if target < self.gain else self.gain + (target - self.gain) * 0.5
        return np.clip(piece * self.gain, -1, 1).astype(np.float32)


# ---------------------------------------------------------------- loading (in the worker)

def set_affinity_self(cpus: int) -> None:
    """Keeps this process (and what it starts) on the first `cpus` logical processors."""
    if os.name == "nt" and cpus:
        import ctypes

        k = ctypes.windll.kernel32
        k.SetProcessAffinityMask.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        k.SetProcessAffinityMask(k.GetCurrentProcess(), ((1 << cpus) - 1) << int(os.environ.get("BENCH_CPU_START", "0")))


def set_priority(prio: str) -> None:
    if os.name != "nt" or prio == "normal":
        return
    import ctypes

    cls = {"below": 0x4000, "idle": 0x40}[prio]
    ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), cls)


def ort_options(threads: int, spin: bool):
    import onnxruntime as ort

    so = ort.SessionOptions()
    so.intra_op_num_threads = threads
    so.inter_op_num_threads = 1
    if not spin:
        so.add_session_config_entry("session.intra_op.allow_spinning", "0")
        so.add_session_config_entry("session.inter_op.allow_spinning", "0")
    return so


def app_threads() -> int:
    return max(2, min(8, (os.cpu_count() or 4) // 2))  # app.asr_onnx.cpu_threads() with «auto»


class Model:
    """One interface for every runtime: recognize(array) -> text; stream() for the streaming ones."""

    def __init__(self, root: Path, key: str, threads: int, spin: bool, device: str, lang: str):
        self.key, self.m, self.lang, self.device = key, MODELS[key], lang, device
        kind = self.m["kind"]
        d = model_dir(root, key)
        t0 = time.perf_counter()
        if kind == "onnx":
            if device == "gpu":
                try:
                    import torch  # noqa: F401 - its CUDA libraries serve ONNX Runtime too
                except ImportError:
                    pass
                import onnxruntime

                onnxruntime.preload_dlls()
            import onnx_asr

            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"] if device == "gpu" else ["CPUExecutionProvider"]
            so = None if device == "gpu" else ort_options(threads, spin)
            self.asr = onnx_asr.load_model(self.m["name"], d, quantization=self.m["quant"], providers=providers,
                                           sess_options=so)
        elif kind.startswith("sherpa"):
            import sherpa_onnx

            provider = "cuda" if device == "gpu" else "cpu"
            if device != "gpu" and not spin:
                conf = paths(root)["tmp"] / "cpu-session.conf"
                conf.parent.mkdir(parents=True, exist_ok=True)
                conf.write_text("SessionConfig.session.intra_op.allow_spinning=0\n"
                                "SessionConfig.session.inter_op.allow_spinning=0\n", encoding="utf-8")
                provider = f"cpu:{conf}"
            ep = dict(enable_endpoint_detection=True, rule1_min_trailing_silence=2.4,
                      rule2_min_trailing_silence=0.6, rule3_min_utterance_length=20.0)
            if kind == "sherpa-nemotron":
                f = {p.name.split(".")[0]: str(p) for p in d.glob("*.onnx")}
                self.rec = sherpa_onnx.OnlineRecognizer.from_transducer(
                    tokens=str(d / "tokens.txt"), encoder=f["encoder"], decoder=f["decoder"], joiner=f["joiner"],
                    num_threads=threads, sample_rate=SR, feature_dim=128, decoding_method="greedy_search",
                    provider=provider, **ep)
            else:
                onnx = next(p for p in d.glob("*.onnx"))
                self.rec = sherpa_onnx.OnlineRecognizer.from_t_one_ctc(
                    model=str(onnx), tokens=str(d / "tokens.txt"), num_threads=threads, provider=provider, **ep)
        elif kind == "whisper":
            from faster_whisper import WhisperModel

            if device == "gpu":
                try:  # CTranslate2 finds cuBLAS / cuDNN in the folder of PyTorch's CUDA libraries
                    import torch

                    os.add_dll_directory(str(Path(torch.__file__).parent / "lib"))
                except ImportError:
                    pass
                self.w = WhisperModel(str(d), device="cuda", compute_type="float16")
            else:
                self.w = WhisperModel(str(d), device="cpu", compute_type="int8", cpu_threads=threads)
        elif kind == "qwen":
            import torch
            from qwen_asr import Qwen3ASRModel

            self.q = Qwen3ASRModel.from_pretrained(self.m["name"], dtype=torch.bfloat16, device_map="cuda:0",
                                                   max_inference_batch_size=8, max_new_tokens=448)
        self.load_sec = time.perf_counter() - t0
        self.streaming = kind.startswith("sherpa")

    def recognize(self, a) -> str:
        kind = self.m["kind"]
        if kind == "onnx":
            kw = {"language": self.lang} if self.m["name"].startswith("nemo-canary") else {}
            return str(self.asr.recognize(a, sample_rate=SR, **kw) or "")
        if kind == "whisper":
            segs, _ = self.w.transcribe(a, language=self.lang, beam_size=5, vad_filter=False,
                                        condition_on_previous_text=False)
            return " ".join(s.text.strip() for s in segs)
        if kind == "qwen":
            r = self.q.transcribe(audio=(a, SR), language=QWEN_LANG[self.lang])
            r = r[0] if isinstance(r, list) else r
            return str(getattr(r, "text", r))
        # a streaming model on a whole phrase
        import numpy as np

        s = self.new_stream()
        s.accept_waveform(SR, a)
        s.accept_waveform(SR, np.zeros(int(0.8 * SR), dtype=np.float32))
        s.input_finished()
        while self.rec.is_ready(s):
            self.rec.decode_stream(s)
        return self.clean(self.rec.get_result(s))

    def recognize_batch(self, arrays) -> List[str]:
        if self.m["kind"] == "onnx" and not self.m["name"].startswith("nemo-canary"):
            return [str(x or "") for x in self.asr.recognize(list(arrays), sample_rate=SR)]
        return [self.recognize(a) for a in arrays]

    def new_stream(self):
        s = self.rec.create_stream()
        if self.m["kind"] == "sherpa-nemotron":
            s.set_option("language", NEMOTRON_LANG.get(self.lang, "auto"))
        return s

    @staticmethod
    def clean(text: str) -> str:
        return re.sub(r"<\|?[a-z]{2}(-[A-Z]{2})?\|?>", "", text or "").strip()  # a language tag of "auto"


# ---------------------------------------------------------------- worker: offline

def worker_offline(root: Path, job: Dict[str, Any]) -> Dict[str, Any]:
    import numpy as np
    import soundfile as sf

    set_priority(job.get("prio", "normal"))
    out: Dict[str, Any] = {"langs": {}}
    model = None
    for lang in job["langs"]:
        if lang not in MODELS[job["model"]]["langs"]:
            continue
        if model is None:
            model = Model(root, job["model"], job["threads"], job["spin"], job["device"], lang)
            out["load_sec"] = round(model.load_sec, 2)
        model.lang = lang
        d = paths(root)["data"] / "fleurs" / lang
        phrases = json.loads((d / "phrases.json").read_text(encoding="utf-8"))[: job["n"]]
        arrays = [level(sf.read(d / p["file"], dtype="float32")[0]) for p in phrases]
        model.recognize(arrays[0])  # warm-up, not timed
        hyps, times = [], []
        for a in arrays:
            t0 = time.perf_counter()
            hyps.append(model.recognize(a))
            times.append(time.perf_counter() - t0)
        refs = [p["text"] for p in phrases]
        w, c = wer_cer(refs, hyps)
        audio = sum(len(a) for a in arrays) / SR
        out["langs"][lang] = {"wer": round(w, 2), "cer": round(c, 2), "rtfx": round(audio / sum(times), 1),
                              "n": len(phrases), "audio_sec": round(audio, 1),
                              "hyps": [{"ref": r, "hyp": h} for r, h in zip(refs, hyps)]}
        say(f"  {job['model']} {lang}: WER {w:.2f} CER {c:.2f} RTFx {audio / sum(times):.1f}")
    return out


def vad_chunks(root: Path, audio, max_sec: float = 25.0) -> List[Tuple[int, int]]:
    """Speech parts by the Silero VAD (pause >= 300 ms), joined into pieces of at most max_sec."""
    vad = SileroStream(vad_path(root), False)
    speech: List[Tuple[int, int]] = []
    start, silence = None, 0
    for pos in range(0, len(audio) - 512, 512):
        p = vad.prob(audio[pos:pos + 512])
        if start is None and p >= 0.5:
            start, silence = max(0, pos - 1600), 0
        elif start is not None:
            silence = 0 if p >= 0.35 else silence + 512
            if silence >= 0.3 * SR:
                speech.append((start, min(len(audio), pos + 1600)))
                start = None
    if start is not None:
        speech.append((start, len(audio)))
    out: List[Tuple[int, int]] = []
    for a, b in speech:
        while b - a > max_sec * SR:  # one long phrase: cut
            out.append((a, a + int(max_sec * SR)))
            a += int(max_sec * SR)
        if out and b - out[-1][0] <= max_sec * SR:
            out[-1] = (out[-1][0], b)
        else:
            out.append((a, b))
    return out


def recognize_long(model: "Model", root: Path, audio) -> str:
    kind = model.m["kind"]
    if kind == "onnx" and not model.m["name"].startswith("nemo-canary"):
        import onnx_asr

        vad = onnx_asr.load_vad("silero", vad_path(root))
        m = model.asr.with_vad(vad, max_speech_duration_s=20, min_silence_duration_ms=300, speech_pad_ms=120,
                               batch_size=8)
        return " ".join(str(r.text or "") for r in m.recognize(audio, sample_rate=SR))
    if kind == "whisper":
        segs, _ = model.w.transcribe(audio, language=model.lang, beam_size=5, vad_filter=True)
        return " ".join(s.text.strip() for s in segs)
    if kind.startswith("sherpa"):
        s = model.new_stream()
        texts = []
        step = int(0.5 * SR)
        for i in range(0, len(audio), step):
            s.accept_waveform(SR, audio[i:i + step])
            while model.rec.is_ready(s):
                model.rec.decode_stream(s)
            if model.rec.is_endpoint(s):
                texts.append(model.clean(model.rec.get_result(s)))
                model.rec.reset(s)
        import numpy as np

        s.accept_waveform(SR, np.zeros(SR, dtype=np.float32))
        s.input_finished()
        while model.rec.is_ready(s):
            model.rec.decode_stream(s)
        texts.append(model.clean(model.rec.get_result(s)))
        return " ".join(t for t in texts if t)
    return " ".join(model.recognize(audio[a:b]) for a, b in vad_chunks(root, audio))


def worker_longform(root: Path, job: Dict[str, Any]) -> Dict[str, Any]:
    """The public long recordings of --root\\meetings: WER of the whole text, RTFx."""
    import soundfile as sf

    set_priority(job.get("prio", "normal"))
    out: Dict[str, Any] = {"files": {}}
    model = None
    for f in sorted((root / "meetings").glob("*.wav")):
        lang = f.name[:2]
        if lang not in MODELS[job["model"]]["langs"]:
            continue
        if model is None:
            model = Model(root, job["model"], job["threads"], job["spin"], job["device"], lang)
            out["load_sec"] = round(model.load_sec, 2)
        model.lang = lang
        audio = level(sf.read(f, dtype="float32")[0])
        ref = f.with_suffix(".txt").read_text(encoding="utf-8")
        t0 = time.perf_counter()
        hyp = recognize_long(model, root, audio)
        dt = time.perf_counter() - t0
        w, c = wer_cer([ref], [hyp])
        out["files"][f.stem] = {"wer": round(w, 2), "cer": round(c, 2), "rtfx": round(len(audio) / SR / dt, 1),
                                "minutes": round(len(audio) / SR / 60, 1)}
        say(f"  {job['model']} {f.stem}: WER {w:.2f} RTFx {len(audio) / SR / dt:.1f}")
    return out


# ---------------------------------------------------------------- worker: live

class Feeder:
    """The long file in real time: what has been 'spoken' by now."""

    def __init__(self, audio, speed: float = 1.0):
        self.audio, self.speed = audio, speed
        self.t0 = time.perf_counter()
        self.pos = 0

    def now(self) -> float:
        return (time.perf_counter() - self.t0) * self.speed

    def take(self):
        end = min(len(self.audio), int(self.now() * SR))
        piece = self.audio[self.pos:end]
        self.pos = end
        return piece

    def done(self) -> bool:
        return self.pos >= len(self.audio)

    def wait_until(self, t: float) -> None:
        dt = t / self.speed - (time.perf_counter() - self.t0)
        if dt > 0:
            time.sleep(dt)


class SileroStream:
    """Silero VAD frame by frame (512 samples): speech start and end with a 500 ms pause."""

    def __init__(self, path: Path, spin: bool):
        import numpy as np
        import onnxruntime as ort

        f = next(p for p in path.glob("*.onnx") if "int8" not in p.name and "16k" not in p.name) \
            if any(path.glob("*.onnx")) else None
        self.sess = ort.InferenceSession(str(f), ort_options(1, spin), providers=["CPUExecutionProvider"])
        self.inputs = [i.name for i in self.sess.get_inputs()]
        self.state = np.zeros((2, 1, 128), dtype=np.float32)
        self.context = np.zeros((1, 64), dtype=np.float32)
        self.np = np

    def prob(self, frame) -> float:
        np = self.np
        x = np.concatenate([self.context, frame.reshape(1, -1)], axis=1)
        feeds = {}
        for name in self.inputs:
            if name == "input":
                feeds[name] = x
            elif name == "state":
                feeds[name] = self.state
            elif name == "sr":
                feeds[name] = np.array(SR, dtype=np.int64)
        out = self.sess.run(None, feeds)
        self.state = out[1]
        self.context = x[:, -64:]
        return float(out[0].reshape(-1)[0])


def _events_metrics(events: List[Dict[str, Any]], segs: List[Dict[str, Any]], total: float) -> Dict[str, Any]:
    finals = [e for e in events if e["kind"] == "final"]
    lat = [e["at"] - e["end"] for e in finals if e.get("end") is not None]
    first = []
    texts = [e for e in events if e["text"]]
    j = 0
    for s in segs:
        while j < len(texts) and texts[j]["at"] < s["start"] + 0.2:
            j += 1
        if j < len(texts) and texts[j]["at"] < s["end"] + 3:
            first.append(texts[j]["at"] - s["start"])
    hyp = " ".join(e["text"] for e in finals)
    ref = " ".join(s["text"] for s in segs if s["end"] <= total)
    w, c = wer_cer([ref], [hyp])

    def pct(v, q):
        return round(sorted(v)[min(len(v) - 1, int(q * len(v)))], 2) if v else None

    return {"wer": round(w, 2), "cer": round(c, 2), "finals": len(finals),
            "final_latency_median": round(statistics.median(lat), 2) if lat else None, "final_latency_p90": pct(lat, 0.9),
            "first_draft_median": round(statistics.median(first), 2) if first else None,
            "first_draft_p90": pct(first, 0.9)}


def live_window_app(root: Path, job: Dict[str, Any], audio, segs, total: float) -> Dict[str, Any]:
    """The app's own captions (app.live.LiveSession) with its own model loading (app.asr_onnx), fed as the page does:
    a post of the audio gathered since the last one about every second, never two at once."""
    os.environ["VERBALIOX_DATA_DIR"] = str(paths(root)["tmp"] / "app-data")
    os.environ["VERBALIOX_MODELS_DIR"] = str(paths(root)["models"] / "app")
    sys.path.insert(0, str(ROOT))
    from app import asr_onnx, live
    from app.database import init_db, update_settings

    init_db()
    mid = "gigaam-v3" if job["model"].startswith("gigaam") else "parakeet-v3"
    update_settings({"live_whisper_model": mid, "cpu_threads": str(job["threads_setting"])})
    if job["model"] not in ("parakeet-fp32", "gigaam-rnnt"):
        # the same code with another quantization: the model from the bench's folder, as int8
        key = job["model"]
        import onnx_asr

        orig = onnx_asr.load_model

        def load_model(name, path=None, **kw):
            return orig(name, model_dir(root, key), **{**kw, "quantization": MODELS[key]["quant"]})

        onnx_asr.load_model = load_model
        asr_onnx.fetch = lambda _mid: None
        asr_onnx.is_installed = lambda _mid: True
        vdir = vad_path(root)
        asr_onnx._vad_dir = lambda: vdir
    if not job["spin"]:
        orig_opts = asr_onnx._cpu_options

        def opts(*a, **k):  # the app passes the threads of the copy (asr_onnx._load)
            so = orig_opts(*a, **k)
            so.add_session_config_entry("session.intra_op.allow_spinning", "0")
            so.add_session_config_entry("session.inter_op.allow_spinning", "0")
            return so

        asr_onnx._cpu_options = opts
    t0 = time.perf_counter()
    asr_onnx._load(mid)
    load_sec = time.perf_counter() - t0
    sess = live.LiveSession(job["lang"], None)
    assert sess.onnx_model == mid, sess.onnx_model
    stop_queue = threading.Event()
    queue_stats = {"audio_sec": 0.0, "busy_sec": 0.0}
    if job.get("queue_inproc"):
        # the queue's transcription in the same process with the same model, as app/transcriber.py does on the CPU
        qwav = paths(root)["data"] / "fleurs" / job["lang"] / "long.wav"

        def queue_loop():
            while not stop_queue.is_set():
                t = time.perf_counter()

                def check():
                    if stop_queue.is_set():
                        raise InterruptedError

                try:
                    asr_onnx.transcribe(mid, qwav, total, lambda _p: None, check)
                    queue_stats["audio_sec"] += total
                except InterruptedError:
                    pass
                queue_stats["busy_sec"] += time.perf_counter() - t

        threading.Thread(target=queue_loop, daemon=True).start()
    feeder = Feeder(audio)
    events: List[Dict[str, Any]] = []
    steps: List[float] = []
    seen, partial = 0, ""
    sent_at = 0.0
    while not feeder.done():
        feeder.wait_until(sent_at + 1.0)
        sent_at = feeder.now()
        piece = feeder.take()
        if not piece.size:
            continue
        sess.add_pcm16((piece.clip(-1, 1) * 32767).astype("<i2").tobytes())
        t = time.perf_counter()
        sess.step()
        steps.append(time.perf_counter() - t)
        at = feeder.now()
        for line in sess.lines[seen:]:
            events.append({"kind": "final", "at": at, "end": line["end"], "text": line["text"]})
        seen = len(sess.lines)
        if sess.partial != partial:
            partial = sess.partial
            events.append({"kind": "draft", "at": at, "text": partial})
    stop_queue.set()
    res = {"total": total}  # the scores: in the parent (the app's Python has no jiwer)
    res.update({"load_sec": round(load_sec, 2), "steps": len(steps),
                "step_median": round(statistics.median(steps), 3) if steps else None,
                "step_max": round(max(steps), 3) if steps else None, "events": events, "error": sess.error})
    if job.get("queue_inproc"):
        res["queue_rtfx"] = round(queue_stats["audio_sec"] / max(1e-6, queue_stats["busy_sec"]), 2)
        res["queue_audio_sec"] = queue_stats["audio_sec"]
    return res


def live_vad(model: Model, root: Path, job: Dict[str, Any], audio, segs, total: float) -> Dict[str, Any]:
    import numpy as np

    vad = SileroStream(vad_path(root), job["spin"])
    feeder = Feeder(audio)
    events: List[Dict[str, Any]] = []
    calls: List[float] = []
    buf = np.zeros(0, dtype=np.float32)   # audio not yet given to the VAD
    pos = 0                               # samples given to the VAD
    speech_start: Optional[int] = None
    silence = 0
    last_speech = 0
    last_draft = 0.0
    draft = ""
    pad = int(0.1 * SR)
    hist = np.zeros(0, dtype=np.float32)  # all the audio (for the phrase's samples)
    tick = job.get("tick", 0.2)
    k = 0
    lev = StreamLevel()
    while not feeder.done():
        k += 1
        feeder.wait_until(k * tick)
        piece = lev(feeder.take())
        hist = np.concatenate([hist, piece])
        buf = np.concatenate([buf, piece])
        ended: Optional[Tuple[int, int]] = None
        while buf.size >= 512 and ended is None:
            fr, buf = buf[:512], buf[512:]
            p = vad.prob(fr)
            pos += 512
            if speech_start is None:
                if p >= 0.5:
                    speech_start, silence, last_speech = max(0, pos - 512 - pad), 0, pos
            else:
                if p >= 0.35:
                    silence, last_speech = 0, pos
                else:
                    silence += 512
                if silence >= 0.5 * SR and last_speech - speech_start >= 0.25 * SR:
                    ended = (speech_start, last_speech)
                elif silence >= 0.5 * SR:
                    speech_start = None  # too short: noise
                elif pos - speech_start >= 20 * SR:
                    ended = (speech_start, pos)
        at = feeder.now()
        if ended is not None:
            a, b = ended
            t = time.perf_counter()
            text = model.recognize(hist[a:min(len(hist), b + pad)])
            calls.append(time.perf_counter() - t)
            events.append({"kind": "final", "at": feeder.now(), "end": b / SR, "text": text})
            speech_start, draft = None, ""
            last_draft = feeder.now()
            if buf.size:  # the rest of this tick goes to the VAD at the next one
                pass
        elif speech_start is not None and at - last_draft >= job.get("draft_sec", 1.2) \
                and pos - speech_start >= 0.5 * SR:
            t = time.perf_counter()
            text = model.recognize(hist[speech_start:pos])
            calls.append(time.perf_counter() - t)
            last_draft = feeder.now()
            if text != draft:
                draft = text
                events.append({"kind": "draft", "at": feeder.now(), "text": text})
    res = _events_metrics(events, segs, total)
    res.update({"calls": len(calls), "call_median": round(statistics.median(calls), 3) if calls else None,
                "call_max": round(max(calls), 3) if calls else None, "events": events})
    return res


def live_stream(model: Model, job: Dict[str, Any], audio, segs, total: float) -> Dict[str, Any]:
    feeder = Feeder(audio)
    events: List[Dict[str, Any]] = []
    s = model.new_stream()
    text = ""
    tick = job.get("tick", 0.2)
    k = 0
    fed = 0
    seg_start = 0.0      # audio time of the stream's start (after the last reset)
    busy: List[float] = []
    lev = StreamLevel()
    while not feeder.done():
        k += 1
        feeder.wait_until(k * tick)
        piece = lev(feeder.take())
        if not piece.size:
            continue
        t = time.perf_counter()
        s.accept_waveform(SR, piece)
        fed += piece.size
        while model.rec.is_ready(s):
            model.rec.decode_stream(s)
        cur = model.clean(model.rec.get_result(s))
        busy.append(time.perf_counter() - t)
        at = feeder.now()
        if cur != text and cur:
            events.append({"kind": "draft", "at": at, "text": cur})
        text = cur
        if model.rec.is_endpoint(s):
            if text:
                end = None
                try:
                    r = model.rec.get_result_all(s)
                    if r.timestamps:
                        end = seg_start + float(r.timestamps[-1]) + 0.08
                except Exception:
                    pass
                events.append({"kind": "final", "at": at, "end": end, "text": text})
            model.rec.reset(s)
            seg_start = fed / SR
            text = ""
    if text:
        events.append({"kind": "final", "at": feeder.now(), "end": None, "text": text})
    res = _events_metrics(events, segs, total)
    res.update({"decode_median": round(statistics.median(busy), 4) if busy else None,
                "decode_max": round(max(busy), 3) if busy else None, "events": events})
    return res


def worker_live(root: Path, job: Dict[str, Any]) -> Dict[str, Any]:
    import soundfile as sf

    set_priority(job.get("prio", "normal"))
    d = paths(root)["data"] / "fleurs" / job["lang"]
    audio = sf.read(d / "long.wav", dtype="float32")[0]
    segs = json.loads((d / "long.json").read_text(encoding="utf-8"))
    total = len(audio) / SR
    if job.get("seconds"):
        total = min(total, job["seconds"])
        audio = audio[: int(total * SR)]
        segs = [s for s in segs if s["end"] <= total]
    if job["scheme"] == "window":
        return live_window_app(root, job, audio, segs, total)
    model = Model(root, job["model"], job["threads"], job["spin"], job["device"], job["lang"])
    model.recognize(audio[: 3 * SR])  # warm-up
    res = (live_stream(model, job, audio, segs, total) if job["scheme"] == "stream"
           else live_vad(model, root, job, audio, segs, total))
    res["load_sec"] = round(model.load_sec, 2)
    return res


# ---------------------------------------------------------------- worker: the queue's transcription

def worker_queue(root: Path, job: Dict[str, Any]) -> Dict[str, Any]:
    """Transcribes the long file again and again until the stop file appears (as the queue would, with the VAD)."""
    import soundfile as sf

    set_priority(job.get("prio", "normal"))
    audio = level(sf.read(paths(root)["data"] / "fleurs" / job["lang"] / "long.wav", dtype="float32")[0])
    stop = Path(job["stop_file"])
    m = MODELS[job["model"]]
    t0 = time.perf_counter()
    done_sec, busy = 0.0, 0.0
    if m["kind"] == "onnx":
        import onnx_asr

        asr = onnx_asr.load_model(m["name"], model_dir(root, job["model"]), quantization=m["quant"],
                                  sess_options=ort_options(job["threads"], job["spin"]))
        vad = onnx_asr.load_vad("silero", vad_path(root), sess_options=ort_options(1, job["spin"]))
        model = asr.with_vad(vad, max_speech_duration_s=20, min_silence_duration_ms=300, speech_pad_ms=120,
                             batch_size=8)
        load = time.perf_counter() - t0
        while not stop.exists():
            t = time.perf_counter()
            reached = 0.0  # audio time transcribed in this pass
            for r in model.recognize(audio, sample_rate=SR):
                reached = float(r.end)
                if stop.exists():
                    break
            else:
                reached = len(audio) / SR
            done_sec += reached
            busy += time.perf_counter() - t
    else:
        mod = Model(root, job["model"], job["threads"], job["spin"], job.get("device", "cpu"), job["lang"])
        load = mod.load_sec
        piece = 30 * SR
        while not stop.exists():
            for i in range(0, len(audio), piece):
                if stop.exists():
                    break
                t = time.perf_counter()
                mod.recognize(audio[i:i + piece])
                busy += time.perf_counter() - t
                done_sec += min(piece, len(audio) - i) / SR
    return {"load_sec": round(load, 2), "audio_sec": round(done_sec, 1), "busy_sec": round(busy, 1),
            "rtfx": round(done_sec / max(busy, 1e-6), 2)}


# ---------------------------------------------------------------- probe of responsiveness

def run_probe(stop_file: str, out_file: str, interval: float = 0.01, cpus: int = 0) -> None:
    set_affinity_self(cpus)
    lates: List[float] = []
    stop = Path(stop_file)
    n = 0
    while True:
        t = time.perf_counter()
        time.sleep(interval)
        lates.append((time.perf_counter() - t - interval) * 1000)
        n += 1
        if n % 50 == 0 and stop.exists():
            break
    lates.sort()
    res = {"samples": len(lates), "p50_ms": round(lates[len(lates) // 2], 2),
           "p99_ms": round(lates[int(0.99 * len(lates))], 2), "p999_ms": round(lates[int(0.999 * len(lates))], 2),
           "max_ms": round(lates[-1], 1), "stalls_50": sum(1 for x in lates if x > 50),
           "stalls_200": sum(1 for x in lates if x > 200)}
    Path(out_file).write_text(json.dumps(res), encoding="utf-8")


# ---------------------------------------------------------------- the parent: runs and sampling

class Sampler:
    """Processor and memory of the given processes and of the whole system, every 0.5 s."""

    def __init__(self):
        import psutil

        self.psutil = psutil
        self.procs: Dict[str, Any] = {}
        self.data: Dict[str, Dict[str, List[float]]] = {}
        self.sys: List[float] = []
        self.kids: Dict[int, Any] = {}
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def add(self, name: str, pid: int) -> None:
        try:
            p = self.psutil.Process(pid)
            p.cpu_percent(None)
            self.procs[name] = p
            self.data[name] = {"cpu": [], "rss": []}
        except self.psutil.Error:
            pass

    def start(self) -> None:
        self.psutil.cpu_percent(None)
        self.thread.start()
        # DPC and interrupt time, hard page faults: Windows counters every second (only the numbers are kept)
        self.counters: List[List[float]] = []
        try:
            self.typeperf = subprocess.Popen(
                ["typeperf", r"\Processor(_Total)\% DPC Time", r"\Processor(_Total)\% Interrupt Time",
                 r"\Memory\Pages/sec", "-si", "1"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)

            def read():
                for line in self.typeperf.stdout:
                    cells = [c.strip('"') for c in line.strip().split('","')]
                    if len(cells) == 4:
                        try:
                            self.counters.append([float(c) for c in cells[1:]])
                        except ValueError:
                            pass

            threading.Thread(target=read, daemon=True).start()
        except OSError:
            self.typeperf = None

    def _run(self) -> None:
        n = self.psutil.cpu_count() or 1
        while not self._stop.wait(0.5):
            self.sys.append(self.psutil.cpu_percent(None))
            for name, p in list(self.procs.items()):
                try:
                    rss = p.memory_info().rss
                    cpu = p.cpu_percent(None)
                    for c in p.children(recursive=True):
                        try:
                            if c.pid not in self.kids:
                                self.kids[c.pid] = c
                                c.cpu_percent(None)
                                continue
                            rss += c.memory_info().rss
                            cpu += self.kids[c.pid].cpu_percent(None)
                        except self.psutil.Error:
                            pass
                    self.data[name]["cpu"].append(cpu / n)  # share of the whole processor, %
                    self.data[name]["rss"].append(rss / 2**20)
                except self.psutil.Error:
                    pass

    def stop(self) -> Dict[str, Any]:
        self._stop.set()
        self.thread.join(2)

        def summary(v):
            return {"mean": round(statistics.mean(v), 1), "peak": round(max(v), 1)} if v else None

        out = {"system_cpu": summary(self.sys[2:] or self.sys)}
        if getattr(self, "typeperf", None):
            self.typeperf.kill()
            c = self.counters[1:]
            if c:
                out["dpc_pct"] = summary([x[0] for x in c])
                out["interrupt_pct"] = summary([x[1] for x in c])
                out["pages_per_sec"] = summary([x[2] for x in c])
        for name, d in self.data.items():
            out[name] = {"cpu": summary(d["cpu"][2:] or d["cpu"]), "rss_peak_mb": round(max(d["rss"]), 0) if d["rss"] else None}
        return out


def affinity_mask(cpus: int) -> Optional[List[int]]:
    start = int(os.environ.get("BENCH_CPU_START", "0"))
    return list(range(start, start + cpus)) if cpus else None


def set_affinity(pid: int, cpus: Optional[List[int]]) -> None:
    if cpus:
        import psutil

        try:
            psutil.Process(pid).cpu_affinity(cpus)
        except psutil.Error:
            pass


def spawn_worker(args, job: Dict[str, Any], name: str, python: Optional[str] = None) -> Tuple[subprocess.Popen, Path]:
    p = paths(args.root)
    p["tmp"].mkdir(parents=True, exist_ok=True)
    jf = p["tmp"] / f"{name}.job.json"
    rf = p["tmp"] / f"{name}.result.json"
    rf.unlink(missing_ok=True)
    jf.write_text(json.dumps({**job, "cpus": args.cpus, "result_file": str(rf)}, ensure_ascii=False), encoding="utf-8")
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "HF_HUB_DISABLE_TELEMETRY": "1"}
    if job.get("device", "cpu") == "cpu":
        env["CUDA_VISIBLE_DEVICES"] = "-1"
    proc = subprocess.Popen([python or sys.executable, str(Path(__file__).resolve()), "worker", "--root", str(args.root),
                             "--job", str(jf)], env=env)
    return proc, rf


def run_job(args, job: Dict[str, Any], name: str, python: Optional[str] = None) -> Dict[str, Any]:
    sampler = Sampler()
    proc, rf = spawn_worker(args, job, name, python)
    set_affinity(proc.pid, affinity_mask(args.cpus))
    sampler.add("worker", proc.pid)
    sampler.start()
    proc.wait()
    usage = sampler.stop()
    res = json.loads(rf.read_text(encoding="utf-8")) if rf.exists() else {"error": f"exit code {proc.returncode}"}
    res["usage"] = usage
    return res


def gpu_used_mb() -> Optional[int]:
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10).stdout
        return int(out.split()[0])
    except Exception:
        return None


def save(args, name: str, data: Dict[str, Any]) -> None:
    d = paths(args.root)["results"]
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def threads_of(value: str) -> int:
    return app_threads() if value == "app" else int(value)


def job_base(args) -> Dict[str, Any]:
    return {"threads": threads_of(args.threads), "threads_setting": args.threads if args.threads != "app" else "auto",
            "spin": args.spin == "on", "prio": args.prio, "device": args.device}


def cmd_offline(args) -> None:
    for key in args.models:
        name = f"offline-{key}-{args.device}" + (f"-{args.tag}" if args.tag else "")
        say(f"== {name}")
        job = {**job_base(args), "mode": "offline", "model": key, "langs": args.langs, "n": args.n}
        vram0 = gpu_used_mb() if args.device == "gpu" else None
        stop = threading.Event()
        vram_peak = [0]
        if vram0 is not None:
            def watch():
                while not stop.wait(1.0):
                    v = gpu_used_mb()
                    if v:
                        vram_peak[0] = max(vram_peak[0], v)
            threading.Thread(target=watch, daemon=True).start()
        res = run_job(args, job, name, args.python)
        stop.set()
        if vram0 is not None:
            res["vram_mb"] = vram_peak[0] - vram0
        res["job"] = job
        save(args, name, res)


def cmd_longform(args) -> None:
    for key in args.models:
        name = f"longform-{key}-{args.device}" + (f"-{args.tag}" if args.tag else "")
        say(f"== {name}")
        job = {**job_base(args), "mode": "longform", "model": key}
        res = run_job(args, job, name, args.python)
        res["job"] = job
        save(args, name, res)


def _live_job(args) -> Dict[str, Any]:
    return {**job_base(args), "mode": "live", "model": args.model, "scheme": args.scheme, "lang": args.lang,
            "seconds": args.seconds, "tick": args.tick, "draft_sec": args.draft_sec}


def _live_python(args) -> Optional[str]:
    if args.scheme == "window":
        return args.app_python or str(ROOT / ".venv" / "Scripts" / "python.exe")
    return args.python


def run_name(args, mode: str) -> str:
    parts = [mode, args.model, args.scheme, args.lang, f"t{args.threads}", f"spin-{args.spin}", args.prio]
    if getattr(args, "queue", None):
        parts.append(f"q-{args.queue}-{args.queue_prio}")
    if args.cpus:
        parts.append(f"cpus{args.cpus}")
    if args.tag:
        parts.append(args.tag)
    return "-".join(parts)


def score_events(args, res: Dict[str, Any], job: Dict[str, Any]) -> None:
    """WER and latencies of a live run whose worker sent only its events (scheme window)."""
    if "events" not in res or "wer" in res:
        return
    d = paths(args.root)["data"] / "fleurs" / job["lang"]
    segs = json.loads((d / "long.json").read_text(encoding="utf-8"))
    total = res.get("total") or 1e9
    res.update(_events_metrics(res["events"], [s for s in segs if s["end"] <= total], total))


def cmd_live(args) -> None:
    name = run_name(args, "live")
    say(f"== {name}")
    job = _live_job(args)
    res = run_job(args, job, name, _live_python(args))
    score_events(args, res, job)
    res["job"] = job
    save(args, name, res)
    say(json.dumps({k: v for k, v in res.items() if k not in ("events", "job")}, ensure_ascii=False))


def start_ffmpeg(cpus) -> Tuple[subprocess.Popen, Dict[str, Any]]:
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-loglevel", "error", "-re", "-f", "lavfi", "-i",
           "testsrc2=s=1920x1080:r=30", "-vf", "noise=alls=12:allf=t", "-c:v", "libx264", "-preset", "veryfast",
           "-tune", "zerolatency", "-f", "null", "-", "-progress", "pipe:1"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    set_affinity(proc.pid, cpus)
    stats: Dict[str, Any] = {"frames": [], "speed": []}

    def read():
        for line in proc.stdout:
            k, _, v = line.strip().partition("=")
            if k == "frame":
                stats["frames"].append((time.perf_counter(), int(v)))
            elif k == "speed" and v.endswith("x"):
                try:
                    stats["speed"].append(float(v[:-1]))
                except ValueError:
                    pass

    threading.Thread(target=read, daemon=True).start()
    return proc, stats


def ffmpeg_summary(stats: Dict[str, Any]) -> Dict[str, Any]:
    fr = stats["frames"]
    if len(fr) < 3:
        return {}
    fps = [(b[1] - a[1]) / (b[0] - a[0]) for a, b in zip(fr, fr[1:]) if b[0] > a[0]]
    fps = fps[2:] or fps
    return {"fps_mean": round(statistics.mean(fps), 1), "fps_min": round(min(fps), 1),
            "share_below_28": round(sum(1 for f in fps if f < 28) / len(fps), 3)}


def cmd_call(args) -> None:
    """live + the queue's transcription + a video call's load + the probe, all at once."""
    name = run_name(args, "call")
    say(f"== {name}")
    p = paths(args.root)
    p["tmp"].mkdir(parents=True, exist_ok=True)
    cpus = affinity_mask(args.cpus)
    stop = p["tmp"] / f"{name}.stop"
    stop.unlink(missing_ok=True)
    probe_out = p["tmp"] / f"{name}.probe.json"
    probe_out.unlink(missing_ok=True)
    probe = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "probe", "--stop", str(stop),
                              "--out", str(probe_out), "--cpus", str(args.cpus)])
    set_affinity(probe.pid, cpus)
    sampler = Sampler()
    ff, ffstats = (None, None)
    if not args.no_video:
        ff, ffstats = start_ffmpeg(cpus)
        sampler.add("ffmpeg", ff.pid)
    q = qrf = None
    if args.queue and args.queue != "inproc":
        qjob = {"mode": "queue", "model": args.queue, "lang": args.lang, "threads": threads_of(args.queue_threads),
                "spin": args.spin == "on", "prio": args.queue_prio, "stop_file": str(stop), "device": "cpu"}
        q, qrf = spawn_worker(args, qjob, name + ".queue", args.python)
        set_affinity(q.pid, cpus)
        sampler.add("queue", q.pid)
    time.sleep(args.warmup)
    job = {**_live_job(args), "queue_inproc": args.queue == "inproc"}
    live_proc, lrf = spawn_worker(args, job, name + ".live", _live_python(args))
    set_affinity(live_proc.pid, cpus)
    sampler.add("live", live_proc.pid)
    sampler.start()
    live_proc.wait()
    usage = sampler.stop()
    stop.write_text("stop")
    for pr in (q, probe):
        if pr is not None:
            try:
                pr.wait(timeout=120)
            except subprocess.TimeoutExpired:
                pr.kill()
    if ff is not None:
        ff.terminate()
        ff.wait(10)
    res = json.loads(lrf.read_text(encoding="utf-8")) if lrf.exists() else {"error": f"live exit {live_proc.returncode}"}
    res["usage"] = usage
    score_events(args, res, job)
    res["probe"] = json.loads(probe_out.read_text(encoding="utf-8")) if probe_out.exists() else None
    res["queue"] = json.loads(qrf.read_text(encoding="utf-8")) if qrf and qrf.exists() else None
    res["video"] = ffmpeg_summary(ffstats) if ffstats else None
    res["job"] = {**job, "queue": args.queue, "queue_threads": args.queue_threads, "queue_prio": args.queue_prio,
                  "cpus": args.cpus, "video": not args.no_video}
    save(args, name, res)
    brief = {k: res.get(k) for k in ("wer", "final_latency_median", "final_latency_p90", "first_draft_median",
                                      "probe", "video", "queue", "queue_rtfx")}
    brief["cpu"] = usage
    say(json.dumps(brief, ensure_ascii=False))


def cmd_idle(args) -> None:
    """The probe (and the video load) with no recognition: the baseline of the stalls."""
    name = "idle" + ("-video" if not args.no_video else "") + (f"-cpus{args.cpus}" if args.cpus else "") + \
        (f"-{args.tag}" if args.tag else "")
    p = paths(args.root)
    p["tmp"].mkdir(parents=True, exist_ok=True)
    cpus = affinity_mask(args.cpus)
    stop = p["tmp"] / f"{name}.stop"
    stop.unlink(missing_ok=True)
    out = p["tmp"] / f"{name}.probe.json"
    probe = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "probe", "--stop", str(stop), "--out", str(out), "--cpus", str(args.cpus)])
    set_affinity(probe.pid, cpus)
    ff, st = (None, None) if args.no_video else start_ffmpeg(cpus)
    sampler = Sampler()
    sampler.start()
    time.sleep(args.seconds or 120)
    usage = sampler.stop()
    stop.write_text("stop")
    probe.wait(60)
    if ff:
        ff.terminate()
        ff.wait(10)
    res = {"probe": json.loads(out.read_text(encoding="utf-8")), "video": ffmpeg_summary(st) if st else None,
           "usage": usage, "job": {"cpus": args.cpus, "video": not args.no_video, "seconds": args.seconds or 120}}
    save(args, name, res)
    say(json.dumps(res, ensure_ascii=False))


def cmd_worker(args) -> None:
    job = json.loads(Path(args.job).read_text(encoding="utf-8"))
    set_affinity_self(job.get("cpus", 0))
    try:
        if job["mode"] == "offline":
            res = worker_offline(args.root, job)
        elif job["mode"] == "live":
            res = worker_live(args.root, job)
        elif job["mode"] == "longform":
            res = worker_longform(args.root, job)
        else:
            res = worker_queue(args.root, job)
    except Exception as e:
        import traceback

        traceback.print_exc()
        res = {"error": f"{type(e).__name__}: {e}"[:500]}
    Path(job["result_file"]).write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")


def cmd_prepare(args) -> None:
    prepare_data(args.root, args.n)
    fetch_vad(args.root)
    for key in args.models or [k for k, m in MODELS.items() if m["kind"] in ("onnx", "whisper") or
                               m["kind"].startswith("sherpa")]:
        try:
            fetch_model(args.root, key)
        except Exception as e:
            say(f"{key}: FAILED {e}")


# ---------------------------------------------------------------- report

def cmd_report(args) -> None:
    """Tables of every result (without the recognized texts) in --out: results.md and results.json."""
    d = paths(args.root)["results"]
    runs = {f.stem: json.loads(f.read_text(encoding="utf-8")) for f in sorted(d.glob("*.json"))}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    lines = ["# Raw results (tools/bench_asr.py)", ""]
    off = {k: v for k, v in runs.items() if k.startswith("offline-")}
    if off:
        lines += ["## offline (FLEURS test, 100 phrases per language)", "",
                  "| run | ru WER | ru CER | ru RTFx | en WER | en RTFx | de WER | de RTFx | load s | CPU % mean | RSS peak MB | VRAM MB |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for k, v in off.items():
            L = v.get("langs", {})

            def g(lang, key):
                return L.get(lang, {}).get(key, "—")

            u = (v.get("usage") or {}).get("worker") or {}
            lines.append(f"| {k} | {g('ru', 'wer')} | {g('ru', 'cer')} | {g('ru', 'rtfx')} | {g('en', 'wer')} | "
                         f"{g('en', 'rtfx')} | {g('de', 'wer')} | {g('de', 'rtfx')} | {v.get('load_sec', '—')} | "
                         f"{(u.get('cpu') or {}).get('mean', '—')} | {u.get('rss_peak_mb', '—')} | {v.get('vram_mb', '—')} |")
        lines.append("")
    lf = {k: v for k, v in runs.items() if k.startswith("longform-")}
    if lf:
        names = sorted({n for v in lf.values() for n in (v.get("files") or {})})
        lines += ["## longform (public meeting recordings, WER % / RTFx)", "",
                  "| run | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
        for k, v in lf.items():
            fs = v.get("files") or {}
            lines.append(f"| {k} | " + " | ".join(f"{fs[n]['wer']} / {fs[n]['rtfx']}" if n in fs else "—" for n in names) + " |")
        lines.append("")
    for mode in ("live", "call"):
        rs = {k: v for k, v in runs.items() if k.startswith(mode + "-")}
        if not rs:
            continue
        lines += [f"## {mode}", "",
                  "| run | WER | final latency med / p90 s | first draft med s | live CPU % mean / peak | live RSS MB | "
                  "system CPU % | probe p99 / max ms | stalls >50 / >200 ms | video fps mean / min | queue RTFx | DPC % mean / peak | pages/s peak |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for k, v in rs.items():
            u = v.get("usage") or {}
            lw = u.get("live") or u.get("worker") or {}
            pr = v.get("probe") or {}
            vi = v.get("video") or {}
            q = v.get("queue") or {}
            lines.append(
                f"| {k} | {v.get('wer', v.get('error', '—'))} | {v.get('final_latency_median', '—')} / "
                f"{v.get('final_latency_p90', '—')} | {v.get('first_draft_median', '—')} | "
                f"{(lw.get('cpu') or {}).get('mean', '—')} / {(lw.get('cpu') or {}).get('peak', '—')} | "
                f"{lw.get('rss_peak_mb', '—')} | {(u.get('system_cpu') or {}).get('mean', '—')} | "
                f"{pr.get('p99_ms', '—')} / {pr.get('max_ms', '—')} | {pr.get('stalls_50', '—')} / {pr.get('stalls_200', '—')} | "
                f"{vi.get('fps_mean', '—')} / {vi.get('fps_min', '—')} | {q.get('rtfx', v.get('queue_rtfx', '—'))} | "
                f"{(u.get('dpc_pct') or {}).get('mean', '—')} / {(u.get('dpc_pct') or {}).get('peak', '—')} | "
                f"{(u.get('pages_per_sec') or {}).get('peak', '—')} |")
        lines.append("")
    idle = {k: v for k, v in runs.items() if k.startswith("idle")}
    if idle:
        lines += ["## idle (no recognition)", "", "| run | probe p99 / max ms | stalls >50 / >200 | video fps mean / min | system CPU % |",
                  "|---|---|---|---|---|"]
        for k, v in idle.items():
            pr, vi = v.get("probe") or {}, v.get("video") or {}
            lines.append(f"| {k} | {pr.get('p99_ms')} / {pr.get('max_ms')} | {pr.get('stalls_50')} / {pr.get('stalls_200')} | "
                         f"{vi.get('fps_mean', '—')} / {vi.get('fps_min', '—')} | {((v.get('usage') or {}).get('system_cpu') or {}).get('mean')} |")
        lines.append("")
    (out / "results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def strip(v):
        if isinstance(v, dict):
            return {k: strip(x) for k, x in v.items() if k not in ("events", "hyps")}
        if isinstance(v, list):
            return [strip(x) for x in v]
        return v

    (out / "results.json").write_text(json.dumps(strip(runs), ensure_ascii=False, indent=1), encoding="utf-8")
    say(f"{len(runs)} runs -> {out}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--root", type=Path, required=True)
        p.add_argument("--threads", default="app", help='number or "app" (app.asr_onnx.cpu_threads)')
        p.add_argument("--spin", choices=["on", "off"], default="on")
        p.add_argument("--prio", choices=["normal", "below", "idle"], default="normal")
        p.add_argument("--device", choices=["cpu", "gpu"], default="cpu")
        p.add_argument("--cpus", type=int, default=0, help="keep the run on the first N logical processors")
        p.add_argument("--python", help="Python of the worker (a venv with the model's runtime)")
        p.add_argument("--tag", default="")

    p = sub.add_parser("prepare")
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--n", type=int, default=100)
    p.add_argument("--models", nargs="*")
    p.set_defaults(fn=cmd_prepare)

    p = sub.add_parser("meetings")
    p.add_argument("--root", type=Path, required=True)
    p.set_defaults(fn=lambda a: prepare_meetings(a.root))

    p = sub.add_parser("longform")
    common(p)
    p.add_argument("--models", nargs="+", required=True)
    p.set_defaults(fn=cmd_longform)

    p = sub.add_parser("offline")
    common(p)
    p.add_argument("--models", nargs="+", required=True)
    p.add_argument("--langs", nargs="+", default=["ru", "en", "de"])
    p.add_argument("--n", type=int, default=100)
    p.set_defaults(fn=cmd_offline)

    for mode, fn in (("live", cmd_live), ("call", cmd_call)):
        p = sub.add_parser(mode)
        common(p)
        p.add_argument("--model", required=True)
        p.add_argument("--scheme", choices=["window", "vad", "stream"], required=True)
        p.add_argument("--lang", default="ru")
        p.add_argument("--seconds", type=float, default=0, help="only the first N seconds of the long file")
        p.add_argument("--tick", type=float, default=0.2, help="how often audio arrives (vad, stream)")
        p.add_argument("--draft-sec", type=float, default=1.2)
        p.add_argument("--app-python", help="Python of the app (scheme window; default: the repository's .venv)")
        if mode == "call":
            p.add_argument("--queue", help='model of the queue\'s transcription, or "inproc" (window: the app\'s own, same process)')
            p.add_argument("--queue-threads", default="app")
            p.add_argument("--queue-prio", choices=["normal", "below", "idle"], default="normal")
            p.add_argument("--no-video", action="store_true")
            p.add_argument("--warmup", type=float, default=20.0, help="seconds for the queue to load before captions start")
        p.set_defaults(fn=fn)

    p = sub.add_parser("idle")
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--cpus", type=int, default=0)
    p.add_argument("--seconds", type=float, default=120)
    p.add_argument("--no-video", action="store_true")
    p.add_argument("--tag", default="")
    p.set_defaults(fn=cmd_idle)

    p = sub.add_parser("report")
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(fn=cmd_report)

    p = sub.add_parser("worker")
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--job", required=True)
    p.set_defaults(fn=cmd_worker)

    p = sub.add_parser("probe")
    p.add_argument("--stop", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--cpus", type=int, default=0)
    p.set_defaults(fn=lambda a: run_probe(a.stop, a.out, cpus=a.cpus))

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
