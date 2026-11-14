"""
Bench of local LLMs for the analysis the app does: the protocol (generate_meeting_summary) and the tasks
(the steps of commitments.extract, without writing to the database), on recordings of a copy of the data.

    set VERBALIOX_DATA_DIR=<copy> & set VERBALIOX_MODELS_DIR=<copy>
    python tools/llm_bench.py --models qwen3.5:4b gemma4:e4b --meetings 84 85 --profile 8gb --out bench.jsonl
    python tools/llm_bench.py ... --cpu            # every layer on the processor (num_gpu 0)
    python tools/llm_bench.py ... --ctx 32768      # a longer context (the long recording is read in one pass)

The Ollama address is the one in the copy's Settings. Before each model every model is unloaded
(app.bench.clean_slate); the model is loaded once with a short prompt first (warm-up: the disk cache and
the GPU kernels), then measured. One JSON line per model x recording is appended to --out: timings and
Ollama's own counters of every request, the peak video memory of the card and the processor memory of
Ollama, how much of the model was on the GPU, the protocol, the tasks, and checks of the answers (JSON,
<think>, language, «[?]» points). The profile itself (a smaller card) is made outside, by
tools/vram_ballast.py.
"""

import argparse
import json
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

# What every request sent to Ollama and got back: the counters of its answer, the raw text (with any
# <think> block) and the options that were forced
_calls: List[Dict[str, Any]] = []
_force_options: Dict[str, Any] = {}
_orig_post = httpx.Client.post


def _post(self, url, *a, **kw):
    path = str(url)
    if path.endswith(("/api/chat", "/api/generate")) and isinstance(kw.get("json"), dict) and kw["json"].get("model"):
        body = dict(kw["json"])
        if _force_options and (body.get("messages") or body.get("prompt")):
            body["options"] = {**(body.get("options") or {}), **_force_options}
        kw["json"] = body
        t0 = time.perf_counter()
        resp = _orig_post(self, url, *a, **kw)
        wall = time.perf_counter() - t0
        try:
            data = resp.json()
        except Exception:
            data = {}
        if body.get("messages") or body.get("prompt"):
            msg = data.get("message") or {}
            _calls.append({
                "kind": "chat" if path.endswith("/api/chat") else "generate",
                "wall": round(wall, 2),
                "format": bool(body.get("format")),
                "num_ctx": (body.get("options") or {}).get("num_ctx"),
                "load": (data.get("load_duration") or 0) / 1e9,
                "prompt_tokens": data.get("prompt_eval_count") or 0,
                "prompt_sec": (data.get("prompt_eval_duration") or 0) / 1e9,
                "gen_tokens": data.get("eval_count") or 0,
                "gen_sec": (data.get("eval_duration") or 0) / 1e9,
                "total": (data.get("total_duration") or 0) / 1e9,
                "raw": str(msg.get("content") or data.get("response") or ""),
                "thinking": str(msg.get("thinking") or data.get("thinking") or ""),
                "done_reason": data.get("done_reason"),
            })
        return resp
    return _orig_post(self, url, *a, **kw)


httpx.Client.post = _post


class Peak(threading.Thread):
    """The peak used video memory of the card (nvidia-smi) and resident memory of Ollama's processes."""

    def __init__(self):
        super().__init__(daemon=True)
        self.vram = self.ram = 0.0
        self.stop = False

    def run(self):
        while not self.stop:
            try:
                out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                                     capture_output=True, text=True, timeout=10).stdout
                self.vram = max(self.vram, int(out.split()[0]) / 1024)
                # Working set of every ollama.exe (the server and its model runner), without psutil
                rows = subprocess.run(["tasklist", "/FI", "IMAGENAME eq ollama.exe", "/FO", "CSV", "/NH"],
                                      capture_output=True, text=True, timeout=10).stdout
                kb = sum(int(re.sub(r"\D", "", r.split('","')[-1]) or 0) for r in rows.splitlines() if r.startswith('"'))
                self.ram = max(self.ram, kb / 2**20)
            except Exception:
                pass
            time.sleep(0.5)


def _ps(base: str) -> List[Dict[str, Any]]:
    try:
        return [{"name": m["name"], "size_gb": round(m["size"] / 2**30, 2),
                 "vram_gb": round(m.get("size_vram", 0) / 2**30, 2),
                 "gpu_share": round(m.get("size_vram", 0) / m["size"], 3) if m.get("size") else 0,
                 "context": m.get("context_length")}
                for m in httpx.get(f"{base}/api/ps", timeout=10).json().get("models", [])]
    except Exception:
        return []


TASK_SCHEMA = {
    "type": "object",
    "properties": {"tasks": {"type": "array", "items": {
        "type": "object",
        "properties": {"who": {"type": "string"}, "what": {"type": "string"}, "due": {"type": "string"},
                       "quote": {"type": "string"}},
        "required": ["who", "what", "due", "quote"]}}},
    "required": ["tasks"],
}


def _tasks(m: Dict[str, Any], mid: str) -> Dict[str, Any]:
    """commitments.extract up to the database: the same prompt, parts, checks and second look."""
    from app import commitments as c
    from app.llm import target
    from app.ollama_client import build_transcript_lines

    llm = target(mid, local_only=True)
    lines = build_transcript_lines(m["segments"], m.get("speakers") or {})
    try:
        from app.people import fix_name_typos, meeting_roster

        roster = meeting_roster(m)
    except Exception:
        roster, fix_name_typos = [], None
    head = ("Участники встречи (имена и фамилии написаны верно, пиши их так же): " + "; ".join(roster) + "\n\n") if roster else ""
    found, answers = [], []
    parts = c.transcript_parts(lines, max(8000, llm.max_chars - 3000))
    for part in parts:
        ans = llm.chat(c._SYSTEM, head + "Расшифровка:\n" + part)
        answers.append(ans)
        found += c.parse_answer(ans)
    raw_found = len(found)
    supported = [x for x in found if c.supported(x, m)]
    items = c.prune(supported)
    items = c.verify(items, m, llm)
    # JSON objects the model wrote that do not parse (the app drops them silently)
    objs = [o for a in answers for o in re.findall(r"\{[^{}]*\}", re.sub(r"```(?:json)?", "", a))]
    bad = 0
    for o in objs:
        try:
            json.loads(o)
        except ValueError:
            bad += 1
    return {"parts": len(parts), "raw": raw_found, "supported": len(supported), "items": items,
            "json_objects": len(objs), "json_bad": bad}


def _schema_check(m: Dict[str, Any], mid: str, base: str) -> Dict[str, Any]:
    """The same task prompt once with Ollama's `format` (a JSON schema): is the answer valid JSON."""
    from app import commitments as c
    from app.llm_text import thinking_off
    from app.ollama_client import build_transcript_lines, llm_num_ctx

    lines = build_transcript_lines(m["segments"], m.get("speakers") or {})
    part = c.transcript_parts(lines, 12000)[0]
    body = {"model": mid, "stream": False, "format": TASK_SCHEMA,
            "messages": [{"role": "system", "content": c._SYSTEM},
                         {"role": "user", "content": "Расшифровка:\n" + part + "\n\nОтветь JSON-объектом {\"tasks\": [...]}."}],
            "options": {"temperature": 0.1, "num_ctx": llm_num_ctx(), "num_predict": 3072}}
    body.update(thinking_off(mid))
    with httpx.Client(timeout=900.0) as client:
        resp = client.post(f"{base}/api/chat", json=body)
    raw = ((resp.json().get("message") or {}).get("content") or "") if resp.status_code == 200 else ""
    try:
        data = json.loads(raw)
        ok = isinstance(data, dict) and isinstance(data.get("tasks"), list) and all(
            isinstance(t, dict) and {"who", "what"} <= set(t) for t in data["tasks"])
        n = len(data.get("tasks") or []) if ok else 0
    except ValueError:
        ok, n = False, 0
    return {"valid": ok, "tasks": n, "status": resp.status_code, "error": "" if resp.status_code == 200 else resp.text[:200]}


def run(args) -> None:
    from app import bench
    from app.asr_onnx import guess_language
    from app.database import get_meeting
    from app.grounding import UNVERIFIED_MARK, ground_summary
    from app import ollama_client
    from app.ollama_client import generate_meeting_summary
    from app.vram import _ollama_base

    # The context as asked, not as the card would choose (a longer context reads a longer recording
    # in one pass: the same share of the context as at 16k)
    ollama_client.CONTEXT_SCALE = args.ctx / ollama_client.LLM_NUM_CTX
    if args.cpu:
        _force_options["num_gpu"] = 0
    if args.max_answer:
        ollama_client.LLM_MAX_ANSWER_TOKENS = args.max_answer
    if args.num_gpu is not None:
        _force_options["num_gpu"] = args.num_gpu
    base = _ollama_base()
    out = Path(args.out)
    for mid in args.models:
        bench._ollama_unload_all()
        t0 = time.perf_counter()
        opts = {"num_ctx": ollama_client.llm_num_ctx(), **_force_options}
        try:
            with httpx.Client(timeout=1800.0) as client:
                w = client.post(f"{base}/api/generate", json={"model": mid, "prompt": "Скажи одно слово: готово.",
                                                              "stream": False, "keep_alive": "30m", "options": opts,
                                                              "think": False} if "gpt-oss" not in mid else
                                {"model": mid, "prompt": "Say one word: ready.", "stream": False, "keep_alive": "30m",
                                 "options": opts})
                w.raise_for_status()
        except Exception as e:
            _append(out, {"model": mid, "profile": args.profile, "error": f"load: {e}"[:300]})
            continue
        warm = time.perf_counter() - t0
        ps_loaded = _ps(base)
        for meeting_id in args.meetings:
            m = get_meeting(meeting_id)
            _calls.clear()
            peak = Peak()
            peak.start()
            rec: Dict[str, Any] = {"model": mid, "profile": args.profile, "think_off": bool(getattr(args, "think_off", False)), "num_gpu": args.num_gpu, "max_answer": args.max_answer, "ctx": ollama_client.llm_num_ctx(),
                                   "cpu": args.cpu, "meeting": meeting_id, "warm_load_sec": round(warm, 1),
                                   "transcript_chars": sum(len(str(s.get("text") or "")) for s in m["segments"]),
                                   "duration_min": round(float(m.get("duration") or 0) / 60, 1)}
            try:
                t = time.perf_counter()
                md = generate_meeting_summary(m["segments"], m.get("speakers") or {}, "protocol", model_name=mid,
                                              answer_lang=bench._answer_lang(m), local_only=True)
                rec["protocol_sec"] = round(time.perf_counter() - t, 1)
                proto_calls = len(_calls)
                ps_during = _ps(base)
                grounded = ground_summary(md, m["segments"], m.get("speakers") or {})
                points = [ln for ln in grounded.splitlines() if re.match(r"\s*(?:[-*+]|\d+[.)])\s+\S", ln)]
                rec.update(protocol=grounded, points=len(points),
                           unverified=sum(1 for ln in points if UNVERIFIED_MARK in ln),
                           protocol_lang=guess_language(md[:20000]), answer_lang=bench._answer_lang(m))
                if not args.no_tasks:
                    t = time.perf_counter()
                    tk = _tasks(m, mid)
                    rec["tasks_sec"] = round(time.perf_counter() - t, 1)
                    rec["tasks"] = tk.pop("items")
                    rec["tasks_stats"] = tk
                rec["ps"] = ps_during or ps_loaded
                calls = list(_calls)
                rec["requests"] = len(calls)
                rec["protocol_requests"] = proto_calls
                rec["think_leak"] = sum(1 for c in calls if "<think>" in c["raw"].lower() or c["thinking"])
                rec["truncated"] = sum(1 for c in calls if c["done_reason"] == "length")
                pt, ps_ = sum(c["prompt_tokens"] for c in calls), sum(c["prompt_sec"] for c in calls)
                gt, gs = sum(c["gen_tokens"] for c in calls), sum(c["gen_sec"] for c in calls)
                rec.update(prompt_tokens=pt, prefill_tps=round(pt / ps_, 1) if ps_ else 0,
                           gen_tokens=gt, gen_tps=round(gt / gs, 1) if gs else 0,
                           first_ttft_sec=round(calls[0]["load"] + calls[0]["prompt_sec"], 2) if calls else None,
                           max_prompt_tokens=max((c["prompt_tokens"] for c in calls), default=0))
                rec["calls"] = [{k: v for k, v in c.items() if k not in ("raw", "thinking")} for c in calls]
                if args.schema:
                    rec["schema"] = _schema_check(m, mid, base)
            except Exception as e:  # noqa: BLE001
                import traceback

                traceback.print_exc()
                rec["error"] = f"{type(e).__name__}: {e}"[:400]
            peak.stop = True
            rec.update(peak_vram_gb=round(peak.vram, 2), peak_ollama_ram_gb=round(peak.ram, 2))
            _append(out, rec)
            print(json.dumps({k: rec.get(k) for k in ("model", "profile", "meeting", "protocol_sec", "tasks_sec",
                                                      "prefill_tps", "gen_tps", "peak_vram_gb", "error")},
                             ensure_ascii=False), flush=True)
    bench._ollama_unload_all()


def _append(path: Path, rec: Dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", nargs="+", required=True)
    ap.add_argument("--meetings", nargs="+", type=int, required=True)
    ap.add_argument("--profile", default="24gb", help="a label for the report (the ballast makes the profile)")
    ap.add_argument("--ctx", type=int, default=16384)
    ap.add_argument("--cpu", action="store_true", help="num_gpu 0: every layer on the processor")
    ap.add_argument("--num-gpu", type=int, default=None,
                    help="layers on the GPU (Ollama num_gpu): WDDM pages a ballast out to system RAM when a model does "
                         "not fit, so a model larger than the card is split by hand as Ollama would split it there")
    ap.add_argument("--max-answer", type=int, default=None, help="LLM_MAX_ANSWER_TOKENS for this run (num_predict)")
    ap.add_argument("--no-tasks", action="store_true", help="the protocol only")
    ap.add_argument("--schema", action="store_true", help="also one task request with a JSON schema in `format`")
    ap.add_argument("--think-off", action="store_true",
                    help="turn thinking off by the model's capabilities (/api/show), not by its name prefix")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    if args.think_off:
        _think_off_by_capabilities()
    run(args)


def _think_off_by_capabilities() -> None:
    """Replaces app.llm_text.thinking_off for this run: every model whose Ollama capabilities include
    "thinking" gets think=false; gpt-oss cannot turn it off and gets the lowest level instead."""
    from app import llm_text
    from app.vram import _ollama_base
    caps: Dict[str, List[str]] = {}

    def thinking_off(model):
        name = model or ""
        if name not in caps:
            try:
                r = _orig_post(httpx.Client(timeout=30), f"{_ollama_base()}/api/show", json={"model": name})
                caps[name] = list(r.json().get("capabilities") or [])
            except Exception:
                caps[name] = []
        if "thinking" not in caps[name]:
            return {}
        return {"think": "low"} if name.lower().startswith("gpt-oss") else {"think": False}

    llm_text.thinking_off = thinking_off


if __name__ == "__main__":
    main()
