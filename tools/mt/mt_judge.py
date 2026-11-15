# Bench tool of 2026-11-15 (bench-report/translation.md). Paths point to the benchmark workspace C:s-llm\mt.
"""Caption lines have no reference: a judge model (qwen3.6:35b-a3b) scores each translation 1-5 for meaning
(adequacy) and Russian/English quality (fluency), all models' translations of a line shown together, blind
and shuffled, so the scores are comparable."""
import glob, json, os, random
import httpx

D = r"C:\vs-llm\mt"
CAP = json.load(open(os.path.join(D, "captions.json"), encoding="utf-8"))
OUT = {}
for f in glob.glob(os.path.join(D, "out", "*.captions.cuda.json")):
    r = json.load(open(f, encoding="utf-8")); OUT.setdefault(r["pair"], {})[r["model"]] = r["hyp"]
SCHEMA = {"type": "object", "properties": {"scores": {"type": "array", "items": {"type": "object", "properties": {
    "id": {"type": "integer"}, "adequacy": {"type": "integer"}, "fluency": {"type": "integer"}}, "required": ["id", "adequacy", "fluency"]}}},
    "required": ["scores"]}
SYSTEM = ("You rate translations of live speech captions (fragments of continuous speech, recognition errors possible). "
          "For each candidate give adequacy 1-5 (5: the meaning of the source fragment fully and correctly conveyed, nothing "
          "added or invented) and fluency 1-5 (5: natural, grammatical target language). An empty candidate gets 1 and 1. "
          "Answer only JSON with one entry per candidate id.")
random.seed(7)
res = {}
for pair, by_model in OUT.items():
    tgt = "Russian" if pair.endswith("ru") else "English"
    models = sorted(by_model)
    for i, src in enumerate(CAP[pair]):
        order = models[:]; random.shuffle(order)
        cands = "\n".join(f"{k + 1}. {by_model[m][i]}" for k, m in enumerate(order))
        body = {"model": "qwen3.6:35b-a3b", "stream": False, "think": False, "format": SCHEMA, "keep_alive": "30m",
                "options": {"temperature": 0, "num_ctx": 8192},
                "messages": [{"role": "system", "content": SYSTEM},
                             {"role": "user", "content": f"Source ({pair.split('-')[0]}): {src}\nTarget language: {tgt}\nCandidates:\n{cands}"}]}
        d = httpx.post("http://127.0.0.1:11435/api/chat", json=body, timeout=600).json()
        for s in json.loads(d["message"]["content"])["scores"]:
            k = int(s["id"]) - 1
            if 0 <= k < len(order):
                a = res.setdefault(pair, {}).setdefault(order[k], [0, 0, 0]); a[0] += s["adequacy"]; a[1] += s["fluency"]; a[2] += 1
for pair, by in res.items():
    for m, (a, f, n) in sorted(by.items(), key=lambda kv: -kv[1][0] / kv[1][2]):
        print(pair, m.ljust(14), "adequacy", round(a / n, 2), "fluency", round(f / n, 2), "n", n, flush=True)
json.dump(res, open(os.path.join(D, "judge.json"), "w"), indent=1)
