"""
Update check and self-update from GitHub Releases.

Check: GET api.github.com/repos/<repo>/releases/latest (only that request; no data about the user
or the computer is sent). At most every CHECK_INTERVAL_SEC, and only if the setting
"update_check" is on.

Update (on the user's click):
  1. the release archive Verbaliox-vX.Y.Z.zip is downloaded into <data>/updates and checked
     against the release's SHA256SUMS.txt;
  2. this module is started as a separate process (`python -m app.updater apply ...`) and the app
     quits; the updater waits for it to exit, shows a small progress window, backs up the files it
     will replace, copies the new program files over the program folder (never the user's data,
     models or Python environments), installs Python packages again if requirements.txt changed,
     and starts Verbaliox.exe. On any failure the backup is restored.

Automatic updates (setting "update_auto", on by default): a newer release found by the check is
downloaded in the background; it is installed when the user clicks "Restart", or when the app is
closed (then it is not started again). The folder .git of a git checkout is never touched.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# Loaded before the update replaces the program files
from app.pyenv import ensure_pip, find_uv, mark_requirements

GITHUB_REPO = "pravken/Verbaliox"
LATEST_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
# With "Get beta versions" on: the newest of the recent releases, pre-releases (v0.5.0-beta.1) too;
# releases/latest never names a pre-release
RELEASES_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases?per_page=30"
CHECK_INTERVAL_SEC = 6 * 3600
# When the API refuses (403/429: GitHub allows 60 requests an hour per address without an account, and an office or
# a VPN shares one address — reported by the user): the public feed of the releases and the release's own files,
# which have no such limit. The signature of SHA256SUMS.txt is checked the same way.
FEED_URL = f"https://github.com/{GITHUB_REPO}/releases.atom"
RAW_URL = f"https://raw.githubusercontent.com/{GITHUB_REPO}"
RATE_LIMITED = "GitHub временно ограничил число проверок с этого адреса. Программа проверит снова позже."
# Files are only ever downloaded from this repository's releases
DOWNLOAD_PREFIX = f"https://github.com/{GITHUB_REPO}/releases/download/"
# The author's release key (minisign format, app/release_sign.py, docs/release-signing.md). Set: an
# update installs only with SHA256SUMS.txt.minisig signed by it for that very release. Empty: the
# checksum alone is checked, as before the key existed.
RELEASE_PUBLIC_KEY = "RWT8fmjh8HjA/sAFcnc7vHWhzK+i+OircfoKXDPiKs5QnNnrGdiRRIpB"
# Never replaced by an update: user data, models and the Python environments
# .venv-new and .venv-old: the move to Python 3.11 (app/envmove.py); python and .uv-cache: the Python uv installs for
# the program and its downloads (setup.bat, app/paths.py: «.python» was written here, which is no folder of it: an audit)
PROTECTED = {".venv", ".venv-new", ".venv-old", ".venv-dub", ".python", "python", ".uv-cache", "models", "data",
             "node_modules", ".git"}

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0

_state: Dict[str, Any] = {
    "checked_at": 0.0, "latest": None, "error": "",
    "download": {"active": False, "progress": 0, "done": False, "error": "", "path": ""},
}
_lock = threading.Lock()


# ------------------------------------------------------------------ versions
_PRE_RANK = {"alpha": 0, "a": 0, "beta": 1, "b": 1, "rc": 2}


def parse_version(text: str) -> tuple:
    """'v1.10.2' -> (1, 10, 2, 1, 0, 0); '0.2.0-beta.1' -> (0, 2, 0, 0, 1, 1): a pre-release sorts
    below its release (alpha < beta < rc), so a beta tester is offered the final version.
    Anything unparsable sorts lowest."""
    m = re.match(r"^\s*v?(\d+(?:\.\d+)*)(?:[-.]?(alpha|beta|rc|a|b)\.?(\d*))?", str(text or ""), re.IGNORECASE)
    if not m:
        return (0, 0, 0, 0, 0, 0)
    nums = [int(n) for n in m.group(1).split(".")[:3]]
    nums += [0] * (3 - len(nums))
    if m.group(2):
        return (*nums, 0, _PRE_RANK[m.group(2).lower()], int(m.group(3) or 0))
    return (*nums, 1, 0, 0)


def is_newer(latest: str, current: str) -> bool:
    return parse_version(latest) > parse_version(current)


def current_version() -> str:
    from app import __version__

    return __version__


def is_git_checkout() -> bool:
    from app.paths import APP_DIR

    return (APP_DIR / ".git").exists()


# ------------------------------------------------------------------ check
def changelog_notes(tag: str, text: str) -> str:
    """The notes of a release from CHANGELOG.md, as the release page has them (tools/release_notes.py): every
    section of the version, the English one first. A beta gets the sections of its coming version."""
    base = re.sub(r"^v", "", tag.strip()).split("-")[0]
    sections, inside = [], False
    for line in text.splitlines():
        if line.startswith("## "):
            inside = re.match(rf"^## {re.escape(base)}(\s|$)", line) is not None
            if inside:
                sections.append([])
        if inside and line.strip() != "---":
            sections[-1].append(line)
    english = [x for x in sections if x[0].rstrip().endswith("English")]
    blocks = english + [x for x in sections if x not in english]
    return "\n\n".join("\n".join(x).strip() for x in blocks).strip()


def _latest_from_feed(c: Any, beta: bool) -> Optional[Dict[str, Any]]:
    """The newest release by the public feed (no API, no limit per hour): its tag from the feed, its files
    from its SHA256SUMS.txt, its notes from CHANGELOG.md of that tag. None: no release."""
    # the client asks the API for JSON: the feed is asked for as what it is
    r = c.get(FEED_URL, headers={"Accept": "application/atom+xml, application/xml;q=0.9, */*;q=0.8"})
    r.raise_for_status()
    tags = {t for t in re.findall(rf"/{re.escape(GITHUB_REPO)}/releases/tag/([\w.\-]+)", r.text, re.IGNORECASE)}
    # a pre-release is told by its version (v0.9.0-beta.1): the feed does not say which ones are
    tags = [t for t in tags if beta or parse_version(t)[3] == 1]
    if not tags:
        return None
    tag = max(tags, key=parse_version)
    base = f"{DOWNLOAD_PREFIX}{tag}/"
    sums = c.get(base + "SHA256SUMS.txt")
    sums.raise_for_status()
    names = [ln.split()[-1].lstrip("*") for ln in sums.text.splitlines() if len(ln.split()) == 2]
    zip_name = next((n for n in names if re.fullmatch(r"Verbaliox-v[\w.\-]+\.zip", n)), None)
    notes = ""
    try:
        log = c.get(f"{RAW_URL}/{tag}/CHANGELOG.md")
        if log.status_code == 200:
            notes = changelog_notes(tag, log.text)[:20000]
    except Exception:
        pass
    return {
        "version": tag.lstrip("v"), "tag": tag, "name": tag, "notes": notes,
        "url": f"https://github.com/{GITHUB_REPO}/releases/tag/{tag}", "published_at": None,
        "zip_url": base + zip_name if zip_name else None, "zip_name": zip_name,
        "sums_url": base + "SHA256SUMS.txt", "sig_url": base + "SHA256SUMS.txt.minisig",
        "zip_digest": "",  # GitHub's own digest comes only with the API: SHA256SUMS.txt and its signature still hold
    }


def _latest_from_api(r: Any, beta: bool) -> Optional[Dict[str, Any]]:
    """The newest release by the API's answer (releases/latest, or the recent ones with betas). None: no release."""
    rel = None
    if r.status_code != 404:  # 404: no release published yet
        r.raise_for_status()
        rel = r.json()
        if beta:
            rel = max((x for x in rel if isinstance(x, dict) and not x.get("draft")),
                      key=lambda x: parse_version(x.get("tag_name") or ""), default=None)
    if rel is None:
        return None
    assets = {a.get("name"): a.get("browser_download_url") for a in rel.get("assets") or []
              if str(a.get("browser_download_url") or "").startswith(DOWNLOAD_PREFIX)}
    # GitHub's own SHA-256 of each uploaded file ("sha256:<hex>"), independent of SHA256SUMS.txt
    digests = {a.get("name"): str(a.get("digest") or "") for a in rel.get("assets") or []}
    zip_name = next((n for n in assets if re.fullmatch(r"Verbaliox-v[\w.\-]+\.zip", n or "")), None)
    return {
        "version": str(rel.get("tag_name") or "").lstrip("v"),
        "tag": rel.get("tag_name"),
        "name": rel.get("name") or rel.get("tag_name"),
        "notes": (rel.get("body") or "")[:20000],
        "url": rel.get("html_url"),
        "published_at": rel.get("published_at"),
        "zip_url": assets.get(zip_name) if zip_name else None,
        "zip_name": zip_name,
        "sums_url": assets.get("SHA256SUMS.txt"),
        "sig_url": assets.get("SHA256SUMS.txt.minisig"),
        "zip_digest": digests.get(zip_name, "").removeprefix("sha256:").lower() if zip_name else "",
    }


def check(force: bool = False) -> Dict[str, Any]:
    """The latest release, cached; never raises."""
    import httpx

    from app.database import get_all_settings

    settings = get_all_settings()
    enabled = settings.get("update_check", "true").lower() == "true"
    beta = settings.get("update_beta", "false").lower() == "true"
    with _lock:
        # switching the beta channel asks again at once
        fresh = time.time() - _state["checked_at"] < CHECK_INTERVAL_SEC and _state.get("beta") == beta
    if (enabled or force) and (force or not fresh):
        try:
            with httpx.Client(timeout=8.0, follow_redirects=True,
                              headers={"Accept": "application/vnd.github+json",
                                       "User-Agent": f"Verbaliox/{current_version()}"}) as c:
                r = c.get(RELEASES_URL if beta else LATEST_URL)
                if r.status_code in (403, 429):  # the API's limit per hour: the public feed instead
                    try:
                        latest = _latest_from_feed(c, beta)
                    except Exception as e:
                        print(f"[update] the API refused ({r.status_code}) and the feed failed: {e}", flush=True)
                        raise RuntimeError(RATE_LIMITED) from None
                else:
                    latest = _latest_from_api(r, beta)
            with _lock:
                _state.update(checked_at=time.time(), latest=latest, error="", beta=beta)
        except Exception as e:
            with _lock:
                _state.update(checked_at=time.time(), error=str(e)[:200], beta=beta)
    st = status()
    _auto_download(st)
    return status()


def status() -> Dict[str, Any]:
    from app.database import get_all_settings

    with _lock:
        latest = _state["latest"]
        out = {
            "current": current_version(),
            "latest": latest,
            "available": bool(latest and is_newer(latest["version"], current_version())),
            "checked_at": _state["checked_at"],
            "error": _state["error"],
            "enabled": get_all_settings().get("update_check", "true").lower() == "true",
            "git_checkout": is_git_checkout(),
            "download": dict(_state["download"]),
        }
        dl = out["download"]
        if dl.get("done") and dl.get("version") and latest and latest.get("version") != dl.get("version"):
            # an archive of an older release than the one found: offered for download again, not to install
            out["download"] = {**dl, "done": False, "stale": True}
    out["auto"] = auto_enabled()
    # A git clone is updated with git: an archive would overwrite the working copy (and its changes)
    out["can_install"] = out["available"] and bool(latest and latest.get("zip_url")) and not out["git_checkout"]
    return out


def auto_enabled() -> bool:
    from app.database import get_all_settings

    return get_all_settings().get("update_auto", "true").lower() == "true"


def _auto_download(st: Dict[str, Any]) -> None:
    """Starts downloading a found update when automatic updates are on."""
    dl = st.get("download") or {}
    # An archive downloaded before a newer release came out is downloaded again: installing it would
    # have put on the older version the window offered as the newer one
    stale = dl.get("done") and dl.get("version") and (st.get("latest") or {}).get("version") != dl.get("version")
    if st.get("can_install") and st.get("auto") and not dl.get("active") and (not dl.get("done") or stale):
        try:
            start_download()
        except RuntimeError:
            pass


# --- A new version said in a Windows notification (asked by the user: the app lives in the tray for days, the
# one check at start-up and a message inside a hidden window were missed). Once per version: when it is
# found, and when it is downloaded and ready. Not in quiet mode; the window keeps its own mark of it
# One tick at a time: two ticks at once (the 30-minute loop and another caller) both read «not told yet» and
# both told the same version (found by CI on Windows: «Вышла Verbaliox» twice)
_notice_lock = threading.Lock()


def notice_tick() -> Dict[str, Any]:
    with _notice_lock:
        return _notice_tick()


def _notice_tick() -> Dict[str, Any]:
    from app import app_status
    from app.database import get_all_settings, update_settings

    st = check()
    settings = get_all_settings()
    latest = st.get("latest") or {}
    ver = latest.get("version") or ""
    if not st.get("available") or not ver:
        return st
    quiet = (settings.get("quiet_mode") or "false").lower() == "true"
    dl = st.get("download") or {}
    if settings.get("update_notified") != ver:
        update_settings({"update_notified": ver})
        if not quiet:
            from app.ui_lang import tr

            how = (tr("Скачается и установится автоматически, когда программа будет свободна. ",
                      "It downloads and installs automatically when the app is idle. ")
                   if st.get("auto") and st.get("can_install") else "")
            app_status.add_notice(tr(f"Вышла Verbaliox {ver}", f"Verbaliox {ver} is available"),
                                  how + tr("Нажмите, чтобы посмотреть, что нового", "Click to see what is new"), "update")
    elif dl.get("done") and not dl.get("stale") and settings.get("update_ready_notified") != ver:
        update_settings({"update_ready_notified": ver})
        if not quiet:
            from app.ui_lang import tr

            app_status.add_notice(tr(f"Verbaliox {ver} готова к установке", f"Verbaliox {ver} is ready to install"),
                                  tr("Установится при выходе из программы. Нажмите, чтобы перезапустить сейчас",
                                     "It installs when the app exits. Click to restart now"), "update")
    return st


def notice_loop() -> None:
    time.sleep(90)  # after the start-up: the page checks once itself then
    while True:
        try:
            notice_tick()
        except Exception as e:
            print(f"[update] notice: {e}", flush=True)
        time.sleep(30 * 60)  # check() asks GitHub at most every CHECK_INTERVAL_SEC; a download done is seen sooner


def _download_current() -> bool:
    """The archive downloaded is of the release found last (call with _lock held)."""
    dl, latest = _state.get("download") or {}, _state.get("latest") or {}
    return bool(dl.get("done") and dl.get("path")) and (not dl.get("version") or not latest
                                                       or dl.get("version") == latest.get("version"))


FAILED_NAME = "update-failed.json"  # in the data folder: the archive whose install failed (its sum)


def failed_before() -> bool:
    """The archive downloaded is the one whose install failed (found in the audit: little disk space or a
    proxy made every automatic attempt fail, and the app restarted and said so every five minutes).
    It is not installed by itself again; a click in the window still installs it, a newer release too."""
    from app.paths import DATA_DIR

    with _lock:
        sha = (_state.get("download") or {}).get("sha256") or ""
    try:
        failed = json.loads((DATA_DIR / FAILED_NAME).read_text(encoding="utf-8")).get("sha256") or ""
    except (OSError, ValueError, AttributeError):
        return False
    return bool(sha) and sha.lower() == failed.lower()


def ready_to_install() -> bool:
    """A downloaded update that automatic updates would install now."""
    with _lock:
        done = _download_current()
    return done and auto_enabled() and not is_git_checkout() and not failed_before()


def install_on_exit() -> bool:
    """Called when the app closes: installs a downloaded update without starting the app again."""
    try:
        with _lock:
            path = _state["download"].get("path") if _download_current() else ""
        if not path or not auto_enabled() or is_git_checkout() or failed_before():
            return False
        launch_installer(restart=False)
        return True
    except Exception:
        traceback.print_exc()
        return False


# ------------------------------------------------------------------ download
def _updates_dir() -> Path:
    from app.paths import DATA_DIR

    d = DATA_DIR / "updates"
    d.mkdir(parents=True, exist_ok=True)
    return d


def start_download() -> Dict[str, Any]:
    st = status()
    if not st["can_install"]:
        raise RuntimeError("Обновление недоступно для установки")
    with _lock:
        if _state["download"]["active"]:
            return status()
        _state["download"] = {"active": True, "progress": 0, "done": False, "error": "", "path": ""}
    threading.Thread(target=_download, args=(st["latest"],), daemon=True, name="update_download").start()
    return status()


def check_signature(sums: bytes, sig_text: str, tag: str, key: Optional[str] = None) -> None:
    """RuntimeError unless `sig_text` is the release key's signature of `sums` for release `tag`."""
    from app import release_sign

    if not sig_text.strip():
        raise RuntimeError("Релиз не подписан ключом автора — обновление отменено")
    try:
        comment = release_sign.verify_file(key or RELEASE_PUBLIC_KEY, sums, sig_text)
    except release_sign.SignatureError as e:
        print(f"[update] signature: {e}", flush=True)
        raise RuntimeError("Подпись релиза не прошла проверку — обновление отменено")
    if f"tag:{tag}" not in comment.split():  # a signature of another release, put next to this one
        print(f"[update] signature is for another release: {comment}", flush=True)
        raise RuntimeError("Подпись релиза не прошла проверку — обновление отменено")


def _download(latest: Dict[str, Any]) -> None:
    import httpx

    def _set(**kw) -> None:
        with _lock:
            _state["download"].update(kw)

    try:
        target = _updates_dir() / latest["zip_name"]
        part = target.with_suffix(".part")
        with httpx.Client(timeout=60.0, follow_redirects=True,
                          headers={"User-Agent": f"Verbaliox/{current_version()}"}) as c:
            expected = None
            if latest.get("sums_url"):
                sums = c.get(latest["sums_url"]).content
                if RELEASE_PUBLIC_KEY:
                    check_signature(sums, c.get(latest["sig_url"]).text if latest.get("sig_url") else "", latest.get("tag") or "")
                for line in sums.decode("utf-8", "replace").splitlines():
                    parts = line.split()
                    if len(parts) == 2 and parts[1].lstrip("*") == latest["zip_name"]:
                        expected = parts[0].lower()
            if not expected:
                raise RuntimeError("В релизе нет контрольной суммы архива (SHA256SUMS.txt)")
            if latest.get("zip_digest") and latest["zip_digest"] != expected:
                raise RuntimeError("Контрольные суммы релиза не совпадают между собой — обновление отменено")
            h = hashlib.sha256()
            with c.stream("GET", latest["zip_url"]) as r:
                r.raise_for_status()
                total = int(r.headers.get("content-length") or 0)
                done = 0
                with part.open("wb") as f:
                    for chunk in r.iter_bytes(1 << 16):
                        f.write(chunk)
                        h.update(chunk)
                        done += len(chunk)
                        if total:
                            _set(progress=int(100 * done / total))
        if h.hexdigest() != expected:
            part.unlink(missing_ok=True)
            raise RuntimeError("Контрольная сумма архива не совпала — файл повреждён или подменён")
        part.replace(target)
        _set(active=False, done=True, progress=100, path=str(target), version=latest.get("version") or "", sha256=expected)
    except Exception as e:
        traceback.print_exc()
        _set(active=False, done=False, error=str(e)[:300])


# Called before the process ends for an update (run.py registers removing the tray icon)
exit_hooks: List[Callable[[], None]] = []


def quit_soon(delay: float = 0.8) -> None:
    """Ends the app shortly after the HTTP answer has been sent, so the updater can replace files."""

    def _quit() -> None:
        time.sleep(delay)
        for hook in list(exit_hooks):
            try:
                hook()
            except Exception:
                pass
        os._exit(0)

    threading.Thread(target=_quit, daemon=True, name="update_quit").start()


def launch_git_update() -> None:
    """A git clone (is_git_checkout): update.bat in a console window of its own — git pull of its branch,
    the changed packages, then it offers to start the app again. It waits a few seconds for the app,
    which quits right after this, to be gone (update.bat waits for a key while Verbaliox.exe runs)."""
    from app.paths import APP_DIR

    if sys.platform != "win32":
        raise RuntimeError("Обновление через git из программы работает только в Windows")
    script = APP_DIR / "update.bat"
    if not is_git_checkout() or not script.is_file():
        raise RuntimeError("Это не клон git с update.bat: обновите программу из «Настройки → Общие → Обновления»")
    flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(f'cmd.exe /c "timeout /t 3 /nobreak >nul & call "{script}""', cwd=str(APP_DIR),
                     creationflags=flags, close_fds=True)


def launch_installer(restart: bool = True, minimized: bool = False) -> None:
    """Starts the updater for the downloaded archive; the caller then quits the app. minimized: the
    app comes back in the tray, without its window (installed in the background, run.py)."""
    from app.paths import APP_DIR, DATA_DIR

    with _lock:
        path = _state["download"].get("path")
        sha = _state["download"].get("sha256") or ""
        dl, latest = _state.get("download") or {}, _state.get("latest") or {}
        current = not (dl.get("version") and latest.get("version") and dl["version"] != latest["version"])
    if not path or not Path(path).is_file():
        raise RuntimeError("Архив обновления не скачан")
    if not current:
        raise RuntimeError("Скачивается более новая версия — установите её, когда она загрузится")
    # The archive was checked when downloaded, possibly days ago: the updater checks it is still that one
    cmd = [sys.executable, "-m", "app.updater", "apply", "--zip", path, "--app-dir", str(APP_DIR),
           "--data-dir", str(DATA_DIR), "--pid", str(os.getpid())] + ([] if restart else ["--no-restart"]) \
        + (["--restart-minimized"] if restart and minimized else []) + (["--sha256", sha] if sha else [])
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(cmd, cwd=str(APP_DIR), creationflags=flags, close_fds=True)


# ------------------------------------------------------------------ apply (separate process)
def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""


def _dub_requirements_hash(app_dir: Path) -> str:
    """The same hash app/dub_setup.py records in its ready mark: both dubbing locks together."""
    files = [app_dir / "requirements-dub.txt", app_dir / "requirements-dub-voxcpm.txt"]
    return hashlib.sha256(b"".join(f.read_bytes() for f in files if f.is_file())).hexdigest()


class UpdateFailed(RuntimeError):
    """An update that did not install. `outcome` says what the program folder holds now:
    "untouched" (nothing was replaced yet), "restored" (the previous version is back) or "broken"
    (putting it back failed too)."""

    def __init__(self, message: str, outcome: str = "untouched") -> None:
        super().__init__(message)
        self.outcome = outcome


OUTCOME_TEXT = {
    "untouched": "Файлы программы не изменены.",
    "restored": "Прежняя версия восстановлена.",
    "broken": "Прежнюю версию восстановить не удалось: скачайте и распакуйте Verbaliox заново "
              "(ваши записи и настройки в папке data не пострадают; подробности в logs\\update.log).",
}

# Program code an update owns: a file of these kinds that the new version no longer has is removed
# (an old module left in app/ could still be imported)
CODE_DIRS = ("app", "static")
CODE_SUFFIXES = {".py", ".js", ".html", ".css"}
# The dubbing environment's ready mark (app/dub_setup.py DUB_READY_MARKER)
DUB_MARKER = Path(".venv-dub") / "verbaliox-dub-ready.txt"
FORMER_DUB_MARKER = Path(".venv-dub") / "verbascribe-dub-ready.txt"  # made while the program was VerbaScribe


def _wait_for_exit(pid: int, timeout: float = 120.0) -> bool:
    """False if the process is still running after `timeout` (it may be finishing a job)."""
    if sys.platform != "win32":
        return True
    import ctypes

    SYNCHRONIZE, WAIT_OBJECT_0 = 0x00100000, 0
    h = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
    if h:
        ended = ctypes.windll.kernel32.WaitForSingleObject(h, int(timeout * 1000)) == WAIT_OBJECT_0
        ctypes.windll.kernel32.CloseHandle(h)
        if not ended:
            return False
    time.sleep(1.0)  # files and the port are released a moment later
    return True


def _stale_code_files(app_dir: Path, new_files: List[str]) -> List[str]:
    """Code files of the installed version that the new one does not ship."""
    new = set(new_files)
    if not any(rel.startswith("app/") for rel in new):  # not a full program archive: remove nothing
        return []
    # compared without letter case: on Windows «Foo.py» renamed «foo.py» is one file, written by the new
    # version, which would be deleted as stale (found in the audit)
    new = {rel.casefold() for rel in new}
    out = []
    for top in CODE_DIRS:
        base = app_dir / top
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if p.suffix.lower() in CODE_SUFFIXES and p.is_file() and "__pycache__" not in p.parts:
                rel = p.relative_to(app_dir).as_posix()
                if rel.casefold() not in new:
                    out.append(rel)
    return sorted(out)


def _preflight(app_dir: Path, need_bytes: int) -> None:
    """Fails before anything is replaced when the program folder is not writable or the disk is full."""
    probe = app_dir / ".update-write-test"
    try:
        probe.write_bytes(b"ok")
        probe.unlink()
    except OSError as e:
        raise UpdateFailed(f"Нет права записи в папку программы {app_dir} ({e}). "
                           "Переместите Verbaliox в папку пользователя или запустите от имени администратора.")
    try:
        free = shutil.disk_usage(app_dir).free
    except OSError:
        return
    if free < need_bytes:
        raise UpdateFailed(f"Недостаточно места на диске: нужно около {need_bytes / 1e9:.1f} ГБ, "
                           f"свободно {free / 1e9:.1f} ГБ.")


def _mark_dub_outdated(app_dir: Path, old_hash: str) -> None:
    """requirements-dub.txt changed: the dubbing environment needs its packages updated. A ready
    mark that records the requirements it was made with notices that itself; an older mark gets
    the previous requirements written in, so it reads as outdated."""
    marker = app_dir / DUB_MARKER
    if not marker.is_file() and (app_dir / FORMER_DUB_MARKER).is_file():
        marker = app_dir / FORMER_DUB_MARKER  # app/dub_setup.py renames it at the next start
    try:
        text = marker.read_text(encoding="utf-8")
    except OSError:
        return
    if not re.search(r"^requirements=", text, re.M):
        try:
            marker.write_text(text.rstrip("\n") + f"\nrequirements={old_hash}\n", encoding="utf-8")
        except OSError:  # the update itself is fine; the next dub check shows what is missing
            pass


def _freeze(py: Path, uv: Optional[str]) -> str:
    if not uv:
        ensure_pip(str(py))
    cmd = [uv, "pip", "freeze", "--python", str(py)] if uv else [str(py), "-m", "pip", "freeze"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                             creationflags=_NO_WINDOW, timeout=120)
        return res.stdout if res.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


# The PyTorch wheels of this version (requirements.txt names its index too) and of the versions before
# it: putting back the packages of an older version needs that one's (torch 2.6 was cu124)
TORCH_INDEX = "https://download.pytorch.org/whl/cu126"
OLDER_TORCH_INDEXES = ["https://download.pytorch.org/whl/cu124"]


def _reinstall(py: Path, uv: Optional[str], frozen_file: Optional[Path], log_dir: Path, backup: Path) -> None:
    """Put back the packages of the previous version: from its own requirements.txt (in the backup),
    checked by its hashes like any install. The list of what was installed (pip freeze, no hashes, from
    any of the indexes) is the last resort, for a backup without that file."""
    indexes = [a for url in [TORCH_INDEX, *OLDER_TORCH_INDEXES] for a in ("--extra-index-url", url)]
    req, hashes = None, ["--require-hashes"]
    try:
        with zipfile.ZipFile(backup) as bz:
            data = bz.read("requirements.txt")
        req = backup.parent / "requirements-before-update.txt"
        req.write_bytes(data)
    except (OSError, KeyError, zipfile.BadZipFile):
        req, hashes = frozen_file, []
    with open(log_dir / "update.log", "a", encoding="utf-8") as lf:
        if req is None:
            lf.write("restore of the Python packages: no previous requirements.txt and no list of the installed ones\n")
            raise RuntimeError("nothing to put the previous Python packages back from")
        if not hashes:
            lf.write("restore of the Python packages: no previous requirements.txt in the backup, "
                     "installing the list of the packages that were installed (without hashes)\n")
        lf.flush()
        cmd = ([uv, "pip", "install", "--python", str(py), "-r", str(req), *hashes,
                "--index-strategy", "unsafe-best-match", *indexes]
               if uv else [str(py), "-m", "pip", "install", "-r", str(req), *hashes, *indexes])
        res = subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT, creationflags=_NO_WINDOW)
    if res.returncode != 0:  # said «restored» over a broken environment (found in an audit)
        raise RuntimeError(f"the previous Python packages were not put back (exit code {res.returncode})")


def _write_member(src, dest: Path) -> None:
    """A file of the program written whole or not at all: beside it, then put in its place. Cut off midway (the
    computer switched off), run.py or updater.py itself was left truncated, and nothing could put the previous
    version back (found in an audit)."""
    tmp = dest.with_name(dest.name + ".upd.tmp")
    try:
        with open(tmp, "wb") as out:
            shutil.copyfileobj(src, out)
        os.replace(tmp, dest)
    except BaseException:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def archive_files(names: List[str], app_dir: Path) -> List[Tuple[str, str]]:
    """(name in the archive, path in the program folder) of the files an update writes. The archive
    holds one top folder (Verbaliox-vX.Y.Z/); a name that would land outside the program folder
    (absolute, a drive, "..", backslashes from another zip tool) or in a protected folder is left out."""
    root = app_dir.resolve()
    norm = [(n, n.replace("\\", "/")) for n in names if not n.replace("\\", "/").endswith("/")]
    first = {x.split("/")[0] for _n, x in norm}
    prefix = first.pop() + "/" if len(first) == 1 and all("/" in x for _n, x in norm) else ""
    out = []
    for n, x in norm:
        rel = x[len(prefix):] if prefix and x.startswith(prefix) else x
        parts = rel.split("/")
        if (not rel or rel.startswith("/") or ":" in rel or any(p in ("", ".", "..") for p in parts)
                or parts[0].lower() in PROTECTED):
            continue
        try:
            (root / rel).resolve().relative_to(root)
        except ValueError:
            continue
        out.append((n, rel))
    return out


IN_PROGRESS = Path("updates") / "in-progress.json"  # in the data folder while files are being replaced


def _restore(backup: Path, app_dir: Path, added: List[str], log_dir: Path) -> List[str]:
    """The previous version's files back from the backup and the files the new version added removed,
    file by file: one held open (Verbaliox.exe still closing) does not stop the others (found in the
    audit: the first locked file ended the restore and the user was told to reinstall). Returns the
    files that could not be put back."""
    failed: List[str] = []
    kept = set()
    with zipfile.ZipFile(backup) as bz:
        for info in bz.infolist():
            rel = info.filename
            kept.add(rel)
            dest = app_dir / rel
            for attempt in range(5):
                try:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with bz.open(info) as src:
                        _write_member(src, dest)
                    break
                except OSError:
                    if attempt == 4:
                        failed.append(rel)
                    else:
                        time.sleep(1.0)
    for rel in added:
        if rel not in kept:
            try:
                (app_dir / rel).unlink(missing_ok=True)
            except OSError:
                failed.append(rel)
    if failed:
        with open(log_dir / "update.log", "a", encoding="utf-8") as lf:
            lf.write("not put back: " + ", ".join(failed[:50]) + "\n")
    return failed


# An installation never takes this long: a mark older than this names no installer at work
INSTALL_MAX_SECONDS = 2 * 3600


def _boot_time() -> Optional[float]:
    """When Windows started (unix seconds); None when not known."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        k32 = ctypes.WinDLL("kernel32")
        k32.GetTickCount64.restype = ctypes.c_ulonglong
        return time.time() - k32.GetTickCount64() / 1000.0
    except Exception:  # noqa: BLE001
        return None


def _denied_is_running(since: Optional[float]) -> bool:
    """A process the app may not look at (access denied) has the installer's number. After a power cut the
    number may belong to a protected process of the next session, and every start would wait on «Идёт
    установка обновления» (found in the review): a mark written before Windows started, or long ago, names
    no installer at work."""
    if since is None:
        return True
    boot = _boot_time()
    if boot is not None and since < boot:
        return False
    return time.time() - since < INSTALL_MAX_SECONDS


def _process_running(pid: int, since: Optional[float] = None) -> bool:
    """True while the process `pid` runs. With `since` (when it wrote its mark), a process started after
    that moment is another program that got the same number, not the installer."""
    if not pid or pid < 0:
        return False
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.OpenProcess.restype = wintypes.HANDLE
            k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            k32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
            k32.CloseHandle.argtypes = [wintypes.HANDLE]
            h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if not h:
                return ctypes.get_last_error() == 5 and _denied_is_running(since)  # access denied: it exists
            try:
                code = wintypes.DWORD()
                if not k32.GetExitCodeProcess(h, ctypes.byref(code)) or code.value != 259:  # STILL_ACTIVE
                    return False
                if since is not None:
                    times = [wintypes.FILETIME() for _ in range(4)]
                    if k32.GetProcessTimes(h, *[ctypes.byref(t) for t in times]):
                        ft = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
                        if ft / 1e7 - 11644473600 > since + 2:
                            return False
                return True
            finally:
                k32.CloseHandle(h)
        except Exception:
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return _denied_is_running(since)
    except OSError:
        return False
    return True


def installer_running(data_dir: Path) -> bool:
    """An update is being installed now: its mark names a process that still runs. Its files must not be
    put back under it (found in the review: a start during the installation rolled the files back)."""
    try:
        info = json.loads((data_dir / IN_PROGRESS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(info, dict):
        return False
    try:
        return _process_running(int(info.get("pid") or 0), float(info["started"]) if info.get("started") else None)
    except (TypeError, ValueError):
        return False


def recover_interrupted(app_dir: Path, data_dir: Path) -> bool:
    """At start: an update cut off while it replaced files (the computer switched off, the process
    killed) left two versions mixed (found in the audit). The previous version is put back from the
    backup; libraries half installed are installed again by the launcher (setup.bat). True when done."""
    marker = data_dir / IN_PROGRESS
    if not marker.is_file() or installer_running(data_dir):  # the installer at work: not cut off
        return False
    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    try:
        info = json.loads(marker.read_text(encoding="utf-8"))
        backup = Path(info.get("backup") or "")
        if backup.is_file():
            _restore(backup, app_dir, list(info.get("added") or []), log_dir)
        if info.get("packages"):  # pip was at work: the launcher installs the previous libraries again
            mark = app_dir / ".venv" / "verbaliox-requirements.sha256"
            if mark.parent.is_dir():
                mark.write_text("interrupted-update", encoding="ascii")
        with open(log_dir / "update.log", "a", encoding="utf-8") as lf:
            lf.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} an update cut off half-way: the previous version put back\n")
    except Exception:
        with open(log_dir / "update.log", "a", encoding="utf-8") as lf:
            lf.write("recovery of an interrupted update failed:\n" + traceback.format_exc())
    marker.unlink(missing_ok=True)
    return True


def apply_update(zip_path: Path, app_dir: Path, data_dir: Path, report: Callable[[str], None]) -> None:
    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    backup = data_dir / "updates" / "backup.zip"
    old_req = _sha256(app_dir / "requirements.txt")
    old_dub_req = _dub_requirements_hash(app_dir)
    replaced: List[str] = []
    restore_packages: Optional[Callable[[], None]] = None

    with zipfile.ZipFile(zip_path) as z:
        files = archive_files(z.namelist(), app_dir)
        stale = _stale_code_files(app_dir, [rel for _n, rel in files])
        new_req = next((hashlib.sha256(z.read(n)).hexdigest() for n, rel in files if rel == "requirements.txt"), old_req)
        # The new files, their backup in the data folder and, with new libraries, room to install them
        size = sum(z.getinfo(n).file_size for n, _rel in files)
        _preflight(app_dir, 2 * size + 200_000_000 + (3_000_000_000 if new_req != old_req else 0))
        report(f"Резервная копия ({len(files)} файлов)…")
        with zipfile.ZipFile(backup, "w", zipfile.ZIP_DEFLATED) as bz:
            for rel in [rel for _n, rel in files] + stale:
                p = app_dir / rel
                if p.is_file():
                    bz.write(p, rel)
                    replaced.append(rel)
        kept_before = set(replaced)
        added = [rel for _n, rel in files if rel not in kept_before]
        marker = data_dir / IN_PROGRESS

        def mark(packages: bool = False) -> None:  # read at the next start if this process is cut off
            # the installer's process: a start of the program while it works does not take it for cut off
            marker.write_text(json.dumps({"backup": str(backup), "added": added, "packages": packages,
                                          "pid": os.getpid(), "started": started}), encoding="utf-8")

        started = time.time()

        mark()
        try:
            report("Замена файлов программы…")
            for i, (n, rel) in enumerate(files):
                dest = app_dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                for attempt in range(10):  # the launcher may still be closing its splash window
                    try:
                        with z.open(n) as src:
                            _write_member(src, dest)
                        break
                    except PermissionError:
                        if attempt == 9:
                            raise
                        time.sleep(1.0)
                if i % 50 == 0:
                    report(f"Замена файлов программы… {i}/{len(files)}")
            for rel in stale:
                (app_dir / rel).unlink(missing_ok=True)
            if _sha256(app_dir / "requirements.txt") != old_req:
                report("Установка библиотек Python (может занять несколько минут)…")
                mark(packages=True)
                py = app_dir / ".venv" / "Scripts" / "python.exe"
                uv = find_uv()
                # What is installed now: put back if the new libraries fail half way
                frozen = _freeze(py, uv)
                frozen_file: Optional[Path] = None
                if frozen:
                    frozen_file = data_dir / "updates" / "packages-before-update.txt"
                    frozen_file.write_text(frozen, encoding="utf-8")
                restore_packages = (lambda: _reinstall(py, uv, frozen_file, log_dir, backup))
                cmd = ([uv, "pip", "install", "--python", str(py), "-r", str(app_dir / "requirements.txt"),
                        "--require-hashes", "--index-strategy", "unsafe-best-match", "--extra-index-url", TORCH_INDEX]
                       if uv else
                       [str(py), "-m", "pip", "install", "-r", str(app_dir / "requirements.txt"),
                        "--require-hashes", "--extra-index-url", TORCH_INDEX])
                with open(log_dir / "update.log", "a", encoding="utf-8") as lf:
                    res = subprocess.run(cmd, cwd=str(app_dir), stdout=lf, stderr=subprocess.STDOUT,
                                         creationflags=_NO_WINDOW)
                if res.returncode != 0:
                    raise RuntimeError("Не удалось установить библиотеки (подробности в logs\\update.log)")
                mark_requirements(app_dir)
            if _dub_requirements_hash(app_dir) != old_dub_req:
                _mark_dub_outdated(app_dir, old_dub_req)
            marker.unlink(missing_ok=True)
        except Exception as e:
            report("Ошибка — восстановление прежней версии…")
            outcome = "restored"
            # Each step on its own: a failure here must not hide the original error
            try:
                if _restore(backup, app_dir, added, log_dir):
                    outcome = "broken"
            except Exception:
                outcome = "broken"
                with open(log_dir / "update.log", "a", encoding="utf-8") as lf:
                    lf.write("restore of the program files failed:\n" + traceback.format_exc())
            if restore_packages:
                report("Восстановление прежних библиотек Python…")
                try:
                    restore_packages()
                except Exception:
                    outcome = "broken"
                    with open(log_dir / "update.log", "a", encoding="utf-8") as lf:
                        lf.write("restore of the Python packages failed:\n" + traceback.format_exc())
                    # the launcher installs the libraries of the version put back at its next start
                    mark = app_dir / ".venv" / "verbaliox-requirements.sha256"
                    try:
                        if mark.parent.is_dir():
                            mark.write_text("interrupted-update", encoding="ascii")
                    except OSError:
                        pass
            marker.unlink(missing_ok=True)  # put back here (or told broken): nothing for the next start
            raise UpdateFailed(str(e), outcome) from e


def refresh_shell_icons() -> None:
    """Explorer shows the new icon of Verbaliox.exe on the desktop and Start menu shortcuts. It keeps
    the old picture in its icon cache after the file is replaced in place (found by the user: the
    shortcut kept the previous icon after an update that changed it). Never fails the update."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        SHCNE_ASSOCCHANGED, SHCNF_IDLIST = 0x08000000, 0x0000
        ctypes.windll.shell32.SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, None, None)
    except Exception:
        pass
    ie4uinit = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "ie4uinit.exe"
    if ie4uinit.is_file():  # rebuilds the icon cache of this user (Windows 10 and 11)
        try:
            subprocess.run([str(ie4uinit), "-show"], capture_output=True, timeout=30,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.SubprocessError):
            pass


def _main(argv: List[str]) -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("action")
    ap.add_argument("--zip", required=True)
    ap.add_argument("--app-dir", required=True)
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--pid", type=int, default=0)
    ap.add_argument("--no-restart", action="store_true")  # installed on exit: the user closed the app
    ap.add_argument("--restart-minimized", action="store_true")  # installed in the background: back in the tray
    ap.add_argument("--sha256", default="")  # the archive's sum checked against the signed release
    a = ap.parse_args(argv)
    app_dir, data_dir = Path(a.app_dir), Path(a.data_dir)

    ui = _ProgressWindow(visible=not a.restart_minimized)  # in the background: no window, only a failure is said
    ok, message = True, ""

    def work() -> None:
        nonlocal ok, message
        try:
            ui.set("Ожидание закрытия Verbaliox…")
            if a.pid and not _wait_for_exit(a.pid):
                # Replacing files under a running program would mix two versions
                raise UpdateFailed("Verbaliox не закрылся за две минуты. Закройте программу и установите обновление снова.")
            if a.sha256 and _sha256(Path(a.zip)) != a.sha256.lower():
                raise UpdateFailed("Архив обновления изменился после проверки — обновление отменено")
            apply_update(Path(a.zip), app_dir, data_dir, ui.set)
            refresh_shell_icons()
            ui.set("Готово." if a.no_restart else "Готово. Запуск Verbaliox…")
            (data_dir / FAILED_NAME).unlink(missing_ok=True)
        except Exception as e:
            ok, message = False, f"{e}\n{OUTCOME_TEXT[getattr(e, 'outcome', 'untouched')]}"
            with open(data_dir / "logs" / "update.log", "a", encoding="utf-8") as lf:
                lf.write(traceback.format_exc())
            try:  # this archive is not installed by itself again (failed_before)
                (data_dir / FAILED_NAME).write_text(json.dumps({"sha256": a.sha256 or _sha256(Path(a.zip)),
                                                                "at": time.time(), "error": str(e)[:300]}), encoding="utf-8")
            except OSError:
                pass
        finally:
            launcher = app_dir / "Verbaliox.exe"
            pythonw = app_dir / ".venv" / "Scripts" / "pythonw.exe"
            if a.restart_minimized and pythonw.is_file():  # after a failure too: the previous version is back
                subprocess.Popen([str(pythonw), str(app_dir / "run.py"), "--minimized"], cwd=str(app_dir))
            elif launcher.is_file() and not (a.no_restart and ok):
                subprocess.Popen([str(launcher)], cwd=str(app_dir))
            ui.close(None if ok else f"Обновление не установлено: {message}")

    threading.Thread(target=work, daemon=True).start()
    ui.run()
    return 0 if ok else 1


class _ProgressWindow:
    """A small always-on-top window; falls back to nothing if tkinter is unavailable. visible=False
    (installed in the background): no window, a failure is told in a message box."""

    def __init__(self, visible: bool = True) -> None:
        self._tk = None
        self._msg = "Обновление Verbaliox…"
        self._visible = visible
        if not visible:
            return
        try:
            import tkinter as tk

            root = tk.Tk()
            root.title("Обновление Verbaliox")
            root.geometry("420x110")
            root.configure(bg="#1c1c1e")
            root.attributes("-topmost", True)
            root.resizable(False, False)
            tk.Label(root, text="Обновление Verbaliox", fg="white", bg="#1c1c1e",
                     font=("Segoe UI Semibold", 12)).pack(anchor="w", padx=20, pady=(18, 4))
            self._var = tk.StringVar(value=self._msg)
            tk.Label(root, textvariable=self._var, fg="#98989d", bg="#1c1c1e",
                     font=("Segoe UI", 9), wraplength=380, justify="left").pack(anchor="w", padx=20)
            self._tk = root
        except Exception:
            self._tk = None

    def set(self, text: str) -> None:
        self._msg = text
        if self._tk is not None:
            self._tk.after(0, lambda: self._var.set(text))

    def close(self, error: Optional[str]) -> None:
        if self._tk is None:
            if error and not self._visible and sys.platform == "win32":
                import ctypes

                ctypes.windll.user32.MessageBoxW(None, error, "Verbaliox", 0x10 | 0x40000)  # error, on top
            return

        def _close() -> None:
            if error:
                from tkinter import messagebox

                messagebox.showerror("Verbaliox", error, parent=self._tk)
            self._tk.destroy()

        self._tk.after(0, _close)

    def run(self) -> None:
        if self._tk is not None:
            self._tk.mainloop()
        else:
            while threading.active_count() > 1:
                time.sleep(0.2)


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
