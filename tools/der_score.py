# Bench tool of 2026-11-14 (bench-report/llm-profiles.md, embeddings.md, diarization.md). Paths point to the
# benchmark workspace C:s-llm (data copy, separate Ollama, downloads); adjust them to rerun.
"""DER (collar 0.25 s, overlap scored) and JER of every hypothesis in results/diar-hyp.jsonl against the AMI
only_words RTTM references; also the speaker-count error and the DER parts (missed, false alarm, confusion)."""
import json, collections
from pyannote.core import Annotation, Segment
from pyannote.metrics.diarization import DiarizationErrorRate, JaccardErrorRate


def ref(ami):
    a = Annotation()
    for l in open(rf"C:\vs-llm\ami\{ami}.rttm", encoding="utf-8"):
        p = l.split()
        a[Segment(float(p[3]), float(p[3]) + float(p[4]))] = p[7]
    return a


rows = []
for l in open(r"C:\vs-llm\results\diar-hyp.jsonl", encoding="utf-8"):
    h = json.loads(l)
    R = ref(h["ami"]); H = Annotation()
    for s, e, spk in h["segments"]:
        if e > s: H[Segment(s, e)] = spk
    der = DiarizationErrorRate(collar=0.25, skip_overlap=False)
    d = der(R, H, detailed=True)
    jer = JaccardErrorRate(collar=0.25, skip_overlap=False)(R, H)
    rows.append({"ami": h["ami"], "encoder": h["encoder"], "mode": h["mode"], "sec": h["sec"], "gpu_extra_mb": h.get("gpu_extra_mb"),
                 "der": round(d["diarization error rate"], 3), "missed": round(d["missed detection"] / d["total"], 3),
                 "false_alarm": round(d["false alarm"] / d["total"], 3), "confusion": round(d["confusion"] / d["total"], 3),
                 "jer": round(jer, 3), "speakers": h["speakers"], "ref_speakers": len(R.labels())})
json.dump(rows, open(r"C:\vs-llm\results\diar-scores.json", "w", encoding="utf-8"), indent=1)
g = collections.defaultdict(list)
for r in rows: g[(r["encoder"], r["mode"])].append(r)
print("encoder mode n DER miss FA conf JER count_err sec_per_meeting gpu_MB")
for k, rs in sorted(g.items()):
    n = len(rs); f = lambda key: round(sum(r[key] for r in rs) / n, 3)
    print(k[0].ljust(24), k[1].ljust(8), n, f("der"), f("missed"), f("false_alarm"), f("confusion"), f("jer"),
          round(sum(abs(r["speakers"] - r["ref_speakers"]) for r in rs) / n, 2), f("sec"), max(r["gpu_extra_mb"] or 0 for r in rs))
