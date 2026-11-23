"""The assistant: its conversations (app/assistant_chats.py) and an answer saved as a document.
The answers themselves come from /api/library/ask (app/api/recording.py)."""

import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

router = APIRouter()


class ChatsPayload(BaseModel):
    chats: List[Dict[str, Any]]


@router.get("/api/assistant/chats")
def api_assistant_chats() -> Dict[str, Any]:
    from app.assistant_chats import load_chats

    return {"chats": load_chats()}


@router.put("/api/assistant/chats")
def api_assistant_save_chats(payload: ChatsPayload) -> Dict[str, Any]:
    from app.assistant_chats import save_chats

    try:
        return {"chats": save_chats(payload.chats)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


class AnswerExportPayload(BaseModel):
    fmt: str  # docx | md | txt
    question: str
    answer: str
    sources: List[Dict[str, Any]] = []
    lang: str = "ru"


@router.post("/api/assistant/export")
def api_assistant_export(payload: AnswerExportPayload) -> Response:
    from app.assistant_chats import answer_docx, answer_text

    heading = "Sources" if payload.lang == "en" else "Источники"
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", payload.question).strip()[:80] or "answer"
    if payload.fmt == "docx":
        body = answer_docx(payload.question, payload.answer, payload.sources, heading)
        media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif payload.fmt in ("md", "txt"):
        text = answer_text(payload.question, payload.answer, payload.sources, heading)
        if payload.fmt == "txt":
            text = re.sub(r"^#+ ", "", text, flags=re.M).replace("**", "")
        body = text.encode("utf-8")
        media = "text/markdown; charset=utf-8" if payload.fmt == "md" else "text/plain; charset=utf-8"
    else:
        raise HTTPException(status_code=400, detail="Неизвестный формат файла")
    return Response(content=body, media_type=media,
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name + '.' + payload.fmt)}"})


class AnswerPersonPayload(BaseModel):
    old: str
    new: str
    meeting_ids: List[int] = []  # the recordings the answer cites
    text: Optional[str] = None  # the answer: its «old» becomes «new»


@router.post("/api/assistant/rename-person")
def api_assistant_rename_person(payload: AnswerPersonPayload) -> Dict[str, Any]:
    """A person an answer of the assistant (a brief, a digest) names is someone else (asked by the user: «not that
    Дмитрий»): the speakers of that name in the recordings it cites take the other name (their analyses and tasks
    follow, app/api/library.set_speaker), and the answer's text has it in place of the old one (whole words, the
    same case). The page saves the conversation with that text."""
    from app.api.library import set_speaker
    from app.database import get_meeting
    from app.speaker_refs import speaker_name
    from app.transcriber import is_transcribing

    old, new = " ".join(payload.old.split())[:120], " ".join(payload.new.split())[:120]
    if not old or not new:
        raise HTTPException(status_code=400, detail="Укажите, кого на кого заменить")
    if old == new:
        raise HTTPException(status_code=400, detail="Новое имя совпадает с прежним")
    ids = list(dict.fromkeys(payload.meeting_ids))
    if len(ids) > 100:
        raise HTTPException(status_code=400, detail="Слишком много записей")
    meetings = [get_meeting(int(i)) for i in ids]
    if any(m is None for m in meetings):
        raise HTTPException(status_code=404, detail="Встреча не найдена")
    done: List[Dict[str, Any]] = []
    busy: List[int] = []
    for m in meetings:
        sids = [sid for sid in (m.get("speakers") or {}) if speaker_name(m["speakers"], sid) == old]
        if not sids:
            continue
        if is_transcribing(m["id"]):  # its speakers would be written over by the job
            busy.append(m["id"])
            continue
        for sid in sids:
            set_speaker(m["id"], sid, new)
        done.append({"id": m["id"], "title": m.get("title") or "", "speakers": len(sids)})
    out: Dict[str, Any] = {"meetings": done, "busy": busy}
    if payload.text is not None:
        out["text"] = replace_name(payload.text, old, new)
    return out


def replace_name(text: str, old: str, new: str) -> str:
    """Every «old» of a text as «new»: a whole word (or words), the same case; «Анна» is not in «Анне» or «Аннабель».
    A one-word name beside another capitalised word is someone's full name and stays («Анна Петрова» for «Анна»),
    as the analysis keeps its speakers (app/speaker_refs.mark_text)."""
    from app.speaker_refs import _CAP_BEFORE, _CAP_WORD

    text = text or ""
    body = r"\s+".join(re.escape(w) for w in old.split())

    def one(m: "re.Match") -> str:
        if " " not in old:
            after = text[m.end():m.end() + 40]
            if re.match(r"[ \t]+", after) and _CAP_WORD.match(after.lstrip(" \t")):
                return m.group(0)
            if _CAP_BEFORE.search(text[max(0, m.start() - 40):m.start()]):
                return m.group(0)
        return new

    return re.sub(r"(?<![\w-])" + body + r"(?![\w-])", one, text)
