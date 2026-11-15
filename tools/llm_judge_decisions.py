# Bench tool of 2026-11-15 (bench-report/analysis-chain.md). Paths point to the benchmark workspace C:\vs-llm
# (a separate Ollama on port 11435); adjust them to rerun.
"""The protocol's decisions that call for an action, and whether a task of the recording covers each.

Reads runs of tools/llm_bench.py --app-flow / --chain. A judge model reads the «Решения» points and the
tasks of a run: for every decision, does it oblige someone to do something concrete after the meeting, and
which task (if any) is that action. Results go to decisions-judge.jsonl next to the runs.
"""
import json, os, re, sys, httpx

JUDGE = os.environ.get("JUDGE", "qwen3.6:35b-a3b")
URL = "http://127.0.0.1:11435/api/chat"
SYSTEM = (
    "You read the decisions of a meeting protocol and the list of tasks found in the same meeting. For every "
    "decision say whether it obliges someone to do something concrete after the meeting (action: true) or is an "
    "agreement, a choice, a rule or a fact that needs no separate follow-up work (action: false). For an action, "
    "give the number of the task that is this action (the same work, the wording may differ), or 0 if no task "
    "covers it. Answer only JSON: {\"decisions\": [{\"n\": <decision number>, \"action\": true|false, \"task\": <task "
    "number or 0>}]} with one entry per decision."
)
SCHEMA = {"type": "object", "properties": {"decisions": {"type": "array", "items": {"type": "object", "properties": {
    "n": {"type": "integer"}, "action": {"type": "boolean"}, "task": {"type": "integer"}},
    "required": ["n", "action", "task"]}}}, "required": ["decisions"]}


def _clean(s):
    return re.sub(r"\s*\[\d{1,2}:\d{2}(?::\d{2})?\]|\s*\[\?\]", "", str(s)).strip()


def judge(decisions, tasks):
    ds = "\n".join(f"{i}. {_clean(d)}" for i, d in enumerate(decisions, 1))
    ts = "\n".join(f"{i}. {t.get('who') or '—'}: {t.get('what')}" for i, t in enumerate(tasks, 1)) or "(no tasks)"
    body = {"model": JUDGE, "stream": False, "think": False, "format": SCHEMA, "keep_alive": "30m",
            "options": {"temperature": 0, "num_ctx": 16384},
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": f"Decisions:\n{ds}\n\nTasks:\n{ts}"}]}
    out = json.loads(httpx.post(URL, json=body, timeout=900).json()["message"]["content"])["decisions"]
    return [x for x in out if 1 <= int(x["n"]) <= len(decisions)]


def main():
    for f in sys.argv[1:]:
        dest = os.path.join(os.path.dirname(f), "decisions-judge.jsonl")
        for line in open(f, encoding="utf-8"):
            r = json.loads(line)
            if r.get("error"):
                continue
            dec = (r.get("after_sync") or {}).get("decisions") or []
            tasks = r.get("tasks") or []
            res = judge(dec, tasks) if dec else []
            actions = [x for x in res if x["action"]]
            rec = {"run": os.path.basename(f)[:-6], "meeting": r["meeting"], "decisions": len(dec),
                   "actions": len(actions), "actions_without_task": sum(1 for x in actions if not 1 <= int(x["task"]) <= len(tasks)),
                   "uncovered": [_clean(dec[int(x["n"]) - 1]) for x in actions if not 1 <= int(x["task"]) <= len(tasks)]}
            with open(dest, "a", encoding="utf-8") as o:
                o.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print(rec["run"], rec["meeting"], rec["decisions"], rec["actions"], rec["actions_without_task"], flush=True)


if __name__ == "__main__":
    main()
