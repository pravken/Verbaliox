"""
What the app is doing right now, in one place: for the tray icon and its tooltip.

The job queue and live caption sessions live in this process. Recording happens in the page
(MediaRecorder), so the page reports its start and end through /api/ui/state.
"""

import time
from typing import Any, Dict, List

from app.ui_lang import tr

_ui: Dict[str, Any] = {"recording": False, "since": 0.0}

KIND_LABELS = {
    "transcribe": "Распознавание",
    "dub": "Дубляж",
    "translate": "Перевод",
    "burn_subs": "Встраивание субтитров",
    "cut": "Нарезка записи",
    "analysis": "Анализ после встречи",
    "complete": "Дополнение заметки",
}
KIND_LABELS_EN = {
    "transcribe": "Transcription",
    "dub": "Dubbing",
    "translate": "Translation",
    "burn_subs": "Subtitle embedding",
    "cut": "Recording trim",
    "analysis": "Post-meeting analysis",
    "complete": "Note completion",
}


def kind_label(kind: str, ru: str = "Задача", en: str = "Task") -> str:
    """The job's name in the UI language (the tooltip, the notice of a job done)."""
    return tr(KIND_LABELS.get(kind, ru), KIND_LABELS_EN.get(kind, en))


# Stopped recordings whose tracks are being mixed (app/api/recording.py): no job may take them meanwhile
mixing: set = set()
# Of them, the ones whose mix waits for the end of a meeting («Не мешать на встречах»): the time it may begin
# (0: after the meeting going on), shown on the card as a countdown; and the ones marked for deletion, deleted
# as soon as the mix is over
mix_wait: Dict[int, float] = {}
# while a meeting goes on (mix_wait 0): which one holds it — {"kind": "calendar"|"recording", "title", "end": "HH:MM"}
mix_why: Dict[int, Dict[str, str]] = {}
mix_deleting: set = set()


def mix_state(meeting_id: int) -> Dict[str, Any]:
    """What the page shows of a recording being mixed: {"mix_wait": time or 0} while it waits, and
    {"mix_deleting": True} once deleted; {} otherwise."""
    out: Dict[str, Any] = {}
    if meeting_id in mix_wait:
        out["mix_wait"] = mix_wait.get(meeting_id, 0.0)
        if not out["mix_wait"] and mix_why.get(meeting_id):
            out["mix_why"] = mix_why[meeting_id]
    if meeting_id in mix_deleting:
        out["mix_deleting"] = True
    return out

# The speech model recognizing each recording right now (the routed model, each model of the precise
# mode in turn): shown as «Идёт расшифровка: <model>», the recording's own choice may be «Авто»
_asr_now: Dict[int, str] = {}


def set_asr_model(meeting_id: int, model: str = "") -> None:
    if model:
        _asr_now[meeting_id] = model
    else:
        _asr_now.pop(meeting_id, None)


def asr_model(meeting_id: int) -> str:
    return _asr_now.get(meeting_id, "")


_notices: List[Dict[str, Any]] = []  # Windows notifications the tray shows next (run.py)

AUTO_SOURCES = {"call": "звонок", "calendar": "встреча по календарю", "meeting": "встреча Teams"}
AUTO_SOURCES_EN = {"call": "call", "calendar": "calendar meeting", "meeting": "Teams meeting"}


def auto_recording_notice(started: bool, source: str, name: str = "") -> Dict[str, str]:
    """The short notification of a recording the app started or stopped by itself: one was going
    on without a word otherwise. Shown even in quiet mode: a recording is never silent."""
    what = (name or "").strip()[:80]
    if started:
        title = tr("● Идёт запись", "● Recording")
        kind = tr(AUTO_SOURCES.get(source, ""), AUTO_SOURCES_EN.get(source, ""))
        text = " · ".join(x for x in (what, kind) if x) or tr("Запись началась сама", "Recording started automatically")
        try:
            from app.database import get_all_settings

            hotkey = (get_all_settings().get("record_hotkey") or "").strip()
        except Exception:
            hotkey = ""
        text += (tr(f"\nОстановить: {hotkey} или в окне Verbaliox", f"\nTo stop: {hotkey} or in the Verbaliox window")
                 if hotkey else tr("\nОстановить — в окне Verbaliox", "\nTo stop, use the Verbaliox window"))
    else:
        title = tr("Запись сохранена", "Recording saved")
        text = (f"{what} · " if what else "") + tr("отправлена на расшифровку", "sent for transcription")
    # a click on it opens the studio with the recording running, or the recording saved
    notice = {"title": title, "text": text, "target": "studio" if started else "last"}
    _notices.append(notice)
    del _notices[:-5]
    return notice


def add_notice(title: str, text: str, target: str = "") -> None:
    """A Windows notification the tray shows next (a click opens `target`, static/js/home.js openFromNotice)."""
    _notices.append({"title": title, "text": text, "target": target})
    del _notices[:-5]


def take_notices() -> List[Dict[str, Any]]:
    out = list(_notices)
    _notices.clear()
    return out


def set_recording(active: bool) -> None:
    was = bool(_ui.get("recording"))
    _ui.update(recording=bool(active), since=time.time() if active else 0.0)
    if was and not active:  # stopped during a calendar meeting: it holds the mix no longer once the call is over
        from app import meeting_guard

        meeting_guard.recording_ended()


def background() -> List[str]:
    """Work outside the queue that closing the app would cut off: downloads, installs, a backup."""
    out: List[str] = []

    def check(label: str, active) -> None:
        try:
            if active():
                out.append(label)
        except Exception:
            pass

    from app import asr_onnx, backup, dictation, dub_setup, ffmpeg_manager, model_manager, onnx_gpu

    check(tr("Скачивание модели", "Downloading a model"), lambda: model_manager._setup_state.get("active")
          or any(d.get("active") for d in asr_onnx._downloads.values()))
    check(tr("Скачивание FFmpeg", "Downloading FFmpeg"), lambda: ffmpeg_manager._state.get("active"))
    check(tr("Установка ускорения видеокарты", "Installing GPU acceleration"), lambda: onnx_gpu._state.get("installing"))
    check(tr("Установка дубляжа", "Installing dubbing"), lambda: dub_setup._state.get("active"))
    check(tr("Резервная копия", "Backup"), lambda: backup.busy > 0)
    check(tr("Диктовка", "Dictation"), lambda: dictation._state.get("active"))
    check(tr("Скачивание по ссылке", "Downloading from a link"), _downloading)
    # a stopped recording whose tracks are being mixed: closing the app now loses the mix, its title
    # and notes (its parts come back only as separate recordings)
    check(tr("Сведение дорожек записи", "Mixing recording tracks"), lambda: bool(mixing))
    try:  # the notes moved to their folders (app/obsidian.relayout), with how far it is
        from app import obsidian

        mv = obsidian._move_state
        if mv.get("active"):
            done, total = mv.get("done", 0), mv.get("total", 0)
            out.append(tr(f"Перемещение заметок Obsidian {done} из {total}", f"Moving Obsidian notes: {done} of {total}"))
    except Exception:
        pass
    return out


def _downloading() -> bool:
    from app.database import _db_lock, get_connection

    with _db_lock:
        conn = get_connection()
        row = conn.execute("SELECT 1 FROM meetings WHERE status = 'downloading' LIMIT 1").fetchone()
        conn.close()
    return row is not None


def snapshot() -> Dict[str, Any]:
    """
    {"state": "idle" | "busy" | "recording", "text": tooltip line in the UI language, "queue": [...], "recording": bool}.
    Recording wins over processing: it is the thing the user must not forget is running.
    """
    from app.transcriber import queue_snapshot

    try:
        queue = queue_snapshot()
    except Exception:
        queue = []
    running = next((q for q in queue if q.get("state") == "running"), None)
    waiting = sum(1 for q in queue if q.get("state") == "waiting")

    if _ui["recording"]:
        mins, secs = divmod(int(time.time() - _ui["since"]), 60)
        text = tr("Идёт запись", "Recording") + f" · {mins:02d}:{secs:02d}"
        state = "recording"
    elif running:
        label = kind_label(running.get("kind"), "Обработка", "Processing")
        title = (running.get("title") or "")[:40]
        text = f"{label}: {title} · {int(running.get('progress') or 0)}%"
        state = "busy"
    else:
        others = background()
        text = " · ".join(others) if others else tr("Готово к работе", "Ready")
        state = "busy" if others else "idle"
    if waiting:
        text += tr(f" · в очереди: {waiting}", f" · queued: {waiting}")
    return {"state": state, "text": text, "queue": queue, "recording": _ui["recording"]}
