"""
The language model for analysis: overviews, tasks, chapters, questions, titles, Obsidian notes.

It is always the local Ollama: the text of a recording does not leave the computer. The cloud models
of earlier versions were removed; their stored settings and API keys are deleted at start
(app.database.drop_cloud_leftovers).

`target()` returns the configured model; `Target.chat(system, user)` is all the callers use.
"""

from dataclasses import dataclass
from typing import Callable, Dict, Optional


class LlmError(RuntimeError):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


def _settings() -> Dict[str, str]:
    from app.database import get_all_settings

    return get_all_settings()


@dataclass
class Target:
    provider: str          # always "ollama"
    model: str
    max_chars: int         # the transcript that fits one request; a longer one is summarised in parts
    chat_fn: Callable[..., str]

    @property
    def label(self) -> str:
        return self.model

    def chat(self, system: str, user: str, short: bool = False, plain: bool = False) -> str:
        """short: a short answer (a title, a check): the model does not reason first.
        plain: a long answer that needs no reasoning (a retelling): the model does not reason either."""
        if short:
            return self.chat_fn(system, user, short=True)
        return self.chat_fn(system, user, plain=True) if plain else self.chat_fn(system, user)


def target(model: Optional[str] = None, start_ollama: bool = True) -> Target:
    """The Ollama model to use: `model` (an Ollama tag) or the one of the settings.
    Raises LlmError when it cannot be used."""
    settings = _settings()
    if model == "cloud":  # a request of an older page: the local model of the settings
        model = None
    return _ollama_target(model, settings, start_ollama)


def available(settings: Optional[Dict[str, str]] = None) -> bool:
    """Whether analysis can run now without starting anything (for automatic steps after a job)."""
    settings = settings or _settings()
    from app.ollama_client import get_ollama_status

    st = get_ollama_status()
    models = st.get("chat_models", st["models"])
    if st["running"]:
        return bool(models)
    # Ollama stops with the app now (and after its idle time): a stopped Ollama this app can start, with a
    # model on the disk, is ready too. The automatic analysis after a transcription starts it (target());
    # this read «not running» as «no analysis» and the overview stopped being made (reported by the user)
    from app.ollama_client import _ollama_address, find_ollama_executable

    host = _ollama_address((settings.get("ollama_url") or "http://127.0.0.1:11434").replace("localhost", "127.0.0.1"))[0]
    return bool(models) and host == "127.0.0.1" and find_ollama_executable() is not None


def _ollama_target(model: Optional[str], settings: Dict[str, str], start: bool) -> Target:
    from app.ollama_client import _ollama_chat, ensure_ollama_running, get_ollama_status

    base_url = (settings.get("ollama_url") or "http://127.0.0.1:11434").replace("localhost", "127.0.0.1").rstrip("/")
    wanted = model or settings.get("ollama_model") or "gemma4:e2b"
    if start:
        ensure_ollama_running(base_url)  # analysis is an explicit user action (or one they turned on)
    status = get_ollama_status(base_url)
    if not status["running"]:
        raise LlmError(
            "Локальный сервер Ollama не установлен или не запущен. Откройте «Настройки», выберите модель LLM и нажмите "
            "«Скачать»."
        )
    models = status.get("chat_models", status["models"])
    if not models:
        raise LlmError(f"В Ollama пока не скачана ни одна модель. Откройте «Настройки» и нажмите «Скачать» напротив {wanted}.")
    if wanted not in models:
        same = [m for m in models if m.startswith(wanted.split(":")[0])]
        wanted = same[0] if same else models[0]
    from app.ollama_client import single_pass_max_chars

    return Target("ollama", wanted, single_pass_max_chars(),
                  lambda system, user, short=False, plain=False: _ollama_chat(base_url, wanted, system, user, short=short, plain=plain))
