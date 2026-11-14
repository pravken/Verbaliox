# Bench tool of 2026-11-14 (bench-report/llm-profiles.md, embeddings.md, diarization.md). Paths point to the
# benchmark workspace C:s-llm (data copy, separate Ollama, downloads); adjust them to rerun.
"""Scores the tasks found by each benchmark run against the reference (bench-report/llm-reference + local refs).

A judge model matches every found task to at most one reference task (same person or role and the same action,
wording may differ). Recall = matched reference tasks / reference tasks; precision = found tasks matched / found.
Results are cached per (model, profile, meeting) in judge-cache.jsonl, so a rerun only judges new runs.
"""
import glob, json, os, sys, time, httpx

JUDGE = os.environ.get("JUDGE", "qwen3.6:35b-a3b")
URL = "http://127.0.0.1:11435/api/chat"
REFS = {}
for p in glob.glob(r"D:\Projects\Antigravity\VerbaScribe-pc\bench-report\llm-reference\*.json") + glob.glob(r"C:\vs-llm\reference\*.json"):
    r = json.load(open(p, encoding="utf-8"))
    REFS[r["meeting_id"]] = r
CACHE = r"C:\vs-llm\results\judge-cache.jsonl"
cache = {}
if os.path.exists(CACHE):
    for l in open(CACHE, encoding="utf-8"):
        x = json.loads(l); cache[x["key"]] = x

SYSTEM = (
    "You compare tasks extracted from a meeting transcript by a program with a reference list made by a human. "
    "For every found task decide which reference task it is the same as: the same action (wording, language and "
    "detail may differ) and a compatible person or role (a speaker label like 'Участник 2' may stand for a named "
    "person; an empty reference 'who' accepts anyone). A found task that only restates a fact, an opinion or "
    "something already done is not a match. Each reference task may be matched by several found tasks. "
    "Answer only JSON: {\"matches\": [{\"found\": <found number>, \"ref\": <reference number or 0 if none>}]} with one "
    "entry per found task."
)
SCHEMA = {"type": "object", "properties": {"matches": {"type": "array", "items": {"type": "object", "properties": {
    "found": {"type": "integer"}, "ref": {"type": "integer"}}, "required": ["found", "ref"]}}}, "required": ["matches"]}


def judge(ref_tasks, found):
    refs = "\n".join(f"{i}. who: {t['who'] or '—'}; what: {t['what']}; due: {t['due'] or '—'}" for i, t in enumerate(ref_tasks, 1))
    fnd = "\n".join(f"{i}. who: {t.get('who') or '—'}; to: {t.get('to') or '—'}; what: {t.get('what')}; due: {t.get('due') or '—'}; "
                    f"quote: {(t.get('quote') or '')[:200]}" for i, t in enumerate(found, 1))
    body = {"model": JUDGE, "stream": False, "think": False, "format": SCHEMA, "keep_alive": "30m",
            "options": {"temperature": 0, "num_ctx": 16384},
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": f"Reference tasks:\n{refs}\n\nFound tasks:\n{fnd}"}]}
    r = httpx.post(URL, json=body, timeout=900).json()
    m = json.loads(r["message"]["content"])["matches"]
    return {int(x["found"]): int(x["ref"]) for x in m if 1 <= int(x["found"]) <= len(found)}


def main():
    files = sys.argv[1:] or sorted(glob.glob(r"C:\vs-llm\results\p*.jsonl"))
    out = open(CACHE, "a", encoding="utf-8")
    for f in files:
        prof = os.path.basename(f)[:-6]
        for l in open(f, encoding="utf-8"):
            r = json.loads(l)
            mid = r["meeting"]
            if mid not in REFS or r.get("error"):
                continue
            key = f"{prof}|{r['model']}|{mid}|{r['ctx']}"
            if key in cache:
                continue
            ref_tasks, found = REFS[mid]["tasks"], r.get("tasks") or []
            t0 = time.time()
            m = judge(ref_tasks, found) if (ref_tasks and found) else {}
            hit_refs = {v for v in m.values() if 1 <= v <= len(ref_tasks)}
            rec = {"key": key, "profile": prof, "model": r["model"], "meeting": mid, "ref_n": len(ref_tasks),
                   "found_n": len(found), "matched_found": sum(1 for v in m.values() if 1 <= v <= len(ref_tasks)),
                   "matched_refs": len(hit_refs), "map": m, "judge_sec": round(time.time() - t0, 1)}
            cache[key] = rec
            out.write(json.dumps(rec, ensure_ascii=False) + "\n"); out.flush()
            print(key, rec["ref_n"], rec["found_n"], rec["matched_refs"], rec["matched_found"], rec["judge_sec"], flush=True)


if __name__ == "__main__":
    main()
