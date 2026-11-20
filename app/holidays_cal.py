"""
Public holidays of the country (and region) chosen in Settings → Календарь → Праздники.

Offline, from the `holidays` package (MIT): its rules cover about 250 countries and their regions.
A holiday counts as a day off: «Главная» leaves it out of the working days of the period, marks it on
the week and in the calendar, and «Свободное время» does not offer its hours.

Settings: holiday_country (ISO code, "" = off), holiday_subdiv (the region's code, "" = the country).
Without the package (an old environment before it moves to Python 3.11) there are no holidays.
"""

from datetime import date, timedelta
from functools import lru_cache
from typing import Any, Dict, List, Tuple


def _lib():
    try:
        import holidays  # noqa: F401

        return holidays
    except Exception:
        return None


def available() -> bool:
    return _lib() is not None


def _split(name: str) -> str:
    """The class name of a country into words: "UnitedStates" → "United States"."""
    out = ""
    for i, ch in enumerate(name):
        if i and ch.isupper() and not name[i - 1].isupper():
            out += " "
        out += ch
    return out


@lru_cache(maxsize=1)
def countries() -> List[Dict[str, Any]]:
    """[{code, name, subdivs: [{code, name}]}]: every country the package knows (English names; the
    page shows the country in the user's language by its code)."""
    lib = _lib()
    if not lib:
        return []
    from holidays.registry import COUNTRIES

    names = {v[1]: _split(v[0]) for v in COUNTRIES.values()}
    out = []
    for code, subs in sorted(lib.list_supported_countries(include_aliases=False).items()):
        subdivs = []
        if subs:
            try:
                aliases = lib.country_holidays(code).get_subdivision_aliases()
            except Exception:
                aliases = {}
            subdivs = [{"code": s, "name": (aliases.get(s) or [s])[0]} for s in subs]
        out.append({"code": code, "name": names.get(code, code), "subdivs": subdivs})
    return out


def home_country() -> str:
    """The country of this computer's region (Windows: Settings → Time & language → Region, not the
    language of Windows: a Russian Windows in Serbia is Serbia), "" when unknown."""
    code = ""
    try:
        import ctypes
        import sys

        if sys.platform == "win32":
            buf = ctypes.create_unicode_buffer(16)
            if ctypes.windll.kernel32.GetUserDefaultGeoName(buf, 16):
                code = buf.value
    except Exception:
        code = ""
    if not code:
        import locale

        try:
            loc = locale.getlocale()[0] or ""
        except Exception:
            loc = ""
        code = loc.replace("-", "_").split("_")[1] if "_" in loc.replace("-", "_") else ""
    code = code.strip().upper()
    return code if len(code) == 2 and code.isalpha() else ""


def _language(cls_obj, lang: str) -> str:
    """The names in the language of the page when the country has it, else English, else its own."""
    langs = tuple(getattr(cls_obj, "supported_languages", ()) or ())
    for want in (("ru",) if lang == "ru" else ()) + ("en_US", "en_GB", "en"):
        if want in langs:
            return want
    return ""


@lru_cache(maxsize=64)
def _year(country: str, subdiv: str, year: int, lang: str) -> Tuple[Tuple[str, str], ...]:
    lib = _lib()
    if not lib or not country:
        return ()
    try:
        probe = lib.country_holidays(country, subdiv=subdiv or None)
        language = _language(probe, lang)
        h = lib.country_holidays(country, subdiv=subdiv or None, years=year, language=language or None)
    except Exception:
        return ()
    return tuple(sorted((d.isoformat(), str(n)) for d, n in h.items()))


def chosen() -> Tuple[str, str]:
    from app.database import get_all_settings

    s = get_all_settings()
    return (s.get("holiday_country") or "").strip().upper(), (s.get("holiday_subdiv") or "").strip()


def between(start: date, end: date, lang: str = "ru", country: str = None, subdiv: str = None) -> Dict[str, str]:
    """{"YYYY-MM-DD": name} of the holidays in start…end (end not included)."""
    if country is None:
        country, subdiv = chosen()
    if not country or end <= start or (end - start).days > 800:
        return {}
    out: Dict[str, str] = {}
    for y in range(start.year, (end - timedelta(days=1)).year + 1):
        for k, n in _year(country, subdiv or "", y, lang):
            if start.isoformat() <= k < end.isoformat():
                out[k] = n
    return out


def is_holiday(day: date, lang: str = "ru") -> str:
    """The name of the holiday on that day, or ""."""
    return between(day, day + timedelta(days=1), lang).get(day.isoformat(), "")
