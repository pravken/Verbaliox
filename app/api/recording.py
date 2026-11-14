"""Recording: system audio, the page, the screen; finishing a recording; live captions."""

import re
import shutil
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import HTTPException, Request
from pydantic import BaseModel
from app.paths import DATA_DIR, UPLOADS_DIR
from app import speech_route
from app.settings_schema import as_int
from app.database import create_meeting, get_all_settings, get_meeting
from app.transcriber import enqueue_meeting_job

from fastapi import APIRouter

from app.main import (  # noqa: E402 - shared helpers live in app/main.py
    _free_bytes, _live_target, _recording_folder, _recordings_dir, _salvage_parts, disk_state, record_mix_command, screen_mix_command,
)

router = APIRouter()

# --- System audio recorded by the app itself (app/system_audio.py): no screen-share prompt ---
class RecordStartPayload(BaseModel):
    system: bool = True

@router.post("/api/record/start")
def api_record_start(payload: RecordStartPayload) -> Dict[str, Any]:
    from app.system_audio import start_capture

    if not payload.system:
        return {"capture_id": None}
    if disk_state()["critical"]:
        raise HTTPException(status_code=507, detail="Недостаточно места на диске для записи")
    try:
        cap = start_capture(UPLOADS_DIR / f"system_{uuid.uuid4().hex[:8]}.wav")
    except Exception as e:  # the page falls back to the browser's screen-share capture
        raise HTTPException(status_code=503, detail=str(e)[:300])
    return {"capture_id": cap.id}

@router.get("/api/record/{capture_id}/level")
def api_record_level(capture_id: str) -> Dict[str, Any]:
    from app.system_audio import get_capture

    cap = get_capture(capture_id)
    if not cap:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    return {"level": cap.level, "error": cap.error}

@router.post("/api/record/{capture_id}/cancel")
def api_record_cancel(capture_id: str) -> Dict[str, Any]:
    from app.system_audio import finish_capture

    cap = finish_capture(capture_id)
    if cap:
        cap.path.unlink(missing_ok=True)
    return {"ok": True}

# --- What the page records (microphone, and the screen or a window), streamed to the server ---
# The page sends its MediaRecorder output every second, so a long recording with video never has to
# fit into the window's memory, and what was recorded survives if the window is closed.
_page_recordings: Dict[str, Path] = {}
# The number of the next chunk each page recording expects: a chunk sent again (its answer was lost,
# the page retried) is not written twice, and none is written out of its place
_page_next_seq: Dict[str, int] = {}

_page_lock = threading.Lock()

def _page_part(page_id: str) -> Path:
    p = _page_recordings.get(page_id)  # a dict read: not under the lock a chunk being written holds
    if p is None:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    return p

@router.post("/api/record/page/start")
def api_record_page_start() -> Dict[str, Any]:
    if disk_state()["critical"]:
        raise HTTPException(status_code=507, detail="Недостаточно места на диске для записи")
    page_id = uuid.uuid4().hex
    part = _recordings_dir() / f".page_{page_id[:12]}.webm.part"
    part.write_bytes(b"")
    with _page_lock:
        _page_recordings[page_id] = part
    return {"page_id": page_id}

@router.post("/api/record/page/{page_id}/chunk")
async def api_record_page_chunk(page_id: str, request: Request) -> Dict[str, Any]:
    from starlette.concurrency import run_in_threadpool

    part = _page_part(page_id)
    data = await request.body()
    if len(data) > 64 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Слишком большой фрагмент записи")
    raw_seq = request.headers.get("x-chunk-seq")
    seq = int(raw_seq) if raw_seq and re.fullmatch(r"[0-9]{1,9}", raw_seq) else None  # «²» is a digit to isdigit()
    gap = request.headers.get("x-chunk-after-gap") == "1"  # the page gave up on a chunk before this one

    def append() -> Dict[str, Any]:  # off the event loop: a slow disk or a virus scan held every request
        with _page_lock:  # one chunk of a page at a time, in its order
            if _page_recordings.get(page_id) is not part:  # finished or cancelled meanwhile: not written into the mix
                raise HTTPException(status_code=404, detail="Запись не найдена")
            if seq is not None:
                expected = _page_next_seq.get(page_id, 0)
                if seq < expected:  # written already: its answer was lost and the page sent it again
                    return {"ok": True, "duplicate": True, "size": part.stat().st_size, "free_bytes": _free_bytes(part.parent)}
                if seq > expected:
                    if not gap:
                        raise HTTPException(status_code=409, detail=f"Ожидается фрагмент {expected}")
                    print(f"[record] chunks {expected}..{seq - 1} of {page_id[:8]} lost: the recording goes on past them", flush=True)
            with part.open("ab") as f:
                f.write(data)
            if seq is not None:
                _page_next_seq[page_id] = seq + 1
        return {"ok": True, "size": part.stat().st_size, "free_bytes": _free_bytes(part.parent)}

    return await run_in_threadpool(append)

@router.post("/api/record/page/{page_id}/cancel")
def api_record_page_cancel(page_id: str) -> Dict[str, Any]:
    with _page_lock:
        part = _page_recordings.pop(page_id, None)
        _page_next_seq.pop(page_id, None)
    if part:
        part.unlink(missing_ok=True)
    return {"ok": True}

# --- The screen or a window recorded by the app (app/screen_capture.py), when the window's own
# screen picker is not available ---
class ScreenStartPayload(BaseModel):
    target: str = "desktop"  # "desktop" or the exact title of a window

@router.get("/api/record/screen/windows")
def api_screen_windows() -> Dict[str, Any]:
    from app import screen_capture

    return {"supported": screen_capture.supported(), "windows": screen_capture.list_windows()}

@router.post("/api/record/screen/start")
def api_screen_start(payload: ScreenStartPayload) -> Dict[str, Any]:
    from app import screen_capture
    from app.ffmpeg_manager import find_tool

    ffmpeg = find_tool("ffmpeg")
    if not ffmpeg:
        raise HTTPException(status_code=503, detail="Для записи экрана нужен FFmpeg (Настройки → Общие)")
    if disk_state()["critical"]:
        raise HTTPException(status_code=507, detail="Недостаточно места на диске для записи")
    path = _recordings_dir() / f".screen_{uuid.uuid4().hex[:12]}.mkv.part"
    try:
        cap = screen_capture.start_capture(ffmpeg, path, payload.target.strip()[:300] or "desktop")
    except RuntimeError as e:
        path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Не удалось начать запись экрана: {e}")
    return {"screen_id": cap.id}

@router.post("/api/record/screen/{screen_id}/cancel")
def api_screen_cancel(screen_id: str) -> Dict[str, Any]:
    from app import screen_capture

    cap = screen_capture.finish_capture(screen_id)
    if cap:
        cap.path.unlink(missing_ok=True)
    return {"ok": True}

class TeamsStartPayload(BaseModel):
    started_at: float = 0           # when the recording began (unix seconds): the marks count from it
    names: List[str] = []           # the people of the calendar meeting: known as names in the captions

@router.post("/api/teams/start")
def api_teams_start(payload: TeamsStartPayload) -> Dict[str, Any]:
    """Reads who is speaking from the Teams captions while recording (setting teams_captions)."""
    from app import teams_captions

    if not teams_captions.enabled():
        return {"state": "off"}
    teams_captions.start(payload.started_at, payload.names[:50])
    return teams_captions.status()

@router.post("/api/teams/stop")
def api_teams_stop() -> Dict[str, Any]:
    """A recording cancelled: the reading of the captions ends, its marks go nowhere."""
    from app import teams_captions

    st = teams_captions.stop()
    st.pop("marks", None)
    return st

@router.post("/api/teams/check")
async def api_teams_check() -> Dict[str, Any]:
    """«Проверить» in Settings → Recording: what is seen in Teams right now (no recording needed)."""
    from starlette.concurrency import run_in_threadpool

    from app import teams_captions

    return await run_in_threadpool(teams_captions.check)

@router.get("/api/teams/meeting")
def api_teams_meeting() -> Dict[str, Any]:
    """The Teams meeting open now, by its window's title (app/meeting_watch.py): the page starts a new
    recording when it changes and stops the recording when the meeting is over."""
    from app import meeting_watch

    return meeting_watch.current()

@router.get("/api/teams/status")
def api_teams_status() -> Dict[str, Any]:
    from app import teams_captions

    st = teams_captions.status()
    marks = st.pop("marks", None) or []  # all of them go with the recording; the page gets the latest
    st["recent"] = [{"at": m["at"], "name": m["name"], "text": (m.get("text") or "")[:200]} for m in marks[-40:]]
    return st

class RecordFinishPayload(BaseModel):
    title: str = "Запись"
    page_id: Optional[str] = None     # what the page recorded (microphone and/or video)
    capture_id: Optional[str] = None  # system audio recorded by the app
    screen_id: Optional[str] = None   # the screen or a window recorded by the app
    has_video: bool = False           # the page recording has a video track (screen, window, tab)
    has_mic: bool = False             # the page recording has an audio track
    notes: str = ""                   # what the user wrote in the studio during the recording
    started_at: float = 0             # when the recording began (unix seconds): the calendar meeting
    page_started_at: float = 0        # when the page's recorder began (unix seconds): lines up the system audio
    speakers_hint: int = 0            # how many people, chosen in the studio (0: found by the voices)
    speaker_marks: List[Dict[str, Any]] = []  # «Сейчас говорит»: [{at: seconds into the recording, name}]

def _run_ffmpeg(cmd: List[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError as e:  # FFmpeg missing: reported like a failed run, so the parts are kept
        return subprocess.CompletedProcess(cmd, 1, "", str(e))

@router.post("/api/record/finish")
async def api_record_finish(payload: RecordFinishPayload) -> Dict[str, Any]:
    """Ends a recording: stops the system-audio capture, joins it with what the page recorded
    (microphone, video) and queues the result for transcription."""
    from starlette.concurrency import run_in_threadpool

    from app import teams_captions
    from app.system_audio import finish_capture

    # «Speaking now» read from the Teams captions during the recording join the ones clicked in the studio
    teams = await run_in_threadpool(teams_captions.stop)
    if teams.get("marks"):
        payload.speaker_marks = [*payload.speaker_marks,
                                 *({"at": m["at"], "name": m["name"], "text": m.get("text", "")} for m in teams["marks"])]
        print(f"[teams] {len(teams['marks'])} caption line(s), {len(teams['names'])} name(s) read", flush=True)

    page: Optional[Path] = None
    if payload.page_id:
        def take_page() -> Optional[Path]:  # the lock may wait for a chunk being written: not on the event loop
            with _page_lock:
                _page_next_seq.pop(payload.page_id, None)
                return _page_recordings.pop(payload.page_id, None)

        page = await run_in_threadpool(take_page)
        if page is not None and (not page.is_file() or page.stat().st_size == 0):
            page.unlink(missing_ok=True)
            page = None
    # its thread is joined (up to 5 s): not on the event loop, which serves every other request
    cap = await run_in_threadpool(finish_capture, payload.capture_id) if payload.capture_id else None
    system = cap.path if cap and cap.path.is_file() else None
    if system is not None and cap._thread.is_alive():  # its thread did not end in time: the file is not closed
        from app.system_audio import repair_rf64

        await run_in_threadpool(repair_rf64, system)
    screen: Optional[Path] = None
    if payload.screen_id:
        from app import screen_capture

        scap = await run_in_threadpool(screen_capture.finish_capture, payload.screen_id)
        if scap and scap.path.is_file() and scap.path.stat().st_size > 0:
            screen = scap.path
    if not page and not system and not screen:
        raise HTTPException(status_code=404, detail="Запись пуста: звук не был получен")

    # The system audio begins before the page's recorder (the microphone is asked for meanwhile)
    system_skip = 0.0
    if cap and page and payload.page_started_at > 0 and cap.started_at > 0:
        system_skip = min(30.0, max(0.0, payload.page_started_at - cap.started_at))
    safe_stem = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", payload.title.strip() or "Запись")[:100]

    # The recording is in the library at once, «Сведение дорожек»: the echo removal and the mix (minutes
    # for an hour-long meeting) run in the background, and it queues itself for transcription when done.
    # Off the event loop: the database lock, and the calendar (its link or Outlook, up to a minute and a
    # half) read for the meeting's name, would hold every other request meanwhile
    def register() -> Dict[str, Any]:
        settings = get_all_settings()
        m = create_meeting(
            title=payload.title.strip()[:300] or safe_stem,
            filename=safe_stem,
            media_path="",
            language=settings.get("language", "auto"),
            model_name=speech_route.default_choice(settings),
            num_speakers_hint=payload.speakers_hint if 0 < payload.speakers_hint <= 20 else as_int(settings.get("num_speakers"), 0),
            source="recording",
            owns_media=False,  # its file comes with the mix
            title_is_default=True,
            has_video=bool(screen or (payload.has_video and page)),
        )
        from app import app_status
        from app.database import update_meeting_progress

        app_status.mixing.add(m["id"])
        update_meeting_progress(m["id"], status="mixing", progress=1, stage_text="Сведение дорожек записи...")
        _attach_recording_info(m["id"], payload)
        threading.Thread(target=_mix_in_background, args=(m["id"], payload, page, system, screen, system_skip, safe_stem),
                         daemon=True, name="record_mix").start()
        return m

    m = await run_in_threadpool(register)
    return {"created": [await run_in_threadpool(get_meeting, m["id"]) or m]}


def _mix_parts(payload: RecordFinishPayload, page: Optional[Path], system: Optional[Path], screen: Optional[Path],
               system_skip: float, safe_stem: str) -> Optional[Dict[str, Any]]:
    """The parts of a recording made one file: {"dest", "has_video"}, or None when they could not be
    joined (each part is then kept as a recording of its own, _salvage_parts, and that is returned as
    {"salvaged": ...})."""
    from app.ffmpeg_manager import tool_cmd

    # The speakers' echo taken out of the microphone (app/echo_cancel.py): the mix then uses the
    # cleaned microphone instead of the page's sound
    mic: Optional[Path] = None
    echo_done = False
    original_system: Optional[Path] = None
    if page and system and payload.has_mic and (get_all_settings().get("rec_echo_cancel") or "true").lower() == "true":
        from app.echo_cancel import clean_microphone

        cleaned = page.with_name(page.name + ".mic.wav")
        lined_up = page.with_name(page.name + ".sys.wav")
        if clean_microphone(tool_cmd("ffmpeg"), page, system, system_skip, cleaned, lined_up):
            mic, echo_done = cleaned, True
            if lined_up.is_file():
                # the system sound where the microphone heard it: mixed instead, nothing more to skip
                original_system, system, system_skip = system, lined_up, 0.0
    # The voice without its noise (app/voice_filter.py, DeepFilterNet): the microphone after the echo
    voice = "no"
    if page and payload.has_mic and (get_all_settings().get("rec_voice_filter") or "true").lower() == "true":
        from app import voice_filter

        if voice_filter.find_exe():
            filtered = page.with_name(page.name + ".voice.wav")
            if voice_filter.clean(tool_cmd("ffmpeg"), mic or page, filtered):
                if mic:
                    mic.unlink(missing_ok=True)
                mic, voice = filtered, "cleaned"
    print(f"[record] tracks: page={'yes' if page else 'no'} system={'yes' if system else 'no'} "
          f"skip={system_skip:.2f}s echo={'removed' if echo_done else 'no'} voice={voice}", flush=True)
    if screen:
        audio = [p for p in ((mic or page) if payload.has_mic else None, system) if p]
        dest = _recording_folder() / f"{uuid.uuid4().hex[:8]}_{safe_stem}.mp4"
        res = _run_ffmpeg(screen_mix_command(tool_cmd("ffmpeg"), screen, audio, dest, system_skip if len(audio) == 2 else 0.0))
        if res.returncode != 0 or not dest.is_file():
            print("[record] mix failed, parts kept:", (res.stderr or "")[-300:], flush=True)
            dest.unlink(missing_ok=True)
            if mic:
                mic.unlink(missing_ok=True)  # the cleaned microphone was made for the mix: the page's part is kept
            if original_system:  # the parts kept are the ones recorded
                system.unlink(missing_ok=True)
                system = original_system
            return {"salvaged": _salvage_parts(payload.title.strip() or "Запись",
                                               [(screen, True), *[(p, p is page and payload.has_video) for p in (page, system) if p]],
                                               payload.notes)}
        # the parts go once the mixed file is registered (a crash in between kept nothing)
        return {"dest": dest, "has_video": True, "cleanup": [p for p in (screen, page, system, mic, original_system) if p]}

    has_video = bool(payload.has_video and page)
    ext = ".webm" if page and (has_video or not system) else ".m4a"
    dest = _recording_folder() / f"{uuid.uuid4().hex[:8]}_{safe_stem}{ext}"
    cmd = record_mix_command(tool_cmd("ffmpeg"), page, system, has_video, payload.has_mic, dest, system_skip, mic=mic)
    if cmd is None:
        shutil.move(str(page), str(dest))  # the recordings folder may be on another drive
    else:
        res = _run_ffmpeg(cmd)
        if res.returncode != 0 or not dest.is_file():
            if page and not system:
                dest.unlink(missing_ok=True)
                shutil.move(str(page), str(dest))  # the original is still playable
            else:
                print("[record] mix failed, parts kept:", (res.stderr or "")[-300:], flush=True)
                dest.unlink(missing_ok=True)
                if mic:
                    mic.unlink(missing_ok=True)  # the page's own part is kept instead
                if original_system:
                    system.unlink(missing_ok=True)
                    system = original_system
                return {"salvaged": _salvage_parts(payload.title.strip() or "Запись",
                                                   [(p, has_video if p is page else False) for p in (page, system) if p],
                                                   payload.notes)}
    cleanup = [p for p in (page if cmd is not None else None, system, mic, original_system) if p]
    return {"dest": dest, "has_video": has_video, "cleanup": cleanup}


def _mix_in_background(meeting_id: int, payload: RecordFinishPayload, page: Optional[Path], system: Optional[Path],
                       screen: Optional[Path], system_skip: float, safe_stem: str) -> None:
    """The mix of a stopped recording, then its transcription queued; the recording waits as «mixing»."""
    import traceback

    from app import app_status, events
    from app.database import delete_meeting, set_recording_media, update_meeting_progress
    from app.naming import rename_recording_file

    done: Optional[Dict[str, Any]] = None
    try:
        done = _mix_parts(payload, page, system, screen, system_skip, safe_stem)
        if done is None or done.get("salvaged") is not None:  # kept part by part: they are the recordings now
            delete_meeting(meeting_id)
            return
        set_recording_media(meeting_id, str(done["dest"]), bool(done["has_video"]))
        from app.database import delete_file

        # The recording has its file now: a part still held open (an antivirus, the capture thread) is
        # deleted at the next start, and a failed rename leaves the file under its first name. Neither
        # is a reason to mark the recording failed and keep it from transcription
        for p in done.get("cleanup") or []:
            delete_file(str(p))
        try:
            rename_recording_file(meeting_id)  # "2026-10-20 Запись 14-05.m4a"; renamed again once titled
        except Exception:
            traceback.print_exc()
        update_meeting_progress(meeting_id, status="queued", progress=0, stage_text="В очереди на распознавание")
        enqueue_meeting_job(meeting_id)
    except Exception as e:
        traceback.print_exc()
        if not (done and done.get("dest") and (get_meeting(meeting_id) or {}).get("media_path")):
            # failed before the recording had its file: what was recorded is kept part by part, now
            try:
                if done and done.get("dest"):
                    Path(done["dest"]).unlink(missing_ok=True)
                left = [(p, (p is page and payload.has_video) or p is screen) for p in (screen, page, system)
                        if p and Path(p).is_file()]
                from app.main import _salvage_parts

                _salvage_parts(payload.title.strip() or "Запись", left, payload.notes)
                delete_meeting(meeting_id)
                return
            except Exception:
                traceback.print_exc()
        update_meeting_progress(meeting_id, status="failed", progress=0, stage_text="",
                                error_message=f"Не удалось свести дорожки записи: {e}"[:500])
    finally:
        app_status.mixing.discard(meeting_id)
        events.publish({"type": "list"})


def _attach_recording_info(meeting_id: int, payload: RecordFinishPayload) -> None:
    """What the studio knew of the recording: the notes, the «Сейчас говорит» marks, the Teams captions
    as a transcript version, the calendar meeting it was."""
    from app.database import update_meeting_fields

    if payload.notes.strip():
        update_meeting_fields(meeting_id, user_notes=payload.notes[:50000])
    if payload.speaker_marks:
        from app.database import save_transcript_version, set_speaker_marks
        from app.teams_captions import TEAMS, as_transcript

        set_speaker_marks(meeting_id, payload.speaker_marks)
        # The Teams captions are a transcript of their own: shown by their chip, a voice in the merging
        teams_version = as_transcript([mk for mk in payload.speaker_marks if mk.get("text")])
        if teams_version:
            save_transcript_version(meeting_id, TEAMS, teams_version)
    try:
        from datetime import datetime

        from app import calendar_ics

        calendar_ics.apply_to_recording(meeting_id, datetime.fromtimestamp(payload.started_at) if payload.started_at > 0 else None)
    except Exception as e:
        print("[calendar]", e, flush=True)

class UiLangPayload(BaseModel):
    lang: str = "ru"

@router.post("/api/ui/lang")
def api_ui_lang(payload: UiLangPayload) -> Dict[str, Any]:
    """Remembers the UI language for the launcher's splash screen (read by Verbaliox.exe)."""
    lang = "en" if payload.lang == "en" else "ru"
    try:
        (DATA_DIR / "ui-lang.txt").write_text(lang, encoding="utf-8")
    except OSError:
        pass
    return {"lang": lang}

# --- What the page is doing, for the tray icon (see app/app_status.py) ---
class UiStatePayload(BaseModel):
    recording: bool = False

class AutoRecordNoticePayload(BaseModel):
    started: bool
    source: str = "call"   # "call" (app/call_watch.py) or "calendar"
    name: str = ""         # the app of the call or the title of the meeting

@router.post("/api/ui/auto-record")
def api_auto_record_notice(payload: AutoRecordNoticePayload) -> Dict[str, Any]:
    """The page started or stopped a recording by itself: a Windows notification says so."""
    from app.app_status import auto_recording_notice

    return auto_recording_notice(payload.started, payload.source, payload.name)

@router.post("/api/ui/state")
def api_ui_state(payload: UiStatePayload) -> Dict[str, Any]:
    from app.app_status import set_recording, snapshot

    set_recording(payload.recording)
    st = snapshot()
    return {"state": st["state"], "text": st["text"]}

# --- Live captions while recording (see app/live.py) ---
class LiveStartPayload(BaseModel):
    lang: Optional[str] = None
    translate_to: Optional[str] = None
    capture_id: Optional[str] = None  # system audio recorded by the app is mixed into the captions
    speed: str = "quality"            # "quality": the configured model, "fast": a small installed one
    pair: Optional[List[str]] = None  # with translate_to="auto": the two languages, e.g. ["ru", "en"]
    draft: bool = False               # translate the phrase still being spoken too

@router.post("/api/live/start")
def api_live_start(payload: LiveStartPayload) -> Dict[str, Any]:
    from app.live import start_session

    target, pair = _live_target(payload.translate_to, payload.pair)
    s = start_session(payload.lang, target, payload.capture_id, payload.speed, pair)
    s.draft = payload.draft
    return s.state()

@router.post("/api/live/{session_id}/audio")
async def api_live_audio(session_id: str, request: Request, since: int = 0) -> Dict[str, Any]:
    """Body: 16 kHz mono 16-bit little-endian PCM. Returns new final lines, translations and the draft."""
    from starlette.concurrency import run_in_threadpool

    from app.live import get_session

    s = get_session(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Сеанс субтитров не найден")
    data = await request.body()
    if len(data) > 4 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Слишком большой фрагмент звука")
    s.add_pcm16(data)
    await run_in_threadpool(s.step)
    return s.state(since)

class LiveConfigPayload(BaseModel):
    translate_to: Optional[str] = None
    speed: Optional[str] = None
    speech_lang: Optional[str] = None  # "auto" or a language code; None keeps the current one
    pair: Optional[List[str]] = None
    draft: Optional[bool] = None
    caption_model: Optional[str] = None    # "auto" or a model id; None keeps the current one
    translate_model: Optional[str] = None  # "" for auto (by speed) or an Ollama model; None keeps it

class LiveEarlierLine(BaseModel):
    at: float = 0
    text: str = ""

class LiveAskPayload(BaseModel):
    question: str
    lang: str = "ru"
    # Captions switched off and on again: the lines of the sessions before (the page keeps them) and
    # where the current session begins in the recording
    earlier: List[LiveEarlierLine] = []
    offset: float = 0

@router.post("/api/live/{session_id}/ask")
def api_live_ask(session_id: str, payload: LiveAskPayload) -> Dict[str, Any]:
    """A question about what was said so far in a running recording (its live captions)."""
    from app.audio_utils import format_timestamp
    from app.live import get_session
    from app.llm import LlmError, target
    from app.ollama_client import _lang_phrase

    s = get_session(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Субтитры этой записи не идут")
    question = payload.question.strip()[:500]
    if not question:
        raise HTTPException(status_code=400, detail="Пустой вопрос")
    offset = max(0.0, float(payload.offset or 0))
    lines = [f"[{format_timestamp(max(0.0, e.at))}] {e.text.strip()[:500]}" for e in payload.earlier[-3000:] if e.text.strip()]
    lines += [f"[{format_timestamp(ln['start'] + offset)}] {ln['text']}" for ln in s.lines if (ln.get("text") or "").strip()]
    if s.partial:
        lines.append(f"[сейчас] {s.partial}")
    if not lines:
        raise HTTPException(status_code=400, detail="Пока ничего не сказано")
    try:
        llm = target(None)
    except LlmError as e:
        raise HTTPException(status_code=503, detail=str(e))
    text = "\n".join(lines)[-max(6000, llm.max_chars - 2000):]  # the latest part if the call is long
    system = ("Ты помогаешь во время идущего разговора. Отвечай ТОЛЬКО по расшифровке ниже (она из живых субтитров и может "
              "содержать ошибки распознавания). Если ответа нет — так и скажи. Коротко, по делу, 1–4 предложения, "
              f"ссылайся на время в квадратных скобках. Отвечай {_lang_phrase(payload.lang)}.")
    try:
        answer = llm.chat(system, f"Расшифровка разговора:\n{text}\n\nВопрос: {question}")
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)[:300])
    return {"answer": answer, "model": llm.label, "cloud": llm.is_cloud}

@router.post("/api/live/{session_id}/config")
def api_live_config(session_id: str, payload: LiveConfigPayload) -> Dict[str, Any]:
    """Changes the caption translation while recording (language, fast or quality model)."""
    from app.live import get_session

    s = get_session(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Сеанс субтитров не найден")
    target, pair = _live_target(payload.translate_to, payload.pair)
    if payload.draft is not None:
        s.draft = payload.draft
    if payload.caption_model is not None:
        s.set_caption_model(payload.caption_model)
    if payload.translate_model is not None:
        s.set_translate_model(payload.translate_model)
    s.configure(target, payload.speed if payload.speed in ("quality", "fast") else None, payload.speech_lang, pair)
    return s.state(0)

@router.get("/api/live/models")
def api_live_models() -> Dict[str, Any]:
    from app.live_translate import model_choices

    return model_choices()

@router.post("/api/live/{session_id}/stop")
def api_live_stop(session_id: str) -> Dict[str, Any]:
    from app.live import stop_session

    stop_session(session_id)
    return {"ok": True}

class LibraryAskPayload(BaseModel):
    question: str
    lang: str = "ru"
    model: Optional[str] = None
    folder_id: Optional[int] = None  # only recordings in this folder and the folders inside it
    meeting_ids: Optional[List[int]] = None  # only these recordings

@router.post("/api/library/ask")
def api_library_ask(payload: LibraryAskPayload) -> Dict[str, Any]:
    """Answers a question from the transcripts of all recordings, a folder or chosen ones (app/library_qa.py)."""
    from app.database import get_folder, meeting_ids_in_folder
    from app.library_qa import ask_library

    scope: Optional[List[int]] = None
    if payload.folder_id is not None:
        if not get_folder(payload.folder_id):
            raise HTTPException(status_code=404, detail="Папка не найдена")
        scope = meeting_ids_in_folder(payload.folder_id)
    if payload.meeting_ids is not None:
        ids = [int(i) for i in payload.meeting_ids][:500]
        scope = ids if scope is None else [i for i in scope if i in ids]
    try:
        return ask_library(payload.question, answer_lang=payload.lang, model_name=payload.model, meeting_ids=scope)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
