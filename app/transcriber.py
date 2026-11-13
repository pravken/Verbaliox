from __future__ import annotations  # type hints name WhisperModel, which is imported only when used

import json
import re
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from app.hardware import clear_vram, get_hardware_info, register_cuda_dlls

register_cuda_dlls()

# faster-whisper (CTranslate2) and the speaker model (PyTorch) are imported when a job needs them,
# not when the app starts: the window opens in seconds even from a cold disk

from app import vocab
from app.audio_utils import extract_audio_16k_mono, format_timestamp, get_media_duration
from app.database import (
    AUDIO_DIR,
    MODELS_DIR,
    edit_meeting,
    get_all_settings,
    get_meeting,
    meeting_status,
    save_meeting_dub,
    save_meeting_results,
    merge_summaries,
    save_segments_backup,
    stash_transcript_for,
    update_meeting_progress,
)
from app.ollama_client import generate_meeting_summary
from app.text_utils import (
    clean_filler_words_in_segments,
    is_hallucination,
    is_low_quality_segment,
)

# Single worker queue ensures batch jobs run one after another without VRAM collisions
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="whisper_worker")

# Jobs that are queued or running, and jobs the user asked to cancel
_jobs_lock = threading.Lock()
_active_jobs: Set[int] = set()
_cancel_requested: Set[int] = set()
# Mirror of the executor's FIFO for the UI: which recording is running and which are waiting
_queue: List[Dict[str, Any]] = []
_running_id: Optional[int] = None


class JobCancelled(Exception):
    pass


def is_job_active(meeting_id: int) -> bool:
    with _jobs_lock:
        return meeting_id in _active_jobs


def is_transcribing(meeting_id: int) -> bool:
    """A recognition job or a merge of versions of this recording is queued or running: either replaces
    the transcript shown, and edits made meanwhile were hidden by its result."""
    with _jobs_lock:
        return any(q["id"] == meeting_id and q["kind"] in ("transcribe", "merge") for q in _queue)


_running_thread: Optional[int] = None


def request_cancel(meeting_id: int) -> bool:
    """Marks a queued/running job for cancellation. It stops at the next checkpoint; a request to the
    analysis model or FFmpeg it waits on is broken off at once."""
    from app import cancel_scope

    with _jobs_lock:
        if meeting_id not in _active_jobs:
            return False
        _cancel_requested.add(meeting_id)
        # under the lock: let go of it first, the job could end and the next one start on the same
        # worker thread, whose requests the abort then broke off («Обработка отменена» on another recording)
        if _running_id == meeting_id and _running_thread is not None:
            cancel_scope.abort(_running_thread)
    return True


def _publish_queue_changed() -> None:
    from app import events

    events.publish({"type": "queue"})


def _queue_add(meeting_id: int, kind: str, lang: Optional[str] = None) -> None:
    """Call with _jobs_lock held."""
    _queue.append({"id": meeting_id, "kind": kind, "lang": lang, "queued_at": time.time(), "started_at": None})


def _queue_start(meeting_id: int) -> None:
    global _running_id, _running_thread
    from app import cancel_scope, idle_unload

    idle_unload.touch()
    cancel_scope.reset(threading.get_ident())
    with _jobs_lock:
        _running_id = meeting_id
        _running_thread = threading.get_ident()
        for q in _queue:
            if q["id"] == meeting_id:
                q["started_at"] = time.time()
    _publish_queue_changed()


def _queue_finish(meeting_id: int) -> None:
    global _running_id
    from app import idle_unload

    idle_unload.touch()
    from app import app_status

    app_status.set_asr_model(meeting_id)
    with _jobs_lock:
        _queue[:] = [q for q in _queue if q["id"] != meeting_id]
        if _running_id == meeting_id:
            _running_id = None
    _publish_queue_changed()


def queue_snapshot() -> List[Dict[str, Any]]:
    """Running job first, then waiting jobs in the order they will run."""
    from app.database import meeting_briefs

    with _jobs_lock:
        items = [dict(q) for q in _queue]
        running = _running_id
        cancelling = set(_cancel_requested)
    if not items:
        return []
    meetings = meeting_briefs(list({q["id"] for q in items}))
    items.sort(key=lambda q: 0 if q["id"] == running else 1)
    out = []
    waiting_pos = 0
    for q in items:
        m = meetings.get(q["id"])
        if not m:
            continue
        is_running = q["id"] == running
        if not is_running:
            waiting_pos += 1
        out.append(
            {
                **q,
                "title": m.get("title") or "",
                "state": "running" if is_running else "waiting",
                "position": 0 if is_running else waiting_pos,
                "cancelling": q["id"] in cancelling,
                "progress": m.get("progress", 0),
                "stage_text": m.get("stage_text", ""),
            }
        )
    return out


def _drop_work_audio(meeting_id: int, wav_path: Path) -> None:
    """The 16 kHz WAV is for recognition only (345 MB for three hours). The player's waveform is kept
    as a small envelope and the WAV deleted when the app holds its own copy of the sound; a file used
    in place (added by its path) may be moved by its owner, so its WAV stays as the sound to play."""
    import json

    from app.audio_utils import loudness_peaks, peaks_file
    from app.database import delete_file, update_meeting_fields

    m = get_meeting(meeting_id) or {}
    if not m.get("owns_media") or not Path(m.get("media_path") or "").is_file() or not wav_path.is_file():
        return
    try:
        peaks_file(meeting_id).write_text(json.dumps(loudness_peaks(wav_path)), encoding="utf-8")
    except Exception:
        traceback.print_exc()
        return
    update_meeting_fields(meeting_id, audio_path="")
    delete_file(str(wav_path))


def drop_old_work_audio() -> int:
    """_drop_work_audio for recordings no job works on that still have their WAV; returns how many.
    Cancelled and failed ones too: their WAV stayed for good (a retry extracts the sound again)."""
    from app.database import _db_lock, get_connection

    with _db_lock:
        conn = get_connection()
        rows = conn.execute("SELECT id, audio_path FROM meetings WHERE status IN ('completed', 'cancelled', 'failed') "
                            "AND owns_media = 1 AND COALESCE(audio_path, '') != ''").fetchall()
        conn.close()
    n = 0
    for r in rows:
        if not is_job_active(int(r["id"])) and Path(r["audio_path"]).is_file():
            _drop_work_audio(int(r["id"]), Path(r["audio_path"]))
            n += 1
    return n


def _cancel_wanted(meeting_id: int) -> bool:
    with _jobs_lock:
        return meeting_id in _cancel_requested


def _check_cancel(meeting_id: int) -> None:
    with _jobs_lock:
        if meeting_id in _cancel_requested:
            raise JobCancelled()


def clean_meeting_transcript(meeting_id: int) -> Dict[str, Any]:
    import copy

    removed_box = [0]

    def clean(m: Dict[str, Any]) -> tuple:
        segments = m.get("segments") or []
        before = copy.deepcopy(segments)
        cleaned, removed_box[0] = clean_filler_words_in_segments(segments)
        if not removed_box[0]:
            return ()
        m["segments"], m["segments_backup"] = cleaned, before
        return ("segments", "segments_backup")

    updated = edit_meeting(meeting_id, clean)
    if updated is None:
        raise ValueError("Встреча не найдена")
    return {"meeting": updated, "removed_count": removed_box[0]}


def enqueue_meeting_job(meeting_id: int) -> bool:
    """Queues a job unless the same recording is already queued or being processed."""
    with _jobs_lock:
        if meeting_id in _active_jobs:
            return False
        _active_jobs.add(meeting_id)
        _cancel_requested.discard(meeting_id)
        _queue_add(meeting_id, "transcribe")
    _executor.submit(_run_job, meeting_id)
    _publish_queue_changed()
    return True


def _run_job(meeting_id: int) -> None:
    _queue_start(meeting_id)
    try:
        _process_meeting_job(meeting_id)
    finally:
        _queue_finish(meeting_id)
        with _jobs_lock:
            _active_jobs.discard(meeting_id)
            _cancel_requested.discard(meeting_id)
            queue_empty = not _active_jobs
        if queue_empty:
            try:  # a driver failing here (after sleep) must not skip the exports below
                release_whisper_model()
                from app import asr_onnx

                asr_onnx.release_gpu()  # the video memory goes back to the summary model
            except Exception:
                traceback.print_exc()
        _run_pending_exports(meeting_id)


def _run_pending_exports(meeting_id: int) -> None:
    """Exports that waited for this recording's job (see app/pending_exports.py)."""
    try:
        from app.pending_exports import process

        process(meeting_id)
    except Exception:
        traceback.print_exc()


# A job on a finished recording (dub, translation, cut, subtitles) gives it back the status it had:
# a cancelled or failed recording with half a transcript must not become "completed" (the retention
# setting deletes the sound of completed recordings)
FINISHED_STATUSES = ("completed", "failed", "cancelled", "cleared")


def _status_to_return(meeting_id: int) -> str:
    status = meeting_status(meeting_id)
    return status if status in FINISHED_STATUSES else "completed"


def enqueue_dub_job(meeting_id: int, target_lang: str) -> bool:
    """Queues a translate-and-dub job in the same single worker, so it never shares VRAM with a transcription."""
    with _jobs_lock:
        if meeting_id in _active_jobs:
            return False
        _active_jobs.add(meeting_id)
        _cancel_requested.discard(meeting_id)
        _queue_add(meeting_id, "dub", target_lang)
    back = _status_to_return(meeting_id)
    update_meeting_progress(
        meeting_id, status="dubbing", progress=0, stage_text="Дубляж в очереди...", error_message=""
    )
    _executor.submit(_run_dub_job, meeting_id, target_lang, back)
    _publish_queue_changed()
    return True


def _run_dub_job(meeting_id: int, target_lang: str, back: str = "completed") -> None:
    from app.dubbing import run_dub_job

    def _progress(pct: int, text: str) -> None:
        update_meeting_progress(meeting_id, progress=pct, stage_text=text)

    # The transcript stays valid whatever happens to the dub, so the recording goes back to the status
    # it had (`back`); the dub result (or error) is reported in stage_text / error_message.
    _queue_start(meeting_id)
    try:
        meeting = get_meeting(meeting_id)
        if not meeting:
            return
        # Whisper may still be cached from a previous job; the dub models need that VRAM
        release_whisper_model()
        entry = run_dub_job(meeting, target_lang, _progress, lambda: _check_cancel(meeting_id))
        save_meeting_dub(meeting_id, entry)
        update_meeting_progress(
            meeting_id,
            status=back,
            progress=100,
            stage_text=f"Дубляж ({target_lang.upper()}) готов: {Path(entry['path']).name}"
            + (f"; не удалось озвучить фраз: {failed}" if (failed := (entry.get("stats") or {}).get("failed_phrases")) else ""),
            error_message="",
        )
    except JobCancelled:
        update_meeting_progress(meeting_id, status=back, progress=100, stage_text="Дубляж отменён", error_message="")
    except Exception as e:
        tb = traceback.format_exc()
        update_meeting_progress(
            meeting_id,
            status=back,
            progress=100,
            stage_text=f"Ошибка дубляжа: {str(e)[:140]}",
            error_message=f"{e}\n\n{tb[-800:]}",
        )
    finally:
        _queue_finish(meeting_id)
        clear_vram()
        with _jobs_lock:
            _active_jobs.discard(meeting_id)
            _cancel_requested.discard(meeting_id)
        _run_pending_exports(meeting_id)


def _enqueue_side_job(meeting_id: int, kind: str, lang: str, status: str, queued_text: str, runner, *args) -> bool:
    """Queues a job that works on a finished transcript (translation, subtitle rendering)."""
    with _jobs_lock:
        if meeting_id in _active_jobs:
            return False
        _active_jobs.add(meeting_id)
        _cancel_requested.discard(meeting_id)
        _queue_add(meeting_id, kind, lang)
    back = _status_to_return(meeting_id)
    update_meeting_progress(meeting_id, status=status, progress=0, stage_text=queued_text, error_message="")
    _executor.submit(_run_side_job, meeting_id, back, runner, *args)
    _publish_queue_changed()
    return True


def _run_side_job(meeting_id: int, back: str, runner, *args) -> None:
    # Like a dub, these jobs never invalidate the transcript: the recording goes back to the status it
    # had (`back`) and the outcome (done, cancelled, error) is reported in stage_text / error_message.
    _queue_start(meeting_id)
    try:
        done_text = runner(meeting_id, *args)
        update_meeting_progress(meeting_id, status=back, progress=100, stage_text=done_text, error_message="")
    except JobCancelled:
        update_meeting_progress(meeting_id, status=back, progress=100, stage_text=_SIDE_JOB_NAMES[runner][1], error_message="")
    except Exception as e:
        tb = traceback.format_exc()
        update_meeting_progress(
            meeting_id,
            status=back,
            progress=100,
            stage_text=f"Ошибка ({_SIDE_JOB_NAMES[runner][0]}): {str(e)[:140]}",
            error_message=f"{e}\n\n{tb[-800:]}",
        )
    finally:
        _queue_finish(meeting_id)
        with _jobs_lock:
            _active_jobs.discard(meeting_id)
            _cancel_requested.discard(meeting_id)
        _run_pending_exports(meeting_id)


def _translate_runner(meeting_id: int, target_lang: str, model: Optional[str], only_changed: bool) -> str:
    from app.translation import run_translate_job

    res = run_translate_job(
        meeting_id,
        target_lang,
        model=model,
        only_changed=only_changed,
        progress=lambda pct, text: update_meeting_progress(meeting_id, progress=pct, stage_text=text),
        check_cancel=lambda: _check_cancel(meeting_id),
    )
    if not res.get("translated"):
        return f"Перевод ({target_lang.upper()}) уже актуален"
    return f"Перевод ({target_lang.upper()}) готов: {res['translated']} реплик, модель {res.get('model')}"


def _burn_runner(meeting_id: int, lang: str, srt_text: str, out_path: str) -> str:
    from app.video_subtitles import burn_subtitles, probe_media

    meeting = get_meeting(meeting_id)
    if not meeting:
        raise RuntimeError("Запись не найдена")
    media = Path(meeting["media_path"])
    if not media.exists():
        raise RuntimeError(f"Исходный файл не найден: {media}")
    # Whisper may still be cached; the encoder is CPU-bound, but free the VRAM anyway
    release_whisper_model()
    update_meeting_progress(meeting_id, progress=1, stage_text="Встраивание субтитров: подготовка...")
    duration = probe_media(media)["duration"] or float(meeting.get("duration") or 0.0)
    out = burn_subtitles(
        media,
        srt_text,
        Path(out_path),
        duration,
        lambda pct, text: update_meeting_progress(meeting_id, progress=pct, stage_text=text),
        lambda: _check_cancel(meeting_id),
    )
    return f"Видео с субтитрами ({lang.upper()}) готово: {out}"


def _cut_runner(meeting_id: int, kind: str, intervals: List[Tuple[float, float]], has_video: bool, out_path: str) -> str:
    from app.ffmpeg_manager import tool_cmd
    from app.media_cut import DENOISE_FILTER, run_cut

    meeting = get_meeting(meeting_id)
    if not meeting:
        raise RuntimeError("Запись не найдена")
    media = Path(meeting["media_path"])
    if not media.exists():
        raise RuntimeError(f"Исходный файл не найден: {media}")
    label = {"highlights": "Нарезка ключевых моментов", "denoise": "Запись без шума"}.get(kind, "Запись без запинок и пауз")
    update_meeting_progress(meeting_id, progress=1, stage_text=f"{label}: подготовка...")
    out = run_cut(tool_cmd("ffmpeg"), media, intervals, has_video, Path(out_path),
                  lambda r: update_meeting_progress(meeting_id, progress=max(1, int(99 * r)), stage_text=f"{label}: {int(100 * r)}%"),
                  lambda: _check_cancel(meeting_id), afilter=DENOISE_FILTER if kind == "denoise" else "")
    return f"{label} готова: {out}"


def enqueue_cut_job(meeting_id: int, kind: str, intervals: List[Tuple[float, float]], has_video: bool, out_path: str) -> bool:
    return _enqueue_side_job(
        meeting_id, "cut", kind, "rendering", "Нарезка в очереди...", _cut_runner, kind, intervals, has_video, out_path,
    )


def _merge_runner(meeting_id: int) -> str:
    """One transcript from the transcripts of several models (app/transcript_merge.py), shown as the
    version "merged"; the others stay."""
    from app import llm
    from app.database import all_transcripts, is_local_only
    from app.model_manager import format_whisper_model_name
    from app.transcript_merge import MERGED, merge

    meeting = get_meeting(meeting_id)
    if not meeting:
        raise RuntimeError("Запись не найдена")
    versions = all_transcripts(meeting_id)
    update_meeting_progress(meeting_id, progress=5, stage_text="Сведение версий: сопоставление слов...")
    chat, note = None, ""
    try:
        chat = llm.target(None, local_only=is_local_only(meeting)).chat
    except Exception as e:  # no analysis model: the disputed places go to the more accurate model
        print(f"[merge] no analysis model: {e}", flush=True)
        note = " Модель анализа недоступна: спорные места решены по точности моделей."
    # The version on screen is the base: its phrases and speakers — with the names given there — are
    # what the merged text keeps (the most accurate model's were taken, with the names before the renaming)
    shown = meeting.get("transcript_model") or ""
    res = merge(versions, meeting.get("language") or "", chat,
                progress=lambda pct, text: update_meeting_progress(meeting_id, progress=pct, stage_text=text),
                check_cancel=lambda: _check_cancel(meeting_id),
                base=shown if shown not in ("", MERGED, "teams") else None)
    # names given on screen, only when the result is split by the same voices (the version shown is its
    # base): another model's split numbers other people alike, SPEAKER_00 there is not SPEAKER_00 here
    same_split = res["base"] == shown
    for sid, sp in ((meeting.get("speakers") or {}).items() if same_split else []):
        if sid in res["speakers"] and isinstance(sp, dict) and sp.get("name"):
            res["speakers"][sid] = {**res["speakers"][sid], "name": sp["name"], **({"color": sp["color"]} if sp.get("color") else {})}
    _check_cancel(meeting_id)
    stash_transcript_for(meeting_id, MERGED)
    save_segments_backup(meeting_id, [])
    save_meeting_results(meeting_id, speakers=res["speakers"], segments=res["segments"],
                         language=versions[res["base"]].get("language") or meeting.get("language"), transcript_model=MERGED)
    from app.database import set_merged_models

    set_merged_models(meeting_id, res["models"])
    names = ", ".join(format_whisper_model_name(m) for m in res["models"])
    return (f"Сведено из {len(res['models'])} версий ({names}): спорных мест {res['disputed']}, "
            f"из них выбрала модель анализа {res['by_llm']}.{note}")


def enqueue_merge_job(meeting_id: int) -> bool:
    return _enqueue_side_job(meeting_id, "merge", "", "merging", "Сведение версий в очереди...", _merge_runner)


def _words_text(seg: Dict[str, Any]) -> str:
    return " ".join("".join(str(w.get("word") or "") for w in seg.get("words") or []).split())


def resplit_input(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The lines of a transcript as the splitting by voices takes them. A line whose text is still its
    words may be cut at pauses; a line typed over (its text no longer its words) stays whole, so the
    correction is kept."""
    out = []
    for seg in segments:
        s = {k: v for k, v in seg.items() if k not in ("id", "speaker")}
        if seg.get("words") and _words_text(seg) != " ".join(str(seg.get("text") or "").split()):
            s["keep_whole"] = True
        out.append(s)
    return out


def carry_names(old_segments: List[Dict[str, Any]], old_speakers: Dict[str, Dict[str, Any]],
                new_segments: List[Dict[str, Any]], new_speakers: Dict[str, Dict[str, Any]]) -> int:
    """Names given before the new split: a voice still called «Участник N» takes the name of the earlier
    speaker it shares most of its time with, when that is more than half of its time. Each name once,
    to the voice sharing the most seconds with it (one person split in two: the larger part)."""
    from app.voice_profiles import is_default_name

    def spans(segs):
        return [(float(s.get("start") or 0), float(s.get("end") or 0), s.get("speaker")) for s in segs]

    old = spans(old_segments)
    taken = {str(m.get("name") or "").strip().lower() for m in new_speakers.values() if not is_default_name(str(m.get("name") or ""))}
    best: List[Tuple[float, str, str]] = []  # (seconds shared, new speaker, old speaker)
    for sid in new_speakers:
        mine = [(a, b) for a, b, s in spans(new_segments) if s == sid]
        total = sum(b - a for a, b in mine) or 1.0
        shared: Dict[str, float] = {}
        for a, b in mine:
            for oa, ob, os_ in old:
                ov = min(b, ob) - max(a, oa)
                if ov > 0:
                    shared[os_] = shared.get(os_, 0.0) + ov
        for os_, sec in shared.items():
            if sec / total > 0.5:
                best.append((sec, sid, os_))
    named = 0
    used = set()
    for _sec, sid, os_ in sorted(best, key=lambda b: -b[0]):
        meta = old_speakers.get(os_) or {}
        name = str(meta.get("name") or "").strip()
        if sid in used or not name or is_default_name(name) or name.lower() in taken:
            continue
        if not is_default_name(str(new_speakers[sid].get("name") or "")):
            continue
        new_speakers[sid]["name"] = name
        for k in ("color", "role", "is_me"):
            if meta.get(k) not in (None, ""):
                new_speakers[sid][k] = meta[k]
        used.add(sid)
        taken.add(name.lower())
        named += 1
    return named


def _resplit_runner(meeting_id: int, num_speakers: int) -> str:
    """The participants split by voices again on the text there is: nothing is recognized again, the
    corrections typed stay; names come back from the voices known, the studio's marks and Teams
    captions, and the names given before."""
    from app.diarizer import diarize_and_merge_segments, unload_diarizer

    meeting = get_meeting(meeting_id)
    if not meeting:
        raise RuntimeError("Запись не найдена")
    old_segments = meeting.get("segments") or []
    if not old_segments:
        raise RuntimeError("Нет расшифровки, которую можно разделить по голосам")
    wav = Path(meeting.get("audio_path") or "")
    made = None
    if not wav.is_file():
        media = Path(meeting.get("media_path") or "")
        if not media.is_file():
            raise RuntimeError(f"Исходный файл не найден: {media}")
        update_meeting_progress(meeting_id, progress=2, stage_text="Разделение участников: извлечение звука...")
        processing = meeting.get("processing") or {}
        made = wav = AUDIO_DIR / f"resplit_{meeting_id}.wav"
        extract_audio_16k_mono(media, wav, denoise=processing.get("denoise", True), loudnorm=processing.get("loudnorm", True),
                               check_cancel=lambda: _check_cancel(meeting_id))
    try:
        settings = get_all_settings()
        device = settings.get("device") or get_hardware_info()["recommended_device"]
        release_whisper_model()
        _release_onnx()

        def _cb(pct: int, msg: str) -> None:
            _check_cancel(meeting_id)
            update_meeting_progress(meeting_id, progress=pct, stage_text=msg)

        speakers, segments = diarize_and_merge_segments(
            wav_path=wav, raw_segments=resplit_input(old_segments), device=device,
            num_speakers_hint=max(0, int(num_speakers or 0)), diarization_enabled=True, progress_callback=_cb)
    finally:
        unload_diarizer()
        if made is not None:
            from app.database import delete_file

            delete_file(str(made))
    for seg in segments:
        seg.pop("keep_whole", None)
    try:
        from app.voice_profiles import apply_to_speakers

        apply_to_speakers(speakers)
    except Exception:
        traceback.print_exc()
    if meeting.get("speaker_marks"):
        apply_speaker_marks(speakers, segments, meeting["speaker_marks"])
    carry_names(old_segments, meeting.get("speakers") or {}, segments, speakers)
    _check_cancel(meeting_id)

    from app.database import edit_meeting

    def _put(m: Dict[str, Any]) -> tuple:
        # the backup of a cleaning (fillers) is of the lines before this split: brought back it would undo it
        m["segments_backup"] = []
        m["segments"], m["speakers"] = segments, speakers
        return ("segments", "speakers", "segments_backup")

    edit_meeting(meeting_id, _put)
    return f"Участники разделены заново: {len(speakers)}, реплик: {len(segments)}"


def enqueue_resplit_job(meeting_id: int, num_speakers: int = 0) -> bool:
    return _enqueue_side_job(meeting_id, "resplit", "", "splitting", "Разделение участников в очереди...",
                             _resplit_runner, num_speakers)


# runner -> (name for error messages, text after a cancel)
_SIDE_JOB_NAMES = {
    _resplit_runner: ("разделение участников", "Разделение участников отменено"),
    _cut_runner: ("нарезка записи", "Нарезка отменена"),
    _translate_runner: ("перевод", "Перевод отменён"),
    _burn_runner: ("встраивание субтитров", "Встраивание субтитров отменено"),
    _merge_runner: ("сведение версий", "Сведение версий отменено"),
}


def enqueue_translate_job(meeting_id: int, target_lang: str, model: Optional[str] = None, only_changed: bool = False) -> bool:
    return _enqueue_side_job(
        meeting_id, "translate", target_lang, "translating", "Перевод в очереди...",
        _translate_runner, target_lang, model, only_changed,
    )


def enqueue_burn_subtitles_job(meeting_id: int, lang: str, srt_text: str, out_path: str) -> bool:
    return _enqueue_side_job(
        meeting_id, "burn_subs", lang, "rendering", "Встраивание субтитров в очереди...",
        _burn_runner, lang, srt_text, out_path,
    )


def _load_whisper_with_fallback(model_name: str, device: str, compute_type: str) -> WhisperModel:
    """
    Loads faster-whisper model with automatic fallback across compute_types and CPU
    so the program works reliably on ANY user's GPU or CPU.
    """
    from app.model_manager import get_whisper_model_path

    register_cuda_dlls()
    whisper_cache = MODELS_DIR / "whisper"
    whisper_cache.mkdir(parents=True, exist_ok=True)
    model_or_path = get_whisper_model_path(model_name)

    attempts = [
        (device, compute_type),
    ]
    if device == "cuda":
        if compute_type != "int8_float16":
            attempts.append(("cuda", "int8_float16"))
        if compute_type != "int8":
            attempts.append(("cuda", "int8"))
        attempts.append(("cpu", "int8"))
    elif compute_type != "int8":
        attempts.append(("cpu", "int8"))

    last_err = None
    for dev, ctype in attempts:
        try:
            from faster_whisper import WhisperModel

            model = WhisperModel(
                model_or_path,
                device=dev,
                compute_type=ctype,
                download_root=str(whisper_cache),
            )
            if (dev, ctype) != (device, compute_type):
                print(f"[transcriber] Whisper {model_name} loaded as {dev}/{ctype} instead of {device}/{compute_type}", flush=True)
            _whisper_cache["loaded_as"] = (dev, ctype)
            return model
        except Exception as e:
            last_err = e
            continue

    raise RuntimeError(f"Не удалось инициализировать модель Whisper ({model_name}): {last_err}")


# --- Whisper model reuse between queued jobs ---
# Loading large-v3 takes several seconds and a lot of disk I/O. When more recordings are waiting
# in the queue and the GPU has room, the model stays loaded for the next job instead of being
# reloaded every time. It is released when the queue becomes empty, before an LLM summary on
# GPUs without enough free memory, and after any error.
_KEEP_MIN_FREE_VRAM_GB = 3.0  # leave room for the speaker model while Whisper stays loaded
_whisper_cache: Dict[str, Any] = {"key": None, "model": None}


def _free_vram_gb() -> float:
    """Free memory of the video card for all programs (NVML first, app/vram.py): torch alone on Windows
    misses the caption worker's and Ollama's memory, and the waits below were made for exactly those."""
    try:
        from app.vram import gpu_memory

        mem = gpu_memory()
        return float(mem["free_gb"]) if mem else 0.0
    except Exception:
        return 0.0


# About how much VRAM a job needs for Whisper plus the speaker model, in GB
_JOB_VRAM_GB = {"large-v3": 5.0, "large-v3-turbo": 3.5, "medium": 3.0, "small": 2.0}
LIVE_WAIT_POLL_SEC = 5.0


def _wait_for_vram_after_live(meeting_id: int, model_name: str) -> None:
    """While a recording with live captions runs, its caption model shares the GPU. A job that would
    not fit next to it waits for the recording to end instead of running out of memory in the
    middle of both (which can abort the job or stop the captions)."""
    from app import live

    need = _JOB_VRAM_GB.get(model_name, 4.0)
    waited = False
    while live.active_session_count() and _free_vram_gb() < need:
        if not waited:
            update_meeting_progress(meeting_id, stage_text="Ожидание: видеопамять занята субтитрами идущей записи...")
            waited = True
        _check_cancel(meeting_id)
        time.sleep(LIVE_WAIT_POLL_SEC)
    if waited:
        update_meeting_progress(meeting_id, stage_text="Загрузка модели Whisper...")


def _get_whisper_model(model_name: str, device: str, compute_type: str) -> Tuple[WhisperModel, bool]:
    """Returns (model, reused)."""
    key = (model_name, device, compute_type)
    if _whisper_cache["model"] is not None and _whisper_cache["key"] == key:
        return _whisper_cache["model"], True
    release_whisper_model()
    model = _load_whisper_with_fallback(model_name, device, compute_type)
    _whisper_cache.update(key=key, model=model)
    return model, False


def release_whisper_model() -> None:
    if _whisper_cache["model"] is not None:
        _whisper_cache.update(key=None, model=None)
        clear_vram()


def whisper_cache_key() -> Optional[Tuple[str, str, str]]:
    """(model, device, compute_type) of the Whisper model kept in memory, as it was really loaded (a
    load on the video card that failed falls back to the processor), or None."""
    if _whisper_cache["model"] is None or not _whisper_cache["key"]:
        return None
    dev, ctype = _whisper_cache.get("loaded_as") or _whisper_cache["key"][1:]
    return (_whisper_cache["key"][0], dev, ctype)


def _whisper_device(requested: str) -> str:
    """Where the Whisper model in memory really runs: a processor fallback must not get the video
    card's batches (16 windows at once on the CPU: much slower, gigabytes of memory)."""
    key = whisper_cache_key()
    return key[1] if key else requested


def running_job_kind() -> Optional[str]:
    """Kind of the job the worker runs now ("transcribe", "dub", "translate", ...), or None."""
    with _jobs_lock:
        for q in _queue:
            if q["id"] == _running_id:
                return q["kind"]
        return "other" if _preloading else None


def _asr_label(meeting_id: int) -> str:
    """« — Whisper Turbo»: the model recognizing the recording now, for the stage text."""
    from app import app_status
    from app.model_manager import format_whisper_model_name

    model = app_status.asr_model(meeting_id)
    return f" — {format_whisper_model_name(model)}" if model else ""


def running_meeting_id() -> Optional[int]:
    with _jobs_lock:
        return _running_id


def stop_all_jobs(wait_sec: float = 0.0) -> int:
    """«Unload all» as a switch: every queued and running job is cancelled (it stops at its next
    checkpoint); waits up to wait_sec for the running one to end. Returns how many were asked."""
    with _jobs_lock:
        ids = list(_active_jobs)
        _cancel_requested.update(ids)
        thread = _running_thread if _running_id is not None else None
    if thread is not None:
        from app import cancel_scope

        cancel_scope.abort(thread)
    deadline = time.time() + wait_sec
    while wait_sec and time.time() < deadline:
        with _jobs_lock:
            if _running_id is None and not _preloading:
                break
        time.sleep(0.2)
    return len(ids)


_preloading = False


_preloading_name: Optional[str] = None


def _preload_whisper(model_name: Optional[str] = None) -> None:
    global _preloading, _preloading_name
    try:
        settings = get_all_settings()
        hw = get_hardware_info()
        _get_whisper_model(
            model_name or settings.get("whisper_model") or "large-v3-turbo",
            settings.get("device") or hw["recommended_device"],
            settings.get("compute_type") or hw["recommended_compute_type"],
        )
    except Exception:
        traceback.print_exc()
    finally:
        with _jobs_lock:
            _preloading = False
            _preloading_name = None


def enqueue_whisper_preload(model_name: Optional[str] = None) -> bool:
    """Loads a Whisper model (the one from the settings by default) in the job worker, so it never
    races a job. A transcription with the same model reuses it. False when the queue is busy."""
    global _preloading, _preloading_name
    with _jobs_lock:
        if _queue or _preloading:
            return False
        _preloading = True
        _preloading_name = model_name or get_all_settings().get("whisper_model") or "large-v3-turbo"
    _executor.submit(_preload_whisper, model_name)
    return True


def _other_jobs_waiting(meeting_id: int) -> bool:
    with _jobs_lock:
        return bool(_active_jobs - {meeting_id})


def _should_keep_whisper(meeting_id: int, device: str, settings: Dict[str, str]) -> bool:
    if settings.get("keep_model_loaded", "true").lower() != "true":
        return False
    if not _other_jobs_waiting(meeting_id):
        return False
    return device != "cuda" or _free_vram_gb() >= _KEEP_MIN_FREE_VRAM_GB


def _batch_size_for(device: str, hw: Dict[str, Any]) -> int:
    if device != "cuda":
        return 0  # batching gains little on CPU and raises RAM use: decode sequentially
    vram = float(hw.get("vram_total_gb") or 0.0)
    if vram >= 10:
        return 16
    if vram >= 5.5:
        return 8
    return 4


AUTO_CHAPTERS_MIN_SEC = 600  # chapters are made by themselves for recordings this long


def _detect_speech_language(wav_path: Path, main: str, device: str, compute_type: str) -> Optional[str]:
    """The language of the first minute, heard by the main model (app/speech_route.py): Whisper names
    it, GigaAM / Parakeet write text whose letters show it. None when it cannot tell (too little
    speech, the model not downloaded: it is not fetched only for this)."""
    import soundfile as sf

    from app import asr_onnx, speech_route
    from app.model_manager import is_whisper_model_installed

    audio, sr = sf.read(str(wav_path), dtype="float32", frames=int(16000 * speech_route.DETECT_SECONDS))
    if getattr(audio, "ndim", 1) > 1:
        audio = audio.mean(axis=1)
    if asr_onnx.is_onnx_model(main):
        if not asr_onnx.is_installed(main):
            return None
        clip = wav_path.with_name(wav_path.stem + ".lang.wav")
        try:
            sf.write(str(clip), audio, sr)
            from app import onnx_gpu

            # Where the recording would run, so the job reuses this copy instead of loading a second one
            segs = asr_onnx.transcribe(main, clip, speech_route.DETECT_SECONDS, lambda _r: None, lambda: None,
                                       gpu=onnx_gpu.gpu_for_job(main))
        finally:
            clip.unlink(missing_ok=True)
        return speech_route.lang_of_text(" ".join(s["text"] for s in segs))
    if not is_whisper_model_installed(main):
        return None
    model, _ = _get_whisper_model(main, device, compute_type)  # kept: the recording likely needs it next
    _segments, info = model.transcribe(audio, language=None, vad_filter=True, beam_size=1)
    # Silence or music in the first minute: Whisper still names a language, with a low probability
    if float(getattr(info, "language_probability", 0.0) or 0.0) < speech_route.MIN_LANG_PROBABILITY:
        return None
    return "ru" if (info.language or "") == "ru" else "other"


def _start_transcription(
    whisper_model: WhisperModel,
    wav_path: Path,
    *,
    batch_size: int,
    duration: float,
    language: Optional[str],
    hotwords: str,
    vad_enabled: bool,
    multilingual: bool = False,
):
    vad_parameters = dict(min_silence_duration_ms=450, speech_pad_ms=250)
    if batch_size > 0:
        # BatchedInferencePipeline decodes several ~30 s windows at once (much faster on GPU).
        # Without VAD it needs the windows spelled out.
        clips = None
        if not vad_enabled:
            clips = []
            t = 0.0
            while t < duration - 0.2:
                clips.append({"start": t, "end": min(duration, t + 30.0)})
                t += 30.0
        from faster_whisper import BatchedInferencePipeline

        return BatchedInferencePipeline(model=whisper_model).transcribe(
            str(wav_path),
            language=language,
            hotwords=hotwords or None,
            word_timestamps=True,
            vad_filter=vad_enabled,
            vad_parameters=vad_parameters if vad_enabled else None,
            clip_timestamps=clips,
            batch_size=batch_size,
            multilingual=multilingual,
        )
    return whisper_model.transcribe(
        str(wav_path),
        language=language,
        hotwords=hotwords or None,
        word_timestamps=True,
        vad_filter=vad_enabled,
        vad_parameters=vad_parameters,
        condition_on_previous_text=False,
        multilingual=multilingual,
    )


PARTIAL_EVERY_SEC = 20.0


_partial_shown: set = set()  # recordings whose text on screen is a part saved by the job running


def _index_partial(meeting_id: int) -> bool:
    """A first transcription cancelled or failed half way leaves the text recognized so far on screen
    (_PartialTranscript): it is indexed, so it is found by the search like any text. True if there was one."""
    if meeting_id not in _partial_shown:
        return False
    _partial_shown.discard(meeting_id)
    try:
        m = get_meeting(meeting_id) or {}
        if m.get("transcript_model") or not m.get("segments"):
            return False
        save_meeting_results(meeting_id, segments=m["segments"], speakers=m.get("speakers") or {})
        return True
    except Exception:
        traceback.print_exc()
        return False


class _PartialTranscript:
    """Shows the text while it is recognized: every PARTIAL_EVERY_SEC the phrases so far are saved
    (one speaker until diarization runs) and the page is told to reload them."""

    def __init__(self, meeting_id: int):
        self.meeting_id = meeting_id
        self.last = time.time()
        # A recording transcribed again keeps its transcript (edits, speaker names) until the new
        # one is complete: a cancel or a failure must not leave only a fragment of it
        m = get_meeting(meeting_id) or {}
        self.enabled = not (m.get("segments") or [])

    def push(self, raw_segments: List[Dict[str, Any]], force: bool = False) -> None:
        # Longer transcripts are saved less often: each save writes the whole text so far
        every = PARTIAL_EVERY_SEC * max(1, len(raw_segments) // 300 + 1)
        if not self.enabled or not raw_segments or (not force and time.time() - self.last < every):
            return
        self.last = time.time()
        from app import events

        partial = [{**seg, "id": i, "speaker": "SPEAKER_00"} for i, seg in enumerate(raw_segments)]
        save_meeting_results(self.meeting_id, segments=partial, reindex=False,
                             speakers={"SPEAKER_00": {"name": "Участник 1", "color": "#0A84FF"}})
        _partial_shown.add(self.meeting_id)
        events.publish({"type": "segments", "id": self.meeting_id})


def _collect_segments(meeting_id: int, segments_iter, total_dur: float,
                      report: Optional[Callable[[float], None]] = None) -> List[Dict[str, Any]]:
    """report(ratio): progress of another model's pass (the precise mode) instead of the job's own
    progress and the text shown while it is recognized."""
    raw_segments: List[Dict[str, Any]] = []
    partial = None if report else _PartialTranscript(meeting_id)
    for seg in segments_iter:
        _check_cancel(meeting_id)
        text = (seg.text or "").strip()
        if is_hallucination(text) or is_low_quality_segment(
            getattr(seg, "no_speech_prob", None),
            getattr(seg, "avg_logprob", None),
            getattr(seg, "compression_ratio", None),
        ):
            continue

        words_list = []
        if seg.words:
            for w in seg.words:
                words_list.append(
                    {
                        "start": round(float(w.start), 2),
                        "end": round(float(w.end), 2),
                        "word": w.word,
                        "prob": round(float(getattr(w, "probability", 1.0)), 2),
                    }
                )

        raw_segments.append(
            {
                "start": round(float(seg.start), 2),
                "end": round(float(seg.end), 2),
                "text": text,
                "words": words_list,
            }
        )

        ratio = min(1.0, float(seg.end) / total_dur)
        if report:
            report(ratio)
            continue
        partial.push(raw_segments)
        # Update progress between 16% and 65%
        pct = 16 + int(49 * ratio)
        update_meeting_progress(
            meeting_id,
            progress=pct,
            stage_text=(
                f"Транскрибация{_asr_label(meeting_id)}: {format_timestamp(seg.end)} из {format_timestamp(total_dur)} "
                f"({int(ratio * 100)}%)"
            ),
        )
    # Batched decoding yields windows in order, but keep the timeline strictly sorted
    raw_segments.sort(key=lambda s: (s["start"], s["end"]))
    return raw_segments


def _after_transcription(
    meeting_id: int,
    segments: List[Dict[str, Any]],
    speakers: Dict[str, Any],
    lang: str,
    settings: Dict[str, str],
) -> List[str]:
    """Optional steps that must never fail the transcription; returns short notes for the status."""
    from app import obsidian
    from app.database import update_meeting_fields
    from app.ollama_client import generate_meeting_title, is_generic_title

    notes: List[str] = []
    meeting = get_meeting(meeting_id) or {}
    if (
        segments
        and settings.get("auto_title", "true").lower() == "true"
        and meeting.get("title_is_default")
        and is_generic_title(meeting.get("title") or "")
    ):
        from app import llm
        from app.database import is_local_only

        local_only = is_local_only(meeting)
        if llm.available(settings, local_only=local_only):
            update_meeting_progress(meeting_id, progress=94, stage_text="Название записи по содержанию...")
            try:
                title = generate_meeting_title(segments, speakers, answer_lang=lang, local_only=local_only)
                if title:
                    update_meeting_fields(meeting_id, title=title, title_is_default=0)
                    from app.naming import rename_recording_file

                    rename_recording_file(meeting_id)
            except Exception as e:
                print(f"[title] meeting {meeting_id}: {e}", flush=True)
    try:  # a recurring meeting joins the series of the earlier ones (app/series.py)
        from app import series

        series.auto_assign(meeting_id)
    except Exception as e:
        print(f"[series] meeting {meeting_id}: {e}", flush=True)
    if obsidian.auto_export_enabled(settings):
        update_meeting_progress(meeting_id, progress=97, stage_text="Сохранение заметки в Obsidian...")
        try:
            # The job is not "completed" yet: the note is written for the finished transcript
            path = obsidian.export_meeting(meeting_id, generate=True, in_job=True)
            notes.append(f"заметка Obsidian: {path.name}")
        except Exception as e:
            notes.append(f"Obsidian: {str(e)[:120]}")
    return notes


def _live_captions_on() -> bool:
    try:
        from app import live

        return live.has_sessions()
    except Exception:
        return False


def _release_onnx(model: Optional[str] = None) -> None:
    """GigaAM / Parakeet out of memory, but not the copy the live captions of a recording going on
    use (the processor's): it reloaded for seconds each time, captions stalled, 2-3 times a job."""
    from app import asr_onnx

    if _live_captions_on():
        if model:
            asr_onnx.release(model, gpu=True)
        else:
            asr_onnx.release_gpu()
    elif model:
        asr_onnx.release(model)
    else:
        asr_onnx.release()


def _release_speech_models() -> None:
    """Whisper and GigaAM / Parakeet out of memory: the next model (another one, or the analysis
    model) loads into a free computer instead of next to them."""
    release_whisper_model()
    try:
        _release_onnx()
    except Exception:
        traceback.print_exc()
    try:  # the worker of live captions keeps its Whisper after a recording: not while captions run
        from app import live

        worker = live._worker
        if worker is not None and worker.proc is not None and worker.proc.poll() is None and not live.has_sessions():
            with worker.lock:
                worker._kill()
    except Exception:
        traceback.print_exc()
    clear_vram()


def _release_analysis_models() -> None:
    """The analysis models Ollama holds go before a speech model loads (not while live captions run),
    and so does the Whisper the caption worker keeps for two minutes after a recording: with them still
    in the video memory GigaAM / Parakeet went to the processor for the whole recording."""
    try:
        from app.vram import ollama_loaded, ollama_release_others

        asked = set(ollama_release_others())
        # Ollama frees the memory a while after it is asked: waited for (a second was often too short)
        deadline = time.time() + 6.0
        while asked and time.time() < deadline and asked & {m["name"] for m in ollama_loaded()}:
            time.sleep(0.3)
    except Exception as e:
        print(f"[transcriber] Ollama models not unloaded: {e}", flush=True)
    try:
        from app import live

        worker = live._worker
        if worker is not None and worker.proc is not None and worker.proc.poll() is None and not live.has_sessions():
            with worker.lock:
                worker._kill()
    except Exception:
        traceback.print_exc()


_WORD_RE = re.compile(r"\w+", re.UNICODE)


def _phrase_by_words(segments: List[Dict[str, Any]], at: float, text: str, window: float = 15.0) -> Optional[str]:
    """The speaker of the phrase within `window` s of `at` that shares most words with `text` (half of
    them at least), or None."""
    words = {w for w in _WORD_RE.findall(text.lower()) if len(w) > 2}
    if len(words) < 2:
        return None
    best, score = None, 0.5
    for seg in segments:
        a, b = float(seg.get("start") or 0), float(seg.get("end") or 0)
        if b < at - window or a > at + window:
            continue
        seg_words = {w for w in _WORD_RE.findall(str(seg.get("text") or "").lower()) if len(w) > 2}
        if not seg_words:
            continue
        share = len(words & seg_words) / len(words)
        if share > score:
            best, score = seg.get("speaker"), share
    return best


def apply_speaker_marks(speakers: Dict[str, Dict[str, Any]], segments: List[Dict[str, Any]],
                        marks: List[Dict[str, Any]]) -> int:
    """«Сейчас говорит» marked in the studio: the voice heard at those moments gets the name. Each
    mark votes for the speaker of the phrase going on then (or the nearest one within 3 s); each
    name goes to one voice and each voice takes one name, the strongest votes first. Returns how
    many voices were named."""
    votes: Dict[Tuple[str, str], int] = {}
    for mk in marks or []:
        at, name = float(mk.get("at") or 0), str(mk.get("name") or "").strip()
        if not name:
            continue
        # A caption line of Teams: the phrase near it with the same words (captions lag behind and the
        # moment can fall on the next speaker's phrase)
        by_text = _phrase_by_words(segments, at, mk.get("text") or "")
        if by_text is not None:
            if by_text in speakers:
                votes[(name, by_text)] = votes.get((name, by_text), 0) + 2  # a match of words weighs more
            continue
        best, gap = None, 3.0
        for seg in segments:
            a, b = float(seg.get("start") or 0), float(seg.get("end") or 0)
            d = 0.0 if a <= at <= b else min(abs(at - a), abs(at - b))
            if d < gap or (d == 0.0 and best is None):
                best, gap = seg.get("speaker"), d
                if d == 0.0:
                    break
        if best in speakers:
            votes[(name, best)] = votes.get((name, best), 0) + 1
    named, used_names, used_spk = 0, set(), set()
    for (name, spk), _n in sorted(votes.items(), key=lambda kv: -kv[1]):
        if name.lower() in used_names or spk in used_spk:
            continue
        speakers[spk]["name"] = name
        used_names.add(name.lower())
        used_spk.add(spk)
        named += 1
    return named


# --- The precise mode: other models recognize the recording too, and the versions are merged ---
ENSEMBLE_CANDIDATES = ("gigaam-v3", "large-v3", "parakeet-v3", "large-v3-turbo")
ENSEMBLE_MAX_MODELS = 3  # with the main one: each model is one more pass over the whole recording
ENSEMBLE_ALWAYS = "large-v3"  # Whisper Pro


def ensemble_models(settings: Dict[str, str], main_model: str, lang: Optional[str], mixed: bool) -> List[str]:
    """The other models of the precise mode for a recording: installed and knowing its language. The
    ones chosen in the settings, else the most accurate installed ones (transcript_merge.ranked)."""
    from app import asr_onnx
    from app.model_manager import WHISPER_CATALOG, is_whisper_model_installed
    from app.transcript_merge import ranked

    chosen = [m.strip() for m in (settings.get("asr_ensemble_models") or "").split(",") if m.strip()]
    whisper_ids = {m["id"] for m in WHISPER_CATALOG}
    out: List[str] = []
    for m in chosen or ENSEMBLE_CANDIDATES:
        if m == main_model or m in out:
            continue
        if asr_onnx.is_onnx_model(m):
            if not asr_onnx.is_installed(m) or not asr_onnx.supports_language(m, lang):
                continue
            if mixed and len(asr_onnx.ONNX_MODELS[m]["languages"]) == 1:
                continue
        elif m not in whisper_ids or not is_whisper_model_installed(m):
            continue
        out.append(m)
    if chosen:
        return out
    order = ranked(out, lang or "")
    # Whisper Pro is always among them when it is downloaded: the most robust for noisy calls and
    # accents, it is the variant the others are weighed against
    if ENSEMBLE_ALWAYS in order:
        order = [ENSEMBLE_ALWAYS] + [m for m in order if m != ENSEMBLE_ALWAYS]
    return order[: ENSEMBLE_MAX_MODELS - 1]


def _speakers_by_time(segments: List[Dict[str, Any]], base: List[Dict[str, Any]]) -> None:
    """Another model's phrases get the speaker of the phrase split by voices they overlap most."""
    for seg in segments:
        best, speaker = 0.0, (base[0].get("speaker") if base else "SPEAKER_00")
        for b in base:
            ov = min(seg["end"], float(b.get("end") or 0)) - max(seg["start"], float(b.get("start") or 0))
            if ov > best:
                best, speaker = ov, b.get("speaker")
        seg["speaker"] = speaker or "SPEAKER_00"


def _recognize_with(meeting_id: int, model: str, wav_path: Path, total_dur: float, language: Optional[str],
                    mixed: bool, processing: Dict[str, Any], settings: Dict[str, str], device: str,
                    compute_type: str, hw: Dict[str, Any], report: Callable[[float], None]) -> List[Dict[str, Any]]:
    """One more pass of another model over the recording: phrases with their words, no speakers."""
    from app import asr_onnx, onnx_gpu

    if asr_onnx.is_onnx_model(model):
        use_gpu = onnx_gpu.gpu_for_job(model)
        args = (model, wav_path, total_dur, report, lambda: _check_cancel(meeting_id))
        try:
            segs = asr_onnx.transcribe(*args, gpu=use_gpu, leveling=processing.get("leveling", True))
        except JobCancelled:
            raise
        except Exception:
            if not use_gpu:
                raise
            traceback.print_exc()
            asr_onnx.release(model, gpu=True)
            segs = asr_onnx.transcribe(*args, leveling=processing.get("leveling", True))
        _release_onnx(model)  # the next model or the analysis model needs the memory
        return segs
    whisper, _ = _get_whisper_model(model, device, compute_type)
    batch = _batch_size_for(_whisper_device(device), hw) if settings.get("batched_inference", "true").lower() == "true" else 0
    decode = dict(duration=total_dur, language=language, hotwords=vocab.hotwords(),
                  vad_enabled=processing.get("vad", True), multilingual=mixed)
    try:
        it, _info = _start_transcription(whisper, wav_path, batch_size=batch, **decode)
        return _collect_segments(meeting_id, it, total_dur, report=report)
    except JobCancelled:
        raise
    except Exception:
        if not batch:
            raise
        clear_vram()
        it, _info = _start_transcription(whisper, wav_path, batch_size=0, **decode)
        return _collect_segments(meeting_id, it, total_dur, report=report)


def _made_with(language: Optional[str], mixed: bool, processing: Dict[str, Any]) -> Dict[str, Any]:
    """What a model's version was recognized with: a version made with another language or other
    sound processing is not reused by a later precise run."""
    return {"language": "mixed" if mixed else (language or "auto"), "denoise": bool(processing.get("denoise", True)),
            "loudnorm": bool(processing.get("loudnorm", True)), "vad": bool(processing.get("vad", True))}


def _run_ensemble(meeting_id: int, main_model: str, extra: List[str], wav_path: Path, total_dur: float,
                  language: Optional[str], detected_lang: str, mixed: bool, processing: Dict[str, Any],
                  settings: Dict[str, str], device: str, compute_type: str, hw: Dict[str, Any],
                  segments: List[Dict[str, Any]], speakers: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The other models recognize the recording, each version is kept, and all are merged into one
    (app/transcript_merge.py): where the models differ the analysis model picks the variant by the
    words around it, a portion of places at a time. Returns the merge result, None if it was not made."""
    from datetime import datetime

    from app import llm
    from app.database import all_transcripts, is_local_only, save_transcript_version
    from app.model_manager import format_whisper_model_name
    from app.transcript_merge import MERGED, merge

    done: List[str] = []
    ready = all_transcripts(meeting_id)
    made_with = _made_with(language, mixed, processing)

    def reusable(version: Dict[str, Any]) -> bool:
        if not version.get("segments"):
            return False
        if version.get("made_with") is not None:
            return version["made_with"] == made_with
        # made before versions said how: only one in the language heard now
        return not detected_lang or (version.get("language") or "") in ("", detected_lang)

    for k, model in enumerate(extra):
        _check_cancel(meeting_id)
        if reusable(ready.get(model) or {}):
            # this model already transcribed the recording: its version is used as it is (its phrases
            # take the speakers of this run), not recognized again
            segs = ready[model]["segments"]
            _speakers_by_time(segs, segments)
            save_transcript_version(meeting_id, model, {**ready[model], "segments": segs, "speakers": speakers})
            done.append(model)
            continue
        _release_speech_models()  # one model in memory at a time: the one before goes first
        name = format_whisper_model_name(model)
        from app import app_status

        app_status.set_asr_model(meeting_id, model)
        lo, hi = 70 + 15 * k // len(extra), 70 + 15 * (k + 1) // len(extra)

        def report(ratio: float, name=name, lo=lo, hi=hi, k=k) -> None:
            update_meeting_progress(meeting_id, status="transcribing", progress=lo + int((hi - lo) * min(1.0, ratio)),
                                    stage_text=f"Точный режим: распознавание {name} ({k + 1} из {len(extra)}): "
                                               f"{format_timestamp(ratio * total_dur)} из {format_timestamp(total_dur)}")

        report(0.0)
        try:
            segs = _recognize_with(meeting_id, model, wav_path, total_dur, language, mixed, processing, settings,
                                   device, compute_type, hw, report)
        except JobCancelled:
            raise
        except Exception as e:  # one model failing leaves the others
            print(f"[ensemble] {model} failed on meeting {meeting_id}: {e}", flush=True)
            traceback.print_exc()
            continue
        segs = vocab.fix_segments([s for s in segs if (s.get("text") or "").strip()])
        _speakers_by_time(segs, segments)
        for i, seg in enumerate(segs):
            seg["id"] = i
        save_transcript_version(meeting_id, model, {"segments": segs, "speakers": speakers, "language": detected_lang,
                                                    "made_with": made_with,
                                                    "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
        done.append(model)
    _release_speech_models()  # the analysis model resolves the disputed places next
    if not done:
        return None
    _check_cancel(meeting_id)
    # «transcribing», not «merging»: this is still the transcription job, resumed after a restart like
    # its other steps (a «merging» recording was taken for a manual merge and set completed, with no
    # summary or title ever made)
    update_meeting_progress(meeting_id, status="transcribing", progress=86, stage_text="Сведение версий: сопоставление слов...")
    chat = None
    try:
        chat = llm.target(None, local_only=is_local_only(get_meeting(meeting_id))).chat
    except Exception as e:  # no analysis model: the disputed places go to the more accurate model
        print(f"[ensemble] no analysis model: {e}", flush=True)
    # the Teams captions of the recording (app/teams_captions.py) are one more voice, a light one
    versions = {m: v for m, v in all_transcripts(meeting_id).items() if m in [main_model, *done, "teams"]}
    res = merge(versions, detected_lang or "", chat, base=main_model,
                progress=lambda pct, text: update_meeting_progress(meeting_id, progress=86 + 3 * pct // 100, stage_text=text),
                check_cancel=lambda: _check_cancel(meeting_id))
    _check_cancel(meeting_id)
    stash_transcript_for(meeting_id, MERGED)
    save_meeting_results(meeting_id, speakers=res["speakers"], segments=res["segments"], language=detected_lang,
                         transcript_model=MERGED)
    from app.database import set_merged_models

    set_merged_models(meeting_id, res["models"])
    res["chat"] = chat is not None
    return res


def _process_meeting_job(meeting_id: int) -> None:
    meeting = get_meeting(meeting_id)
    if not meeting:
        return
    from app.database import update_meeting_fields

    whisper_model = None

    settings = get_all_settings()
    hw = get_hardware_info()

    media_path = Path(meeting["media_path"])
    if not media_path.exists():
        update_meeting_progress(
            meeting_id,
            status="failed",
            progress=0,
            stage_text="Ошибка: исходный медиафайл не найден",
            error_message=f"Файл не найден: {media_path}",
        )
        return

    try:
        # 1. Extract 16kHz mono WAV + Studio Voice Denoising & Loudness Normalization
        # What is done to the sound and the text: chosen for this recording, else the settings
        processing = meeting.get("processing") or {}
        denoise, loudnorm = processing.get("denoise", True), processing.get("loudnorm", True)
        update_meeting_progress(
            meeting_id,
            status="extracting_audio",
            progress=4,
            stage_text=(
                "Шумоподавление и нормализация громкости (FFmpeg)..." if denoise and loudnorm
                else "Шумоподавление (FFmpeg)..." if denoise
                else "Нормализация громкости (FFmpeg)..." if loudnorm
                else "Извлечение аудиодорожки (FFmpeg 16 kHz mono)..."
            ),
            error_message="",
        )

        wav_path = AUDIO_DIR / f"meeting_{meeting_id}.wav"
        _check_cancel(meeting_id)  # cancelled while waiting: do not spend minutes extracting audio
        extract_audio_16k_mono(media_path, wav_path, denoise=denoise, loudnorm=loudnorm,
                               check_cancel=lambda: _check_cancel(meeting_id))
        duration = get_media_duration(wav_path) or get_media_duration(media_path)
        _release_analysis_models()  # the speech model gets the memory an analysis model held

        update_meeting_progress(
            meeting_id,
            progress=10,
            stage_text=f"Звук очищен и выровнен ({format_timestamp(duration)}). Загрузка модели Whisper...",
            duration=duration,
            audio_path=str(wav_path),
        )

        # 2. Load Whisper model
        from app.model_manager import format_whisper_model_name

        model_name = meeting.get("model_name") or settings.get("whisper_model") or "large-v3-turbo"
        if model_name in ("merged", "teams"):  # not models (a recording that showed one could get its name as its model)
            from app import speech_route

            model_name = speech_route.default_choice(settings)
        device = settings.get("device") or hw["recommended_device"]
        compute_type = settings.get("compute_type") or hw["recommended_compute_type"]
        # The language chosen for the recording: kept apart from the one heard (stored in language below),
        # so "several languages" or "auto" stay for the next run
        lang_setting = meeting.get("language_choice") or meeting.get("language") or settings.get("language") or "auto"
        if not meeting.get("language_choice"):
            from app.database import update_meeting_fields

            update_meeting_fields(meeting_id, language_choice=lang_setting)
        from app import speech_route

        if model_name == speech_route.AUTO:
            # The model for Russian or the main one, by the language of the speech (app/speech_route.py)
            if speech_route.routing_on(settings) and lang_setting in ("auto", "", None):
                update_meeting_progress(meeting_id, stage_text="Определение языка речи...")
            model_name, routed_lang = speech_route.resolve(
                settings, lang_setting,
                lambda: _detect_speech_language(wav_path, speech_route.main_model(settings), device, compute_type))
            if routed_lang == "ru" and lang_setting in ("auto", "", None):
                lang_setting = "ru"
            from app import asr_onnx as _onnx

            if _onnx.is_onnx_model(model_name) and not _onnx.is_onnx_model(speech_route.main_model(settings)):
                release_whisper_model()  # Whisper heard the language; GigaAM / Parakeet does the rest
            _check_cancel(meeting_id)
        pretty_whisper = format_whisper_model_name(model_name)
        # "mixed": people switch languages (Russian and English in one call): detected per window
        mixed = lang_setting == "mixed"
        language = None if lang_setting in ("auto", "mixed", "", None) else lang_setting
        vad_enabled = processing.get("vad", True)

        _check_cancel(meeting_id)
        from app import asr_onnx

        from app.model_manager import WHISPER_REPLACED

        model_name = {**WHISPER_REPLACED, **asr_onnx.REPLACED}.get(model_name, model_name)
        from app import app_status

        app_status.set_asr_model(meeting_id, model_name)
        # The precise mode on a recording this model already transcribed («Все модели» to add the
        # others): its text is used as it is — recognizing it again took minutes and replaced the
        # corrections made in it. A language chosen since then that differs from the one heard: done anew
        shown = meeting.get("segments") or []
        heard = (meeting.get("language") or "").strip()
        diarization_enabled = processing.get("diarization", True)
        num_speakers_hint = int(meeting.get("num_speakers_hint") or settings.get("num_speakers") or 0)
        made_with_now = json.dumps({**_made_with(language, lang_setting == "mixed", processing),
                                    "diarization": bool(diarization_enabled), "speakers": num_speakers_hint}, sort_keys=True)
        before = meeting.get("transcript_made_with") or ""
        reuse_main = bool(processing.get("ensemble") and shown and meeting.get("transcript_model") == model_name
                          # made the same way (the number of people, the processing, the language);
                          # a text from before this was kept: by the language alone
                          and (before == made_with_now if before
                               else lang_setting in ("auto", "mixed", "", None) or lang_setting == heard))
        marks_named = 0
        mixed = lang_setting == "mixed"
        if reuse_main:
            merged_segments = [dict(x) for x in shown]
            speakers_meta = dict(meeting.get("speakers") or {})
            # the language heard: the page's re-run writes its choice («auto») over it, so a real one
            # is taken from the text itself when it is not there
            if heard in ("", "auto", "mixed"):
                heard = asr_onnx.guess_language(" ".join(str(x.get("text") or "") for x in shown[:80])) or ""
            detected_lang = language or heard or "ru"
            whisper_model = None
            update_meeting_progress(meeting_id, status="transcribing", progress=66,
                                    stage_text=f"Точный режим: расшифровка {pretty_whisper} уже есть — берётся она")
        else:
            onnx_engine = asr_onnx.is_onnx_model(model_name)
            if onnx_engine:
                # GigaAM / Parakeet on ONNX Runtime (app/asr_onnx.py): on the GPU when its build is installed
                # and there is room (app/onnx_gpu.py), else on the CPU
                if mixed and len(asr_onnx.ONNX_MODELS[model_name]["languages"]) == 1:
                    raise RuntimeError(f"{asr_onnx.ONNX_MODELS[model_name]['name']} понимает только один язык. Для записей на "
                                       "нескольких языках выберите Parakeet или Whisper.")
                if not asr_onnx.supports_language(model_name, language):
                    raise RuntimeError(f"{asr_onnx.ONNX_MODELS[model_name]['name']} не распознаёт язык «{language}». "
                                       "Выберите Whisper или другую модель для этой записи.")
                from app import onnx_gpu

                onnx_name = asr_onnx.ONNX_MODELS[model_name]["name"]
                if not asr_onnx.is_installed(model_name):  # picked before it was downloaded: its files first
                    update_meeting_progress(meeting_id, progress=12, stage_text=f"Скачивание модели {onnx_name}...")
                    try:
                        asr_onnx.ensure_downloaded(model_name, lambda pct: update_meeting_progress(
                            meeting_id, stage_text=f"Скачивание модели {onnx_name}: {pct}%"))
                    except Exception as e:
                        raise RuntimeError(f"Не удалось скачать модель {onnx_name}: {e}")
                    _check_cancel(meeting_id)
                use_gpu = onnx_gpu.gpu_for_job(model_name)
                update_meeting_progress(meeting_id, status="transcribing", progress=15,
                                        stage_text=f"Распознавание речи — {asr_onnx.ONNX_MODELS[model_name]['name']}"
                                        + (" на видеокарте" if use_gpu else ""))
                total_dur = max(1.0, float(duration or 1.0))

                where = {"gpu": " на видеокарте" if use_gpu else ""}

                def _onnx_progress(ratio: float) -> None:
                    update_meeting_progress(meeting_id, progress=16 + int(49 * ratio),
                                            stage_text=f"Транскрибация — {onnx_name}{where['gpu']}: {format_timestamp(ratio * total_dur)} из {format_timestamp(total_dur)}")

                partial = _PartialTranscript(meeting_id)
                onnx_done: List[Dict[str, Any]] = []

                def _onnx_progress_and_partial(ratio: float) -> None:
                    _onnx_progress(ratio)
                    partial.push(onnx_done)

                try:
                    raw_segments = asr_onnx.transcribe(model_name, wav_path, total_dur, _onnx_progress_and_partial,
                                                       lambda: _check_cancel(meeting_id), out=onnx_done, gpu=use_gpu,
                                                       leveling=processing.get("leveling", True))
                except JobCancelled:
                    raise
                except Exception:
                    if not use_gpu:
                        raise
                    traceback.print_exc()  # CUDA out of memory, a missing DLL: the CPU does the same work
                    asr_onnx.release(model_name, gpu=True)
                    onnx_done.clear()
                    where["gpu"] = " на процессоре"
                    update_meeting_progress(meeting_id, stage_text="Видеокарта не справилась — распознавание на процессоре")
                    raw_segments = asr_onnx.transcribe(model_name, wav_path, total_dur, _onnx_progress_and_partial,
                                                       lambda: _check_cancel(meeting_id), out=onnx_done,
                                                       leveling=processing.get("leveling", True))
                text_all = " ".join(s["text"] for s in raw_segments)
                detected_lang = language or asr_onnx.guess_language(text_all)
                whisper_model = None
                reused = False
            else:
                from app.model_manager import ensure_whisper_model, is_whisper_model_installed

                if not is_whisper_model_installed(model_name):  # picked before it was downloaded: the model first
                    update_meeting_progress(meeting_id, progress=12, stage_text=f"Скачивание модели {pretty_whisper}...")
                    shown = {"mb": -100.0}

                    def _download_progress(mb: float, total: float) -> None:
                        _check_cancel(meeting_id)  # a cancel stops the download too
                        if mb - shown["mb"] >= 20 or mb >= total:
                            shown["mb"] = mb
                            update_meeting_progress(meeting_id, stage_text=f"Скачивание модели {pretty_whisper}: {mb:.0f} из {total:.0f} МБ")

                    try:
                        ensure_whisper_model(model_name, _download_progress, lambda: _check_cancel(meeting_id))
                    except JobCancelled:
                        raise
                    except Exception as e:
                        raise RuntimeError(f"Не удалось скачать модель {pretty_whisper}: {e}")
                if device == "cuda" and _whisper_cache["key"] != (model_name, device, compute_type):
                    _wait_for_vram_after_live(meeting_id, model_name)
                whisper_model, reused = _get_whisper_model(model_name, device, compute_type)

                # `hotwords` is applied to every 30s window; `initial_prompt` would only affect the first
                # window because condition_on_previous_text is disabled.
                hotwords = vocab.hotwords()
                runs_on = _whisper_device(device)
                batch_size = (
                    _batch_size_for(runs_on, hw)
                    if settings.get("batched_inference", "true").lower() == "true"
                    else 0
                )
                update_meeting_progress(
                    meeting_id,
                    status="transcribing",
                    progress=15,
                    stage_text=f"Распознавание речи — {pretty_whisper}"
                    + (" на процессоре: видеокарта не загрузила модель" if device == "cuda" and runs_on != "cuda" else "")
                    + (f", пакетами по {batch_size}" if batch_size else "")
                    + (" (модель уже загружена)" if reused else ""),
                )
                total_dur = max(1.0, float(duration or 1.0))
                decode = dict(duration=total_dur, language=language, hotwords=hotwords, vad_enabled=vad_enabled, multilingual=mixed)

                try:
                    segments_iter, info = _start_transcription(whisper_model, wav_path, batch_size=batch_size, **decode)
                    raw_segments = _collect_segments(meeting_id, segments_iter, total_dur)
                except JobCancelled:
                    raise
                except Exception as batch_err:
                    if not batch_size:
                        raise
                    # e.g. out of GPU memory with a large batch: redo the file the classic way
                    print(f"[transcriber] Batched decoding failed ({batch_err}); retrying sequentially", flush=True)
                    clear_vram()
                    update_meeting_progress(
                        meeting_id, progress=16, stage_text=f"Распознавание речи — {pretty_whisper} (обычный режим)"
                    )
                    segments_iter, info = _start_transcription(whisper_model, wav_path, batch_size=0, **decode)
                    raw_segments = _collect_segments(meeting_id, segments_iter, total_dur)

                detected_lang = getattr(info, "language", None) or (language or "ru")

            # The dictionary for every model: Whisper only took it as a hint, GigaAM and Parakeet not at all
            raw_segments = vocab.fix_segments(raw_segments)

            # Free Whisper before diarization unless the next queued job can reuse it
            whisper_model = None
            if not _should_keep_whisper(meeting_id, device, settings):
                release_whisper_model()
            clear_vram()
            _check_cancel(meeting_id)

            # 3. Speaker Diarization (token-free ECAPA-TDNN clustering)
            diarization_enabled = processing.get("diarization", True)
            num_speakers_hint = int(meeting.get("num_speakers_hint") or settings.get("num_speakers") or 0)

            update_meeting_progress(
                meeting_id,
                status="diarizing",
                progress=68,
                stage_text="Разделение участников встречи по голосам...",
            )

            def _diar_cb(pct: int, msg: str) -> None:
                _check_cancel(meeting_id)  # called per batch of voices: a cancel stops the splitting at once
                update_meeting_progress(meeting_id, progress=pct, stage_text=msg)

            from app.diarizer import diarize_and_merge_segments

            speakers_meta, merged_segments = diarize_and_merge_segments(
                wav_path=wav_path,
                raw_segments=raw_segments,
                device=device,
                num_speakers_hint=num_speakers_hint,
                diarization_enabled=diarization_enabled,
                progress_callback=_diar_cb,
            )
            # Speakers whose voice was named in earlier recordings get that name again
            try:
                from app.voice_profiles import apply_to_speakers

                named = apply_to_speakers(speakers_meta)
                if named:
                    print(f"[voice profiles] recognised {named} speaker(s) in meeting {meeting_id}")
            except Exception:
                traceback.print_exc()
            # «Сейчас говорит» marked in the studio while recording: those names win over a remembered voice
            marks_named = 0
            if meeting.get("speaker_marks") and diarization_enabled:
                marks_named = apply_speaker_marks(speakers_meta, merged_segments, meeting["speaker_marks"])

            _check_cancel(meeting_id)
            # The transcript of another model stays among the versions (the dropdown above the text)
            stash_transcript_for(meeting_id, model_name)
            save_segments_backup(meeting_id, [])  # a backup of the previous run does not belong to this one
            # Fillers stay in the text: «Без запинок» hides them only when the text is shown
            # (text_utils.filler_view); the setting clean_fillers turns that view on by default

            if mixed:
                # Each phrase keeps its own language: shown in the transcript, used by translation
                for seg in merged_segments:
                    seg["lang"] = asr_onnx.guess_language(seg.get("text") or "")
                langs = [seg["lang"] for seg in merged_segments]
                detected_lang = max(set(langs), key=langs.count) if langs else detected_lang

            save_meeting_results(
                meeting_id,
                speakers=speakers_meta,
                segments=merged_segments,
                language=detected_lang,
                transcript_model=model_name,
            )
            from app.database import update_meeting_fields as _fields

            _fields(meeting_id, transcript_made_with=made_with_now)

            clear_vram()

        # The count of speakers said for the recording was corrected by the voices (app/diarizer.py)
        speakers_note = ""
        if diarization_enabled and num_speakers_hint in (1, 2) and len(speakers_meta) >= 3:
            speakers_note = f"участников больше, чем указано: по голосам их {len(speakers_meta)}"

        # The precise mode: other models recognize the recording too, and the versions are merged
        ensemble_note = ""
        if processing.get("ensemble") and merged_segments and not _cancel_wanted(meeting_id):
            extra = ensemble_models(settings, model_name, detected_lang or language, mixed)
            if not extra:
                ensemble_note = "точный режим: нет других установленных моделей для этого языка"
            else:
                try:
                    res = _run_ensemble(meeting_id, model_name, extra, wav_path, max(1.0, float(duration or 1.0)),
                                        language, detected_lang, mixed, processing, settings, device, compute_type, hw,
                                        merged_segments, speakers_meta)
                except JobCancelled:
                    # the main transcript is saved and complete: it stays, like a cancel after it (below)
                    _release_speech_models()
                    res = None
                    ensemble_note = "точный режим отменён: оставлена расшифровка основной модели"
                if res:
                    merged_segments, speakers_meta = res["segments"], res["speakers"]
                    ensemble_note = (f"сведено из {len(res['models'])} моделей, спорных мест {res['disputed']}"
                                     + (f", по смыслу выбрано {res['by_llm']}" if res["chat"] else
                                        " (модель анализа недоступна: решено по точности моделей)"))
                elif not ensemble_note:
                    ensemble_note = "точный режим: другие модели не справились, оставлена расшифровка основной"

        # Cancelled once the transcript is saved: it is complete and stays; the steps after it (the
        # overview, the title, the note) are skipped instead of running for minutes
        skipped = _cancel_wanted(meeting_id)

        # 4. Automatic AI Summary via local Ollama (if enabled and Ollama has a model)
        auto_summary = processing.get("summary", settings.get("auto_summary", "true").lower() == "true") and not skipped
        total_len = max((float(x.get("end") or 0) for x in merged_segments), default=0.0)
        summaries = meeting.get("summaries") or {}

        if auto_summary and merged_segments:
            from app import llm

            from app.database import is_local_only

            local_only = is_local_only(get_meeting(meeting_id))
            if llm.available(settings, local_only=local_only):
                cloud = llm.uses_cloud(settings) and not local_only
                if not cloud:  # the analysis model loads alone: the speech models go first
                    _release_speech_models()
                update_meeting_progress(
                    meeting_id,
                    status="summarizing",
                    progress=90,
                    stage_text="Формирование обзора записи (" + ("облачная модель" if cloud else "Ollama") + ")...",
                )
                try:
                    where = "облачная модель" if cloud else "Ollama"
                    part_notes: Dict[str, Any] = {}  # the parts of a long recording, read once for both
                    summary_md = generate_meeting_summary(
                        progress=lambda done, total: update_meeting_progress(
                            meeting_id, stage_text=f"Формирование обзора записи ({where}): часть {done} из {total}..."),
                        segments=merged_segments,
                        speakers=speakers_meta,
                        template_key="protocol",
                        user_notes=(get_meeting(meeting_id) or {}).get("user_notes") or "",
                        answer_lang=detected_lang,
                        local_only=local_only,
                        part_notes=part_notes,
                    )
                    from app.grounding import ground_summary

                    if settings.get("summary_grounding", "true").lower() == "true":
                        summary_md = ground_summary(summary_md, merged_segments, speakers_meta)
                    summaries["protocol"] = summary_md
                    merge_summaries(meeting_id, {"protocol": summary_md}, remove=("error",))
                    # The topics above the timeline: worth it for a meeting long enough to have several
                    if settings.get("auto_chapters", "true").lower() == "true" and total_len >= AUTO_CHAPTERS_MIN_SEC:
                        try:
                            update_meeting_progress(meeting_id, stage_text="Темы разговора для таймлайна...")
                            chapters_md = generate_meeting_summary(
                                segments=merged_segments, speakers=speakers_meta, template_key="chapters",
                                answer_lang=detected_lang, local_only=local_only, part_notes=part_notes)
                            summaries["chapters"] = chapters_md
                            merge_summaries(meeting_id, {"chapters": chapters_md})
                        except Exception as ch_err:
                            print(f"[chapters] meeting {meeting_id}: {ch_err}", flush=True)
                    if settings.get("auto_commitments", "true").lower() == "true":
                        try:
                            from app import commitments

                            commitments.extract(meeting_id)
                        except Exception as c_err:
                            print(f"[commitments] meeting {meeting_id}: {c_err}", flush=True)
                except Exception as sum_err:
                    if not _cancel_wanted(meeting_id):  # a cancel broke the request off: not an error
                        summaries["error"] = str(sum_err)
                        merge_summaries(meeting_id, {"error": str(sum_err)})

        clear_vram()

        # 5. A title from the content instead of a file name, and the note in Obsidian
        skipped = skipped or _cancel_wanted(meeting_id)
        notes = ["обзор и название пропущены (отмена)"] if skipped else \
            _after_transcription(meeting_id, merged_segments, speakers_meta, detected_lang, settings)
        if ensemble_note:
            notes = [ensemble_note, *notes]
        if speakers_note:
            notes = [speakers_note, *notes]
        if marks_named:
            notes = [f"имена по отметкам «Сейчас говорит»: {marks_named}", *notes]
        from app import semantic

        semantic.kick()  # indexed for search by meaning once the queue is free

        update_meeting_progress(
            meeting_id,
            status="completed",
            progress=100,
            stage_text=f"Готово! Участников: {len(speakers_meta)}, реплик: {len(merged_segments)}" + "".join(f"; {n}" for n in notes),
        )
        if settings.get("delete_media_after", "false").lower() == "true":
            # Privacy setting: the transcript stays, the sound goes
            from app.database import remove_media

            remove_media(meeting_id)
        else:
            _drop_work_audio(meeting_id, wav_path)

    except JobCancelled:
        whisper_model = None
        release_whisper_model()
        try:  # a cancel inside the splitting by voices left its model loaded
            from app.diarizer import unload_diarizer

            unload_diarizer()
        except Exception:
            pass
        partial = _index_partial(meeting_id)
        update_meeting_progress(
            meeting_id,
            status="cancelled",
            stage_text="Обработка отменена" + (": показана часть, распознанная до отмены" if partial else ""),
            error_message="",
        )
    except Exception as e:
        whisper_model = None
        release_whisper_model()
        tb = traceback.format_exc()
        _index_partial(meeting_id)
        update_meeting_progress(
            meeting_id,
            status="failed",
            stage_text=f"Ошибка: {str(e)[:140]}",
            error_message=f"{e}\n\n{tb[-800:]}",
        )
