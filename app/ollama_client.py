import json
import re
import os
import shutil
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx

from app.audio_utils import format_timestamp
from app.database import get_all_settings, update_settings

RECOMMENDED_LLM_MODELS: List[Dict[str, Any]] = [
    # Measured on 9 real meetings at 10, 8 and 6 GB and without a GPU (bench-report/llm-profiles.md)
    {
        "id": "gemma4:e4b",
        "min_ollama": "0.30.9",  # what the model asks of Ollama in its registry config
        "name": "Gemma 4 E4B",
        "badge": "6.6 GB · Apache",
        "size": "6.6 GB",
        "vram": "8+ GB VRAM",
        "license": "Apache",
        "desc_ru": "Google Gemma 4 E4B (≈4 млрд эффективных параметров). Лучший результат в замерах программы на реальных встречах: находит больше всех задач и решений; протокол часовой встречи — около 1,5 минуты на видеокарте. Рекомендуется для видеокарт от 8 ГБ.",
        "desc_en": "Google Gemma 4 E4B (≈4B effective parameters). The best result in the app's measurements on real meetings: it finds the most tasks and decisions; an hour's protocol in about 1.5 minutes on a GPU. Recommended for cards with 8 GB or more.",
        "good_ru": "Задачи и решения встречи, протоколы на русском и английском почти без выдуманных чисел; в памяти около 5 ГБ, помещается вместе с распознаванием речи",
        "good_en": "Tasks and decisions of a meeting, summaries in Russian and English with almost no made-up numbers; about 5 GB in memory, fits next to speech recognition",
        "weak_ru": "Находит не все задачи и иногда добавляет лишние — проверяйте список; длинный протокол иногда обрывается в конце; без видеокарты протокол часа — около 11 минут",
        "weak_en": "Does not find every task and sometimes adds extra ones, so check the list; a long protocol is sometimes cut at the end; without a GPU an hour's protocol takes about 11 minutes",
        "min_vram_gb": 8,  # 0: fine without a GPU too
        "cpu_ok": False,
    },
    {
        "id": "gemma4:e2b",
        "min_ollama": "0.30.9",  # what the model asks of Ollama in its registry config
        "name": "Gemma 4 E2B",
        "badge": "4.6 GB · Apache",
        "size": "4.6 GB",
        "vram": "4–8 GB / CPU",
        "license": "Apache",
        "desc_ru": "Google Gemma 4 E2B (≈2 млрд эффективных параметров). В замерах на реальных встречах находит заметно больше задач, чем Qwen3.5 4B; протокол часовой встречи на процессоре — около 5 минут. Для видеокарт до 8 ГБ и компьютеров без видеокарты.",
        "desc_en": "Google Gemma 4 E2B (≈2B effective parameters). On real meetings it found noticeably more tasks than Qwen3.5 4B; an hour's protocol on the CPU in about 5 minutes. For cards under 8 GB and computers without one.",
        "good_ru": "Лёгкая: около 3 ГБ видеопамяти; протоколы на русском и английском без выдуманных чисел; лучший выбор для ноутбуков",
        "good_en": "Light: about 3 GB of video memory; summaries in Russian and English without made-up numbers; the best choice for laptops",
        "weak_ru": "Находит меньше задач, чем Gemma 4 E4B, — проверяйте список",
        "weak_en": "Finds fewer tasks than Gemma 4 E4B, so check the list",
        "min_vram_gb": 4,  # 0: fine without a GPU too
        "cpu_ok": True,
    },
]

_LLM_DISPLAY_NAMES: Dict[str, str] = {
    "gemma4:e4b": "Gemma 4 E4B",
    "gemma4:e2b": "Gemma 4 E2B",
    "qwen3:8b": "Qwen3 8B",
    "qwen3:14b": "Qwen3 14B",
    "qwen3:4b": "Qwen3 4B",
    "qwen3.5:4b": "Qwen3.5 4B",
    # no longer offered (bench-report/report.md), named still for those who have them; qwen3:8b, qwen3:14b,
    # qwen3.5:4b and qwen2.5:1.5b: one of the two gemma4 finds more, faster, in less memory
    # (bench-report/llm-profiles.md; 14b and 1.5b not measured)
    "qwen2.5:7b": "Qwen 7B Standard",
    "qwen2.5:14b": "Qwen 14B Pro",
    "mistral:7b": "Mistral 7B",
    "qwen2.5:1.5b": "Qwen Lite",
}


def format_llm_model_name(model_id: str) -> str:
    """
    Formats a technical Ollama tag (e.g. 'qwen2.5:1.5b') into a clean human-readable title
    without colons or version dots running together.
    """
    raw = (model_id or "").strip()
    if not raw:
        return "Ollama AI"
    lower = raw.lower()
    if lower in _LLM_DISPLAY_NAMES:
        return _LLM_DISPLAY_NAMES[lower]
    for k, v in _LLM_DISPLAY_NAMES.items():
        if lower.startswith(k):
            return v
    # Clean fallback for custom models: e.g. 'llama3.2:8b' -> 'Llama 8B'
    parts = raw.split(":")
    family = parts[0].replace("-", " ").replace("_", " ")
    # Strip trailing version numbers/dots from family name if followed by size tag
    import re
    family_clean = re.sub(r"[\d\.]+$", "", family).strip().title() or family.title()
    if len(parts) > 1 and parts[1].lower() != "latest":
        tag = parts[1].upper().replace(".", " ")
        return f"{family_clean} {tag}"
    return family_clean


_pull_state: Dict[str, Any] = {
    "active": False,
    "model": "",
    "status": "Ожидание",
    "progress": 0,
    "downloaded_mb": 0.0,
    "total_mb": 0.0,
    "error": "",
    "logs": [],
}
_pull_lock = threading.Lock()


def _append_log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    logs = _pull_state.get("logs", [])
    logs.append(line)
    if len(logs) > 80:
        logs[:] = logs[-80:]
    _pull_state["logs"] = logs
    _pull_state["status"] = msg


def find_ollama_executable() -> Optional[str]:
    in_path = shutil.which("ollama")
    if in_path:
        return in_path

    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        candidate = Path(local_app_data) / "Programs" / "Ollama" / "ollama.exe"
        if candidate.exists():
            return str(candidate)
    return None


def _ollama_address(base_url: Optional[str] = None) -> tuple:
    """(host, port) of the Ollama address in Settings (default 127.0.0.1:11434)."""
    from urllib.parse import urlparse

    if not base_url:
        base_url = get_all_settings().get("ollama_url") or "http://127.0.0.1:11434"
    u = urlparse(base_url if "://" in base_url else "http://" + base_url)
    host = (u.hostname or "127.0.0.1").replace("localhost", "127.0.0.1")
    return host, u.port or (443 if u.scheme == "https" else 11434 if host == "127.0.0.1" else 80)


def _is_ollama_port_open(host: Optional[str] = None, port: Optional[int] = None) -> bool:
    import socket

    if host is None or port is None:
        h, p = _ollama_address()
        host, port = host or h, port or p
    try:
        with socket.create_connection((host, port), timeout=0.15 if host == "127.0.0.1" else 0.8):
            return True
    except OSError:
        return False


_started_serve: Optional["subprocess.Popen"] = None  # the `ollama serve` the app started itself


def release_on_exit(timeout: float = 1.5) -> List[str]:
    """When the app closes: an Ollama the user started (not ours, which ends with the app) is left running,
    but lets go of the models it keeps in memory. Quick and never raises. Returns the models asked to go."""
    if _started_serve is not None and _started_serve.poll() is None:
        return []  # ours: ended with the app (app/shutdown.py)
    try:
        from app.database import get_all_settings

        base = (get_all_settings().get("ollama_url") or "http://127.0.0.1:11434").replace("localhost", "127.0.0.1").rstrip("/")
        host, port = _ollama_address(base)
        if host != "127.0.0.1" or not _is_ollama_port_open(host, port):
            return []  # another computer's Ollama is not ours to empty
        with httpx.Client(timeout=timeout) as client:
            names = [m.get("name") or m.get("model") for m in client.get(f"{base}/api/ps").json().get("models") or []]
            for name in [n for n in names if n]:
                try:
                    client.post(f"{base}/api/generate", json={"model": name, "keep_alive": 0})
                except httpx.HTTPError:
                    pass
        return [n for n in names if n]
    except Exception as e:
        print(f"[ollama] models not let go on exit: {e}", flush=True)
        return []


def ensure_ollama_running(base_url: str = "http://127.0.0.1:11434", auto_start: bool = True) -> bool:
    host, port = _ollama_address(base_url)
    if _is_ollama_port_open(host, port):
        return True
    if host != "127.0.0.1":
        return False  # Ollama on another computer is not started from here

    if not auto_start:
        return False

    exe = find_ollama_executable()
    if exe:
        try:
            # One model in memory at a time and one answer at a time, unless the user set otherwise:
            # two models side by side took the computer's memory and slowed everything down
            env = {**os.environ}
            env.setdefault("OLLAMA_MAX_LOADED_MODELS", "1")
            env.setdefault("OLLAMA_NUM_PARALLEL", "1")
            try:  # the video memory left to the system (app/mem_reserve.py): what does not fit goes to the processor
                from app.mem_reserve import ollama_env

                for k, v in ollama_env().items():
                    env.setdefault(k, v)
            except Exception:
                traceback.print_exc()
            proc = subprocess.Popen(
                [exe, "serve"],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            )
            # Ours: it ends with the app, its runners and the model in memory too (it stayed after the app
            # was closed: reported by the user); bound to the app's job, it ends on a crash as well
            from app.shutdown import track

            track(proc)
            global _started_serve
            _started_serve = proc
            for _ in range(80):  # a cold start (first run, slow disk) can take many seconds
                time.sleep(0.25)
                if _is_ollama_port_open(host, port):
                    return True
        except Exception:
            pass
    return False


def _user_env(name: str) -> str:
    """A user environment variable as saved in the registry (a process started before it was set
    does not see it in os.environ)."""
    if sys.platform != "win32":
        return ""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            return str(winreg.QueryValueEx(key, name)[0]).strip()
    except OSError:
        return ""


def ollama_models_dir() -> str:
    """Where Ollama keeps its models (OLLAMA_MODELS, or .ollama\\models in the user's folder)."""
    custom = os.environ.get("OLLAMA_MODELS", "").strip() or _user_env("OLLAMA_MODELS")
    return custom or str(Path.home() / ".ollama" / "models")


def models_on_disk(models_dir: Optional[str] = None) -> List[str]:
    """The models Ollama has downloaded, read from its folder (manifests/<registry>/<namespace>/<model>/<tag>)
    without starting it: named as its /api/tags names them («gemma4:e4b», «user/model:tag», «hf.co/user/model:tag»).
    The program no longer keeps Ollama running, and a model it already has must not read as missing."""
    root = Path(models_dir or ollama_models_dir()) / "manifests"
    names: List[str] = []
    try:
        for tag in root.glob("*/*/*/*"):
            if not tag.is_file() or tag.name.startswith("."):
                continue
            model, namespace, registry = tag.parent.name, tag.parent.parent.name, tag.parent.parent.parent.name
            if registry == "registry.ollama.ai":
                name = f"{model}:{tag.name}" if namespace == "library" else f"{namespace}/{model}:{tag.name}"
            else:
                name = f"{registry}/{namespace}/{model}:{tag.name}"
            names.append(name)
    except OSError:
        return []
    return sorted(set(names))


def use_program_folder_for_ollama_models() -> None:
    """Before the app installs Ollama: its models (gigabytes each) go next to the program, as the speech
    models do, instead of the system disk. Only when nobody chose a folder (OLLAMA_MODELS) and Ollama
    has no models in its default folder yet, which would be left behind."""
    if sys.platform != "win32" or os.environ.get("OLLAMA_MODELS") or _user_env("OLLAMA_MODELS"):
        return
    if (Path.home() / ".ollama" / "models").exists():
        return
    from app.paths import MODELS_DIR

    target = MODELS_DIR / "ollama"
    try:
        target.mkdir(parents=True, exist_ok=True)
        os.environ["OLLAMA_MODELS"] = str(target)  # the server this app starts
        subprocess.run(["setx", "OLLAMA_MODELS", str(target)], capture_output=True, timeout=30,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))  # Ollama started by itself
    except (OSError, subprocess.SubprocessError):
        pass


def delete_ollama_model(name: str) -> None:
    base = (get_all_settings().get("ollama_url") or "http://127.0.0.1:11434").replace("localhost", "127.0.0.1").rstrip("/")
    if not _is_ollama_port_open(*_ollama_address(base)):
        raise RuntimeError("Ollama не запущена — запустите её, чтобы удалить модель")
    with httpx.Client(timeout=30.0) as client:
        r = client.request("DELETE", f"{base}/api/delete", json={"model": name})
    if r.status_code == 404:
        raise RuntimeError("Модель не найдена в Ollama")
    r.raise_for_status()


# Models that only turn text into vectors (search by meaning, app/semantic.py): Ollama answers a
# chat with them by 400 "does not support chat", so they are never picked to write text
_EMBEDDING_HINTS = ("embed", "bge-", "bge:", "e5-", "minilm", "gte-", "snowflake-arctic")


def is_embedding_model(name: str) -> bool:
    n = str(name or "").lower()
    semantic = (get_all_settings().get("semantic_model") or "bge-m3").lower().split(":")[0]
    return n.split(":")[0] == semantic or any(h in n for h in _EMBEDDING_HINTS)


def chat_models(models: List[str]) -> List[str]:
    return [m for m in models if not is_embedding_model(m)]


def raise_for_ollama(resp: "httpx.Response") -> None:
    """Like raise_for_status, with Ollama's own words: its 400 says what is wrong ("model does
    not support chat"), httpx's message only gives the status and the address."""
    if resp.status_code < 400:
        return
    try:
        resp.read()
        err = resp.json().get("error") or resp.text
    except Exception:
        err = getattr(resp, "text", "") or ""
    err = str(err).strip()[:200]
    if re.search(r"memory|alloc|out of memory|oom", err, re.I):
        # the memory left to the system (app/mem_reserve.py) is kept: the model does not fit in the rest
        raise RuntimeError(f"Модели не хватило памяти ({err}). Закройте другие программы, выберите модель меньшего размера "
                           "или уменьшите запас в «Настройки → Общие → Оставлять системе».")
    raise RuntimeError(f"Ollama ответила ошибкой {resp.status_code}: {err}")


def get_ollama_status(base_url: Optional[str] = None) -> Dict[str, Any]:
    settings = get_all_settings()
    if not base_url:
        base_url = settings.get("ollama_url", "http://127.0.0.1:11434")
    base_url = base_url.replace("localhost", "127.0.0.1")
    active_model = settings.get("ollama_model", "gemma4:e2b")

    exe = find_ollama_executable()
    # Status polling never starts background processes: Ollama is only launched after an
    # explicit user action (model download or AI summary request).
    running = _is_ollama_port_open(*_ollama_address(base_url))
    models: List[str] = []
    if running:
        try:
            with httpx.Client(timeout=0.8) as client:
                resp = client.get(f"{base_url.rstrip('/')}/api/tags")
                if resp.status_code == 200:
                    data = resp.json()
                    models = [m["name"] for m in data.get("models", [])]
        except Exception:
            running = False
    if not running:
        # started only when analysis needs it: what it has downloaded is on the disk
        models = models_on_disk()

    # The embedding model chosen as the analysis model (it was listed among them before 0.5.1): the
    # first model that writes text takes its place, once
    if models and is_embedding_model(active_model):
        usable = chat_models(models)
        if usable:
            active_model = usable[0]
            update_settings({"ollama_model": active_model})
            print(f"[ollama] analysis model was an embedding model, now {active_model}", flush=True)

    # Build catalog with installed flags
    catalog = []
    installed_set = set(models)
    for item in RECOMMENDED_LLM_MODELS:
        is_inst = item["id"] in installed_set or any(
            m.startswith(item["id"] + "-") for m in installed_set
        )
        catalog.append({**item, "installed": is_inst})

    # Also append any other custom models the user has in Ollama
    known_ids = {item["id"] for item in RECOMMENDED_LLM_MODELS}
    for m in chat_models(models):  # an embedding model is not offered as the analysis model
        if m not in known_ids:
            catalog.append(
                {
                    "id": m,
                    "name": format_llm_model_name(m),
                    "badge": "Локальная",
                    "size": "Локальная",
                    "vram": "GPU/CPU",
                    "desc_ru": "Установленная пользователем модель в Ollama",
                    "desc_en": "User-installed Ollama model",
                    "installed": True,
                }
            )

    return {
        "installed": exe is not None or running,
        "running": running,
        "models_dir": ollama_models_dir(),
        "base_url": base_url,
        "active_model": active_model,
        "models": models,
        "chat_models": chat_models(models),  # the ones that can write text (not embedding models)
        "catalog": catalog,
        "pull_state": dict(_pull_state),
    }


def _close_ollama_app(seconds: float = 10.0) -> None:
    """The Ollama installer opens its own app (a window and a tray icon) when it ends: it is closed, the
    program starts the Ollama server itself, without a window, when analysis needs it."""
    if sys.platform != "win32":
        return
    flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    end = time.time() + seconds
    while time.time() < end:  # the app may appear a moment after the installer ends
        subprocess.run(["taskkill", "/F", "/IM", "ollama app.exe"], capture_output=True, creationflags=flags)
        time.sleep(0.5)


def _install_ollama_if_needed() -> bool:
    """
    If Ollama is not installed on Windows, installs it automatically via winget
    and streams progress into _pull_state['logs'].
    """
    if find_ollama_executable() is not None:
        return True

    _append_log("Сервер Ollama не найден на ПК. Запускаю автоматическую установку Ollama через winget")
    use_program_folder_for_ollama_models()
    _pull_state["progress"] = 5

    cmd = [
        "winget",
        "install",
        "-e",
        "--id",
        "Ollama.Ollama",
        "--accept-source-agreements",
        "--accept-package-agreements",
        "--silent",
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
    )

    if proc.stdout:
        for line in proc.stdout:
            clean = line.strip()
            if clean and len(clean) > 3 and not all(c in "-\\|/" for c in clean):
                _append_log(f"winget: {clean[:100]}")

    proc.wait()
    time.sleep(2.0)
    _close_ollama_app()

    if find_ollama_executable() is not None:
        _append_log("Ollama установлена на компьютер.")
        return True

    return False


def _version_tuple(text: str) -> Tuple[int, ...]:
    """'0.30.9' -> (0, 30, 9); '0.31.0-rc1' -> (0, 31, 0)"""
    return tuple(int(n) for n in re.findall(r"\d+", str(text).split("-", 1)[0])[:3])


def ollama_too_old(model_name: str, base_url: str) -> Optional[Tuple[str, str]]:
    """(installed, needed) when the running Ollama is older than the model asks for; None when it is
    new enough, the model asks for nothing, or the version is not known. An old Ollama refused gemma4
    with an English message of its own, or a bare «412»."""
    needed = next((m.get("min_ollama") for m in RECOMMENDED_LLM_MODELS if m["id"] == model_name), None)
    if not needed:
        return None
    try:
        r = httpx.get(f"{base_url.rstrip('/')}/api/version", timeout=5.0)
        installed = str(r.json().get("version") or "")
    except Exception:
        return None
    if not installed or not _version_tuple(installed):
        return None
    return (installed, needed) if _version_tuple(installed) < _version_tuple(needed) else None


def start_model_pull(
    model_name: str,
    base_url: Optional[str] = None,
    allow_install: bool = False,
) -> Dict[str, Any]:
    """
    Starts downloading an Ollama model in a background thread with real-time logs and progress.
    Ollama itself is installed via winget only when the user explicitly confirmed it (allow_install).
    """
    if not base_url:
        base_url = get_all_settings().get("ollama_url", "http://127.0.0.1:11434")
    base_url = base_url.replace("localhost", "127.0.0.1")
    pretty_name = format_llm_model_name(model_name)

    with _pull_lock:
        if _pull_state["active"]:
            return dict(_pull_state)
        _pull_state.update(
            {
                "active": True,
                "model": model_name,
                "status": f"Подготовка к загрузке {pretty_name}",
                "progress": 1,
                "downloaded_mb": 0.0,
                "total_mb": 0.0,
                "error": "",
                "logs": [],
            }
        )
        _append_log(f"Запрошена установка модели {pretty_name}")

    def _worker():
        try:
            # 1. Check / Install Ollama if not present
            if not ensure_ollama_running(base_url):
                if find_ollama_executable() is None and not allow_install:
                    raise RuntimeError(
                        "Ollama не установлена. Подтвердите установку в окне настроек или установите её вручную: https://ollama.com/download"
                    )
                installed_ok = _install_ollama_if_needed()
                if not installed_ok:
                    raise RuntimeError(
                        "Не удалось автоматически установить Ollama. Скачайте установщик с https://ollama.com/download"
                    )
                _append_log("Запуск фоновой службы Ollama")
                if not ensure_ollama_running(base_url):
                    raise RuntimeError("Ollama установлена, но локальный сервер ещё не ответил. Попробуйте через 5 секунд.")

            _append_log("Подключение к локальному серверу Ollama")
            old = ollama_too_old(model_name, base_url)
            if old:
                raise RuntimeError(
                    f"Для модели {pretty_name} нужна Ollama {old[1]} или новее, а установлена {old[0]}. "
                    "Обновите Ollama (https://ollama.com/download) и нажмите «Скачать» ещё раз."
                )
            _pull_state["progress"] = 8

            last_logged_status = ""
            last_logged_pct = -5

            with httpx.Client(timeout=None) as client:
                with client.stream(
                    "POST",
                    f"{base_url.rstrip('/')}/api/pull",
                    json={"name": model_name, "stream": True},
                ) as resp:
                    resp.raise_for_status()
                    for line in resp.iter_lines():
                        if not line:
                            continue
                        data = json.loads(line)
                        if "error" in data and data["error"]:
                            raise RuntimeError(str(data["error"]))

                        status_txt = data.get("status", "Загрузка")
                        total = data.get("total", 0)
                        completed = data.get("completed", 0)

                        if total and total > 0:
                            dl_mb = round(completed / (1024 * 1024), 1)
                            tot_mb = round(total / (1024 * 1024), 1)
                            pct = int(round((completed / total) * 100))
                            _pull_state.update(
                                {
                                    "downloaded_mb": dl_mb,
                                    "total_mb": tot_mb,
                                    "progress": max(1, min(99, pct)),
                                    "status": f"Скачивание {pretty_name} — {dl_mb} из {tot_mb} МБ ({pct}%)",
                                }
                            )
                            if pct - last_logged_pct >= 10:
                                last_logged_pct = pct
                                _append_log(f"Скачивание {pretty_name} — {dl_mb} / {tot_mb} МБ ({pct}%)")
                        else:
                            _pull_state["status"] = status_txt
                            if status_txt != last_logged_status:
                                last_logged_status = status_txt
                                _append_log(f"Ollama — {status_txt}")

            # Automatically set this newly downloaded model as the active LLM model
            update_settings({"ollama_model": model_name})
            _append_log(f"Модель {pretty_name} скачана и выбрана как активная.")
            _pull_state.update(
                {
                    "active": False,
                    "status": f"Модель {pretty_name} установлена и активна",
                    "progress": 100,
                }
            )
        except Exception as e:
            _append_log(f"ОШИБКА: {e}")
            _pull_state.update(
                {
                    "active": False,
                    "status": f"Ошибка: {e}",
                    "error": str(e),
                }
            )

    threading.Thread(target=_worker, daemon=True).start()
    return dict(_pull_state)


# A long segment (one speaker talking for a minute) gets a time stamp for every phrase inside it,
# so the analysis can point to the moment, not only to where the speaker started
LINE_SPLIT_SEC = 6.0
LINE_MAX_SEC = 15.0
_SENTENCE_END = (".", "!", "?", "…", ";")


def _segment_parts(seg: Dict[str, Any]) -> List[tuple]:
    """(start, text) pieces of a segment: at sentence ends after LINE_SPLIT_SEC, at the latest after
    LINE_MAX_SEC. Segments without word timings or short ones stay whole."""
    words = [w for w in seg.get("words") or [] if str(w.get("word") or "").strip()]
    start = float(seg.get("start", 0.0) or 0.0)
    end = float(seg.get("end", start) or start)
    text = (seg.get("text") or "").strip()
    if not words or end - start <= LINE_SPLIT_SEC:
        return [(start, text)]
    parts, cur, cur_start = [], [], None
    for w in words:
        if cur_start is None:
            cur_start = float(w.get("start", start) or start)
        cur.append(str(w.get("word")))
        span = float(w.get("end", cur_start) or cur_start) - cur_start
        word = str(w.get("word")).strip()
        if (span >= LINE_SPLIT_SEC and word.endswith(_SENTENCE_END)) or span >= LINE_MAX_SEC:
            parts.append((cur_start, "".join(cur).strip()))
            cur, cur_start = [], None
    if cur:
        parts.append((cur_start if cur_start is not None else start, "".join(cur).strip()))
    # Word timings follow the original recognition: after an edit the words may no longer match
    joined = " ".join(p[1] for p in parts)
    if _normalize(joined) != _normalize(text):
        return [(start, text)]
    return parts


def _normalize(text: str) -> str:
    return re.sub(r"\W+", "", (text or "").casefold())


def build_transcript_lines(
    segments: List[Dict[str, Any]],
    speakers: Dict[str, Dict[str, Any]],
) -> List[str]:
    lines = []
    for seg in segments:
        spk_id = seg.get("speaker", "SPEAKER_00")
        spk_name = speakers.get(spk_id, {}).get("name", spk_id)
        for i, (start, text) in enumerate(_segment_parts(seg)):
            ts = format_timestamp(start)
            # The speaker is named once per segment; its continuation lines only carry the time
            lines.append(f"[{ts}] {spk_name}: {text}" if i == 0 else f"[{ts}] {text}")
    return lines


_UNNAMED_RU = re.compile(r"^Участник[ _]?(\d+)$", re.I)


def speakers_in_language(speakers: Dict[str, Dict[str, Any]], answer_lang: Optional[str]) -> Dict[str, Dict[str, Any]]:
    """The unnamed speakers as the answer's language calls them: «Участник 2» is «Speaker 2» for an English
    overview (an English protocol mixed «Участник» and «Participant», and once wrote «Uчастник» with a
    Latin U, bench-report/analysis-chain.md). Named speakers stay as they are."""
    if not str(answer_lang or "").lower().startswith("en"):
        return speakers
    out = {}
    for key, sp in (speakers or {}).items():
        name = str((sp or {}).get("name") or "") if isinstance(sp, dict) else ""
        m = _UNNAMED_RU.match(name.strip())
        out[key] = {**sp, "name": f"Speaker {m.group(1)}"} if m else sp
    return out


def _chunk_lines(lines: List[str], max_chars: int) -> List[str]:
    chunks: List[str] = []
    current: List[str] = []
    size = 0
    for line in lines:
        if current and size + len(line) + 1 > max_chars:
            chunks.append("\n".join(current))
            current, size = [], 0
        current.append(line)
        size += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


# A transcript up to this size is analysed in one request (fits num_ctx together with the prompt).
# Longer recordings are summarised chunk by chunk first, so nothing in the middle is dropped.
# These are the sizes for a card under 8 GB and for the processor; see llm_context_scale.
SINGLE_PASS_MAX_CHARS = 20000
CHUNK_MAX_CHARS = 14000
LLM_NUM_CTX = 16384
LLM_MAX_ANSWER_TOKENS = 3072  # the longest overview or chapters run to ~1500 tokens
# With a 32k context: the note of a part of an hour-long recording (3800–4600 tokens) and the protocol in steps
# (3600–5300) were cut at 3072 and asked again, 15–30 s each (bench-report/analysis-chain.md)
LLM_MAX_ANSWER_TOKENS_LARGE = 6144
MFU_SUMMARY_CHARS = 6000     # the organizer's follow-up in every summary request (as much as the notes)
LARGE_CONTEXT_VRAM_GB = 7.5   # an "8 GB" card reports a little under 8
CONTEXT_SCALE: Optional[float] = None  # set by tools/llm_bench.py --ctx; None: chosen by the card


def llm_context_scale() -> float:
    """2 on a card of 8 GB and more: the context doubles to 32k and a recording is read in bigger
    parts (an hour in 3 parts instead of 5). Measured on the PC (bench-report/llm-profiles.md): the
    protocol is ready 1.5-2 times sooner, no worse, for 0.3-0.5 GB more. A 6 GB card and the
    processor keep 16k: there the longer context costs memory and time the model does not have."""
    if CONTEXT_SCALE is not None:
        return CONTEXT_SCALE
    try:
        from app.hardware import _gpu_probe

        gpu = _gpu_probe()
    except Exception:
        gpu = None
    return 2.0 if gpu and float(gpu[1] or 0) >= LARGE_CONTEXT_VRAM_GB else 1.0


def llm_num_ctx() -> int:
    return int(LLM_NUM_CTX * llm_context_scale())


def llm_max_answer_tokens() -> int:
    """The answer limit: more room with the 32k context of a card of 8 GB and more (16k keeps its room
    for the transcript)."""
    return LLM_MAX_ANSWER_TOKENS_LARGE if llm_num_ctx() >= 32768 else LLM_MAX_ANSWER_TOKENS


def single_pass_max_chars() -> int:
    return int(SINGLE_PASS_MAX_CHARS * llm_context_scale())


def chunk_max_chars() -> int:
    return int(CHUNK_MAX_CHARS * llm_context_scale())

_LANG_PHRASES: Dict[str, str] = {
    "ru": "на русском языке",
    "en": "на английском языке",
    "uk": "на украинском языке",
    "be": "на белорусском языке",
    "kk": "на казахском языке",
    "de": "на немецком языке",
    "fr": "на французском языке",
    "es": "на испанском языке",
    "it": "на итальянском языке",
    "pt": "на португальском языке",
    "zh": "на китайском языке",
    "ja": "на японском языке",
}


def _lang_phrase(code: Optional[str]) -> str:
    key = (code or "").strip().lower()[:2]
    return _LANG_PHRASES.get(key, "на том же языке, на котором ведётся запись")


SYSTEM_GROUNDING_PROMPT = (
    "Ты — аккуратный ассистент для анализа расшифровок аудио- и видеозаписей в программе Verbaliox. "
    "Анализируй ТОЛЬКО реальный текст предоставленной расшифровки.\n"
    "ПРАВИЛА:\n"
    "1. Опирайся только на факты, фразы, предметы и имена, которые явно есть в тексте расшифровки.\n"
    "2. Не выдумывай имена людей, встречи, проекты, решения или задачи, которых нет в исходном тексте.\n"
    "3. Запись может быть любого жанра: интервью, монолог, обзор, лекция, подкаст, бытовой разговор, видеоролик или беседа. "
    "Описывай ровно то, о чём реально говорят спикеры.\n"
    "4. Не повторяй одну и ту же фразу несколько раз. Пиши грамотно {lang} в формате Markdown без эмодзи.\n"
    "5. Не оформляй цитаты и ответы блоками кода (```): цитируй обычным текстом или через «>». "
    "Таймкоды пиши в квадратных скобках: [ММ:СС] или диапазоном [ММ:СС–ММ:СС].\n"
    "6. Называй участников ровно так, как они подписаны перед репликами в расшифровке (например, «Участник 2»). "
    "Не заменяй их на «Пользователь», «Спикер», «Собеседник» и не придумывай им имена; имя из самого разговора "
    "используй, только если в тексте явно сказано, что это он."
)

SUMMARY_TEMPLATES: Dict[str, str] = {
    # Result first, then the talk (the order of the Teams Facilitator's notes: decisions, open questions
    # and next steps in sight; the discussion grouped by topic, not by the clock)
    "protocol": (
        "Составь точный структурированный обзор приведённой ниже расшифровки записи {lang} в формате Markdown (без эмодзи).\n\n"
        "Используй следующую структуру (заголовки тоже пиши на языке ответа):\n"
        "## Краткое содержание\n"
        "(2–3 предложения: кто говорит, о чём речь и к чему пришли — строго по тексту расшифровки)\n\n"
        "## Решения\n"
        "(О чём договорились или что решили — по пунктам, с таймкодами `[ММ:СС]`. Если решений не было, "
        "напиши одной строкой без пункта: «Решений не принималось»)\n\n"
        "## Открытые вопросы\n"
        "(Что осталось нерешённым, спорным или отложено на потом и к чему нужно вернуться — по пунктам, с таймкодами. "
        "Если таких нет, напиши одной строкой без пункта: «Открытых вопросов нет»)\n\n"
        "## Следующие шаги\n"
        "(Кто что делает дальше и к какому сроку, если он прозвучал, — коротко, по пункту на человека или действие. "
        "Если никто ничего не взял на себя, напиши одной строкой без пункта: «Следующие шаги не назывались»)\n\n"
        "## Обсуждение по темам\n"
        "(Сгруппируй разговор по темам, а не по порядку времени: подзаголовок `###` на тему, под ним по пунктам, "
        "что сказали и какие мнения прозвучали, с таймкодами `[ММ:СС]`)\n\n"
        "## Упомянутые имена, объекты и детали\n"
        "(Какие имена, предметы, места, цифры или конкретные факты прозвучали в речи)"
    ),
    # The first step of the analysis in steps (app/analysis_chain.py): the result alone, the protocol is later
    "decisions": (
        "Выпиши {lang} итоги приведённой ниже расшифровки в формате Markdown (без эмодзи), только два раздела:\n\n"
        "## Решения\n"
        "(О чём договорились или что решили — по пунктам, с таймкодами `[ММ:СС]`. Решение — то, что участники "
        "этой встречи постановили сделать, изменить или выбрать; только решённое в разговоре, а не предложенное "
        "или обсуждённое. Не включай регламент встречи, правила, условия договоров, сроки и цифры из докладов "
        "и другие факты о положении дел, инструкции и описание того, как что-то устроено или делается («при "
        "смене размера править оба файла»), призывы и вежливые реплики («готов ответить на вопросы»). Встреча "
        "может быть на любом языке: правило то же. Если решений не было, "
        "напиши одной строкой без пункта: «Решений не принималось»)\n\n"
        "## Открытые вопросы\n"
        "(Что осталось нерешённым, спорным или отложено и к чему нужно вернуться — по пунктам, с таймкодами. "
        "Если таких нет, напиши одной строкой без пункта: «Открытых вопросов нет»)\n\n"
        "Больше ничего не пиши: ни вступления, ни других разделов."
    ),
    "tasks": (
        "Проанализируй приведённую ниже расшифровку и выпиши {lang} только те задачи, планы или действия, которые реально упоминаются в тексте.\n\n"
        "ВАЖНО: Если в записи нет никаких рабочих задач, поручений или дедлайнов (например, это рассказ, интервью, обзор или бытовая беседа), "
        "НЕ выдумывай их! В таком случае прямо напиши, что в записи не ставились задачи или поручения, и ниже кратко перечисли, "
        "какие действия или события описывали говорящие в своих репликах (с таймкодами `[ММ:СС]`)."
    ),
    "tldr": (
        "Сделай короткую и точную выжимку (TL;DR) этой записи {lang} строго по фактам из текста (без выдумывания и без эмодзи):\n"
        "- **О чём запись**: 1–2 предложения.\n"
        "- **Ключевые моменты**: 2–5 коротких пунктов с таймкодами `[ММ:СС]` о том, что именно было сказано."
    ),
    # The user's own notes from the meeting, each one expanded from the transcript (Granola-style)
    "notes": (
        "Ниже есть заметки, которые пользователь сам делал во время встречи. Разверни их {lang} в итоговый "
        "конспект в формате Markdown (без эмодзи): сохрани порядок и формулировки пользователя как заголовки "
        "или пункты, а под каждым кратко допиши по расшифровке, что именно было сказано, кем, с таймкодами `[ММ:СС]`. "
        "Если заметка не находит подтверждения в расшифровке, оставь её как есть и пометь «(в записи не найдено)». "
        "В конце добавь «## Что ещё обсуждали» — важное из записи, чего нет в заметках."
    ),
    # A follow-up email to the participants (opened in the mail app by the page)
    "followup": (
        "Напиши {lang} короткое деловое письмо участникам по итогам этой встречи, от лица пользователя. "
        "Структура: одна строка «Тема: …», пустая строка, приветствие, 1–2 предложения о встрече, «Договорились:» — "
        "решения списком, «Задачи:» — кто, что и к какому сроку, следующий шаг или дата следующей встречи, если прозвучала. "
        "Обычный текст без Markdown-заголовков, таймкодов и эмодзи, не длиннее 200 слов. Только то, что было сказано."
    ),
    # Parsed by the app into a clickable table of contents: keep the line format strict
    "chapters": (
        "Раздели запись на смысловые главы по порядку: от 3 до 12 глав, по одной на каждую смену темы. "
        "Ответь {lang}. Каждая глава — ровно одна строка строго в формате:\n"
        "- [ММ:СС] Название главы — одно короткое предложение о её содержании\n"
        "Время — момент начала главы, взятый из таймкодов расшифровки (для записей длиннее часа — [Ч:ММ:СС]). "
        "Первая глава начинается с [00:00]. Не пиши ничего, кроме этих строк: без заголовков, вступления и итогов."
    ),
}


# The analysis model leaves the memory once its work is done: AFTER_WORK_UNLOAD_SEC after the last
# answer with no new question (an overview of a long recording asks several in a row) Ollama lets go
# of every model it holds. Not while live captions run (their translation model works on).
AFTER_WORK_UNLOAD_SEC = 20.0
_work_lock = threading.Lock()
_work = {"active": 0, "timer": None}


def _speech_job_waits() -> bool:
    """A transcription is queued or running: it needs the video memory the analysis model holds."""
    try:
        from app import transcriber

        with transcriber._jobs_lock:
            return any(q["kind"] == "transcribe" for q in transcriber._queue)
    except Exception:
        return False


def _after_work_unload() -> None:
    """After the analysis model's work: unloaded at once only when a transcription waits for the video
    memory; otherwise it stays as long as Settings → «выгружать через N минут» says (keep_alive), so a
    next question to the assistant does not wait seconds for it to load again."""
    with _work_lock:
        if _work["active"]:
            return
    if not _speech_job_waits():
        return
    try:
        from app.vram import ollama_release_others

        gone = ollama_release_others()
        if gone:
            print(f"[ollama] unloaded after the work: {', '.join(gone)}", flush=True)
    except Exception as e:
        print(f"[ollama] not unloaded after the work: {e}", flush=True)


def _work_started() -> None:
    with _work_lock:
        _work["active"] += 1
        if _work["timer"]:
            _work["timer"].cancel()
            _work["timer"] = None


def _work_done() -> None:
    with _work_lock:
        _work["active"] = max(0, _work["active"] - 1)
        if _work["active"]:
            return
        timer = threading.Timer(AFTER_WORK_UNLOAD_SEC, _after_work_unload)
        timer.daemon = True
        _work["timer"] = timer
    timer.start()


# The analysis model's answers being written, by thread: an overview or a question to the assistant
# runs as a plain request, not a queued job, so «Выгрузить всё» did not see it: the model was unloaded
# and the next part of the overview loaded it again. They are known here and can be stopped
# (stop_analysis). A thread stays «in the analysis» a little after an answer: an overview is many
# answers one after another, and a stop between two of them still ends it
_analysis_lock = threading.Lock()
_analysis: Dict[int, str] = {}         # thread -> model writing an answer for it now
_analysis_ended: Dict[int, float] = {}  # thread -> when its last answer ended
ANALYSIS_LINGER_SEC = 3.0


def analysis_running() -> List[str]:
    """The analysis models writing an answer now (for the memory panel: the model is busy)."""
    with _analysis_lock:
        return sorted(set(_analysis.values()))


def stop_analysis() -> int:
    """The answers being written end at once (Aborted in their requests), and so does the overview or
    answer they belong to. Returns how many were stopped."""
    from app import cancel_scope

    now = time.time()
    with _analysis_lock:
        threads = set(_analysis) | {t for t, at in _analysis_ended.items() if now - at < ANALYSIS_LINGER_SEC}
    for tid in threads:
        cancel_scope.abort(tid)
    return len(threads)


def _analysis_enter(model: str) -> None:
    from app import cancel_scope

    tid = threading.get_ident()
    with _analysis_lock:
        recent = time.time() - _analysis_ended.get(tid, 0.0) < ANALYSIS_LINGER_SEC
        _analysis[tid] = model
    try:
        from app import transcriber

        job_thread = tid == transcriber._running_thread
    except Exception:
        job_thread = False
    # A stop of an earlier request on this pooled thread is not this one's (a job resets its own)
    if not recent and not job_thread:
        cancel_scope.reset(tid)


def _analysis_leave() -> None:
    tid = threading.get_ident()
    with _analysis_lock:
        _analysis.pop(tid, None)
        _analysis_ended[tid] = time.time()
        for t in [t for t, at in _analysis_ended.items() if time.time() - at > 600]:
            del _analysis_ended[t]


LLM_RETRY_ANSWER_TOKENS = 8192  # once, when an answer was cut at LLM_MAX_ANSWER_TOKENS


def _goes_round(text: str) -> bool:
    """A model repeating itself: of the last 12 lines, half or more were already written."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    tail = lines[-12:]
    return len(tail) >= 6 and len(tail) - len(set(tail)) >= len(tail) // 2


def _ollama_chat(base_url: str, model: str, system: str, user: str, short: bool = False, plain: bool = False) -> str:
    """short: a short answer (a title, «да / нет» checks, a feature's name): the model does not reason
    first, which is most of the time of such an answer. plain: a long answer without reasoning (the notes
    of a part of a long recording): no thinking either, but a cut answer is still asked again."""
    from app import idle_unload

    idle_unload.touch(model)
    payload: Dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": {
            "temperature": 0.1,
            "top_p": 0.85,
            "repeat_penalty": 1.15,
            "num_ctx": llm_num_ctx(),
            # An answer stops at this length: a small model caught in a loop (the same lines again and
            # again) wrote until the whole context was full, for many minutes on a processor
            "num_predict": llm_max_answer_tokens(),
        },
    }
    keep_alive = idle_unload.ollama_keep_alive()
    if keep_alive:
        payload["keep_alive"] = keep_alive  # Ollama frees the model after the same idle time
    from app.llm_text import strip_think, thinking_off
    from app import cancel_scope

    try:  # one model in memory at a time: the idle speech models and another analysis model go first
        from app.vram import ollama_release_others, release_idle_speech_models

        gone = release_idle_speech_models(model)
        if gone:
            print(f"[ollama] unloaded before {model}: {', '.join(gone)}", flush=True)
        ollama_release_others(keep=model)
    except Exception as e:
        print(f"[ollama] others not unloaded: {e}", flush=True)

    def request() -> str:
        # asked here, once the answer counts as being written: Ollama is asked what the model can do
        payload.update(thinking_off(model, analysis=not (short or plain), base_url=base_url))
        with httpx.Client(timeout=600.0) as client:
            resp = client.post(f"{base_url}/api/chat", json=payload)
            raise_for_ollama(resp)
            data = resp.json()
            # Cut at the answer limit (a model that reasons spends part of it thinking: gemma4's summaries
            # lost their end in 6 of 9 recordings): asked once more with room to finish, not saved cut
            # Not for a short answer (a title, a yes or no) and not for a model gone round in circles: more room
            # would only give it more of the same lines
            first = str((data.get("message") or {}).get("content") or "")
            if (data.get("done_reason") == "length" and payload["options"]["num_predict"] < LLM_RETRY_ANSWER_TOKENS
                    and not short and not _goes_round(first)):
                print(f"[ollama] {model}: the answer was cut at {payload['options']['num_predict']} tokens, asked again", flush=True)
                payload["options"]["num_predict"] = LLM_RETRY_ANSWER_TOKENS
                resp = client.post(f"{base_url}/api/chat", json=payload)
                raise_for_ollama(resp)
                data = resp.json()
            if data.get("done_reason") == "length":
                print(f"[ollama] {model}: the answer is cut at {payload['options']['num_predict']} tokens", flush=True)
            msg = data.get("message") or {}
            return strip_think(str(msg.get("content") or data.get("response") or ""))

    def stop_answer() -> None:  # a cancelled job: Ollama stops writing (the model is unloaded)
        from app.vram import ollama_unload

        ollama_unload([model])

    _work_started()
    _analysis_enter(model)
    try:
        return cancel_scope.call(request, on_abort=stop_answer)
    finally:
        _analysis_leave()
        _work_done()


MAX_NOTE_ROUNDS = 3


def _join_notes(notes: List[str]) -> str:
    return "\n\n".join(f"### Фрагмент {i}\n{n}" for i, n in enumerate(notes, start=1))


def _fit_notes(llm, system_prompt: str, notes: List[str], budget: int, lang: str) -> str:
    """The notes of all parts of a long recording, condensed until they fit one request. Sent as they
    were, the notes of an hour and a half ran over the model's context, and Ollama silently dropped the
    beginning: the overview then told only the last part of the meeting."""
    for _ in range(MAX_NOTE_ROUNDS):
        text = _join_notes(notes)
        if len(text) <= budget:
            return text
        # Neighbouring notes condensed together, each group about half of what one request holds
        groups: List[List[str]] = [[]]
        size = 0
        for n in notes:
            if groups[-1] and size + len(n) > budget // 2:
                groups.append([])
                size = 0
            groups[-1].append(n)
            size += len(n)
        part_budget = max(1500, budget // max(2, len(groups) + 1))
        condensed = []
        for g in groups:
            condensed.append(llm.chat(
                system_prompt,
                "Ниже последовательные конспекты частей длинной записи:\n```text\n" + _join_notes(g) + "\n```\n\n"
                f"Сожми их {lang} в один конспект не длиннее {part_budget} знаков: сохрани все решения, задачи, "
                "сроки, имена и главные мысли с их таймкодами `[ЧЧ:ММ:СС]`/`[ММ:СС]`, по порядку записи. "
                "Ничего не добавляй от себя.",
            ))
        notes = condensed
    # Still too long after the rounds: every part keeps its beginning, so no part of the meeting is lost
    each = max(500, budget // max(1, len(notes)) - 40)
    return _join_notes([n[:each] for n in notes])


def generate_meeting_summary(
    segments: List[Dict[str, Any]],
    speakers: Dict[str, Dict[str, Any]],
    template_key: str = "protocol",
    custom_prompt: str = "",
    model_name: Optional[str] = None,
    base_url: Optional[str] = None,
    answer_lang: Optional[str] = "ru",
    local_only: bool = False,
    user_notes: str = "",
    template_prompt: str = "",
    progress: Optional[Callable[[int, int], None]] = None,
    part_notes: Optional[Dict[str, Any]] = None,
    participants: Optional[List[str]] = None,
    mfu: str = "",
    features_note: str = "",
    context_note: str = "",
) -> str:
    """mfu: the organizer's meeting follow-up the user pasted: the decisions and tasks agreed on;
    participants: who was in the meeting, their names written right (app/people.meeting_roster):
    the model writes them so, and a name it still misspells is put right in its answer;
    template_prompt: the instruction of a template the user made (Settings → Analysis);
    user_notes: what the user wrote during the meeting, taken into account by every summary;
    progress(done, total): the parts of a long recording read so far (it is read part by part);
    part_notes: a dict kept by the caller across calls on the same transcript — the notes of the parts
    of a long recording are made once (the overview and the chapters asked for the very same ones)."""
    from app.llm import target

    # Ollama, or the cloud model chosen in Settings → Analysis ("cloud" asks for it explicitly)
    llm = target(model_name, local_only=local_only)
    lines = build_transcript_lines(segments, speakers_in_language(speakers, answer_lang))
    transcript_text = "\n".join(lines)
    if not transcript_text.strip():
        raise RuntimeError("Транскрипт пуст, нечего анализировать.")

    lang = _lang_phrase(answer_lang)
    system_prompt = SYSTEM_GROUNDING_PROMPT.format(lang=lang)

    if custom_prompt.strip():
        instruction = (
            "Ответь на вопрос или выполни задание пользователя СТРОГО на основе приведённой ниже "
            "расшифровки записи. Ничего не додумывай от себя. Указывай имена спикеров и таймкоды `[ММ:СС]`, "
            f"где это уместно. Отвечай {lang} в формате Markdown без эмодзи.\n\n"
            f"Вопрос / задание пользователя: {custom_prompt.strip()}"
        )
    elif template_prompt.strip():
        instruction = (
            f"{template_prompt.strip()}\n\nОтвечай {lang} в формате Markdown без эмодзи, строго по расшифровке, "
            "с таймкодами `[ММ:СС]` там, где это уместно."
        )
    else:
        instruction = SUMMARY_TEMPLATES.get(template_key, SUMMARY_TEMPLATES["protocol"]).format(lang=lang)
    notes = (user_notes or "").strip()[:6000]
    if notes:
        instruction += (
            "\n\nЗаметки, которые пользователь сделал во время встречи (что для него главное), — учти их в первую "
            f"очередь и не теряй ни одной:\n```text\n{notes}\n```"
        )
    elif template_key == "notes" and not custom_prompt.strip():
        raise RuntimeError("У записи нет ваших заметок: напишите их во вкладке «Мои заметки» или во время записи в студии")
    context_note = (context_note or "").strip()[:3000]
    if context_note:  # what the other tabs of this recording found (app/meeting_context.py): one story in all
        instruction += "\n\n" + context_note
    if (features_note or "").strip():  # Словарь → Фичи: what the meeting's feature is, its words
        instruction += "\n\nВстреча относится к фиче (что это и как в ней называются вещи):\n" + features_note.strip()[:2000]
    try:
        from app import vocab

        glossary = vocab.glossary_note(already=(features_note or "")[:2000])
    except Exception:
        glossary = ""
    if glossary:
        instruction += "\n\n" + glossary
    mfu_text = (mfu or "").strip()[:MFU_SUMMARY_CHARS]
    if mfu_text:
        instruction += (
            "\n\nMFU — итоги встречи, которые написал её организатор и разослал участникам. Решения, задачи, сроки "
            "и ответственных бери из MFU: это согласованный людьми текст. Расшифровку используй для подробностей и "
            "таймкодов; где она расходится с MFU, верь MFU:\n<mfu>\n" + mfu_text.replace("</mfu>", "") + "\n</mfu>"
        )

    roster = [p for p in (participants or []) if str(p).strip()][:40]
    roster_note = (
        "Участники этой встречи — их имена и фамилии написаны верно: " + "; ".join(roster) + ". "
        "Когда речь о ком-то из них (в том числе когда распознавание исказило имя, а в разговоре человека зовут "
        "коротко или иначе: «Макс» — Максим, «Саша» — Александр, по фамилии, латиницей или кириллицей), пиши имя и фамилию "
        "точно как в этом списке, буква в букву. Не придумывай фамилии, отчества и должности, которых нет "
        "ни в этом списке, ни в расшифровке; если не ясно, о ком речь, пиши имя так, как оно сказано."
    ) if roster else ""
    # The user's contacts besides the participants: a person named in the talk is written as in the contacts
    # (app/people.known_people; a cloud service gets only the ones the transcript names)
    known: List[str] = []
    if participants is not None:
        try:
            from app.people import known_people

            known = known_people({"segments": segments, "speakers": speakers}, exclude=roster, cloud=llm.is_cloud)
        except Exception:
            known = []
    if roster or known:
        known_rule = (
            "Людей называй полным именем и фамилией из этих списков, а не уменьшительными или короткими формами "
            "(не «Дима» или «Саня», а полное имя и фамилия того человека из списка), даже если в разговоре их зовут коротко. "
            "Короткую форму оставляй, только если неясно, кто из списка это."
        )
    else:
        known_rule = ""
    if known:
        roster_note = (roster_note + "\n\n" if roster_note else "") + (
            "Люди из контактов пользователя — в разговоре могут упоминаться и те, кого нет на встрече: "
            + "; ".join(known) + ". Если в разговоре говорят о ком-то из них (по имени, коротко, по фамилии или "
            "с искажением распознавания), пиши имя и фамилию как в этом списке. Не упоминай людей из этого "
            "списка, о которых в записи не говорили."
        )

    if known_rule:
        roster_note = roster_note + "\n" + known_rule
    source_label = "Вот точная расшифровка аудио/видеозаписи"
    single_pass_max = single_pass_max_chars() if not llm.is_cloud else llm.max_chars
    # the user's notes go in the same request: the transcript gets the room they leave (a recording
    # just under the limit with notes did not fit, and Ollama dropped its beginning without a word)
    # and so do the feature's note and the glossary (the PC check of 0.8.7-beta.2: room was left, but the
    # budget did not know of them)
    added = len((features_note or "").strip()[:2000]) + len(glossary) + len(context_note)
    whole_max = max(8000, single_pass_max - len((user_notes or "").strip()[:6000]) - len(mfu_text) - added)
    if len(transcript_text) > whole_max:
        # Map step: condense each part of a long recording into detailed timestamped notes
        chunks = _chunk_lines(lines, chunk_max_chars() if not llm.is_cloud else llm.max_chars // 2)
        focus = (
            f"Особенно подробно выпиши всё, что относится к вопросу: {custom_prompt.strip()}\n"
            if custom_prompt.strip()
            else ""
        )
        notes: List[str] = []
        reuse = part_notes is not None and not focus
        if reuse and part_notes.get("chunks") == len(chunks) and part_notes.get("model") == llm.label \
                and len(part_notes.get("notes") or []) == len(chunks):
            notes = list(part_notes["notes"])
            chunks = []  # read already, by the overview before
        for idx, chunk in enumerate(chunks, start=1):
            if progress:
                progress(idx, len(chunks))
            notes.append(
                llm.chat(  # a retelling: gemma4's reasoning cut these at the answer limit, 2–3 retries an hour
                    system_prompt,
                    f"Это фрагмент {idx} из {len(chunks)} расшифровки длинной записи:\n```text\n{chunk}\n```\n\n"
                    f"Составь {lang} подробный конспект этого фрагмента списком: кто что сказал, факты, мнения, "
                    f"решения, задачи и сроки — каждый пункт с таймкодом `[ММ:СС]`. {focus}"
                    "Пиши только то, что есть в тексте фрагмента." + (f"\n\n{roster_note}" if roster_note else ""),
                    plain=True,
                )
            )
        if reuse and chunks:
            part_notes.update(chunks=len(chunks), model=llm.label, notes=list(notes))
        transcript_text = _fit_notes(llm, system_prompt, notes, whole_max, lang)
        source_label = (
            "Запись длинная, поэтому ниже приведены последовательные конспекты всех её фрагментов "
            "(с таймкодами исходной записи, от начала до конца)"
        )
        instruction += (
            "\n\nОхвати всю запись от начала до конца: каждый фрагмент должен попасть в ответ, "
            "а не только последние."
        )

    user_message = (
        f"{source_label}:\n"
        f"```text\n{transcript_text}\n```\n\n"
        + (f"{roster_note}\n\n" if roster_note else "")
        + f"Задание:\n{instruction}\n\n"
        "Напоминание: пиши ТОЛЬКО о том, что реально сказано в записи. "
        "Не выдумывай посторонних людей, встреч или проектов."
    )
    answer = llm.chat(system_prompt, user_message)
    if roster or known:  # a participant's or a contact's name still written with a letter wrong
        from app.people import fix_name_typos

        answer = fix_name_typos(answer, roster + [k.split(" (также:")[0] for k in known])
    try:  # «Дима», a spelling merged into «Дмитрий Орлов»: the full name, as in the contacts
        from app.people import expand_names

        answer = expand_names(answer)
    except Exception:
        pass
    from app.analysis_edits import fix_with_dictionary

    return fix_with_dictionary(answer)  # a word corrected by hand once stays corrected


# --- A title for a recording, from its content ---
_GENERIC_TITLE_WORDS = {
    "запись", "записи", "аудио", "видео", "звук", "встреча", "созвон", "голосовая", "заметка", "компьютера",
    "новая", "новый", "без", "названия", "микрофон", "экран",
    "recording", "record", "rec", "audio", "video", "vid", "voice", "note", "memo", "meeting", "call", "zoom",
    "teams", "screen", "screencast", "capture", "computer", "new", "untitled", "track", "mic", "system",
    "img", "mov", "dsc", "gmt", "file", "clip", "output", "export", "final", "copy", "копия",
}


def is_generic_title(title: str) -> bool:
    """True for titles that say nothing about the content: 'Запись 14-05', 'zoom_0', 'VID_20240512_1302',
    'Recording (3)'. Such titles may be replaced by one made from the transcript."""
    words = re.findall(r"[^\W\d_]+", (title or "").casefold())
    return all(w in _GENERIC_TITLE_WORDS or len(w) <= 1 for w in words)


def generate_meeting_title(
    segments: List[Dict[str, Any]],
    speakers: Dict[str, Dict[str, Any]],
    answer_lang: Optional[str] = "ru",
    model_name: Optional[str] = None,
    local_only: bool = False,
) -> str:
    """A short title (3-8 words) for the recording from the beginning of its transcript."""
    from app.llm import target

    # the title by content is turned on by the user (auto_title): a stopped Ollama is started, as for the overview
    llm = target(model_name, local_only=local_only)
    text = "\n".join(build_transcript_lines(segments, speakers))[:7000]
    if not text.strip():
        raise RuntimeError("Транскрипт пуст")
    lang = _lang_phrase(answer_lang)
    system = (
        "Ты придумываешь короткие точные названия для расшифровок встреч, звонков и записей. "
        f"Отвечай {lang}. Выведи только название: 3–8 слов, без кавычек, без точки в конце, без даты, "
        "без слов «Встреча», «Запись», «Обсуждение» в начале, если можно обойтись без них."
    )
    raw = llm.chat(system, f"Расшифровка:\n{text}\n\nНазвание:", short=True)
    title = clean_title(raw, answer_lang)
    if len(title) < 3:
        raise RuntimeError("Модель не дала названия")
    return title


# Chinese, Japanese and Korean characters: Qwen sometimes slips a Chinese word into an answer in
# another language, and the title becomes the file name
_CJK_RE = re.compile(r"[\u2e80-\u2fff\u3000-\u30ff\u3100-\u31ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uf900-\ufaff\uff00-\uffef]+")


def clean_title(raw: str, answer_lang: Optional[str] = None) -> str:
    from app.llm_text import strip_think

    raw = strip_think(raw or "")
    if (answer_lang or "")[:2] not in ("zh", "ja", "ko"):
        raw = _CJK_RE.sub(" ", raw)
    line = next((" ".join(ln.split()) for ln in raw.splitlines() if ln.strip()), "")
    line = re.sub(r"^(название|title)\s*[:：-]\s*", "", line, flags=re.IGNORECASE)
    prev = None
    while line != prev:  # «Title». or "Title." in any order
        prev = line
        line = re.sub(r"[.。]+$", "", line.strip().strip("\"'«»“”`*#")).strip()
    return line[:120]
