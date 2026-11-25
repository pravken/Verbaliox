"""System, models, settings, dictionary and live progress (SSE)."""

import json
import os
import re
import sys
from typing import Any, Dict, List, Optional
from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from app import events, paths
from app.paths import DATA_DIR, MODELS_DIR, UPLOADS_DIR
from app import vocab
from app.database import add_dictionary_term, delete_dictionary_term, get_all_settings, list_dictionary, set_dictionary_variants, toggle_dictionary_term, update_settings
from app.ffmpeg_manager import ffmpeg_status, start_ffmpeg_download
from app.hardware import get_hardware_info
from app.ollama_client import get_ollama_status, start_model_pull

from fastapi import APIRouter

from app.main import (  # noqa: E402 - shared helpers live in app/main.py
    _recordings_dir,
)

router = APIRouter()

# --- System, Hardware & Settings ---
def windows_text_scale() -> Optional[int]:
    """«Make text bigger» of Windows (Accessibility → Text size), in percent; None elsewhere or unset.
    The page takes its first interface scale from it (audit 5.5)."""
    if sys.platform != "win32":
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Accessibility") as key:
            value, _ = winreg.QueryValueEx(key, "TextScaleFactor")
        return int(value)
    except (OSError, ValueError, TypeError):
        return None


@router.get("/api/system")
def api_system_info() -> Dict[str, Any]:
    from app.model_manager import get_models_status

    return {
        "text_scale": windows_text_scale(),
        "hardware": get_hardware_info(),
        "settings": get_all_settings(),
        "ollama": get_ollama_status(),
        "models": get_models_status(),
        "ffmpeg": ffmpeg_status(),
        "paths": {
            "data": str(DATA_DIR), "models": str(MODELS_DIR), "legacy_conflict": paths.LEGACY_CONFLICT,
            "recordings": str(_recordings_dir()), "uploads": str(UPLOADS_DIR),
            "recordings_default": str(paths.DEFAULT_RECORDINGS_DIR),
        },
    }

@router.get("/api/ffmpeg/status")
def api_ffmpeg_status() -> Dict[str, Any]:
    return ffmpeg_status()

@router.post("/api/ffmpeg/install")
def api_ffmpeg_install() -> Dict[str, Any]:
    """Downloads the pinned FFmpeg build into the user data folder (the button; the first start does it by itself)."""
    return start_ffmpeg_download()

@router.get("/api/voice-filter/status")
def api_voice_filter_status() -> Dict[str, Any]:
    from app import voice_filter

    return voice_filter.status()

@router.post("/api/voice-filter/install")
def api_voice_filter_install() -> Dict[str, Any]:
    """DeepFilterNet's program (app/voice_filter.py): downloaded in the background, checked by its hash."""
    from app import voice_filter

    return voice_filter.start_download()

@router.post("/api/onnx-models/{model_id}/download")
def api_onnx_download(model_id: str) -> Dict[str, Any]:
    """GigaAM / Parakeet (app/asr_onnx.py): downloaded in the background."""
    from app import asr_onnx

    try:
        return asr_onnx.start_download(model_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.delete("/api/onnx-models/{model_id}")
def api_onnx_delete(model_id: str) -> Dict[str, Any]:
    from app import asr_onnx

    if not asr_onnx.is_onnx_model(model_id):
        raise HTTPException(status_code=404, detail="Неизвестная модель")
    from app import live
    from app.transcriber import running_job_kind

    if running_job_kind() == "transcribe":
        raise HTTPException(status_code=409, detail="Идёт распознавание — удалите модель после него")
    if live.model_in_use(model_id):
        raise HTTPException(status_code=409, detail="Идут живые субтитры — удалите модель после записи")
    return {"ok": asr_onnx.delete_model(model_id)}

@router.get("/api/models/status")
def api_models_status() -> Dict[str, Any]:
    from app.model_manager import get_models_status

    return get_models_status()

class ModelsSetupPayload(BaseModel):
    whisper_model: str = "large-v3-turbo"
    install_diarizer: bool = True
    # False: only download (the Russian model, or for later); the main model stays as it is
    select: bool = True

@router.post("/api/models/setup")
def api_models_setup(payload: ModelsSetupPayload) -> Dict[str, Any]:
    from app.model_manager import start_models_setup

    return start_models_setup(
        whisper_model_id=payload.whisper_model.strip(),
        install_diarizer=payload.install_diarizer,
        select=payload.select,
    )

@router.delete("/api/models/{model_id}")
def api_delete_whisper_model(model_id: str) -> Dict[str, Any]:
    from app.model_manager import delete_whisper_model, get_models_status
    from app.transcriber import running_job_kind

    if running_job_kind() == "transcribe":
        raise HTTPException(status_code=409, detail="Идёт распознавание — удалите модель после него")
    from app import live

    if live.has_sessions():
        raise HTTPException(status_code=409, detail="Идут живые субтитры — удалите модель после записи")
    worker = live._worker
    if worker is not None and worker.proc is not None:  # an idle caption worker still holds its model files
        with worker.lock:
            worker._kill()
    from app.transcriber import release_whisper_model

    release_whisper_model()
    try:
        delete_whisper_model(model_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return get_models_status()

class SettingsUpdatePayload(BaseModel):
    settings: Dict[str, Any]

@router.get("/api/mcp/config")
def api_mcp_config() -> Dict[str, Any]:
    """The lines that connect an agent (Claude Desktop, Claude Code) to the library (app/mcp_server.py)."""
    from app.mcp_server import client_config

    cfg = client_config()
    return {"claude_desktop": json.dumps(cfg["claude_desktop"], ensure_ascii=False, indent=2), "claude_code": cfg["claude_code"]}


@router.post("/api/settings")
def api_update_settings(payload: SettingsUpdatePayload) -> Dict[str, Any]:
    from app.database import _CLOUD_SETTINGS
    from app.settings_schema import SERVER_KEYS, clean_all

    try:
        # the cloud settings of earlier versions are not stored again (an older page may still send them),
        # nor what the program writes itself
        values = clean_all({k: v for k, v in payload.settings.items()
                            if not str(k).startswith("llm_") and k not in _CLOUD_SETTINGS and k not in SERVER_KEYS})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    before = get_all_settings()
    was_auto = (before.get("obsidian_auto") or "false") == "true"
    was_economy = (before.get("economy_mode") or "false") == "true"
    was_threads = before.get("cpu_threads") or "auto"
    was_layout = (before.get("date_folders") or "off", before.get("obsidian_feature_folders") or "true")
    updated = update_settings(values)
    if "economy_mode" in values and (values["economy_mode"] == "true") != was_economy:
        from app import economy

        if values["economy_mode"] == "true":  # for the time chosen beside it
            end = economy.until_for(values.get("economy_for") or before.get("economy_for") or "0")
            update_settings({"economy_until": f"{end:.0f}" if end else ""})
        else:
            update_settings({"economy_until": ""})
        economy.applied(values["economy_mode"] == "true")
    if "cpu_threads" in values and values["cpu_threads"] != was_threads:
        try:  # the models on the processor load again with the new number of threads
            from app import asr_onnx

            asr_onnx.release_cpu()
        except Exception as e:
            print(f"[asr_onnx] {e}", flush=True)
    if values.get("obsidian_auto") == "true" and not was_auto:
        # auto-export turned on: the recordings made before it get their notes too (asked by the user)
        try:
            from app.obsidian import export_all

            export_all(missing_only=True)
        except Exception as e:
            print(f"[obsidian] notes of the earlier recordings: {e}", flush=True)
    now_layout = (values.get("date_folders", was_layout[0]) or "off", values.get("obsidian_feature_folders", was_layout[1]) or "true")
    if now_layout != was_layout:
        # the folders of the notes changed (by date, by feature): the notes made before move there, in the
        # background (asked by the user), and back when it is turned off
        try:
            from app.obsidian import relayout

            relayout()
        except Exception as e:
            print(f"[obsidian] moving the notes: {e}", flush=True)
    if "dictionary_fuzzy" in values:
        vocab.invalidate()
    if "start_with_windows" in values:
        from app import autostart

        try:
            autostart.set_enabled(values["start_with_windows"] == "true")
        except OSError as e:
            raise HTTPException(status_code=500, detail=f"Не удалось изменить автозапуск Windows: {e}")
    if "semantic_search" in payload.settings or "semantic_model" in payload.settings:
        from app import semantic

        semantic.kick()
    if any(k in values and values[k] != (before.get(k) or "") for k in ("live_translate_model_quality", "live_translate_model_fast")):
        from app import live

        live.translate_models_changed()  # the captions running now take the new choice too
    if "mem_reserve_ram" in values or "mem_reserve_vram" in values:
        from app import mem_reserve

        mem_reserve.apply()  # the cap of the work processes now; the card's reserve when Ollama starts again
    return {"settings": updated, "ollama": get_ollama_status()}


@router.get("/api/memory/reserve")
def api_memory_reserve() -> Dict[str, Any]:
    """The memory left to the system: the computer's RAM and video memory, the reserves and their «auto»."""
    from app import mem_reserve

    return mem_reserve.status()

@router.get("/api/ollama/status")
def api_ollama_status() -> Dict[str, Any]:
    return get_ollama_status()

class OllamaPullPayload(BaseModel):
    model: str
    allow_install: bool = False

@router.post("/api/ollama/pull")
def api_ollama_pull(payload: OllamaPullPayload) -> Dict[str, Any]:
    return start_model_pull(payload.model.strip(), allow_install=payload.allow_install)

# --- Custom Dictionary ---
@router.get("/api/dictionary")
def api_list_dictionary() -> List[Dict[str, Any]]:
    return list_dictionary(active_only=False)

class DictionaryCreatePayload(BaseModel):
    term: str
    category: str = "Термин"
    variants: Optional[str] = None  # "клод, klot": how the term may be recognized

@router.post("/api/dictionary")
def api_add_dictionary(payload: DictionaryCreatePayload) -> Dict[str, Any]:
    try:
        # Support adding comma-separated or newline-separated batch of terms at once
        raw_terms = [
            t.strip()
            for line in payload.term.splitlines()
            for t in line.split(",")
            if t.strip()
        ]
        if not raw_terms:
            raise HTTPException(status_code=400, detail="Введите хотя бы одно слово или фразу")
        last_item = {}
        for t in raw_terms:
            last_item = add_dictionary_term(t, payload.category, payload.variants)
        vocab.invalidate()
        return {"added": len(raw_terms), "last": last_item, "items": list_dictionary()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

class DictionaryTogglePayload(BaseModel):
    active: Optional[bool] = None
    variants: Optional[str] = None
    term: Optional[str] = None      # the word itself written anew
    category: Optional[str] = None

@router.patch("/api/dictionary/{term_id}")
def api_toggle_dictionary(term_id: int, payload: DictionaryTogglePayload) -> Dict[str, Any]:
    if payload.active is not None:
        toggle_dictionary_term(term_id, payload.active)
    if payload.term is not None or payload.category is not None:
        from app.database import rename_dictionary_term

        if payload.term is not None and not payload.term.strip():
            raise HTTPException(status_code=400, detail="Пустое слово")
        try:
            rename_dictionary_term(term_id, payload.term, payload.category)
        except ValueError as e:
            raise HTTPException(status_code=409, detail=str(e))
    if payload.variants is not None:
        set_dictionary_variants(term_id, payload.variants)
    vocab.invalidate()
    return {"ok": True}

@router.get("/api/dictionary/usage")
def api_dictionary_usage() -> Dict[str, int]:
    """How many recordings hold each word (the section «Словарь»): {term id: recordings}."""
    from app.dictionary_page import usage

    return {str(k): v for k, v in usage().items()}

@router.get("/api/dictionary/offers")
def api_dictionary_offers() -> List[Dict[str, Any]]:
    """«Предложено из записей»: words corrected by hand that the dictionary has not learned."""
    from app.dictionary_page import offers

    return offers()

class DictionaryOfferPayload(BaseModel):
    wrong: str
    right: str

@router.post("/api/dictionary/offers/hide")
def api_dictionary_offer_hide(payload: DictionaryOfferPayload) -> Dict[str, Any]:
    from app.dictionary_page import hide

    hide(payload.wrong, payload.right)
    return {"ok": True}

@router.delete("/api/dictionary")
def api_clear_dictionary() -> Dict[str, Any]:
    from app.database import clear_dictionary

    clear_dictionary()
    vocab.invalidate()
    return {"ok": True}

@router.delete("/api/dictionary/{term_id}")
def api_delete_dictionary(term_id: int) -> Dict[str, Any]:
    delete_dictionary_term(term_id)
    vocab.invalidate()
    return {"ok": True}

# --- Live progress (Server-Sent Events) ---
_SSE_HEARTBEAT_SEC = 15.0

@router.get("/api/events")
async def api_events(request: Request) -> StreamingResponse:
    """
    Pushes processing progress and library changes to the UI instead of it polling every 2 s.
    Events: {"type": "progress", "id", status?, progress?, stage_text?, error_message?, duration?}
    and {"type": "list"} (a recording was added, renamed or deleted).
    """
    sub = events.subscribe()

    async def stream():
        try:
            yield 'retry: 3000\ndata: {"type": "hello"}\n\n'
            while True:
                batch = await sub.next_batch(_SSE_HEARTBEAT_SEC)
                if await request.is_disconnected():
                    break
                if not batch:
                    yield ": ping\n\n"
                    continue
                for ev in batch:
                    yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        finally:
            events.unsubscribe(sub)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


# --- Opening links in the default browser ---
class OpenUrlPayload(BaseModel):
    url: str

@router.post("/api/open-url")
def api_open_url(payload: OpenUrlPayload) -> Dict[str, Any]:
    """Opens a web link in the default browser (the app window itself never navigates away)."""
    import webbrowser
    from urllib.parse import urlparse

    u = urlparse(payload.url.strip())
    if u.scheme == "mailto":  # a draft in the mail app (no address: the user picks the recipients)
        if len(payload.url) > 8000:
            raise HTTPException(status_code=400, detail="Слишком длинное письмо")
        # The page encodes the text (encodeURIComponent): a raw line break or quote would reach the mail
        # program's command line as it is
        if re.search(r'[\x00-\x1f\x7f"<>]', payload.url):
            raise HTTPException(status_code=400, detail="Ссылка на письмо записана неверно")
        if sys.platform == "win32":
            os.startfile(payload.url.strip())  # noqa: S606 - a mailto: link the user asked to open
        else:
            webbrowser.open(payload.url.strip())
        return {"ok": True}
    if u.scheme not in ("https", "http") or not u.netloc:
        raise HTTPException(status_code=400, detail="Можно открыть только веб-ссылку")
    webbrowser.open(u.geturl())
    return {"ok": True}
