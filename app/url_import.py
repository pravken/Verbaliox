"""
Import by link: a video or podcast page (YouTube, VK Video, RuTube, a podcast episode, a direct
file link …) is downloaded with yt-dlp (Unlicense) and transcribed like an imported file.

yt-dlp is installed into the program's Python the first time it is needed (it is updated often,
so the newest version is taken). Only the sound is downloaded when the site offers it separately.
"""

import importlib
import threading
import traceback
import uuid
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from app.paths import UPLOADS_DIR

PACKAGE = "yt-dlp"
MAX_BYTES = 8 * 2**30  # a link to more than this (a day-long video, a disk image) is not downloaded

_cancel: Dict[int, threading.Event] = {}  # downloads running, by recording


class _Cancelled(Exception):
    pass


def cancel(meeting_id: int) -> bool:
    """Stops the download of this recording; False when none runs."""
    ev = _cancel.get(meeting_id)
    if ev is None:
        return False
    ev.set()
    return True


_waiting: set = set()  # recordings of a playlist whose download has not begun yet


def drop(meeting_id: int) -> None:
    """The recording is being deleted: a playlist's video still waiting is only left out (the others
    go on); a download running is stopped."""
    if meeting_id in _waiting:
        _waiting.discard(meeting_id)
        _cancel.pop(meeting_id, None)
        return
    cancel(meeting_id)


def ensure_package() -> None:
    """Installs yt-dlp when it is missing: the version and file pinned in asr_onnx.PINNED."""
    try:
        importlib.import_module("yt_dlp")
        return
    except ImportError:
        pass
    from app import asr_onnx

    asr_onnx.install_pinned(PACKAGE)


def valid_url(url: str) -> bool:
    u = urlparse((url or "").strip())
    return u.scheme in ("http", "https") and bool(u.netloc)


def start(url: str, model_name: str, language: str, num_speakers: int, folder_id: Optional[int] = None,
          playlist: bool = False) -> Dict[str, Any]:
    """Creates the recording at once (shown as downloading) and downloads it in the background;
    then it goes into the transcription queue. `playlist`: a link to a playlist or a channel brings
    each of its videos as a recording of its own, in a new folder named after it (otherwise only
    the first video is downloaded)."""
    from app.database import create_meeting, get_meeting, update_meeting_progress

    if not valid_url(url):
        raise ValueError("Нужна ссылка вида https://…")
    host = urlparse(url).netloc.removeprefix("www.")
    m = create_meeting(title=host, filename=url[:300], media_path="", language=language, model_name=model_name,
                       num_speakers_hint=num_speakers, source="import", folder_id=folder_id, owns_media=True,
                       title_is_default=True)
    update_meeting_progress(m["id"], status="downloading", progress=1, stage_text="Скачивание по ссылке…")
    threading.Thread(target=_download, args=(m["id"], url, playlist), daemon=True, name=f"url_import_{m['id']}").start()
    return get_meeting(m["id"]) or m


MAX_PLAYLIST = 200  # videos of one playlist taken at most


def playlist_info(url: str) -> Optional[Dict[str, Any]]:
    """{"title", "entries": [(url, title)]} when the link is a playlist or a channel of several videos,
    else None. Only the list is read (no video is resolved): a few seconds even for a long one."""
    ensure_package()
    import yt_dlp

    opts = {"quiet": True, "no_warnings": True, "extract_flat": "in_playlist", "socket_timeout": 30,
            "playlistend": MAX_PLAYLIST}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False) or {}
    if info.get("_type") not in ("playlist", "multi_video"):
        return None
    entries = []
    for e in info.get("entries") or []:
        if not e:
            continue
        u = e.get("webpage_url") or e.get("url") or ""
        if valid_url(u):
            entries.append((u, str(e.get("title") or "").strip()[:300]))
        if len(entries) >= MAX_PLAYLIST:
            break
    if len(entries) < 2:
        return None
    return {"title": str(info.get("title") or "").strip()[:120], "entries": entries}


def probe(url: str) -> Dict[str, Any]:
    """What the link is, asked before the import: {"playlist": bool, "title", "count"}."""
    if not valid_url(url):
        raise ValueError("Нужна ссылка вида https://…")
    try:
        info = playlist_info(url)
    except Exception as e:  # the site said no to the list: the import itself will say why
        print(f"[url] probe of {url[:120]}: {e}", flush=True)
        info = None
    return {"playlist": bool(info), "title": (info or {}).get("title", ""), "count": len((info or {}).get("entries", []))}


def restart(meeting_id: int, url: str) -> bool:
    """False while a download of this recording still runs: a second one would share its cancel and
    leave one of the two files behind."""
    from app.database import update_meeting_progress

    if meeting_id in _cancel:
        return False
    update_meeting_progress(meeting_id, status="downloading", progress=1, stage_text="Скачивание по ссылке…", error_message="")
    threading.Thread(target=_download, args=(meeting_id, url), daemon=True, name=f"url_import_{meeting_id}").start()
    return True


def _drop_files(stem: str) -> None:
    """The file (and the .part pieces) of a download nobody needs any more."""
    for p in UPLOADS_DIR.glob(f"{stem}_*"):
        try:
            p.unlink()
        except OSError:
            pass


def _download(meeting_id: int, url: str, playlist: bool = False) -> None:
    from app.database import update_meeting_progress

    stop = _cancel.setdefault(meeting_id, threading.Event())
    stop.clear()
    ids = [meeting_id]
    try:
        items = None
        if playlist:
            try:
                items = playlist_info(url)
            except Exception as e:
                print(f"[url] not read as a playlist: {e}", flush=True)
        if not items:
            _download_one(meeting_id, url, stop)
            return
        ids = _make_playlist(meeting_id, items, stop)
        total = len(ids)
        for i, (mid, (entry_url, _title)) in enumerate(zip(ids, items["entries"])):
            if stop.is_set():  # «Отменить» on any of them stops the whole playlist
                for rest in ids[i:]:
                    if rest in _waiting or rest == mid:
                        _waiting.discard(rest)
                        update_meeting_progress(rest, status="cancelled", progress=0, stage_text="Скачивание отменено",
                                                error_message="")
                break
            if i and mid not in _waiting:  # deleted while it waited
                continue
            _waiting.discard(mid)
            update_meeting_progress(mid, status="downloading", progress=1,
                                    stage_text=f"Скачивание по ссылке… ({i + 1} из {total})")
            _download_one(mid, entry_url, stop)
    finally:
        for mid in ids:
            _cancel.pop(mid, None)
            _waiting.discard(mid)


def _make_playlist(meeting_id: int, items: Dict[str, Any], stop: threading.Event) -> list:
    """The folder of the playlist and a recording for each of its videos (the first is the one made
    already); all of them share one cancel. Their ids, in the playlist's order."""
    from app.database import (create_folder, create_meeting, get_meeting, set_meeting_folder, set_meeting_processing,
                              update_meeting_fields, update_meeting_progress)

    first = get_meeting(meeting_id) or {}
    folder = create_folder(items["title"] or urlparse(items["entries"][0][0]).netloc.removeprefix("www.") or "Плейлист")
    set_meeting_folder(meeting_id, folder["id"])
    ids = [meeting_id]
    entries = items["entries"]
    if entries[0][1]:
        update_meeting_fields(meeting_id, title=entries[0][1], filename=entries[0][0][:300])
    for n, (entry_url, title) in enumerate(entries[1:], start=2):
        m = create_meeting(title=title or f"{items['title'] or 'Видео'} {n}", filename=entry_url[:300], media_path="",
                           language=first.get("language") or "auto", model_name=first.get("model_name") or "",
                           num_speakers_hint=int(first.get("num_speakers_hint") or 0), source="import",
                           folder_id=folder["id"], owns_media=True, title_is_default=not title)
        if first.get("processing"):
            set_meeting_processing(m["id"], first["processing"])
        update_meeting_progress(m["id"], status="downloading", progress=0,
                                stage_text=f"Ждёт скачивания ({n} из {len(entries)})")
        _cancel[m["id"]] = stop
        _waiting.add(m["id"])
        ids.append(m["id"])
    print(f"[url] playlist «{items['title']}»: {len(ids)} video(s) into folder {folder['id']}", flush=True)
    return ids


def _download_one(meeting_id: int, url: str, stop: threading.Event) -> None:
    from app.database import get_meeting, update_meeting_fields, update_meeting_progress
    from app.ffmpeg_manager import find_tool
    from app.transcriber import enqueue_meeting_job

    stem = uuid.uuid4().hex[:8]
    try:
        ensure_package()
        import yt_dlp

        UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        last = {"pct": 0}

        def hook(d: Dict[str, Any]) -> None:
            if stop.is_set():
                raise _Cancelled()
            if (d.get("downloaded_bytes") or 0) > MAX_BYTES:
                raise RuntimeError(f"файл больше {MAX_BYTES // 2**30} ГБ")
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                pct = int(90 * (d.get("downloaded_bytes") or 0) / total) if total else 0
                if pct >= last["pct"] + 3:
                    last["pct"] = pct
                    update_meeting_progress(meeting_id, progress=max(1, pct), stage_text=f"Скачивание по ссылке… {pct}%")

        ffmpeg = find_tool("ffmpeg")
        opts: Dict[str, Any] = {
            "format": "bestaudio/best",
            "outtmpl": str(UPLOADS_DIR / f"{stem}_%(title).80B.%(ext)s"),
            "noplaylist": True,
            "playlist_items": "1",  # a link to a whole playlist or channel: its first video only
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [hook],
            "windowsfilenames": True,
            "socket_timeout": 30,
            "max_filesize": MAX_BYTES,
        }
        if ffmpeg:
            opts["ffmpeg_location"] = str(Path(ffmpeg).parent)
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info and (info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming")):
                raise RuntimeError("это прямая трансляция: она не кончается, скачать её целиком нельзя")
            size = (info or {}).get("filesize") or (info or {}).get("filesize_approx") or 0
            if size > MAX_BYTES:
                raise RuntimeError(f"файл {size / 2**30:.1f} ГБ, больше {MAX_BYTES // 2**30} ГБ")
            if stop.is_set():
                raise _Cancelled()
            info = ydl.process_ie_result(info, download=True)
        if info and info.get("entries"):
            info = next((e for e in info["entries"] if e), info)
        downloads = (info or {}).get("requested_downloads") or []
        path = Path(downloads[0]["filepath"]) if downloads and downloads[0].get("filepath") else None
        if not path or not path.is_file():
            found = sorted(UPLOADS_DIR.glob(f"{stem}_*"))
            path = found[0] if found else None
        if not path:
            raise RuntimeError("Файл не скачался")
        if not get_meeting(meeting_id):  # the recording was deleted while it was downloading
            _drop_files(stem)
            return
        title = str((info or {}).get("title") or "").strip()[:300]
        date = str((info or {}).get("upload_date") or "")
        if title:
            update_meeting_fields(meeting_id, title=title)
        from app.database import _db_lock, get_connection

        with _db_lock:
            conn = get_connection()
            conn.execute("UPDATE meetings SET media_path = ?, filename = ?, recorded_at = COALESCE(NULLIF(?, ''), recorded_at) WHERE id = ?",
                         (str(path), path.name, f"{date[:4]}-{date[4:6]}-{date[6:8]} 12:00:00" if len(date) == 8 else "", meeting_id))
            conn.commit()
            conn.close()
        update_meeting_progress(meeting_id, status="queued", progress=0, stage_text="В очереди на распознавание")
        enqueue_meeting_job(meeting_id)
    except Exception as e:
        _drop_files(stem)
        if stop.is_set() or isinstance(e, _Cancelled) or isinstance(getattr(e, "exc_info", [None, None])[1], _Cancelled):
            update_meeting_progress(meeting_id, status="cancelled", progress=0, stage_text="Скачивание отменено",
                                    error_message="")
            return
        traceback.print_exc()
        update_meeting_progress(meeting_id, status="failed", progress=0, stage_text="",
                                error_message=f"Не удалось скачать по ссылке: {str(e)[:250]}")
