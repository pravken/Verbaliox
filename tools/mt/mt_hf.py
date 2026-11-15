# Bench tool of 2026-11-15 (bench-report/translation.md). Paths point to the benchmark workspace C:s-llm\mt.
"""Dedicated translation models (transformers) en<->ru: WMT20 sample (200 lines) and 40 caption lines per
direction, one line at a time as live captions would (batch 1); latency per line on the GPU, and on the
processor for the captions. Writes out/<model>.<pair>.<set>.<device>.json."""
import json, os, statistics, sys, time
import torch
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

D = r"C:\vs-llm\mt"
WMT = json.load(open(os.path.join(D, "wmt-sample.json"), encoding="utf-8"))
CAP = json.load(open(os.path.join(D, "captions.json"), encoding="utf-8"))
os.makedirs(os.path.join(D, "out"), exist_ok=True)

MODELS = {
    "opus-mt": {"en-ru": ("Helsinki-NLP/opus-mt-en-ru", "bb09c99d"), "ru-en": ("Helsinki-NLP/opus-mt-ru-en", "fbd6dc73")},
    "m2m100-418M": {"*": ("facebook/m2m100_418M", "55c2e61b")},
    "m2m100-1.2B": {"*": ("facebook/m2m100_1.2B", "7b361841")},
    "madlad400-3b": {"*": ("google/madlad400-3b-mt", "fa184c67")},
}


def make(name, pair, device):
    repo, rev = MODELS[name].get(pair) or MODELS[name]["*"]
    tok = AutoTokenizer.from_pretrained(repo, revision=rev)
    dtype = torch.float16 if (device == "cuda" and name != "madlad400-3b") else (torch.bfloat16 if device == "cuda" else torch.float32)
    model = AutoModelForSeq2SeqLM.from_pretrained(repo, revision=rev, dtype=dtype).to(device).eval()
    src, tgt = pair.split("-")

    def tr(text):
        kw = {}
        if name.startswith("m2m100"):
            tok.src_lang = src; kw["forced_bos_token_id"] = tok.get_lang_id(tgt)
        if name == "madlad400-3b":
            text = f"<2{tgt}> {text}"
        enc = tok(text, return_tensors="pt").to(device)
        with torch.inference_mode():
            out = model.generate(**enc, max_new_tokens=256, num_beams=1, **kw)
        return tok.decode(out[0], skip_special_tokens=True)
    return tr, model


def run(name, device, sets):
    for pair in ("en-ru", "ru-en"):
        tr, model = make(name, pair, device)
        tr("warm up" if pair.startswith("en") else "прогрев")
        if device == "cuda": torch.cuda.reset_peak_memory_stats()
        for sname in sets:
            items = WMT[pair] if sname == "wmt" else [{"src": s} for s in CAP[pair]]
            outs, lat = [], []
            for it in items:
                t0 = time.time(); h = tr(it["src"]); lat.append(time.time() - t0); outs.append(h)
            rec = {"model": name, "pair": pair, "set": sname, "device": device, "hyp": outs,
                   "lat_median": round(statistics.median(lat), 3), "lat_p90": round(sorted(lat)[int(len(lat) * 0.9)], 3),
                   "peak_vram_mb": round(torch.cuda.max_memory_allocated() / 2**20) if device == "cuda" else None}
            json.dump(rec, open(os.path.join(D, "out", f"{name}.{pair}.{sname}.{device}.json"), "w", encoding="utf-8"), ensure_ascii=False)
            print(name, pair, sname, device, "median", rec["lat_median"], "p90", rec["lat_p90"], "vram", rec["peak_vram_mb"], flush=True)
        del model; torch.cuda.empty_cache()


if __name__ == "__main__":
    for name in sys.argv[1:]:
        run(name, "cuda", ("wmt", "captions"))
        if name != "madlad400-3b":
            run(name, "cpu", ("captions",))
