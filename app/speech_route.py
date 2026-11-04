"""
The speech model of a recording whose model is "auto": the model for Russian (setting speech_model_ru,
e.g. GigaAM) when the speech is Russian, the main model (whisper_model, e.g. Whisper Turbo or Parakeet)
for every other language and for speech that mixes languages.

The language comes from the recording's setting; "auto" listens to the first minute with the main
model (Whisper names the language, an ONNX model's text shows it by its letters).
"""

from typing import Callable, Dict, Optional, Tuple

AUTO = "auto"
DETECT_SECONDS = 60.0


def ru_model(settings: Dict[str, str]) -> str:
    return (settings.get("speech_model_ru") or "").strip()


def main_model(settings: Dict[str, str]) -> str:
    return (settings.get("whisper_model") or "").strip() or "large-v3-turbo"


def routing_on(settings: Dict[str, str]) -> bool:
    """A model of its own for Russian is chosen, other than the main one."""
    ru = ru_model(settings)
    return bool(ru) and ru != main_model(settings)


def default_choice(settings: Dict[str, str]) -> str:
    """What a new recording gets when nobody chose its model: "auto" while a Russian model is set."""
    return AUTO if routing_on(settings) else main_model(settings)


def lang_of_text(text: str) -> Optional[str]:
    """"ru", another language, or None when there is too little text to tell. Ukrainian, Belarusian and
    the like are written in Cyrillic too: their own letters keep them away from the Russian model."""
    letters = [ch for ch in text if ch.isalpha()]
    if len(letters) < 20:
        return None
    cyr = [ch for ch in letters if "Ѐ" <= ch <= "ӿ"]
    if len(cyr) < len(letters) * 0.5:
        return "other"
    if any(ch in "іїєґўІЇЄҐЎ" for ch in cyr):
        return "other"
    return "ru"


def resolve(settings: Dict[str, str], lang_setting: Optional[str],
            detect: Callable[[], Optional[str]]) -> Tuple[str, Optional[str]]:
    """(model, "ru" when the speech was taken as Russian, else None). `detect` is called only for
    "auto" speech and may answer None (then the main model takes the recording)."""
    main = main_model(settings)
    if not routing_on(settings):
        return main, None
    lang = (lang_setting or AUTO).strip()
    if lang == "ru":
        return ru_model(settings), "ru"
    if lang != AUTO:  # another language, or several mixed in one recording
        return main, None
    try:
        found = detect()
    except Exception as e:  # the main model takes it: never worse than before the routing existed
        print(f"[speech_route] language not detected: {e}", flush=True)
        found = None
    return (ru_model(settings), "ru") if found == "ru" else (main, None)
