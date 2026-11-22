"""
The UI language for what Windows shows from the tray side: the tray's notifications, its menu and
tooltip, toasts, meeting reminders and the app's message boxes. The page chooses it (POST /api/ui/lang
writes DATA_DIR / "ui-lang.txt": "ru" or "en"); every text is chosen when it is shown, so a switch
applies to the next notice and the next opening of the tray menu.
"""

import threading

DEFAULT = "ru"
FILE_NAME = "ui-lang.txt"

_cache = {"key": None, "lang": DEFAULT}
_lock = threading.Lock()


def _path():
    from app import paths

    return paths.DATA_DIR / FILE_NAME


def current() -> str:
    """"ru" or "en"; "ru" when the page has not chosen one yet. Read again only when the file changed."""
    try:
        st = _path().stat()
    except OSError:
        return DEFAULT
    key = (st.st_mtime_ns, st.st_size)
    with _lock:
        if key == _cache["key"]:
            return _cache["lang"]
    try:
        lang = "en" if _path().read_text(encoding="utf-8").strip() == "en" else DEFAULT
    except OSError:
        return DEFAULT
    with _lock:
        _cache.update(key=key, lang=lang)
    return lang


def save(lang: str) -> str:
    """Remembers the language the page chose; returns it normalized."""
    lang = "en" if lang == "en" else DEFAULT
    try:
        _path().write_text(lang, encoding="utf-8")
    except OSError:
        pass
    with _lock:
        _cache.update(key=None)  # read again: a write within the same tick keeps the same mtime
    return lang


def is_en() -> bool:
    return current() == "en"


def tr(ru: str, en: str) -> str:
    """The text in the UI language."""
    return en if is_en() else ru


def plural_ru(n: int, one: str, few: str, many: str) -> str:
    return one if n % 10 == 1 and n % 100 != 11 else few if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else many


def count(n: int, ru_one: str, ru_few: str, ru_many: str, en_one: str, en_many: str) -> str:
    """«2 минуты» / "2 minutes": the number with its word in the UI language."""
    if is_en():
        return f"{n} {en_one if n == 1 else en_many}"
    return f"{n} {plural_ru(n, ru_one, ru_few, ru_many)}"
