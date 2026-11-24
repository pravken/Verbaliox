"""
Near-real-time translation of live captions (see app/live.py).

One worker thread per caption session talks to Ollama:
  * the model is loaded when the session starts and kept in memory (keep_alive), with the same
    small context every time, so Ollama never reloads it between lines;
  * every final line is a short request of its own (about 0.1-0.3 s on a warm model on a GPU);
  * the draft line (the phrase still being spoken) is translated too, at most every
    DRAFT_INTERVAL_SEC, so the translation follows speech before the phrase is final;
  * a line that failed (Ollama still starting, a timeout) is tried again later instead of being lost.
"""

import re
import threading
import time
import traceback
from typing import Any, Callable, Dict, List, Optional

import httpx

KEEP_ALIVE = "30m"
NUM_CTX = 2048            # short lines: a small context loads and runs faster
DRAFT_INTERVAL_SEC = 1.2  # how often the draft line is translated
MAX_ATTEMPTS = 4

_CJK_RUN = re.compile(r"[\u3000-\u303f\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af\uff00-\uffef]+")

_QUOTES = "\"'`«»“”„‟‘’‚‛‹›〝〞〟＂ "


def _first_line(text: str) -> str:
    """A caption translation is one line; anything after it is the model talking."""
    for line in (text or "").splitlines():
        line = line.strip().strip(_QUOTES).strip()
        if line:
            return line
    return ""


def _degenerate(source: str, tr: str) -> bool:
    """A looping answer: much longer than the line, or a run of words that comes back."""
    if not tr:
        return True
    if len(tr) > 2.2 * len(source) + 20:
        return True
    words = [w.lower().strip(",.!?") for w in tr.split()]
    grams = [" ".join(words[i:i + 3]) for i in range(len(words) - 2)]
    return len(grams) != len(set(grams))


def collapse_repeats(text: str) -> str:
    """'что мы здесь будем что мы здесь будем испытать' -> 'что мы здесь будем испытать':
    a model looping on a fragment repeats a run of words."""
    words = text.split()
    for n in range(6, 1, -1):  # runs of two words or more: "да, да" is fine
        i = 0
        while i + 2 * n <= len(words):
            if [w.lower().strip(",.") for w in words[i:i + n]] == [w.lower().strip(",.") for w in words[i + n:i + 2 * n]]:
                del words[i + n:i + 2 * n]
            else:
                i += 1
    return " ".join(words)


# Serbian is written in Cyrillic and Latin with a one-to-one mapping; models mix them up
_SR_DIGRAPHS = [("Lj", "Љ"), ("LJ", "Љ"), ("lj", "љ"), ("Nj", "Њ"), ("NJ", "Њ"), ("nj", "њ"),
                ("Dž", "Џ"), ("DŽ", "Џ"), ("dž", "џ")]
_SR_LETTERS = dict(zip("ABVGDĐEŽZIJKLMNOPRSTĆUFHCČŠabvgdđežzijklmnoprstćufhcčš",
                       "АБВГДЂЕЖЗИЈКЛМНОПРСТЋУФХЦЧШабвгдђежзијклмнопрстћуфхцчш"))
_SR_BACK = {v: k for k, v in _SR_LETTERS.items()}
_SR_BACK.update({"Љ": "Lj", "љ": "lj", "Њ": "Nj", "њ": "nj", "Џ": "Dž", "џ": "dž"})


def serbian_to_cyrillic(text: str) -> str:
    for lat, cyr in _SR_DIGRAPHS:
        text = text.replace(lat, cyr)
    return "".join(_SR_LETTERS.get(ch, ch) for ch in text)


def serbian_to_latin(text: str) -> str:
    return "".join(_SR_BACK.get(ch, ch) for ch in text)


# The small general model of live captions when no translator (Hy-MT3) is installed. Measured en<->ru
# (bench-report/translation.md): gemma4:e2b is near e4b in quality at ~0.4 s a phrase. Only models free
# for commercial use: qwen2.5:3b (Qwen Research licence), llama3.2 and gemma2 (their own terms) are out.
FAST_MODEL_HINTS = ("gemma4:e2b",)

# Hy-MT translates with the prompt and the sampling of its model card (bench-report/translation-2026-11.md,
# tools/bench_translate.py). Measured with top_p 0.6; the card of Hy-MT3 gives 0.8 (temperature 0.7, top_k 20,
# repetition_penalty 1.05 as here): kept as measured.
HYMT_OPTIONS = {"temperature": 0.7, "top_p": 0.6, "top_k": 20, "repeat_penalty": 1.05, "num_ctx": NUM_CTX,
                "num_predict": 200}


# TranslateGemma: the prompt of its model card, nearly greedy (as measured in tools/bench_translate.py)
TRANSLATEGEMMA_OPTIONS = {"temperature": 0.1, "num_ctx": NUM_CTX, "num_predict": 200}
# A dictation is longer than a caption line: a paragraph or a few
LONG_TEXT_OPTIONS = {"num_ctx": 4096, "num_predict": 1024}


def hymt_prompt(text: str, dst: str) -> str:
    """The English prompt of the Hy-MT model card: one user message, no system prompt, no context lines."""
    return (f"Translate the following text into {dst}. Note that you should only output the "
            f"translated result without any additional explanation:\n\n{text}")


def translategemma_prompt(text: str, src: Optional[str], dst: str) -> str:
    """The format of the TranslateGemma model card (tools/bench_translate.py): one user message, the languages by
    name and code, two blank lines before the text. `src`, `dst`: codes of app/translation.TEXT_LANGUAGES; a source
    that is not known is left out of the sentence."""
    from app.translation import TEXT_LANGUAGES

    d = TEXT_LANGUAGES.get(dst, dst)
    s = TEXT_LANGUAGES.get(src or "")
    if not s:
        return (f"You are a professional translator into {d} ({dst}). Your goal is to accurately convey the meaning "
                f"and nuances of the original text while adhering to {d} grammar, vocabulary, and cultural "
                f"sensitivities. Produce only the {d} translation, without any additional explanations or "
                f"commentary. Please translate the following text into {d}:\n\n\n{text}")
    return (f"You are a professional {s} ({src}) to {d} ({dst}) translator. Your goal is to accurately convey "
            f"the meaning and nuances of the original {s} text while adhering to {d} grammar, vocabulary, and "
            f"cultural sensitivities. Produce only the {d} translation, without any additional explanations or "
            f"commentary. Please translate the following {s} text into {d}:\n\n\n{text}")


def _is_translator(model: Optional[str]) -> bool:
    from app.ollama_client import is_translate_only_model

    return is_translate_only_model(model or "")


def translator_payload(model: str, text: str, src: Optional[str], dst: str, long: bool = False) -> Dict[str, Any]:
    """The request of a translator (Hy-MT, TranslateGemma) with the prompt and the sampling of its model card.
    `src`, `dst`: language codes. `long`: a dictation (paragraphs), not a caption line."""
    from app.ollama_client import is_translategemma
    from app.translation import TEXT_LANGUAGES

    if is_translategemma(model):
        content, options = translategemma_prompt(text, src, dst), dict(TRANSLATEGEMMA_OPTIONS)
    else:
        content, options = hymt_prompt(text, TEXT_LANGUAGES.get(dst, dst)), dict(HYMT_OPTIONS)
    if long:
        options.update(LONG_TEXT_OPTIONS)
    return {"model": model, "stream": False, "messages": [{"role": "user", "content": content}], "options": options}


def translator_chat(model: str, text: str, src: Optional[str], dst: str, timeout: float = 30.0,
                    long: bool = False) -> str:
    """One answer of a translator (a retry samples another one)."""
    from app import idle_unload
    from app.llm_text import strip_think
    from app.ollama_client import raise_for_ollama

    idle_unload.touch(model)
    payload = translator_payload(model, text, src, dst, long=long)
    payload["keep_alive"] = idle_unload.ollama_keep_alive() or KEEP_ALIVE
    with httpx.Client(timeout=timeout) as c:
        r = c.post(f"{_base_url()}/api/chat", json=payload)
        raise_for_ollama(r)
        return strip_think(str((r.json().get("message") or {}).get("content") or "")).strip('"«»`')


def _base_url() -> str:
    from app.database import get_all_settings

    url = get_all_settings().get("ollama_url") or "http://127.0.0.1:11434"
    return url.replace("localhost", "127.0.0.1").rstrip("/")


def installed_models() -> List[str]:
    """The models the captions can translate with (the translators too); a downloaded Hy-MT3 1.8B with its
    broken template is repaired on the way (app/ollama_client.repair_hymt_models)."""
    from app.ollama_client import repair_hymt_models, translate_models

    try:
        with httpx.Client(timeout=2.0) as c:
            names = [m.get("name") for m in c.get(f"{_base_url()}/api/tags").json().get("models") or []]
    except Exception:
        return []
    try:
        names = repair_hymt_models(_base_url(), names)
    except Exception:
        traceback.print_exc()
    return translate_models(names)


# The models chosen in Settings → ИИ-анализ → «Модели перевода» for «Качество» and «Скорость»; empty: «Авто»
CHOICE_KEYS = {"quality": "live_translate_model_quality", "fast": "live_translate_model_fast"}


def choose_models(models: List[str], settings: Dict[str, Any]) -> Dict[str, Any]:
    """{"quality", "fast", "auto": {"quality", "fast"}, "installed"} for the installed `models`. «Авто»:
    «Качество» takes Hy-MT3-7B, else Hy-MT3-1.8B, else the analysis model; «Скорость» takes Hy-MT3-1.8B, else
    gemma4:e2b, else the same as «Качество». A model chosen in the settings comes first while it is installed
    (one that is not, or not listed yet, gives its place to «Авто»)."""
    from app.ollama_client import (HYMT_1_8B, HYMT_7B, _listed, chat_models, translate_model_installed_as,
                                   translate_models)

    models = translate_models(models)
    general = chat_models(models)
    analysis = settings.get("ollama_model") or (general[0] if general else None)
    if analysis and general and analysis not in general:
        same = [m for m in general if m.startswith(analysis.split(":")[0])]
        analysis = same[0] if same else general[0]
    large = translate_model_installed_as(HYMT_7B, models)
    small = translate_model_installed_as(HYMT_1_8B, models)
    auto_quality = large or small or analysis
    auto_fast = small or next((m for m in FAST_MODEL_HINTS if m in models), None) or auto_quality
    out: Dict[str, Any] = {"auto": {"quality": auto_quality, "fast": auto_fast}, "installed": models}
    for kind, key in CHOICE_KEYS.items():
        chosen = str(settings.get(key) or "").strip()
        out[kind] = (_listed(chosen, models) if chosen else None) or out["auto"][kind]
    return out


def model_choices() -> Dict[str, Any]:
    """choose_models for the models Ollama has now. A model chosen in the studio
    (LiveTranslator.model_override) comes before both."""
    from app.database import get_all_settings

    return choose_models(installed_models(), get_all_settings())


def small_chat_model() -> Optional[str]:
    """A small installed model that writes text (not a translator), for short checks; None: the analysis model."""
    return next((m for m in FAST_MODEL_HINTS if m in installed_models()), None)


AUTO = "auto"  # target "auto": a pair of languages, each line goes into the other one (RU ⇄ EN)


def _base(lang: Optional[str]) -> str:
    return (lang or "").split("-")[0].lower()


_EN_WORDS = {"the", "and", "is", "are", "to", "of", "you", "we", "it", "that", "this", "what", "i", "a", "in", "for",
             "on", "with", "do", "not", "be", "have", "can", "so", "but", "they", "was", "will", "yes", "no"}
_NOT_RU = set("іїєґўІЇЄҐЎ")  # Ukrainian and Belarusian letters


def phrase_language(text: str) -> Optional[str]:
    """"ru" or "en" when one phrase is plainly in that language, else None. In a bilingual meeting the
    recognizer gives one language for a whole window; the phrase itself tells which one it is, so a
    Russian phrase is not "translated" into Russian (and AUTO picks the right direction)."""
    letters = [ch for ch in text if ch.isalpha()]
    if len(letters) < 6:
        return None
    cyr = sum(1 for ch in letters if "\u0400" <= ch <= "\u04ff")
    if cyr >= 0.85 * len(letters):
        return None if any(ch in _NOT_RU for ch in text) else "ru"
    if cyr == 0 and all(ch.isascii() for ch in letters):
        words = {w.strip(".,!?;:'\"()").lower() for w in text.split()}
        return "en" if words & _EN_WORDS else None
    return None


class LiveTranslator:
    def __init__(self, get_source_lang: Callable[[], Optional[str]], target: str, speed: str = "quality",
                 pair: Optional[List[str]] = None):
        self._source_lang = get_source_lang
        self.target = target
        self.pair = list(pair or ["ru", "en"])[:2]
        self.speed = speed
        self.error = ""
        self.ready = False
        self._pending: List[Dict[str, Any]] = []   # final lines waiting for a translation
        self._draft_text = ""                      # latest draft line to translate
        self._draft_done_for = ""
        self.draft_translation = ""
        self.draft_target = ""
        self._last_draft_at = 0.0
        self._cond = threading.Condition()
        self._stop = False
        self._model: Optional[str] = None
        self.model_override: Optional[str] = None  # chosen by hand in the studio; None: by speed
        self._context: List[str] = []  # last final lines, given to the model as context
        threading.Thread(target=self._run, daemon=True, name="live_translate").start()

    # ---- from the caption session
    def add_lines(self, lines: List[Dict[str, Any]]) -> None:
        with self._cond:
            for ln in lines:
                ln.setdefault("_attempts", 0)
                self._pending.append(ln)
            self._cond.notify()

    def set_draft(self, text: str) -> None:
        with self._cond:
            self._draft_text = text or ""
            if not self._draft_text:
                self.draft_translation = ""
            self._cond.notify()

    def reset_draft(self) -> None:
        with self._cond:
            self.draft_translation = ""
            self._draft_done_for = ""

    def target_for(self, src_lang: Optional[str]) -> str:
        """The language a line is translated into; in "auto" mode the other language of the pair
        (Russian speech into English and English speech into Russian)."""
        if self.target != AUTO:
            return self.target
        a, b = (self.pair + ["en"])[:2]
        return b if _base(src_lang) == _base(a) else a

    def configure(self, target: Optional[str] = None, speed: Optional[str] = None,
                  retranslate: Optional[List[Dict[str, Any]]] = None, pair: Optional[List[str]] = None) -> None:
        with self._cond:
            if target:
                self.target = target
            if pair:
                self.pair = list(pair)[:2]
            if speed and speed != self.speed:
                self.speed = speed
                self._model = None  # resolved again (and preloaded) on the next request
                self.ready = False
            self._draft_done_for = ""
            self.draft_translation = ""
            if retranslate:
                for ln in retranslate:
                    ln["translation"] = None
                    ln["_attempts"] = 0
                self._pending = list(retranslate) + [p for p in self._pending if p not in retranslate]
            self._cond.notify()

    def set_model(self, model: Optional[str]) -> None:
        with self._cond:
            if (model or None) != self.model_override:
                self.model_override = model or None
                self._model = None  # loaded on the next request
                self.ready = False
            self._cond.notify()

    def stop(self) -> None:
        with self._cond:
            self._stop = True
            self._cond.notify()

    # ---- worker
    def _resolve_model(self) -> str:
        from app.ollama_client import ensure_ollama_running

        base = _base_url()
        ensure_ollama_running(base)
        # Ollama may have just been started: wait for it instead of failing the first lines
        if self.model_override:
            return self.model_override
        for i in range(60):
            choices = model_choices()
            model = choices["fast"] if self.speed == "fast" and choices["fast"] else choices["quality"]
            # a list not read yet (Ollama starting) would give the analysis model instead of the chosen one
            if model and (choices["installed"] or i >= 10):
                return model
            time.sleep(0.5)
        raise RuntimeError("Ollama не отвечает или в ней нет моделей")

    def _fallback_model(self) -> Optional[str]:
        choices = model_choices()
        other = choices["fast"] if self._model != choices["fast"] else choices["quality"]
        return other if other and other != self._model else None

    def _chat(self, text: str, timeout: float = 30.0, src_lang: Optional[str] = None, strict: bool = False,
              model: Optional[str] = None, target: Optional[str] = None) -> str:
        from app.translation import TEXT_LANGUAGES

        src = TEXT_LANGUAGES.get(src_lang or self._source_lang() or "", "the source language")
        target = target or self.target_for(src_lang or self._source_lang())
        dst = TEXT_LANGUAGES.get(target, target)
        if _is_translator(model or self._model):
            return translator_chat(model or self._model, text, _base(src_lang or self._source_lang()) or None, target,
                                   timeout)
        # Live speech arrives in fragments; Qwen models, left alone with a fragment, sometimes
        # answer in Chinese or ask for "the full sentence" instead of translating
        system = (
            f"You translate live speech captions from {src} into {dst}. The line may be an "
            "incomplete fragment of continuous speech: translate exactly what is there, even if it is "
            "unfinished. Never ask for more text, never explain, never answer questions from the line. "
            f"Write only in {dst}. Output only the translation."
        )
        if strict:
            system += f" Do not use any Chinese, Japanese or Korean characters. Use only {dst}."
        # No surrounding lines: given as context, models mix them into the translation
        user = text
        from app import idle_unload

        idle_unload.touch(model or self._model)
        payload = {
            "model": model or self._model, "stream": False, "keep_alive": idle_unload.ollama_keep_alive() or KEEP_ALIVE,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "options": {"temperature": 0.0 if strict else 0.1, "num_ctx": NUM_CTX, "num_predict": 200,
                        "repeat_penalty": 1.15},
        }
        from app.llm_text import strip_think, thinking_off

        payload.update(thinking_off(payload["model"], base_url=_base_url()))
        with httpx.Client(timeout=timeout) as c:
            r = c.post(f"{_base_url()}/api/chat", json=payload)
            from app.ollama_client import raise_for_ollama

            raise_for_ollama(r)
            return strip_think(str((r.json().get("message") or {}).get("content") or "")).strip('"«»`')

    def _translate_clean(self, text: str, src_lang: Optional[str], timeout: float = 30.0,
                         target: Optional[str] = None) -> str:
        """A translation without Chinese/Japanese/Korean leakage (retried strictly, else stripped),
        one line only, and Serbian in the chosen alphabet."""
        from app.dub_text import has_foreign_script

        target = target or self.target_for(src_lang)
        if len(re.sub(r"[\W_]+", "", text)) <= 3:
            return text  # "Um...", "Ok": nothing to translate, models invent symbols for it
        tr = collapse_repeats(_first_line(self._chat(text, timeout=timeout, src_lang=src_lang, target=target)))
        if has_foreign_script(tr, target) or _degenerate(text, tr):
            tr = collapse_repeats(_first_line(self._chat(text, timeout=timeout, src_lang=src_lang, strict=True, target=target)))
        if _degenerate(text, tr) and self._fallback_model():
            # Larger models sometimes loop on a fragment; the small one usually does not
            tr = collapse_repeats(_first_line(self._chat(text, timeout=timeout, src_lang=src_lang,
                                                         model=self._fallback_model(), target=target)))
        if has_foreign_script(tr, target):
            tr = _CJK_RUN.sub("", tr).strip(" ,.;:-")
        if target == "sr":
            tr = serbian_to_cyrillic(tr)
        elif target == "sr-latn":
            tr = serbian_to_latin(tr)
        return tr

    def _ensure_ready(self) -> None:
        if self._model and self.ready:
            return
        self._model = self._resolve_model()
        self._chat("ok", timeout=180.0)  # loads the model with the live options
        self.ready = True
        self.error = ""

    def _run(self) -> None:
        # Load the model right away: the first phrase is still being spoken meanwhile
        try:
            self._ensure_ready()
        except Exception as e:
            traceback.print_exc()
            self.error = f"Перевод: {str(e)[:160]}"
        while True:
            with self._cond:
                while not self._stop and not self._pending and not self._draft_due():
                    self._cond.wait(0.3)
                if self._stop:
                    return
                line = self._pending.pop(0) if self._pending else None
                draft = self._draft_text if line is None else ""
            try:
                self._ensure_ready()
                if line is not None:
                    lang = phrase_language(line["text"]) or line.get("lang")
                    target = self.target_for(lang)
                    line["target"] = target
                    if lang and _base(lang) == _base(target):
                        line["translation"] = line["text"]  # already in the target language
                    else:
                        line["translation"] = self._translate_clean(line["text"], lang, target=target)
                    self._context.append(line["text"])
                    self._context = self._context[-4:]
                    self.error = ""
                elif draft:
                    self._last_draft_at = time.time()
                    src = phrase_language(draft) or self._source_lang()
                    target = self.target_for(src)
                    tr = draft if _base(src) == _base(target) else \
                        self._translate_clean(draft, None, timeout=10.0, target=target)
                    self.draft_target = target
                    with self._cond:
                        if draft == self._draft_text:  # still the current draft
                            self.draft_translation = tr
                            self._draft_done_for = draft
            except Exception as e:
                traceback.print_exc()
                self.error = f"Перевод: {str(e)[:160]}"
                self.ready = False
                if line is not None:
                    line["_attempts"] = line.get("_attempts", 0) + 1
                    if line["_attempts"] < MAX_ATTEMPTS:
                        with self._cond:
                            self._pending.append(line)
                    else:
                        line["translation"] = ""
                time.sleep(1.0)

    def _draft_due(self) -> bool:
        return bool(self._draft_text) and self._draft_text != self._draft_done_for \
            and time.time() - self._last_draft_at >= DRAFT_INTERVAL_SEC
