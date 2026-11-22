"""
Requests to this computer (Ollama at 127.0.0.1) never go through a proxy.

On Windows urllib.request.getproxies() falls back on the proxy of the Windows settings, without its list of
exceptions; httpx (every request of the app) takes that dictionary as it is, so with
a proxy set in Windows a request to http://127.0.0.1:11434 went to the proxy: the transcript in a prompt left
the computer in clear text and Ollama was not reached (found in the security review). Windows itself never
sends loopback addresses to its proxy; here the loopback names are added to the exceptions ("no") of that
dictionary, which httpx reads (install(), called by app/__init__.py before httpx is imported).
"""

import sys
import urllib.request
from typing import Callable, Dict

LOOPBACK = ("localhost", "127.0.0.1", "::1")


def with_loopback_exempt(get: Callable[[], Dict[str, str]]) -> Callable[[], Dict[str, str]]:
    def getproxies() -> Dict[str, str]:
        proxies = dict(get())
        if any(v for k, v in proxies.items() if k != "no"):
            have = [h.strip() for h in (proxies.get("no") or "").split(",") if h.strip()]
            proxies["no"] = ",".join(have + [h for h in LOOPBACK if h not in have])
        return proxies

    getproxies.__wrapped__ = get  # type: ignore[attr-defined]
    return getproxies


def install() -> None:
    if getattr(urllib.request.getproxies, "__wrapped__", None) is None:
        urllib.request.getproxies = with_loopback_exempt(urllib.request.getproxies)
    # httpx imported before the app's package (a test, a tool) holds its own reference: replaced too
    mod = sys.modules.get("httpx._utils")
    if mod is not None and getattr(getattr(mod, "getproxies", None), "__wrapped__", None) is None:
        mod.getproxies = urllib.request.getproxies
