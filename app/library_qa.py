"""
Questions about the whole library ("what was decided about the release last week?").

The question's keywords are looked up in the full-text index of all transcripts (segments_fts,
ranked by bm25); the best fragments, each with its neighbouring lines and the recording's date,
go to the local Ollama model, which answers only from them and cites fragments as [n]. The
answer comes back with the list of fragments, so every citation opens the recording at that moment.

A question can be limited to some recordings (a folder with its subfolders, or one recording).
When the transcripts of such a scope fit the model's context together, the model reads them in
full, cut into numbered fragments, instead of only the lines the search found: questions like
"what were these meetings about?" have no keywords to search for. A larger scope is searched as
usual, and the overviews of its recordings are added when the search finds little.

Not every message is about the recordings: a greeting gets a short reply, and a general question
(explain a term, give advice, write a text) is answered by the model from what it knows, with its
reasoning on and without sources. Only an answer about the recordings lists sources: the fragments it cites.
"""

import re
import sqlite3
from itertools import zip_longest
from typing import Any, Dict, List, Optional

from app.audio_utils import format_timestamp
from app.ollama_client import _segment_parts
from app.database import _db_lock, get_connection, get_meeting

MAX_FRAGMENTS = 14
MAX_CONTEXT_CHARS = 11000
FULL_MODE_MAX_CHARS = 26000   # a scope this small is given to the model in full
FULL_FRAGMENT_CHARS = 1100    # size of one numbered fragment in full mode
SUMMARY_FRAGMENT_CHARS = 1500
_STOPWORDS = set(
    """
    что как где когда кто какой какая какие каких чем это этот эта эти тот там тут был была были было
    будет есть ли же бы не ни на по за из для при про под над без или и а но то так уже еще ещё мы вы
    они он она оно его ее её их нам вам мне меня тебя себя все всё всех весь вся очень можно нужно надо
    свой своя свои который которая которые прошлой прошлый прошлую неделе неделю году месяце сказал
    сказали говорил говорили решили решение решения
    what which who whom whose when where why how the a an of to in on at for with about from by is are
    was were be been it this that these those and or but not do does did said say we you they he she
    """.split()
)


def _terms(question: str) -> List[str]:
    """Keywords of the question as FTS prefix terms; long words are cut to a stem-like prefix so
    'релиза' also finds 'релиз', 'релизе'."""
    words = [w for w in re.findall(r"\w+", question.casefold()) if len(w) >= 3 and w not in _STOPWORDS]
    out: List[str] = []
    for w in words:
        # A crude stem that drops the usual endings: срокам -> срок, релиза -> рели, prefixes -> prefi
        stem = w if len(w) <= 5 else w[: len(w) - 2] if len(w) <= 7 else w[: len(w) - 3]
        if stem not in out:
            out.append(stem)
    return out[:10]


def retrieve(question: str, meeting_ids: Optional[List[int]] = None, limit: int = MAX_FRAGMENTS) -> List[Dict[str, Any]]:
    """Fragments for the question: keyword hits and, with search by meaning on (app/semantic.py),
    the chunks closest in meaning, taken in turn from both lists so each kind gets its best in."""
    keyword = keyword_fragments(question, meeting_ids, limit)
    meaning = semantic_fragments(question, meeting_ids, limit)
    if not meaning:
        return keyword
    out: List[Dict[str, Any]] = []
    for pair in zip_longest(keyword, meaning):
        for f in pair:
            if f is None or any(o["meeting_id"] == f["meeting_id"] and abs(o["start"] - f["start"]) < 20 for o in out):
                continue
            out.append(f)
    return out[:limit]


def semantic_fragments(question: str, meeting_ids: Optional[List[int]] = None, limit: int = MAX_FRAGMENTS) -> List[Dict[str, Any]]:
    from app import semantic

    meetings: Dict[int, Optional[Dict[str, Any]]] = {}
    out = []
    for hit in semantic.search(question, meeting_ids, limit):
        mid = hit["meeting_id"]
        if mid not in meetings:
            meetings[mid] = get_meeting(mid)
        m = meetings[mid]
        if not m:
            continue
        first = hit["text"].split("\n", 1)[0]
        out.append({
            "meeting_id": mid, "title": m.get("title") or "", "date": _meeting_date(m), "start": hit["start"],
            "speaker": hit["speaker"], "text": first.split(": ", 1)[-1][:300], "context": hit["text"],
        })
    return out


def keyword_fragments(question: str, meeting_ids: Optional[List[int]] = None, limit: int = MAX_FRAGMENTS) -> List[Dict[str, Any]]:
    terms = _terms(question)
    if not terms or meeting_ids == []:
        return []
    match = " OR ".join(f'"{t}"*' for t in terms)
    scope_sql, scope_args = "", []
    if meeting_ids is not None:
        scope_sql = f" AND meeting_id IN ({','.join('?' * len(meeting_ids))})"
        scope_args = [int(i) for i in meeting_ids]
    with _db_lock:
        conn = get_connection()
        try:
            rows = conn.execute(
                f"""
                SELECT meeting_id, segment_id, start, bm25(segments_fts) AS score
                FROM segments_fts WHERE segments_fts MATCH ?{scope_sql}
                ORDER BY score LIMIT ?
                """,
                (match, *scope_args, limit * 3),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        conn.close()

    meetings: Dict[int, Optional[Dict[str, Any]]] = {}
    fragments: List[Dict[str, Any]] = []
    seen = set()
    for r in rows:
        mid, sid = int(r["meeting_id"]), int(r["segment_id"])
        if mid not in meetings:
            meetings[mid] = get_meeting(mid)
        m = meetings[mid]
        if not m:
            continue
        segs = m.get("segments") or []
        idx = next((i for i, s in enumerate(segs) if int(s.get("id", -1)) == sid), None)
        if idx is None:
            continue
        # The hit with one line before and after: answers often need the reply or the question
        lo, hi = max(0, idx - 1), min(len(segs), idx + 2)
        key = (mid, lo)
        if key in seen:
            continue
        seen.add(key)
        speakers = m.get("speakers") or {}
        lines = [
            f"{(speakers.get(s.get('speaker')) or {}).get('name') or s.get('speaker')}: {(s.get('text') or '').strip()}"
            for s in segs[lo:hi]
        ]
        seg = segs[idx]
        fragments.append({
            "meeting_id": mid,
            "title": m.get("title") or "",
            "date": _meeting_date(m),
            "start": float(seg.get("start") or 0.0),
            "speaker": (speakers.get(seg.get("speaker")) or {}).get("name") or seg.get("speaker"),
            "text": (seg.get("text") or "").strip(),
            "context": "\n".join(lines),
        })
        if len(fragments) >= limit:
            break
    return fragments


def _speaker_name(speakers: Dict[str, Any], spk: Any) -> str:
    return (speakers.get(spk) or {}).get("name") or str(spk or "")


def full_fragments(meetings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """All lines of the recordings, cut into consecutive fragments of about FULL_FRAGMENT_CHARS."""
    out: List[Dict[str, Any]] = []
    for m in meetings:
        speakers = m.get("speakers") or {}
        segs = [s for s in m.get("segments") or [] if (s.get("text") or "").strip()]
        i = 0
        while i < len(segs):
            lines, size, j = [], 0, i
            while j < len(segs) and (not lines or size + len(segs[j].get("text") or "") < FULL_FRAGMENT_CHARS):
                seg = segs[j]
                name = _speaker_name(speakers, seg.get("speaker"))
                for k, (start, text) in enumerate(_segment_parts(seg)):
                    line = f"[{format_timestamp(start)}] {name + ': ' if k == 0 else ''}{text}"
                    lines.append(line)
                    size += len(line) + 1
                j += 1
            first = segs[i]
            out.append({
                "meeting_id": int(m["id"]), "title": m.get("title") or "", "date": _meeting_date(m),
                "start": float(first.get("start") or 0.0), "speaker": _speaker_name(speakers, first.get("speaker")),
                "text": (first.get("text") or "").strip(), "context": "\n".join(lines),
            })
            i = j
    return out


def summary_fragments(meetings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The overview (or short summary) of each recording, for questions about a whole folder."""
    out = []
    for m in meetings:
        summ = m.get("summaries") or {}
        text = (summ.get("tldr") or summ.get("protocol") or "").strip()
        if not text:
            continue
        out.append({
            "meeting_id": int(m["id"]), "title": m.get("title") or "", "date": _meeting_date(m), "start": 0.0,
            "speaker": "", "text": text.splitlines()[0][:200], "context": "Обзор записи:\n" + text[:SUMMARY_FRAGMENT_CHARS],
        })
    return out


# A message that is not a question about the recordings: a greeting, thanks, a question to the
# assistant itself. It gets a short reply without a search, so «привет» is not answered with
# «the fragments say nothing» and fourteen random sources.
_SMALL_TALK = re.compile(
    r"^\W*(?:"
    r"привет\w*|здравствуй\w*|добр\w+\s+(?:утро|день|вечер|ночи)|доброе утро|хай|хеллоу|салют|ку"
    r"|спасибо\w*|благодарю|спс|пока|до свидания|ок|окей|понятно|ясно|отлично|супер|класс"
    r"|как дела|как ты|кто ты|ты кто|что ты умеешь|что умеешь|чем (?:ты )?можешь помочь|помощь|help"
    r"|hi|hello|hey|good (?:morning|afternoon|evening)|thanks?(?: you)?|thx|bye|ok(?:ay)?|got it|great"
    r"|how are you|who are you|what can you do|how can you help"
    r")(?:[\s,]+(?:ещё|еще|тебе|большое|again|a lot|so much|там))*\W*$",
    re.IGNORECASE,
)


def is_small_talk(question: str) -> bool:
    return bool(_SMALL_TALK.match((question or "").strip()))


# Words that make a question one about the recordings without asking the model
_ABOUT_RECORDINGS = re.compile(
    r"запис|встреч|созвон|звонк|совещан|митинг|планерк|обсужд|обсуди|говорил|сказал|упомина|решил|договорил"
    r"|задач|поручен|участник|спикер|расшифров|видео|ролик|лекци|интервью|медиатек"
    r"|meeting|record|call\b|calls\b|discuss|said|mention|decid|agreed|task|speaker|transcript|video|lecture|interview",
    re.IGNORECASE,
)


def about_recordings(question: str, llm: Any, chosen: bool) -> bool:
    """Whether the question is about the user's recordings (answered from their fragments, with
    citations) or a general one (answered by the model from what it knows). A question with no telling
    words is put to the model in one short check; when unsure, it is about the recordings."""
    if _ABOUT_RECORDINGS.search(question):
        return True
    scope = "выбранных пользователем записях" if chosen else "медиатеке записей пользователя"
    system = (
        f"Пользователь задаёт вопрос ассистенту, который знает о {scope}: встречах, звонках, видео и их расшифровках. "
        "Определи, нужно ли для ответа содержание этих записей (что обсуждали, кто что сказал, решения, задачи, "
        "о чём запись, что там про какую-то тему). Если это общий вопрос, на который отвечают из общих знаний "
        "(объяснить понятие, дать совет, написать или перевести текст, посчитать), ответь «нет». "
        "Если не уверен — «да». Ответь одним словом: да или нет."
    )
    try:
        verdict = (llm.chat(system, question, short=True) or "").strip().casefold()
    except Exception:
        return True
    return not verdict.startswith(("нет", "no"))


def _general(question: str, answer_lang: str, llm: Any, small: bool) -> Dict[str, Any]:
    """An answer without the recordings: a greeting gets a short reply, a general question a considered one
    (a model that can reason does so first)."""
    from app.ollama_client import _lang_phrase

    lang = _lang_phrase(answer_lang)
    if small:
        system = (
            "Ты — ассистент программы Verbaliox. Ты отвечаешь на вопросы по записям встреч и видео пользователя: "
            "находишь, что обсуждали, какие решения и задачи прозвучали, кто что говорил, и даёшь ссылки "
            "на моменты записей. Сейчас сообщение не про записи: ответь коротко и дружелюбно, одной-двумя фразами. "
            f"Ничего не выдумывай о содержании записей. Отвечай {lang}, без эмодзи."
        )
        answer = llm.chat(system, question, short=True)
    else:
        system = (
            "Ты — ассистент программы Verbaliox. Вопрос не о записях пользователя: ответь из своих знаний, "
            "точно и по делу, настолько подробно, насколько нужно. Не выдумывай факты; если не знаешь, так и скажи. "
            "Не упоминай записи и фрагменты. "
            f"Отвечай {lang}, в формате Markdown без эмодзи."
        )
        answer = llm.chat(system, question, think=True)
    return {"answer": answer, "sources": [], "found": True, "model": llm.label, "mode": "chat" if small else "general"}


def _meeting_date(m: Dict[str, Any]) -> str:
    return (m.get("recorded_at") or m.get("created_at") or "")[:10]


def _transcript_chars(m: Dict[str, Any]) -> int:
    return sum(len(s.get("text") or "") + 24 for s in m.get("segments") or [])


def ask_library(
    question: str,
    answer_lang: str = "ru",
    model_name: Optional[str] = None,
    meeting_ids: Optional[List[int]] = None,
) -> Dict[str, Any]:
    from app.llm import LlmError, target
    from app.ollama_client import _lang_phrase

    question = (question or "").strip()[:1000]
    if not question:
        raise ValueError("Пустой вопрос")
    if meeting_ids is not None and not meeting_ids:
        raise ValueError("В выбранной папке нет записей")

    chosen = meeting_ids is not None  # a folder or recordings the user chose, not the whole library
    try:
        llm = target(model_name)  # an explicit user action: Ollama may be started
    except LlmError as e:
        raise RuntimeError(str(e)) from e
    if is_small_talk(question):
        return _general(question, answer_lang, llm, small=True)
    if not about_recordings(question, llm, chosen):
        return _general(question, answer_lang, llm, small=False)
    mode = "search"
    max_chars = MAX_CONTEXT_CHARS
    fragments: List[Dict[str, Any]] = []
    scope_meetings: List[Dict[str, Any]] = []
    if chosen:
        scope_meetings = [m for m in (get_meeting(i) for i in meeting_ids) if m and m.get("segments")]
        if not scope_meetings:
            return {"answer": "", "sources": [], "found": False, "mode": mode}
        if sum(_transcript_chars(m) for m in scope_meetings) <= FULL_MODE_MAX_CHARS:
            mode = "full"
            max_chars = FULL_MODE_MAX_CHARS + 4000
            fragments = full_fragments(scope_meetings)
    if mode == "search":
        fragments = retrieve(question, meeting_ids, limit=MAX_FRAGMENTS)
        if chosen and len(fragments) < 3:
            # Few keyword hits in a folder: its overviews still say what the recordings are about
            fragments = summary_fragments(scope_meetings)[:MAX_FRAGMENTS] + fragments
    if not fragments:
        return {"answer": "", "sources": [], "found": False, "mode": mode}

    blocks, used = [], 0
    for n, f in enumerate(fragments, start=1):
        block = f"[{n}] «{f['title']}», {f['date']}, {format_timestamp(f['start'])}\n{f['context']}"
        if used + len(block) > max_chars:
            fragments = fragments[: n - 1]
            break
        blocks.append(block)
        used += len(block)

    lang = _lang_phrase(answer_lang)
    scope_note = (
        "Ниже — полные расшифровки выбранных записей, разбитые на пронумерованные фрагменты. "
        if mode == "full" else ""
    )
    system = (
        "Ты отвечаешь на вопросы по медиатеке расшифровок записей в программе Verbaliox. "
        f"{scope_note}Используй ТОЛЬКО приведённые фрагменты. Ничего не додумывай. "
        "После каждого утверждения ставь ссылку на фрагмент в квадратных скобках, например [2] или [1][3]. "
        "Если во фрагментах нет ответа, прямо так и скажи одной фразой, без ссылок. "
        "Не оформляй ответ блоками кода. "
        f"Отвечай {lang}, кратко и по делу, в формате Markdown без эмодзи."
    )
    user = "Фрагменты расшифровок:\n\n" + "\n\n".join(blocks) + f"\n\nВопрос: {question}"
    answer = llm.chat(system, user)
    # Only the fragments the answer cites: an answer without citations («the fragments say nothing»,
    # a greeting) has no sources, not every fragment the search brought
    cited = {int(x) for x in re.findall(r"\[(\d{1,3})\]", answer or "")}
    for group in re.findall(r"\[(\d{1,3}(?:\s*[,;]\s*\d{1,3})+)\]", answer or ""):
        cited |= {int(x) for x in re.findall(r"\d+", group)}
    sources = [
        {k: f[k] for k in ("meeting_id", "title", "date", "start", "speaker", "text")} | {"n": n}
        for n, f in enumerate(fragments, start=1) if n in cited
    ]
    return {"answer": answer, "sources": sources, "found": True, "model": llm.label, "mode": mode}
