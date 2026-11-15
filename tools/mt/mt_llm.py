# Bench tool of 2026-11-15 (bench-report/translation.md). Paths point to the benchmark workspace C:s-llm\mt.
"""The app's own live-caption translation (app.live_translate LiveTranslator._translate_clean) with Ollama models,
one line at a time: WMT20 sample and caption lines, en<->ru; latency per line. VERBALIOX_DATA_DIR = a copy whose
ollama_url points at the bench Ollama. usage: mt_llm.py <model> [cpu]"""
import json, os, statistics, sys, time
sys.path.insert(0, r"D:\src\VerbaScribe-pc")
import httpx
from app import live_translate as lt

D = r"C:\vs-llm\mt"
WMT = json.load(open(os.path.join(D, "wmt-sample.json"), encoding="utf-8"))
CAP = json.load(open(os.path.join(D, "captions.json"), encoding="utf-8"))
model = sys.argv[1]; cpu = len(sys.argv) > 2 and sys.argv[2] == "cpu"
if cpu:  # every layer on the processor
    _orig = httpx.Client.post
    def _post(self, url, *a, **kw):
        if url.endswith("/api/chat") and "json" in kw:
            kw["json"].setdefault("options", {})["num_gpu"] = 0
        return _orig(self, url, *a, **kw)
    httpx.Client.post = _post

T = object.__new__(lt.LiveTranslator)
T.pair = ["ru", "en"]; T.speed = "quality"; T.model_override = model; T._model = model; T._context = []
T._fallback_model = lambda: None
sets = ("captions",) if cpu else ("wmt", "captions")
device = "cpu" if cpu else "cuda"
for pair in ("en-ru", "ru-en"):
    src, tgt = pair.split("-")
    T._source_lang = lambda s=src: s; T.target = tgt
    T._translate_clean("Hello, colleagues." if src == "en" else "Здравствуйте, коллеги.", src, timeout=300, target=tgt)
    for sname in sets:
        items = WMT[pair] if sname == "wmt" else [{"src": s} for s in CAP[pair]]
        outs, lat = [], []
        for it in items:
            t0 = time.time()
            try:
                h = T._translate_clean(it["src"], src, timeout=300, target=tgt)
            except Exception as e:
                h = ""
                print("error", type(e).__name__, str(e)[:100], flush=True)
            lat.append(time.time() - t0); outs.append(h)
        name = model.replace(":", "-") + ("-cpu" if cpu else "")
        rec = {"model": model, "pair": pair, "set": sname, "device": device, "hyp": outs,
               "lat_median": round(statistics.median(lat), 3), "lat_p90": round(sorted(lat)[int(len(lat) * 0.9)], 3)}
        json.dump(rec, open(os.path.join(D, "out", f"{model.replace(':', '-')}.{pair}.{sname}.{device}.json"), "w", encoding="utf-8"), ensure_ascii=False)
        print(model, pair, sname, device, "median", rec["lat_median"], "p90", rec["lat_p90"], flush=True)
