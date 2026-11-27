"""
«Обработать всё» in «Записи» (asked by the user): every recording without a text goes to the queue for
recognition, every transcribed one without an analysis to the queue for the analysis, in one go.

Recognition, as «Повторить» of one recording (app/api/library.api_retry_meeting): a recording added without
recognition («added»), and one whose recognition failed or was cancelled before a transcript was made. Never one
with a transcript: a failed or cancelled recognition *again* of a finished recording keeps its model name and is
left alone, as is a recording whose results the user deleted («cleared»: done on purpose). Its file must be
there (or, for a download by link that did not finish, its link).

The analysis, as the one that waited for a meeting to end (app/transcriber.enqueue_analysis_job), asked for here
whatever «Анализ после расшифровки» says: a finished transcript whose analysis has no results. Only when the
analysis model can run (app/llm.available), as after a transcription; otherwise counted and reported, not queued.
"""

import threading
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

TRANSCRIBE_STATUSES = ("added", "failed", "cancelled")
# one «Обработать всё» at a time: two requests at once each planned before the other queued, and queued the same
# recordings twice (a download by link started twice)
_run_lock = threading.Lock()


def _busy(meeting_id: int) -> bool:
    from app import app_status
    from app.transcriber import is_job_active

    return is_job_active(meeting_id) or meeting_id in app_status.mixing


def _needs_transcript(m: Dict[str, Any]) -> bool:
    status = m.get("status")
    if status not in TRANSCRIBE_STATUSES:
        return False
    if status != "added" and (m.get("transcript_model") or "").strip():
        return False  # a finished transcript is there: recognized again only on the user's own «Повторить»
    path = m.get("media_path") or ""
    if path:
        return Path(path).is_file()
    from app import url_import

    return url_import.valid_url(m.get("filename") or "")


def _needs_analysis(m: Dict[str, Any]) -> bool:
    return m.get("status") == "completed" and bool(m.get("has_transcript")) and not m.get("has_summary")


def plan(ids: Optional[Iterable[int]] = None) -> Dict[str, Any]:
    """What «Обработать всё» would do now: {transcribe: [ids], analyse: [ids], analysis_ready}. ids: only
    these recordings (the action of one recording's status in the table)."""
    from app import llm
    from app.database import _db_lock, get_connection, list_meetings

    # the list leaves out the paths of the files: those without a text are read with theirs
    with _db_lock:
        conn = get_connection()
        rows = conn.execute(
            f"SELECT id, status, media_path, filename, transcript_model FROM meetings "
            f"WHERE status IN ({','.join('?' * len(TRANSCRIBE_STATUSES))}) ORDER BY id", TRANSCRIBE_STATUSES).fetchall()
        conn.close()
    only = None if ids is None else {int(i) for i in ids}

    def take(mid: int) -> bool:
        return (only is None or mid in only) and not _busy(mid)

    transcribe = [int(r["id"]) for r in rows if take(int(r["id"])) and _needs_transcript(dict(r))]
    analyse = sorted(int(m["id"]) for m in list_meetings() if take(int(m["id"])) and _needs_analysis(m))
    try:
        ready = bool(llm.available())
    except Exception:
        ready = False
    return {"transcribe": transcribe, "analyse": analyse, "analysis_ready": ready}


def queue_transcription(meeting_id: int, m: Dict[str, Any]) -> bool:
    """One recording to the recognition queue, the steps of «Повторить» (app/api/library.api_retry_meeting).
    False when it could not go (a download by link still runs, or it is in the queue already)."""
    from app import url_import
    from app.database import update_meeting_progress
    from app.transcriber import enqueue_meeting_job

    if not m.get("media_path") and url_import.valid_url(m.get("filename") or ""):
        return url_import.restart(meeting_id, m["filename"])  # a download by link that did not finish
    if _busy(meeting_id):
        return False
    update_meeting_progress(meeting_id, status="queued", progress=0,
                            stage_text="Повторная постановка в очередь...", error_message="")
    if enqueue_meeting_job(meeting_id, manual=True):
        return True
    # queued meanwhile by another way: the recording keeps what it showed (the job queued says its own)
    update_meeting_progress(meeting_id, status=m.get("status") or "added", progress=m.get("progress") or 0,
                            stage_text=m.get("stage_text") or "", error_message=m.get("error_message") or "")
    return False


def run(transcribe: bool = True, analyse: bool = True, ids: Optional[Iterable[int]] = None) -> Dict[str, Any]:
    """Queues what plan() found. Returns the counts: queued for recognition, for the analysis, and the
    analyses left out because the analysis model cannot run."""
    from app import events

    with _run_lock:
        out = _run(transcribe, analyse, ids)
    if out["transcribe"] or out["analyse"]:
        events.publish({"type": "list"})
    return out


def _run(transcribe: bool, analyse: bool, ids: Optional[Iterable[int]]) -> Dict[str, Any]:
    from app.database import get_meeting
    from app.transcriber import enqueue_analysis_job

    p = plan(ids)
    out = {"transcribe": 0, "analyse": 0, "analysis_waiting": 0, "analysis_ready": p["analysis_ready"]}
    if transcribe:
        for mid in p["transcribe"]:
            m = get_meeting(mid)
            if m and queue_transcription(mid, m):
                out["transcribe"] += 1
    if analyse:
        if not p["analysis_ready"]:
            out["analysis_waiting"] = len(p["analyse"])
        else:
            for mid in p["analyse"]:
                if enqueue_analysis_job(mid, True):
                    out["analyse"] += 1
    return out
