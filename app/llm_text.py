"""
Qwen3 and other "thinking" models: Ollama is asked not to think (`think: false`, Ollama 0.9+), and
any <think>…</think> block that still comes back is removed, so answers, titles and translations
never contain the model's reasoning.

Whether a model can think is asked from Ollama itself (`/api/show`, `capabilities` holds "thinking"),
so a model under any name (T-lite, QVikhr from a GGUF) is covered; the name is only a fallback when
Ollama does not answer. Two families are treated otherwise, as measured on meetings
(bench-report/llm-profiles.md):
- gemma4 keeps its thinking for the analysis of a meeting: without it the model found half as
  many tasks (51% -> 26%);
- gpt-oss cannot stop thinking, only think less: `think: "low"`.
"""

import re
import threading
from typing import Any, Dict, Optional

_THINK_RE = re.compile(r"<think>.*?(</think>|$)", re.S | re.I)
_THINKING_FAMILIES = ("qwen3", "deepseek-r1", "qwq", "t-lite", "qvikhr", "magistral")
_KEEP_THINKING = ("gemma4",)
_THINK_LOW = ("gpt-oss",)

_can_think: Dict[str, bool] = {}  # model name -> what Ollama said; asked once per name
_lock = threading.Lock()


def _bare(name: str) -> str:
    """'hf.co/t-tech/T-lite-it-2.1-GGUF:Q4_K_M' -> 't-lite-it-2.1-gguf:q4_k_m'"""
    return name.rsplit("/", 1)[-1]


def _ask_ollama(model: str) -> Optional[bool]:
    try:
        from app.database import get_all_settings

        url = get_all_settings().get("ollama_url")
    except Exception:
        url = None
    base = (url or "http://127.0.0.1:11434").replace("localhost", "127.0.0.1").rstrip("/")
    try:
        import httpx

        r = httpx.post(f"{base}/api/show", json={"model": model}, timeout=3.0)
        if r.status_code != 200:
            return None
        caps = r.json().get("capabilities")
        if not isinstance(caps, list):  # an Ollama older than 0.6 does not say
            return None
        return "thinking" in caps
    except Exception:
        return None


def can_think(model: str) -> bool:
    with _lock:
        if model in _can_think:
            return _can_think[model]
    said = _ask_ollama(model)
    if said is None:  # Ollama not reachable: judge by the name, and ask again next time
        return _bare(model.lower()).startswith(_THINKING_FAMILIES + _THINK_LOW)
    with _lock:
        _can_think[model] = said
    return said


def thinking_off(model: Optional[str], analysis: bool = False) -> Dict[str, Any]:
    """What to add to an Ollama chat request so the model does not spend the answer on reasoning.
    `analysis`: a summary, tasks or an answer about the meeting, where gemma4 keeps its thinking;
    a translation or dubbing line is short and waited for, so there gemma4 does not think either."""
    if not model:
        return {}
    name = _bare(model.lower())
    if analysis and name.startswith(_KEEP_THINKING):
        return {}
    if not can_think(model):
        return {}  # `think` sent to a model that cannot think is refused by some Ollama versions
    if name.startswith(_THINK_LOW):
        return {"think": "low"}
    return {"think": False}


def strip_think(text: str) -> str:
    return _THINK_RE.sub("", text or "").strip()
