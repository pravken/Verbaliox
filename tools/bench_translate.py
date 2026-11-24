"""
Bench of translation models for live captions, en->ru and ru->en: quality (chrF++, COMET if installed),
time per line (median and 90th percentile) and memory of each model.

    .venv\\Scripts\\python tools\\bench_translate.py --out bench-out
    .venv\\Scripts\\python tools\\bench_translate.py --out bench-out --n 5                  # a quick check
    .venv\\Scripts\\python tools\\bench_translate.py --out bench-out --models gemma4:e2b opus-mt
    .venv\\Scripts\\python tools\\bench_translate.py --out bench-out --models translategemma:12b#40
    <venv with unbabel-comet>\\Scripts\\python tools\\bench_translate.py --rescore bench-out\\results.json --comet

Models (--models, default: gemma4:e2b gemma4:e4b translategemma:4b opus-mt):
  * an Ollama name (gemma4:e2b, translategemma:4b, hf.co/tencent/Hy-MT3-1.8B-GGUF:Q4_K_M ...). General models
    go through the code of the live captions (app.live_translate.LiveTranslator._translate_clean: the same
    prompt, options, clean-up and retries). TranslateGemma and Hy-MT get the prompt from their model card
    (one user message); add "@app" to the name to send them the captions' prompt instead.
  * "opus-mt": Helsinki-NLP/opus-mt-en-ru and opus-mt-ru-en run by CTranslate2 (int8; on the video card
    when CTranslate2 sees CUDA). Converted once from Hugging Face into the cache folder (needs torch,
    transformers and sentencepiece: all are in the app's venv).
  * "#N" after a name measures that model on the first N lines only (a large model on a slow PC); the table
    then also gives every model's chrF++ on those same N lines.

Data: WMT24++ (google/wmt24pp, Apache-2.0), the en-ru_RU file: lines of 5-30 words, mostly social posts,
literary and news text, picked evenly with a fixed seed. ru->en uses the same pairs reversed (the Russian
side is a translation itself), so that direction is somewhat easier than real Russian speech.

Each line is translated alone, as the captions do; the model is loaded with one short request first (not
timed), and unloaded when its turn is over. Times are of this PC under its current load: compare models of
one run with each other, not with another PC.

Nothing of the user's data is read or written: the app's data and models folders point to an empty
temporary folder while the script runs, and Ollama is only asked (its address: --ollama, default
http://127.0.0.1:11434; the app or `ollama serve` must be running). Downloads (the test set, Opus-MT) go to
--cache (default: %TEMP%\\verbaliox-bench-translate). Output: --out\\results.json (every translation, the
scores and the settings) and --out\\results.md (the table).
"""

import argparse
import json
import os
import random
import shutil
import statistics
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]

DATASET = "google/wmt24pp"
DATASET_FILE = "en-ru_RU.jsonl"
DATASET_URL = f"https://huggingface.co/datasets/{DATASET}/resolve/main/{DATASET_FILE}"
DEFAULT_MODELS = ["gemma4:e2b", "gemma4:e4b", "translategemma:4b", "opus-mt"]
OPUS = {("en", "ru"): "Helsinki-NLP/opus-mt-en-ru", ("ru", "en"): "Helsinki-NLP/opus-mt-ru-en"}
DIRECTIONS = [("en", "ru"), ("ru", "en")]
LANG_NAMES = {"en": "English", "ru": "Russian"}
# Share of the sample by WMT24++ domain (its "speech" lines are long paragraphs: few pass 5-30 words)
DOMAIN_SHARE = {"speech": 0.03, "news": 0.20, "literary": 0.22, "social": 0.55}
SEED = 2026

# Licences as stated on the model cards; "check" = not plainly free for commercial use: ask before adopting
LICENSES = [
    ("gemma4", "Apache-2.0", "ok"),
    ("translategemma", "Gemma Terms of Use (own terms, use restrictions)", "check"),
    ("hy-mt1.5", "Tencent HY Community License (excludes EU, UK, South Korea)", "no"),
    ("hy-mt2", "Apache-2.0", "ok"),
    ("hy-mt3", "Apache-2.0", "ok"),
    ("qwen3", "Apache-2.0", "ok"),
    ("opus-mt", "Apache-2.0 (en-ru) / CC-BY-4.0 (ru-en)", "ok"),
]


def license_of(model: str) -> Tuple[str, str]:
    name = model.lower().rsplit("/", 1)[-1]
    for prefix, lic, verdict in LICENSES:
        if name.startswith(prefix):
            return lic, verdict
    return "unknown: see the model card", "check"


def say(msg: str) -> None:
    print(msg, flush=True)


# ---------------------------------------------------------------- data

def load_sample(cache: Path, n: int) -> List[Dict[str, Any]]:
    import httpx

    path = cache / DATASET_FILE
    if not path.exists():
        say(f"Downloading {DATASET}/{DATASET_FILE} ...")
        cache.mkdir(parents=True, exist_ok=True)
        with httpx.Client(timeout=120.0, follow_redirects=True) as c:
            r = c.get(DATASET_URL)
            r.raise_for_status()
        tmp = path.with_suffix(".part")
        tmp.write_bytes(r.content)
        tmp.replace(path)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    ok = [r for r in rows if not r.get("is_bad_source") and r.get("domain") in DOMAIN_SHARE
          and 5 <= len(r["source"].split()) <= 30 and "\n" not in r["source"] + r["target"]]
    by_domain: Dict[str, List[Dict[str, Any]]] = {d: [r for r in ok if r["domain"] == d] for d in DOMAIN_SHARE}
    want = {d: min(len(by_domain[d]), int(round(n * share))) for d, share in DOMAIN_SHARE.items() if d != "social"}
    want["social"] = min(len(by_domain["social"]), n - sum(want.values()))
    picked: List[Dict[str, Any]] = []
    for d, k in want.items():
        pool = by_domain[d]
        picked += [pool[int(i * len(pool) / k)] for i in range(k)] if k > 0 else []
    random.Random(SEED).shuffle(picked)  # any prefix (a model run on the first N lines) is a fair sample too
    return [{"id": r["segment_id"], "domain": r["domain"], "en": r["source"], "ru": r["target"]} for r in picked[:n]]


# ---------------------------------------------------------------- scores

def _char_ngrams(text: str, n: int) -> Counter:
    s = "".join(text.split())
    return Counter(s[i:i + n] for i in range(len(s) - n + 1))


_PUNCT_CHARS = set('!"#$%&\'()*+,-./:;<=>?@[\\]^_`{|}~')


def _words(text: str) -> List[str]:
    """Words with leading and trailing punctuation as separate tokens, as sacrebleu's chrF++ does."""
    out: List[str] = []
    for w in text.split():
        if len(w) == 1:
            out.append(w)
            continue
        if w[-1] in _PUNCT_CHARS:
            out += [w[:-1], w[-1]]
        elif w[0] in _PUNCT_CHARS:
            out += [w[0], w[1:]]
        else:
            out.append(w)
    return out


def _word_ngrams(words: List[str], n: int) -> Counter:
    return Counter(tuple(words[i:i + n]) for i in range(len(words) - n + 1))


def chrf_pp(hyps: List[str], refs: List[str]) -> float:
    """Corpus chrF++ (character 6-grams, word 2-grams, beta 2): sacrebleu when installed, else the same
    computation here (they agree to 0.1)."""
    try:
        from sacrebleu.metrics import CHRF

        return round(CHRF(word_order=2).corpus_score(hyps, [refs]).score, 2)
    except ImportError:
        pass
    stats = [[0, 0, 0] for _ in range(8)]  # per order: hyp n-grams, ref n-grams, matches
    for h, r in zip(hyps, refs):
        for n in range(1, 7):
            hc, rc = _char_ngrams(h, n), _char_ngrams(r, n)
            st = stats[n - 1]
            st[0] += sum(hc.values()); st[1] += sum(rc.values()); st[2] += sum((hc & rc).values())
        hw, rw = _words(h), _words(r)
        for n in range(1, 3):
            hc, rc = _word_ngrams(hw, n), _word_ngrams(rw, n)
            st = stats[5 + n]
            st[0] += sum(hc.values()); st[1] += sum(rc.values()); st[2] += sum((hc & rc).values())
    beta2, orders, prec_sum, rec_sum = 4.0, 0, 0.0, 0.0
    for n_hyp, n_ref, match in stats:  # sacrebleu's default: average over the orders both sides have
        if n_hyp and n_ref:
            prec_sum += match / n_hyp
            rec_sum += match / n_ref
            orders += 1
    if not orders or not prec_sum + rec_sum:
        return 0.0
    prec, rec = prec_sum / orders, rec_sum / orders
    return round(100 * (1 + beta2) * prec * rec / (beta2 * prec + rec), 2)


def comet_scores(triples: List[Dict[str, str]]) -> Optional[List[float]]:
    """COMET-22 per line, or None when unbabel-comet is not installed (it is not in the app's venv)."""
    try:
        from comet import download_model, load_from_checkpoint
    except ImportError:
        return None
    global _comet_model
    if _comet_model is None:
        _comet_model = load_from_checkpoint(download_model("Unbabel/wmt22-comet-da"))
    try:
        import torch

        gpus = 1 if torch.cuda.is_available() else 0
    except ImportError:
        gpus = 0
    out = _comet_model.predict(triples, batch_size=16, gpus=gpus, progress_bar=False)
    return [float(s) for s in out.scores]


_comet_model = None


# ---------------------------------------------------------------- Ollama

class Ollama:
    def __init__(self, base: str):
        import httpx

        self.base = base.replace("localhost", "127.0.0.1").rstrip("/")
        self.http = httpx.Client(timeout=300.0)

    def version(self) -> Optional[str]:
        try:
            return self.http.get(f"{self.base}/api/version", timeout=5.0).json().get("version")
        except Exception:
            return None

    def installed(self) -> Dict[str, Dict[str, Any]]:
        return {m["name"]: m for m in self.http.get(f"{self.base}/api/tags").json().get("models") or []}

    def resolve(self, name: str) -> Optional[str]:
        have = self.installed()
        for cand in (name, name + ":latest"):
            if cand in have:
                return cand
        low = {k.lower(): k for k in have}
        return low.get(name.lower()) or low.get(name.lower() + ":latest")

    def loaded(self, model: str) -> Dict[str, Any]:
        for m in self.http.get(f"{self.base}/api/ps").json().get("models") or []:
            if m.get("name") == model or m.get("model") == model:
                return m
        return {}

    def unload(self, model: str) -> None:
        try:
            self.http.post(f"{self.base}/api/generate", json={"model": model, "keep_alive": 0})
        except Exception:
            pass

    def chat(self, model: str, user: str, options: Dict[str, Any], think: Optional[Dict[str, Any]] = None) -> str:
        payload = {"model": model, "stream": False, "keep_alive": "10m",
                   "messages": [{"role": "user", "content": user}], "options": options}
        payload.update(think or {})
        r = self.http.post(f"{self.base}/api/chat", json=payload)
        if r.status_code >= 400:
            raise RuntimeError(f"Ollama {r.status_code}: {r.text[:300]}")
        return str((r.json().get("message") or {}).get("content") or "")


def translategemma_prompt(text: str, src: str, dst: str) -> str:
    """The format on the TranslateGemma model card: one user message, two blank lines before the text."""
    s, d = LANG_NAMES[src], LANG_NAMES[dst]
    return (f"You are a professional {s} ({src}) to {d} ({dst}) translator. Your goal is to accurately convey "
            f"the meaning and nuances of the original {s} text while adhering to {d} grammar, vocabulary, and "
            f"cultural sensitivities. Produce only the {d} translation, without any additional explanations or "
            f"commentary. Please translate the following {s} text into {d}:\n\n\n{text}")


def hymt_prompt(text: str, src: str, dst: str) -> str:
    """The English prompt on the Hy-MT model card (no system prompt)."""
    return (f"Translate the following text into {LANG_NAMES[dst]}. Note that you should only output the "
            f"translated result without any additional explanation:\n\n{text}")


def app_translator(base: str) -> Callable[[str, str, str, str], str]:
    """The live captions' own translation call, pointed at `base`, with nothing from the app's settings."""
    from app import idle_unload, live_translate

    live_translate._base_url = lambda: base
    idle_unload.ollama_keep_alive = lambda: "10m"

    def run(model: str, text: str, src: str, dst: str) -> str:
        t = live_translate.LiveTranslator.__new__(live_translate.LiveTranslator)
        t._source_lang = lambda: src
        t.target, t.pair, t.speed = dst, [src, dst], "quality"
        t._model, t.model_override = model, None
        t._fallback_model = lambda: None  # in the app: the other of the two modes' models
        return t._translate_clean(text, src, target=dst)

    return run


def native_translator(oll: Ollama, prompt: Callable[[str, str, str], str], options: Dict[str, Any]):
    from app.live_translate import _first_line, collapse_repeats
    from app.llm_text import strip_think

    def run(model: str, text: str, src: str, dst: str) -> str:
        return collapse_repeats(_first_line(strip_think(oll.chat(model, prompt(text, src, dst), options))))

    return run


# ---------------------------------------------------------------- Opus-MT (CTranslate2)

class OpusMT:
    def __init__(self, cache: Path, beam: int):
        import ctranslate2

        self.ct2 = ctranslate2
        self.cuda = ctranslate2.get_cuda_device_count() > 0
        self.device = "cuda" if self.cuda else "cpu"
        self.compute = "int8_float16" if self.cuda else "int8"
        self.cache, self.beam = cache, beam
        self.loaded: Dict[Tuple[str, str], Any] = {}

    def path(self, pair: Tuple[str, str]) -> Path:
        return self.cache / ("ct2-" + OPUS[pair].split("/")[-1] + "-int8")

    def prepare(self, pair: Tuple[str, str]) -> None:
        out = self.path(pair)
        if not (out / "model.bin").exists():
            say(f"Converting {OPUS[pair]} to CTranslate2 int8 ...")
            try:
                from ctranslate2.converters import TransformersConverter
            except ImportError as e:
                raise RuntimeError(f"the converter needs transformers and torch ({e})")
            tmp = out.with_name(out.name + ".part")
            shutil.rmtree(tmp, ignore_errors=True)
            TransformersConverter(OPUS[pair], copy_files=["source.spm", "target.spm"]).convert(
                str(tmp), quantization="int8", force=True)
            tmp.replace(out)
        from transformers import AutoTokenizer

        tok = AutoTokenizer.from_pretrained(OPUS[pair])
        model = self.ct2.Translator(str(out), device=self.device, compute_type=self.compute,
                                    intra_threads=0 if self.cuda else min(8, os.cpu_count() or 4))
        self.loaded[pair] = (tok, model)

    def size_mb(self, pair: Tuple[str, str]) -> int:
        return round(sum(p.stat().st_size for p in self.path(pair).rglob("*") if p.is_file()) / 2**20)

    def translate(self, text: str, src: str, dst: str) -> str:
        tok, model = self.loaded[(src, dst)]
        tokens = tok.convert_ids_to_tokens(tok.encode(text))
        res = model.translate_batch([tokens], beam_size=self.beam, max_decoding_length=256)
        ids = tok.convert_tokens_to_ids(res[0].hypotheses[0])
        return tok.decode(ids, skip_special_tokens=True).strip()

    def free(self) -> None:
        self.loaded.clear()


# ---------------------------------------------------------------- run

def gpu_used_mb() -> Optional[int]:
    """Video memory in use on the first card (all programs), from nvidia-smi; None without one."""
    import subprocess

    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10).stdout
        return int(out.split()[0])
    except Exception:
        return None


def _percentile(xs: List[float], q: float) -> float:
    xs = sorted(xs)
    if not xs:
        return 0.0
    k = (len(xs) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def run_model(spec: str, sample: List[Dict[str, Any]], oll: Optional[Ollama],
              opus: Optional[OpusMT]) -> Dict[str, Any]:
    name, _, limit = spec.partition("#")
    lines = sample[: int(limit)] if limit else sample
    force_app = name.endswith("@app")
    name = name[:-4] if force_app else name
    lic, verdict = license_of(name)
    res: Dict[str, Any] = {"model": spec, "license": lic, "license_verdict": verdict, "n": len(lines), "directions": {}}

    if name == "opus-mt":
        if opus is None:
            return {**res, "error": "CTranslate2 is not installed"}
        res.update(engine=f"CTranslate2 {opus.ct2.__version__} {opus.device} {opus.compute}, beam {opus.beam}")
        translate = lambda m, text, src, dst: opus.translate(text, src, dst)  # noqa: E731
        model_id = None
    else:
        if oll is None:
            return {**res, "error": "Ollama is not answering"}
        model_id = oll.resolve(name)
        if not model_id:
            return {**res, "error": f"not in Ollama: run `ollama pull {name}`"}
        low = name.lower()
        if not force_app and "translategemma" in low:
            prompt = "TranslateGemma card prompt"
            translate = native_translator(oll, translategemma_prompt,
                                          {"temperature": 0.1, "num_ctx": 2048, "num_predict": 200})
        elif not force_app and "hy-mt" in low:
            prompt = "Hy-MT card prompt and sampling"
            translate = native_translator(oll, hymt_prompt, {"temperature": 0.7, "top_p": 0.6, "top_k": 20,
                                                             "repeat_penalty": 1.05, "num_ctx": 2048,
                                                             "num_predict": 200})
        else:
            prompt = "live captions (app.live_translate)"
            translate = app_translator(oll.base)
        tag = oll.installed().get(model_id) or {}
        res.update(engine=f"Ollama {oll.version()}", prompt=prompt, ollama_model=model_id,
                   digest=tag.get("digest", "")[:12], file_mb=round((tag.get("size") or 0) / 2**20),
                   quant=(tag.get("details") or {}).get("quantization_level"))

    for src, dst in DIRECTIONS:
        key = f"{src}-{dst}"
        try:
            if name == "opus-mt":
                opus.prepare((src, dst))
                translate(None, "Hello.", src, dst)  # warm-up
                res.setdefault("memory_mb", {})[key] = opus.size_mb((src, dst))
            else:
                translate(model_id, "Good morning, everyone." if src == "en" else "Всем доброе утро.", src, dst)
                ps = oll.loaded(model_id)
                res["memory_mb"] = round((ps.get("size") or 0) / 2**20)
                res["vram_mb"] = round((ps.get("size_vram") or 0) / 2**20)
                res["gpu_used_mb"] = gpu_used_mb()  # the whole card with this model loaded
        except Exception as e:
            res["directions"][key] = {"error": f"{type(e).__name__}: {e}"[:400]}
            say(f"  {spec} {key}: {res['directions'][key]['error']}")
            continue
        hyps, secs, errors = [], [], 0
        for i, row in enumerate(lines, 1):
            t0 = time.perf_counter()
            try:
                hyp = translate(model_id, row[src], src, dst)
            except Exception as e:
                hyp, errors = "", errors + 1
                say(f"  line {row['id']}: {type(e).__name__}: {str(e)[:200]}")
            secs.append(time.perf_counter() - t0)
            hyps.append(hyp)
            if i % 10 == 0 or i == len(lines):
                say(f"  {spec} {key}: {i}/{len(lines)}, median {statistics.median(secs):.2f} s")
        refs = [row[dst] for row in lines]
        res["directions"][key] = {
            "chrf++": chrf_pp(hyps, refs), "sec_median": round(statistics.median(secs), 3),
            "sec_p90": round(_percentile(secs, 0.9), 3), "errors": errors, "hyps": hyps,
        }
    if name == "opus-mt":
        opus.free()
    elif model_id:
        oll.unload(model_id)
    return res


def add_comet(results: Dict[str, Any]) -> bool:
    sample = results["sample"]
    for r in results["models"]:
        for key, d in r.get("directions", {}).items():
            if "hyps" not in d:
                continue
            src, dst = key.split("-")
            triples = [{"src": row[src], "mt": h, "ref": row[dst]} for row, h in zip(sample, d["hyps"])]
            scores = comet_scores(triples)
            if scores is None:
                return False
            d["comet"] = round(sum(scores) / len(scores), 4)
            d["comet_lines"] = [round(s, 4) for s in scores]
    results["comet"] = "Unbabel/wmt22-comet-da"
    return True


def table(results: Dict[str, Any]) -> str:
    models = results["models"]
    sample = results["sample"]
    common = min((r["n"] for r in models if r.get("directions")), default=len(sample))
    has_comet = any("comet" in d for r in models for d in r.get("directions", {}).values())
    head = ["Model", "Licence", "Lines", "chrF++ en→ru", "chrF++ ru→en"]
    if common < len(sample):
        head += [f"chrF++ en→ru / ru→en on the first {common}"]
    if has_comet:
        head += ["COMET en→ru", "COMET ru→en"]
    head += ["s/line en→ru (median / p90)", "s/line ru→en (median / p90)", "File, MB", "Loaded, MB (of it VRAM)",
             "Card in use, MB"]
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for r in models:
        dirs = r.get("directions", {})
        lic = r["license"] + ("" if r["license_verdict"] == "ok" else " ⚠")

        def cell(key: str, field: str, fmt: str = "{:.1f}") -> str:
            d = dirs.get(key) or {}
            return fmt.format(d[field]) if field in d else ("error" if "error" in d else "—")

        row = [r["model"], lic, str(r["n"]), cell("en-ru", "chrf++"), cell("ru-en", "chrf++")]
        if common < len(sample):
            part = []
            for key in ("en-ru", "ru-en"):
                d = dirs.get(key) or {}
                src, dst = key.split("-")
                part.append(f"{chrf_pp(d['hyps'][:common], [s[dst] for s in sample[:common]]):.1f}" if "hyps" in d else "—")
            row.append(" / ".join(part))
        if has_comet:
            row += [cell("en-ru", "comet", "{:.3f}"), cell("ru-en", "comet", "{:.3f}")]
        for key in ("en-ru", "ru-en"):
            d = dirs.get(key) or {}
            row.append(f"{d['sec_median']:.2f} / {d['sec_p90']:.2f}" if "sec_median" in d else "—")
        mem = r.get("memory_mb")
        if isinstance(mem, dict):  # Opus-MT: one model per direction, loaded whole
            row += [" + ".join(str(v) for v in mem.values()), "—"]
        else:
            row += [str(r.get("file_mb") or "—"), f"{mem} ({r.get('vram_mb', 0)})" if mem else r.get("error", "—")]
        row.append(str(r.get("gpu_used_mb") or "—"))
        out.append("| " + " | ".join(row) + " |")
    return "\n".join(out)


def write_outputs(results: Dict[str, Any], out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    notes = [
        f"# Translation bench, {results['date']}", "",
        f"Data: {DATASET} {DATASET_FILE} (Apache-2.0), {len(results['sample'])} lines of 5-30 words; "
        "ru→en is the same pairs reversed (the Russian side is itself a translation).",
        f"PC: {results['pc']}. Ollama {results.get('ollama_version') or '—'}.", "",
        table(results), "",
        "⚠ — licence not plainly free for commercial use: check before adopting.",
        "File: the model on disk (gemma4 includes its vision and audio parts). Loaded: what Ollama reports for "
        "the model with the captions' context (2048). Card in use: nvidia-smi for the whole card right after "
        "the model was loaded, other programs included.",
    ]
    for r in results["models"]:
        for key, d in r.get("directions", {}).items():
            if "error" in d:
                notes.append(f"- {r['model']} {key}: {d['error']}")
        if r.get("error"):
            notes.append(f"- {r['model']}: {r['error']}")
    (out / "results.md").write_text("\n".join(notes) + "\n", encoding="utf-8")


def pc_info() -> str:
    import platform

    gpu = ""
    try:
        import ctranslate2

        gpu = f", CUDA devices seen by CTranslate2: {ctranslate2.get_cuda_device_count()}"
    except Exception:
        pass
    return f"{platform.system()} {platform.release()}, {platform.processor() or platform.machine()}, {os.cpu_count()} threads{gpu}"


def main(argv: Optional[List[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip(),
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, help="folder for results.json and results.md")
    ap.add_argument("--models", nargs="+", default=DEFAULT_MODELS, help="Ollama names, opus-mt; NAME#N: first N lines")
    ap.add_argument("--n", type=int, default=100, help="lines per direction (default 100)")
    ap.add_argument("--ollama", default="http://127.0.0.1:11434")
    ap.add_argument("--cache", type=Path, default=Path(tempfile.gettempdir()) / "verbaliox-bench-translate")
    ap.add_argument("--beam", type=int, default=1, help="Opus-MT beam size (1: greedy, as for live captions)")
    ap.add_argument("--comet", action="store_true", help="add COMET-22 (needs unbabel-comet in this Python)")
    ap.add_argument("--rescore", type=Path, help="score an earlier results.json again (with --comet) and rewrite it")
    args = ap.parse_args(argv)

    if args.rescore:
        results = json.loads(args.rescore.read_text(encoding="utf-8"))
        if args.comet and not add_comet(results):
            say("unbabel-comet is not installed in this Python: pip install unbabel-comet")
            return 2
        write_outputs(results, args.rescore.parent)
        say(table(results))
        return 0
    if not args.out:
        ap.error("--out is required")

    # The app's data and models folders: an empty temporary one, never the user's
    scratch = Path(tempfile.mkdtemp(prefix="verbaliox-bench-"))
    os.environ["VERBALIOX_DATA_DIR"] = str(scratch / "data")
    os.environ["VERBALIOX_MODELS_DIR"] = str(scratch / "models")
    sys.path.insert(0, str(ROOT))
    try:
        from app import paths

        assert paths.DATA_DIR == (scratch / "data").resolve(), paths.DATA_DIR
        sample = load_sample(args.cache, args.n)
        say(f"{len(sample)} lines: {dict(Counter(r['domain'] for r in sample))}")
        oll: Optional[Ollama] = Ollama(args.ollama)
        ollama_version = oll.version()
        if not ollama_version:
            say(f"Ollama does not answer at {args.ollama}: start Verbaliox or `ollama serve`; Ollama models are skipped")
            oll = None
        opus = None
        if "opus-mt" in [m.partition("#")[0] for m in args.models]:
            os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
            try:
                opus = OpusMT(args.cache, args.beam)
            except ImportError:
                say("CTranslate2 is not installed in this Python: Opus-MT is skipped")
        results: Dict[str, Any] = {
            "date": time.strftime("%Y-%m-%d %H:%M"), "pc": pc_info(), "ollama_version": ollama_version,
            "dataset": f"{DATASET} {DATASET_FILE}", "sample": sample, "models": [],
        }
        for spec in args.models:
            say(f"== {spec}")
            r = run_model(spec, sample, oll, opus)
            if r.get("error"):
                say(f"  skipped: {r['error']}")
            results["models"].append(r)
            write_outputs(results, args.out)  # what is done survives an interrupted run
        if args.comet and not add_comet(results):
            say("COMET skipped: unbabel-comet is not installed in this Python (see --rescore)")
        write_outputs(results, args.out)
        say("")
        say(table(results))
        say(f"\nWritten: {args.out / 'results.json'}, {args.out / 'results.md'}")
        return 0
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
