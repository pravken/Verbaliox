# Bench tool of 2026-11-15 (bench-report/translation.md). Paths point to the benchmark workspace C:s-llm\mt.
"""chrF++ (sacrebleu) and COMET-22 (Unbabel/wmt22-comet-da) of every WMT output in out/."""
import glob, json, os
import sacrebleu
from comet import download_model, load_from_checkpoint

D = r"C:\vs-llm\mt"
WMT = json.load(open(os.path.join(D, "wmt-sample.json"), encoding="utf-8"))
cm = load_from_checkpoint(download_model("Unbabel/wmt22-comet-da"))
rows = []
for f in sorted(glob.glob(os.path.join(D, "out", "*.wmt.cuda.json"))):
    r = json.load(open(f, encoding="utf-8")); items = WMT[r["pair"]]
    hyp = r["hyp"]; ref = [x["ref"] for x in items]; src = [x["src"] for x in items]
    chrf = sacrebleu.corpus_chrf(hyp, [ref], word_order=2).score
    comet = cm.predict([{"src": s, "mt": h, "ref": t} for s, h, t in zip(src, hyp, ref)], batch_size=32, gpus=1, progress_bar=False).system_score
    rows.append({"model": r["model"], "pair": r["pair"], "chrf": round(chrf, 1), "comet": round(comet, 4)})
    print(rows[-1], flush=True)
json.dump(rows, open(os.path.join(D, "scores.json"), "w"), indent=1)
