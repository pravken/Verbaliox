"""
Commitments: who promised what to whom, by when — across the meetings of a series.

The analysis model reads a transcript and lists the promises made in it as JSON lines; each one is
checked against the transcript (app/grounding.py) and stored with its time stamp. They stay open
until ticked off (or a later meeting says they are done), and the open ones of a series go into
"since last time", the brief before the next meeting and the questions during a call.

They are also the tasks of the Tasks page: who a task is on is a kind of assignee as well as a name
(someone who speaks in the recording, someone only named in it, a department, another company, or
nobody), with the words of the recording it came from; the due date is a date (from the words of the
recording, said on the day of the meeting), and tasks can be added, reassigned and moved by hand.
"""

import json
import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from app.database import _db_lock, get_connection, get_meeting

_SYSTEM = (
    "Ты извлекаешь из расшифровки встречи задачи: конкретные действия, которые кто-то взялся сделать или которые "
    "ему поручили сделать после встречи. Задача — только если в тексте есть явное обязательство или поручение: "
    "«сделаю», «подготовлю к пятнице», «Иван, отправь отчёт», «договорились, что Пётр займётся». "
    "НЕ задачи: обсуждение и мнения, рассказ о том, что человек делает сейчас или уже сделал, идеи и предложения, "
    "с которыми не согласились, общие планы без конкретного действия, вопросы, пересказ фактов. "
    "Особенно НЕ задачи — действия во время самой встречи, которые делаются тут же: показать или пошарить экран, "
    "включить или выключить микрофон или камеру, «скину ссылку в чат», «сейчас открою», «дай я покажу», "
    "«перезайду», «запишу встречу», «подожди секунду», «дайте слово Анне». Задача — то, что нужно сделать ПОСЛЕ встречи.\n"
    "Примеры. «Сейчас пошарю экран, покажу отчёт» — не задача. «Скину ссылку в чат» — не задача. "
    "«Я сейчас открою таблицу» — не задача. «Мы обсуждали, что можно бы сменить подрядчика» — не задача. "
    "«Отчёт я уже отправил вчера» — не задача. "
    "«Я подготовлю отчёт к пятнице» — задача (кто: говорящий, срок: пятница). "
    "«Ольга, пришли договор юристам после встречи» — задача (кто: Ольга). "
    "«Договорились, что маркетинг обновит презентацию до конца месяца» — задача (кто: маркетинг, kind: team).\n"
    "Одна задача — одно действие; одно и то же не повторяй. "
    "Если сомневаешься, задача ли это, — не включай. Не придумывай. Ответ — только строки JSON, по одному объекту "
    'на строку, без пояснений: {"who": "кто сделает", "kind": "кто это", "to": "для кого (или пусто)", '
    '"what": "что сделать, коротко", "due": "срок словами из текста или пусто", "time": "ММ:СС места в записи", '
    '"quote": "дословные слова из текста, где это сказано"}. '
    "kind — одно из: part (говорит в записи), ext (человек, которого только назвали), team (отдел или группа), "
    "org (другая компания), none (исполнитель не назван, тогда who пусто). "
    "Имена — как в расшифровке. Если задач нет, ответь пустой строкой."
)
# The second look at each task found (verify): the same model reads its words and the lines around them
# and says whether someone really took it on or was given it
_CHECK = (
    "Тебе дан список возможных задач из расшифровки встречи, у каждой — номер, слова из записи и реплики рядом. "
    "Для каждой реши: это задача, которую нужно сделать ПОСЛЕ встречи, то есть кто-то явно взялся сделать "
    "конкретное действие или ему это поручили («сделаю», «подготовлю к пятнице», «Иван, отправь», «договорились, "
    "что Пётр займётся»)? "
    "НЕ задача: действие во время самой встречи (показать экран, включить микрофон, скинуть ссылку в чат, открыть "
    "файл, «сейчас покажу»), особенно если по репликам рядом видно, что оно сделано тут же («вижу экран», «да, "
    "пришло»); обсуждение, мнение, рассказ о том, что человек делает сейчас или уже сделал, предложение, "
    "с которым не согласились, вопрос, пересказ факта, общий план без конкретного действия. "
    "Если да — сразу после «да» через « — » перепиши задачу одним понятным действием: что сделать, 4–12 слов, "
    "начиная с глагола («Прислать смету юристам до пятницы»), только по смыслу слов записи, своими словами, без "
    "обрывков реплик, слов-паразитов и имени исполнителя. Если понятное действие из этих слов не складывается — "
    "это «нет». "
    "Ответ — по строке на задачу, в виде «номер: да — переписанная задача» или «номер: нет», без пояснений."
)
# Reported by the user: the tasks often read as words of the talk glued together, while the overview of the
# same meeting was clear. The small model writes «what» from the words around; the second look (verify) reads
# each task with its words and the lines around and writes it anew as one clear action, or drops it.
_REWRITE_MIN_WORDS, _REWRITE_MAX_CHARS = 2, 200
# The organizer's meeting follow-up (MFU), pasted into the recording: a list people agreed on, so every
# action in it is a task, taken as written; the transcript only adds the moment it was said
_SYSTEM_MFU = (
    "Тебе дан MFU — итоги встречи, которые написал её организатор. Выпиши из него все задачи: кто что должен "
    "сделать после встречи. Это согласованный людьми список: возьми каждый пункт-действие, ничего не пропускай "
    "и ничего не добавляй от себя. Решения, выводы и сведения без действия — не задачи. "
    "Ответ — только строки JSON, по одному объекту на строку, без пояснений: "
    '{"who": "кто сделает", "kind": "кто это", "to": "для кого (или пусто)", "what": "что сделать, коротко", '
    '"due": "срок словами из текста или пусто", "quote": "дословные слова пункта из MFU"}. '
    "kind — одно из: part (участник встречи), ext (человек, которого только назвали), team (отдел или группа), "
    "org (другая компания), none (исполнитель не назван, тогда who пусто). "
    "Имена — как в MFU. Если задач нет, ответь пустой строкой."
)
def language_note(lang: Optional[str]) -> str:
    """A meeting in English gets its tasks in English: Russian tasks stood in its English protocol
    (bench-report/analysis-chain.md). Russian and an unknown language: as the prompt says."""
    if not str(lang or "").lower().startswith("en"):
        return ""
    return ("Встреча на английском: поле what пиши по-английски, как это сказали на встрече; "
            "имена — как в расшифровке.\n\n")


MFU_MAX_CHARS = 20000
MFU = "mfu"  # the source of a task taken from the MFU


def _same_as_mfu(x: Dict[str, Any], y: Dict[str, Any]) -> bool:
    """A task found in the transcript that is one of the MFU's: the same person (or nobody named on
    either side) and mostly the same words; worded differently in the MFU, so looser than _same_task.
    Only the word stems count: «отчёт по продажам» and «отчёт по закупкам» read alike letter by letter
    but are two tasks. When each side has a word the other lacks («продажам» / «закупкам») most words
    must be shared; when one only adds words to the other, most of the shorter one's."""
    wx, wy = (x.get("who") or "").casefold().split(), (y.get("who") or "").casefold().split()
    if wx and wy and wx[0] != wy[0]:  # the first name is enough: «Иван» and «Иван Петров»
        return False
    a, b = _norm_what(x.get("what")), _norm_what(y.get("what"))
    sa, sb = {w[:5] for w in a.split() if len(w) > 2}, {w[:5] for w in b.split() if len(w) > 2}  # word stems
    if a == b:
        return True
    if not (sa and sb):
        return False
    shared = len(sa & sb)
    if sa - sb and sb - sa:  # both say something of their own
        return shared / max(len(sa), len(sb)) >= 0.75
    return shared / min(len(sa), len(sb)) >= 0.6


VERIFY_CONTEXT_SEC = 40  # the lines this far before and after a task's moment go with it


# What is done during the meeting itself, at once: «пошарю экран», «скину ссылку в чат». Judged by the
# words said (the quote), not by single words: «переделать экран оплаты», «подготовить демонстрацию»,
# «купить камеру», «написать в чат поддержки» are tasks (all three audits found the word list dropping them).
# An action is of the meeting when it is
# - meeting control: share the screen, the microphone or camera on/off, a link «в чат», rejoin;
# - or said as «right now» («сейчас», «секунду», «дайте я…») about what is shown in the meeting.
# A due date or «после встречи» / «завтра» makes it a task whatever the words.
# The chat of the meeting itself: «в чат», «в этот чат», not «в чат проекта» / «в чат поддержки»
_MEETING_CHAT = (r"в (этот |наш )?чат(?![ \t]+(?!(и|а|сейчас|тогда|тоже)\b)[а-яёa-z])|в чат (встречи|созвона|звонка)\b|"
                 r"in (the |this )?chat\b(?! (of|for|with)\b)")
_CONTROL = re.compile(
    r"(пошар|расшар|\bшарю|\bшарить|покажу (свой |мой )?экран|включ\w* (свой |мой )?(микрофон|камер|звук)|"
    r"выключ\w* (свой |мой )?(микрофон|камер|звук)|(скину|кину|скидываю|кидаю|брошу|закину|отправлю|пришлю)\b.{0,40}"
    + _MEETING_CHAT + r"|перезайд|переподключ|share (my |the |your )?screen|screen ?shar|\bunmute\b|\bmute (my|your)\b|"
    r"turn (on|off) (my|the) (camera|mic)|(drop|post|paste|put) .{0,30}in (the |this )?chat\b(?! (of|for|with)\b)|\brejoin)", re.I)
_RIGHT_NOW = re.compile(
    r"(\bсейчас\b|\bщас\b|секунд|минутк|\bдай(те)? (я|покажу|открою)|\bдавай(те)? я\b|прямо тут|"
    r"right now|\blet me\b|one sec|give me a (sec|second|minute)|\bi'?ll just\b)", re.I)
# What is shown or heard on the call: a document or a file alone is the subject of real tasks too
_SHOWN = re.compile(
    r"(экран|демонстрац|\bоткро(ю|ем)\b|\bпокаж(у|ем)\b|\bслышно\b|\bвидно\b|микрофон|камер|\bзвук|"
    r"\bscreen\b|\bshow\b|\bopen\b|\bmic\b|camera|\bhear (me|us)\b|\bsee (my|the) screen\b)", re.I)
# Work on the product (a bug of its screen sharing or sound) and work handed to someone after the call
_PRODUCT_WORK = re.compile(r"(почин|исправ|\bбаг|ошибк|передел|\bfix|\bbug|\brepair)", re.I)
_HANDOFF = re.compile(
    r"(отправ|пришл|пришлю|подготов|обнов|сдела|напиш|написать|соберу|разошл|созвон|договорюсь|"
    r"после этого|\bsend\b|\bget back\b|\bprepare|\bupdate|\bwrite\b|\bfollow up|after that)", re.I)
_LATER = re.compile(
    r"(после (встречи|созвона|звонка)|\bпозже|\bпотом\b|\bзавтра|\bдо конца|\bк (понедельник|вторник|сред|четверг|пятниц|"
    r"суббот|воскресен|концу|\d)|after the (meeting|call)|\blater\b|\btomorrow|\bby (monday|tuesday|wednesday|thursday|"
    r"friday|the end|end of|\d))", re.I)


def in_meeting_action(item: Dict[str, Any]) -> bool:
    """An action of the meeting itself (share the screen, turn the microphone on, a link in this chat),
    not a task for after it. In doubt a task stays: a spare card costs a click, a lost task costs more."""
    if (item.get("due") or "").strip():
        return False
    said = str(item.get("quote") or "").strip() or str(item.get("what") or "")
    if _LATER.search(f"{said} {item.get('what') or ''}") or _PRODUCT_WORK.search(said):
        return False
    if _CONTROL.search(said):
        return True
    return bool(not _HANDOFF.search(said) and _RIGHT_NOW.search(said) and _SHOWN.search(said))


def _norm_what(t: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w ]+", " ", (t or "").casefold())).strip()


def _same_task(x: Dict[str, Any], y: Dict[str, Any]) -> bool:
    """The same task said twice: the same words (up to case and punctuation) for the same person, or the
    same person at the same moment in similar words. Similar words alone are not enough: «отправить
    договор» and «проверить договор» are two tasks."""
    from difflib import SequenceMatcher

    if (x.get("who") or "").casefold() != (y.get("who") or "").casefold():
        return False
    a, b = _norm_what(x.get("what")), _norm_what(y.get("what"))
    if a == b:
        return True
    near = x.get("at") is not None and y.get("at") is not None and abs(x["at"] - y["at"]) <= 5
    wa, wb = set(a.split()), set(b.split())
    # at one moment, words reordered or one word changed: the sets of words mostly the same
    return near and (len(wa & wb) / max(1, len(wa | wb)) >= 0.6 or SequenceMatcher(None, a, b).ratio() >= 0.8)


def prune(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """A task said twice (the same words for the same person) is kept once, in the order of the recording."""
    out: List[Dict[str, Any]] = []
    for x in items:
        if not any(_same_task(x, y) for y in out):
            out.append(x)
    return out


PART_OVERLAP_LINES = 4  # lines a part repeats from the end of the one before


def transcript_parts(lines: List[str], max_chars: int) -> List[str]:
    """The transcript in parts of at most max_chars, each starting with the last lines of the one before."""
    parts: List[str] = []
    current: List[str] = []
    size = 0
    for line in lines:
        if current and size + len(line) + 1 > max_chars and len(current) > PART_OVERLAP_LINES:
            parts.append("\n".join(current))
            current = current[-PART_OVERLAP_LINES:]
            size = sum(len(x) + 1 for x in current)
        current.append(line)
        size += len(line) + 1
    if current:
        parts.append("\n".join(current))
    return parts


def _context(item: Dict[str, Any], lines: List[tuple]) -> str:
    """The transcript lines around a task's moment (the whole quote's line when it has no moment)."""
    if item.get("at") is None:
        return ""
    near = [text for at, text in lines if abs(at - item["at"]) <= VERIFY_CONTEXT_SEC]
    return "\n".join(near)[:1500]


def verify(items: List[Dict[str, Any]], m: Dict[str, Any], llm: Any, batch: int = 12) -> List[Dict[str, Any]]:
    """A second look by the model at each task found, with the lines around it: what is discussion, an
    opinion or a report of work goes. An answer the model gives in no readable form keeps the batch as
    it is (the first pass already found them)."""
    if not items:
        return items
    from app.ollama_client import format_timestamp

    speakers = m.get("speakers") or {}
    lines = []
    for seg in m.get("segments") or []:
        name = (speakers.get(seg.get("speaker")) or {}).get("name") or seg.get("speaker") or ""
        at = float(seg.get("start") or 0)
        lines.append((at, f"[{format_timestamp(at)}] {name}: {(seg.get('text') or '').strip()}"))
    kept: List[Dict[str, Any]] = []
    for start in range(0, len(items), batch):
        part = items[start:start + batch]
        blocks = []
        for i, x in enumerate(part, 1):
            when = f" [{format_timestamp(x['at'])}]" if x.get("at") is not None else ""
            blocks.append(f"{i}.{when} {x['who'] or 'кто-то'}: {x['what']}\nСлова: «{x['quote']}»"
                          + (f"\nРядом:\n{_context(x, lines)}" if x.get("at") is not None else ""))
        try:
            answer = llm.chat(_CHECK, "\n\n".join(blocks), short=True)
        except Exception:
            kept.extend(part)
            continue
        found = re.findall(r"(?m)^\s*(\d+)\s*[:.)\-–—]\s*(да|нет|yes|no)\b[ \t]*(?:[—–\-:|][ \t]*(.+))?$", answer or "", flags=re.I)
        verdict = {int(n): v.casefold().startswith(("да", "yes")) for n, v, _w in found}
        if not verdict:
            kept.extend(part)
            continue
        reworded = {int(n): (w or "").strip().strip("«»\"'. ") for n, v, w in found}
        for i, x in enumerate(part, 1):
            if not verdict.get(i, True):
                continue
            better = reworded.get(i) or ""
            if len(better.split()) >= _REWRITE_MIN_WORDS and len(better) <= _REWRITE_MAX_CHARS:
                x = {**x, "what": better[0].upper() + better[1:]}  # one clear action instead of the words around
            kept.append(x)
    return kept


# Who a task is on: someone who speaks in the recording, someone only named in it, a department or
# a group, another company, nobody
KINDS = ("part", "ext", "team", "org", "none")
_KIND_WORDS = {"participant": "part", "speaker": "part", "outside": "ext", "mentioned": "ext", "person": "ext",
               "department": "team", "group": "team", "company": "org", "external": "org"}


_KIND_NAMES_FIXED: List[bool] = []
_READY_AT: List[int] = []  # database.schema_epoch when the tables were made: _init ran before every query


def _init() -> None:
    from app import database

    if _READY_AT and _READY_AT[0] == database.schema_epoch:
        return
    with _db_lock:
        conn = get_connection()
        conn.execute(
            """CREATE TABLE IF NOT EXISTS commitments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                meeting_id INTEGER NOT NULL,
                who TEXT NOT NULL DEFAULT '',
                to_whom TEXT NOT NULL DEFAULT '',
                what TEXT NOT NULL,
                due TEXT NOT NULL DEFAULT '',
                at REAL,
                status TEXT NOT NULL DEFAULT 'open',
                created_at TEXT NOT NULL,
                done_at TEXT NOT NULL DEFAULT ''
            )"""
        )
        conn.execute("CREATE INDEX IF NOT EXISTS commitments_meeting ON commitments (meeting_id)")
        # Tasks of the model the user deleted: they do not come back, and the latest teach the model
        conn.execute("""CREATE TABLE IF NOT EXISTS commitments_dismissed (
                id INTEGER PRIMARY KEY AUTOINCREMENT, meeting_id INTEGER NOT NULL, who TEXT NOT NULL DEFAULT '',
                what TEXT NOT NULL, quote TEXT NOT NULL DEFAULT '', at REAL, created_at TEXT NOT NULL)""")
        # The tasks of the Tasks page (added later: an older library gets the columns empty).
        # meeting_id 0 is a task added by hand without a recording.
        have = {r["name"] for r in conn.execute("PRAGMA table_info(commitments)").fetchall()}
        for column, ddl in (("who_kind", "TEXT NOT NULL DEFAULT ''"), ("quote", "TEXT NOT NULL DEFAULT ''"),
                            ("due_date", "TEXT NOT NULL DEFAULT ''"), ("source", "TEXT NOT NULL DEFAULT 'ai'"),
                            ("edited", "INTEGER NOT NULL DEFAULT 0"), ("updated_at", "TEXT NOT NULL DEFAULT ''")):
            if column not in have:
                conn.execute(f"ALTER TABLE commitments ADD COLUMN {column} {ddl}")
        # tasks the model gave to «team» or «none» (a kind's code written as the person) are on nobody;
        # once a run
        if not _KIND_NAMES_FIXED:
            _KIND_NAMES_FIXED.append(True)
            conn.execute("UPDATE commitments SET who = '', who_kind = 'none' WHERE lower(who) IN ('team', 'none') "
                         "AND source != 'manual' AND edited = 0")
        conn.commit()
        conn.close()
        _READY_AT[:] = [database.schema_epoch]


def norm_kind(value: Any) -> str:
    v = str(value or "").strip().lower()
    return v if v in KINDS else _KIND_WORDS.get(v, "ext")


# --- Due words → a date, said on the day of the meeting: "к пятнице", "до 15 ноября", "завтра" ---
_WEEKDAYS = (("понедельник", "monday"), ("вторник", "tuesday"), ("сред", "wednesday"), ("четверг", "thursday"),
             ("пятниц", "friday"), ("суббот", "saturday"), ("воскресень", "sunday"))
_MONTHS = (("январ", "jan"), ("феврал", "feb"), ("март", "mar"), ("апрел", "apr"), ("ма", "may"), ("июн", "jun"),
           ("июл", "jul"), ("август", "aug"), ("сентябр", "sep"), ("октябр", "oct"), ("ноябр", "nov"), ("декабр", "dec"))
_COUNTS = {"один": 1, "одну": 1, "два": 2, "две": 2, "три": 3, "четыре": 4, "пять": 5, "шесть": 6, "семь": 7,
           "десять": 10, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "ten": 10}


def _month_of(word: str) -> Optional[int]:
    w = word.lower()
    if w in ("мая", "май"):
        return 5
    for i, (ru, en) in enumerate(_MONTHS, 1):
        if (ru != "ма" and w.startswith(ru)) or w.startswith(en):
            return i
    return None


def _near_year(base: date, month: int, day: int) -> Optional[date]:
    """A day and month without a year: this year, or the next one when it is well past (said in
    December about January)."""
    try:
        d = date(base.year, month, day)
    except ValueError:
        return None
    if (base - d).days > 60:
        try:
            d = date(base.year + 1, month, day)
        except ValueError:
            return None
    return d


def parse_due(text: str, base: date) -> Optional[date]:
    """The day the due words mean, said on `base`; None when they name no day."""
    s = (text or "").lower().replace("ё", "е")
    if not s.strip():
        return None
    if "послезавтра" in s or "day after tomorrow" in s:
        return base + timedelta(days=2)
    if "завтра" in s or "tomorrow" in s:
        return base + timedelta(days=1)
    if "сегодня" in s or "today" in s or "tonight" in s:
        return base
    # «через 1.5 недели», «in 2.5 days»: a number with a fraction, before the date pattern took «1.5» for
    # the 1st of May
    m = re.search(r"(?:через|in)\s+(\d+[.,]\d+)\s+(дн|день|недел|месяц|day|week|month)", s)
    if m:
        unit = m.group(2)
        days = float(m.group(1).replace(",", ".")) * (7 if unit.startswith(("недел", "week")) else 30 if unit.startswith(("месяц", "month")) else 1)
        return base + timedelta(days=max(1, round(days)))
    m = re.search(r"\b(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?\b(?!\s*(?:дн|день|недел|месяц|час|day|week|month|hour))", s)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), m.group(3)
        if y:
            try:
                return date(int(y) + (2000 if len(y) == 2 else 0), mo, d)
            except ValueError:
                return None
        return _near_year(base, mo, d)
    m = re.search(r"\b(\d{1,2})\s+([а-яa-z]+)", s)
    if m and _month_of(m.group(2)):
        return _near_year(base, _month_of(m.group(2)), int(m.group(1)))
    m = re.search(r"\b([a-z]{3,})\s+(\d{1,2})\b", s)
    if m and _month_of(m.group(1)):
        return _near_year(base, _month_of(m.group(1)), int(m.group(2)))
    m = re.search(r"через\s+(\d+|[а-я]+)\s+(дн|день|недел|месяц)", s) or re.search(r"in\s+(\d+|[a-z]+)\s+(day|week|month)", s)
    if m:
        n = int(m.group(1)) if m.group(1).isdigit() else _COUNTS.get(m.group(1), 0)
        if n:
            unit = m.group(2)
            return base + timedelta(days=n * (7 if unit.startswith(("недел", "week")) else 30 if unit.startswith(("месяц", "month")) else 1))
    if re.search(r"через\s+неделю|in a week", s):
        return base + timedelta(days=7)
    if re.search(r"на следующей неделе|next week", s):
        return base + timedelta(days=7 - base.weekday())  # its Monday
    if re.search(r"через\s+месяц|in a month", s):
        return base + timedelta(days=30)
    if re.search(r"конц\w*\s+месяц|end of (the )?month", s):
        return date(base.year + (base.month == 12), base.month % 12 + 1, 1) - timedelta(days=1)
    if re.search(r"конц\w*\s+недел|на этой неделе|end of (the )?week|this week", s):
        return base + timedelta(days=max(0, 4 - base.weekday()))  # its Friday
    # A weekday as a word of its own: «сред» inside «средства» or «среди» is no Wednesday. The day named
    # on that same weekday is the next week's one («в среду», «до среды», «к среде» said on a Wednesday:
    # a deadline for today is said «сегодня», handled above), unless the phrase says «эту»/«this»
    for i, (ru, en) in enumerate(_WEEKDAYS):
        ru_re = r"сред(?:а|у|ы|е|ой|ам|ами|ах)?\b" if ru == "сред" else ru
        m = re.search(r"(?<![а-яa-z])(?:" + ru_re + r"|" + en + r")", s)
        if m:
            ahead = (i - base.weekday()) % 7
            if not ahead and not re.search(r"(?:\bэт(?:у|от|а|ой)|\bthis)\s+$", s[:m.start()]):
                ahead = 7
            return base + timedelta(days=ahead)
    return None


def _meeting_day(m: Optional[Dict[str, Any]]) -> date:
    raw = str((m or {}).get("recorded_at") or (m or {}).get("created_at") or "")[:10]
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return date.today()


def participants(m: Optional[Dict[str, Any]]) -> List[str]:
    """The names of the people who speak in a recording."""
    out: List[str] = []
    for v in ((m or {}).get("speakers") or {}).values():
        name = str((v.get("name") if isinstance(v, dict) else v) or "").strip()
        if name and name not in out:
            out.append(name)
    return out


def _seconds(text: str) -> Optional[float]:
    m = re.search(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", text or "")
    if not m:
        return None
    a, b, c = m.groups()
    return int(a) * 3600 + int(b) * 60 + int(c) if c else int(a) * 60 + int(b)


def parse_answer(answer: str) -> List[Dict[str, Any]]:
    """JSON objects of the model's answer (one per line; a list or code fences are tolerated)."""
    text = re.sub(r"```(?:json)?", "", answer or "")
    found: List[Dict[str, Any]] = []
    candidates = re.findall(r"\{[^{}]*\}", text)
    for raw in candidates:
        try:
            obj = json.loads(raw)
        except ValueError:
            continue
        what = str(obj.get("what") or "").strip()
        if not what:
            continue
        who = str(obj.get("who") or "").strip()[:80]
        # a small model sometimes writes the kind's code («team», «none») where the name goes: nobody named
        if who.casefold() in ("team", "none", "part", "ext", "org", "null", "nobody", "unknown", "n/a", "-", "—"):
            who = ""
        found.append({
            "who": who,
            "kind": norm_kind(obj.get("kind")) if who else "none",
            "to": str(obj.get("to") or "").strip()[:80],
            "what": what[:300],
            "due": str(obj.get("due") or "").strip()[:80],
            "at": _seconds(str(obj.get("time") or "")),
            "quote": str(obj.get("quote") or "").strip().strip("«»\"")[:300],
        })
    return found


def supported(item: Dict[str, Any], m: Dict[str, Any]) -> bool:
    """The promise is in the transcript (not made up by the model)."""
    from app.grounding import UNVERIFIED_MARK, ground_summary

    from app.grounding import _fmt

    # «[1:45:30]» past an hour: «[105:30]» was read as 05:30 (found in an audit)
    ts = f" {_fmt(item['at'])}" if item.get("at") is not None else ""
    line = f"- {item['who']} {item['what']}{ts}"
    return UNVERIFIED_MARK not in ground_summary(line, m.get("segments") or [], m.get("speakers") or {})


def extract(meeting_id: int, model_name: Optional[str] = None, hints: Optional[str] = None) -> List[Dict[str, Any]]:
    """Finds the promises of a recording (again: the earlier list of this recording is replaced,
    keeping what was ticked off). hints: more to tell the model (none by default)."""
    from app.llm import target
    from app.ollama_client import build_transcript_lines

    m = get_meeting(meeting_id)
    if not m or not m.get("segments"):
        raise ValueError("Нет текста записи")
    llm = target(model_name)
    from app.ollama_client import speakers_in_language

    # «Speaker 2» in an English meeting, as its overview calls them (tasks said «Участник 2»: an audit)
    lines = build_transcript_lines(m["segments"], speakers_in_language(m.get("speakers") or {}, m.get("language")))
    found: List[Dict[str, Any]] = []
    # Part by part, so the end of a long meeting is read too (it was cut to what fits the model before);
    # the parts overlap by a few lines, so a promise on a border is seen whole
    try:  # who was there, their names written right (app/people.meeting_roster)
        from app.people import fix_name_typos, meeting_roster

        roster = meeting_roster(m)
    except Exception:
        roster, fix_name_typos = [], None
    head = ("Участники встречи (имена и фамилии написаны верно, пиши их так же): " + "; ".join(roster) + ". "
            "В разговоре их могут звать коротко или иначе («Макс» — Максим, «Саша» — Александр, по фамилии, "
            "латиницей или кириллицей); в who пиши имя из этого списка, если ясно, о ком речь.\n\n") if roster else ""
    try:  # the user's contacts besides the participants: a task for someone not in the meeting (app/people.known_people)
        from app.people import known_people

        known = known_people(m, exclude=roster)
    except Exception:
        known = []
    if known:
        head += ("Люди из контактов пользователя (могут упоминаться, хотя их нет на встрече): " + "; ".join(known)
                 + ". Если задача для кого-то из них, в who пиши имя как в этом списке.\n\n")
        roster = roster + [k.split(" (также:")[0] for k in known]
    try:  # the meeting's feature and the dictionary's terms (Словарь, Словарь → Фичи)
        from app import vocab
        from app.features import describe

        about = describe(m.get("features") or [])
        glossary = vocab.glossary_note(already=about)
        head += (f"Встреча относится к фиче:\n{about}\n\n" if about else "") + (glossary + "\n\n" if glossary else "")
        # No protocol points by default: as hints they first narrowed the search, then (said as an addition)
        # added the protocol's points that are not tasks — precision 0.70 against 0.81, the same recall
        # (bench-report/analysis-chain.md, «Перемер задач»). The protocol takes the tasks instead.
        head += (hints + "\n\n") if hints else ""
        head += language_note(m.get("language"))
    except Exception as e:
        print(f"[commitments] no glossary: {e}", flush=True)
    system = _SYSTEM + _dismissed_examples()
    unreadable = False  # an answer with no list in it: the model failed, not «no tasks» (found in the audit)
    for part in transcript_parts(lines, max(8000, llm.max_chars - 3000)):
        answer = llm.chat(system, head + "Расшифровка:\n" + part)
        got = parse_answer(answer)
        if not got and (answer or "").strip() and "{" not in answer and "[" not in answer:
            unreadable = True
        found += got
    mfu = (m.get("mfu") or "").strip()
    from_mfu: List[Dict[str, Any]] = []
    if mfu:  # the organizer's list: its tasks as written, none checked against the transcript
        from_mfu = [{**x, "at": None, "source": MFU} for x in parse_answer(llm.chat(_SYSTEM_MFU, head + "MFU:\n" + mfu[:MFU_MAX_CHARS]))]
    if roster and fix_name_typos:  # a name still written with a letter wrong: as in the roster
        for x in found + from_mfu:
            for k in ("who", "to", "what"):  # the keys of parse_answer
                if isinstance(x.get(k), str):
                    x[k] = fix_name_typos(x[k], roster)
        from app.people import resolve_person

        for x in found + from_mfu:  # «Макс» said in the meeting is the participant «Maksim Orlov» of Teams (one fit only)
            for k in ("who", "to"):
                if isinstance(x.get(k), str) and x[k].strip():
                    x[k] = resolve_person(x[k], roster)
    try:  # a variant of a name merged in the people directory («Макс» added to someone): the directory's name
        from app.people import canonical

        for x in found + from_mfu:
            for k in ("who", "to"):
                if isinstance(x.get(k), str) and x[k].strip():
                    x[k] = canonical(x[k].strip())
    except Exception as e:
        print(f"[commitments] directory names: {e}", flush=True)
    items = prune([x for x in found if supported(x, m) and not in_meeting_action(x)])
    items = verify(items, m, llm)  # a second look, task by task, with the lines around it
    items = [x for x in items if not in_meeting_action(x)]
    dismissed = _dismissed(meeting_id)
    items = [x for x in items if not _was_dismissed(x, dismissed)]  # the user deleted it: it does not come back
    if from_mfu:
        from_mfu = prune([x for x in from_mfu if not _was_dismissed(x, dismissed)])
        rest = []
        for x in items:  # said in the meeting and in the MFU: the MFU's task, with the moment it was said
            twin = next((y for y in from_mfu if _same_as_mfu(x, y)), None)
            if twin is None:
                rest.append(x)
            elif twin.get("at") is None:
                twin["at"] = x.get("at")
        items = from_mfu + rest
    _init()
    now = datetime.now().isoformat(timespec="seconds")
    day, speaking = _meeting_day(m), {n.casefold() for n in participants(m)}
    with _db_lock:
        conn = get_connection()
        if not conn.execute("SELECT 1 FROM meetings WHERE id = ?", (meeting_id,)).fetchone():
            conn.close()  # deleted while its tasks were looked for: they would stay in «Задачи» (found in an audit)
            return []
        # Ticked off: found again by the same task (its words, or the same person at the same moment in
        # similar words) or the same quote from the recording — the model words it differently each time,
        # and a done task came back open after a new transcription
        done_rows = [dict(r) for r in conn.execute(
            "SELECT who, what, quote, at FROM commitments WHERE meeting_id = ? AND status = 'done'", (meeting_id,)).fetchall()]
        done_quotes = {(r["quote"] or "").strip().casefold() for r in done_rows} - {""}

        done_what = {_norm_what(r["what"]) for r in done_rows}

        def was_done(x: Dict[str, Any]) -> bool:
            return (_norm_what(x.get("what")) in done_what  # the same words, whoever the model named
                    or (x.get("quote") or "").strip().casefold() in done_quotes
                    or any(_same_task(x, r) for r in done_rows))
        # What the user added or changed by hand stays as they left it; a task they reworded is still
        # the one the model finds again by its words in the recording (the quote) or its moment
        rows = conn.execute("SELECT what, quote, at, source FROM commitments WHERE meeting_id = ? AND (source = 'manual' OR edited = 1)",
                            (meeting_id,)).fetchall()
        kept = {r["what"].casefold() for r in rows}
        kept_quotes = {(r["quote"] or "").strip().casefold() for r in rows} - {""}
        kept_at = [r["at"] for r in rows if r["source"] != "manual" and r["at"] is not None]
        if unreadable and not items and conn.execute(
                "SELECT 1 FROM commitments WHERE meeting_id = ? AND source != 'manual' AND edited = 0", (meeting_id,)).fetchone():
            # the model's answer could not be read: the tasks found before stay rather than all vanish
            conn.close()
            print(f"[commitments] meeting {meeting_id}: the model's answer had no tasks list; the tasks are kept", flush=True)
            return for_meetings([meeting_id])
        conn.execute("DELETE FROM commitments WHERE meeting_id = ? AND source != 'manual' AND edited = 0", (meeting_id,))
        for x in items:
            if (x["what"].casefold() in kept or (x["quote"] or "").strip().casefold() in kept_quotes
                    or (x["at"] is not None and any(abs(x["at"] - a) <= 1 for a in kept_at))):
                continue
            status = "done" if was_done(x) else "open"
            kind = "part" if x["who"].casefold() in speaking else x["kind"]
            due_date = parse_due(x["due"], day)
            conn.execute(
                "INSERT INTO commitments (meeting_id, who, to_whom, what, due, at, status, created_at, who_kind, quote,"
                " due_date, source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (meeting_id, x["who"], x["to"], x["what"], x["due"], x["at"], status, now, kind, x["quote"],
                 due_date.isoformat() if due_date else "", x.get("source") or "ai"))
        conn.commit()
        conn.close()
    return for_meetings([meeting_id])


def _rows(sql: str, args: tuple) -> List[Dict[str, Any]]:
    _init()
    with _db_lock:
        conn = get_connection()
        rows = [dict(r) for r in conn.execute(sql, args).fetchall()]
        conn.close()
    return rows


def for_meetings(ids: List[int], status: Optional[str] = None) -> List[Dict[str, Any]]:
    if not ids:
        return []
    q = f"SELECT * FROM commitments WHERE meeting_id IN ({','.join('?' * len(ids))})"
    args: tuple = tuple(int(i) for i in ids)
    if status:
        q += " AND status = ?"
        args += (status,)
    return _enrich(_rows(q + " ORDER BY meeting_id, at", args))


def meeting_briefs(ids: Any) -> Dict[int, Dict[str, Any]]:
    """Title, dates and speakers of the given recordings, in one query: the task lists need no
    transcripts (get_meeting would read every segment of every recording). The speakers as the library
    list keeps them: names and colours, without parsing the voice prints of every recording."""
    from app.database import _list_speakers

    ids = sorted({int(i) for i in ids if i})
    out: Dict[int, Dict[str, Any]] = {}
    for start in range(0, len(ids), 500):  # SQLite's limit on the number of parameters
        part = ids[start:start + 500]
        for r in _rows(f"SELECT id, title, recorded_at, created_at, speakers_json FROM meetings WHERE id IN ({','.join('?' * len(part))})",
                       tuple(part)):
            speakers = _list_speakers(r["id"], r.get("speakers_json") or "{}")
            out[r["id"]] = {"id": r["id"], "title": r.get("title") or "", "recorded_at": r.get("recorded_at"),
                            "created_at": r.get("created_at"),
                            "speakers": {k: dict(v) if isinstance(v, dict) else v for k, v in speakers.items()}}
    return out


def _enrich(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The recording's title and date, and for older rows the kind and the date their words give."""
    meetings = meeting_briefs(r["meeting_id"] for r in rows)
    for r in rows:
        mm = meetings.get(r["meeting_id"]) or {}
        r["meeting_title"] = mm.get("title") or ""
        r["meeting_date"] = str(mm.get("recorded_at") or mm.get("created_at") or "")[:10]
        if not r.get("who_kind"):
            names = {n.casefold() for n in participants(mm)}
            r["who_kind"] = "none" if not r["who"] else "part" if r["who"].casefold() in names else "ext"
        if not r.get("due_date") and r.get("due"):
            d = parse_due(r["due"], _meeting_day(mm) if mm else date.today())
            r["due_date"] = d.isoformat() if d else ""
        r.setdefault("due_date", "")
        r.setdefault("quote", "")
        r.setdefault("source", "ai")
    return rows


def open_for_series(series_id: int) -> List[Dict[str, Any]]:
    from app.series import series_meetings

    return for_meetings([r["id"] for r in series_meetings(series_id)], status="open")


def all_open() -> List[Dict[str, Any]]:
    ids = [r["meeting_id"] for r in _rows("SELECT DISTINCT meeting_id FROM commitments WHERE status = 'open'", ())]
    return for_meetings(ids, status="open")


def all_tasks() -> List[Dict[str, Any]]:
    """Every task of the library, open and done, the ones without a recording included."""
    return _enrich(_rows("SELECT * FROM commitments ORDER BY meeting_id, at", ()))


def get_task(task_id: int) -> Optional[Dict[str, Any]]:
    rows = _enrich(_rows("SELECT * FROM commitments WHERE id = ?", (int(task_id),)))
    return rows[0] if rows else None


def _clean_date(value: Any) -> str:
    v = str(value or "").strip()
    if not v:
        return ""
    try:
        return date.fromisoformat(v[:10]).isoformat()
    except ValueError:
        raise ValueError("Неверная дата")


def create(what: str, who: str = "", who_kind: str = "", due_date: str = "", meeting_id: int = 0,
           at: Optional[float] = None) -> Dict[str, Any]:
    """A task added by hand, with or without a recording (and a moment of it)."""
    what = (what or "").strip()[:300]
    if not what:
        raise ValueError("Пустая задача")
    if meeting_id and not get_meeting(int(meeting_id)):
        raise ValueError("Запись не найдена")
    who = (who or "").strip()[:80]
    kind = norm_kind(who_kind) if who else "none"
    due = _clean_date(due_date)
    _init()
    now = datetime.now().isoformat(timespec="seconds")
    with _db_lock:
        conn = get_connection()
        cur = conn.execute(
            "INSERT INTO commitments (meeting_id, who, to_whom, what, due, at, status, created_at, who_kind, due_date,"
            " source, updated_at) VALUES (?,?, '', ?, '', ?, 'open', ?,?,?, 'manual', ?)",
            (int(meeting_id or 0), who, what, at if meeting_id else None, now, kind, due, now))
        new_id = cur.lastrowid
        conn.commit()
        conn.close()
    return get_task(new_id) or {}


_EDITABLE = ("who", "who_kind", "due_date", "what", "status")


def update(task_id: int, changes: Dict[str, Any]) -> Dict[str, Any]:
    """Reassigns, moves, renames or ticks off a task. A change by hand is kept when the tasks of the
    recording are found again."""
    fields = {k: v for k, v in changes.items() if k in _EDITABLE and v is not None}
    if not fields:
        raise ValueError("Изменений нет")
    if "status" in fields and fields["status"] not in ("open", "done"):
        raise ValueError("Неизвестное состояние")
    if "what" in fields:
        fields["what"] = str(fields["what"]).strip()[:300]
        if not fields["what"]:
            raise ValueError("Пустая задача")
    if "who" in fields:
        fields["who"] = str(fields["who"]).strip()[:80]
        if not fields["who"]:
            fields["who_kind"] = "none"
    if "who_kind" in fields:
        fields["who_kind"] = norm_kind(fields["who_kind"])
    if "due_date" in fields:
        fields["due_date"] = _clean_date(fields["due_date"])
        fields["due"] = ""  # the date is the user's now, not the words of the recording
    now = datetime.now().isoformat(timespec="seconds")
    if "status" in fields:
        fields["done_at"] = now if fields["status"] == "done" else ""
    # ticking off is not a change of the task itself
    edited = any(k in fields for k in ("who", "who_kind", "due_date", "what"))
    _init()
    with _db_lock:
        conn = get_connection()
        sets = ", ".join(f"{k} = ?" for k in fields) + ", updated_at = ?" + (", edited = 1" if edited else "")
        n = conn.execute(f"UPDATE commitments SET {sets} WHERE id = ?", (*fields.values(), now, int(task_id))).rowcount
        conn.commit()
        conn.close()
    if not n:
        raise LookupError("Задача не найдена")
    return get_task(task_id) or {}


def delete(task_id: int) -> bool:
    """A task deleted. One the model found is remembered: found again in a new search it is left out, and
    the latest ones deleted are shown to the model as what is not a task."""
    _init()
    with _db_lock:
        conn = get_connection()
        row = conn.execute("SELECT meeting_id, who, what, quote, at, source FROM commitments WHERE id = ?",
                           (int(task_id),)).fetchone()
        if row and row["source"] != "manual" and row["meeting_id"]:
            conn.execute("INSERT INTO commitments_dismissed (meeting_id, who, what, quote, at, created_at) VALUES (?,?,?,?,?,?)",
                         (row["meeting_id"], row["who"], row["what"], row["quote"], row["at"],
                          datetime.now().isoformat(timespec="seconds")))
        n = conn.execute("DELETE FROM commitments WHERE id = ?", (int(task_id),)).rowcount
        conn.commit()
        conn.close()
    return bool(n)


def people(tasks: Optional[List[Dict[str, Any]]] = None,
           meetings: Optional[Dict[int, Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Everyone tasks can be on: the people who speak in the recordings that have tasks and the
    names the tasks carry (with their kind), each with its count of open and done tasks."""
    tasks = all_tasks() if tasks is None else tasks
    found: Dict[str, Dict[str, Any]] = {}

    def add(name: str, kind: str) -> Dict[str, Any]:
        key = name.casefold()
        if key not in found:
            found[key] = {"name": name, "kind": kind, "open": 0, "done": 0}
        elif kind == "part":  # someone who speaks somewhere is a participant
            found[key]["kind"] = "part"
        return found[key]

    briefs = meeting_briefs(t["meeting_id"] for t in tasks) if meetings is None else meetings
    for mid in sorted(briefs):
        for name in participants(briefs[mid]):
            add(name, "part")
    for t in tasks:
        if t["who"]:
            p = add(t["who"], t["who_kind"] or "ext")
            p["done" if t["status"] == "done" else "open"] += 1
    order = {k: i for i, k in enumerate(KINDS)}
    return sorted(found.values(), key=lambda p: (order.get(p["kind"], 9), -p["open"], p["name"].casefold()))


def guess(text: str, names: List[str], base: Optional[date] = None) -> Dict[str, Any]:
    """Who and when the words of a new task name («Анне подготовить отчёт к пятнице»)."""
    s = (text or "").casefold()
    who = ""
    for name in sorted(names, key=len, reverse=True):
        first = name.casefold().split()[0] if name.strip() else ""
        # a stem catches the other forms of a name (Анна, Анне, Анну)
        stem = first[:max(3, len(first) - 2)] if len(first) > 4 else first[:max(3, len(first) - 1)]
        if len(stem) >= 3 and re.search(r"(?:^|\W)" + re.escape(stem), s):
            who = name
            break
    d = parse_due(text, base or date.today())
    return {"who": who, "due_date": d.isoformat() if d else ""}


_REPORT_SYSTEM = (
    "Ты пишешь короткую сводку по задачам команды. Перескажи факты ниже связным деловым текстом на языке фактов, "
    "по тем же разделам. Ничего не добавляй и не выдумывай: только эти задачи, люди и сроки. Без вступлений и "
    "без markdown-разметки, абзацы — через пустую строку."
)


def report(tasks: List[Dict[str, Any]], start: str, end: str, include: List[str], fmt: str = "short",
           lang: str = "ru", today: Optional[date] = None) -> Dict[str, Any]:
    """The summary of a period: the tasks due in it, done / open / overdue, as lines of text (the
    Summary panel). fmt: short, people (one line a person), mail (a letter to the team)."""
    today = today or date.today()
    ru = lang != "en"
    lo, hi = _clean_date(start), _clean_date(end)
    scope = [t for t in tasks if t.get("due_date") and lo <= t["due_date"] <= hi]
    over = [t for t in scope if t["status"] != "done" and t["due_date"] < today.isoformat()]
    done = [t for t in scope if t["status"] == "done"]
    open_ = [t for t in scope if t["status"] != "done" and t not in over]
    nobody = "без исполнителя" if ru else "no assignee"

    def short(t: Dict[str, Any]) -> str:
        w = t["what"]
        return "«" + (w if len(w) <= 60 else w[:58] + "…") + "»" if ru else '"' + (w if len(w) <= 60 else w[:58] + "…") + '"'

    def who(t: Dict[str, Any]) -> str:
        return t["who"] or nobody

    def day(t: Dict[str, Any]) -> str:
        d = date.fromisoformat(t["due_date"])
        return f"{d.day:02d}.{d.month:02d}"

    lines: List[Dict[str, str]] = []
    if fmt == "people":
        names = sorted({who(t) for t in scope}, key=lambda n: (-sum(who(t) == n for t in scope), n.casefold()))
        for n in names:
            mine = [t for t in scope if who(t) == n]
            d, o = [t for t in mine if t in done], [t for t in mine if t in over]
            w = [t for t in mine if t in open_]
            bits = [(f"{len(d)} из {len(mine)} выполнено" if ru else f"{len(d)} of {len(mine)} done")]
            if "over" in include and o:
                bits.append(("просрочено: " if ru else "overdue: ") + ", ".join(map(short, o)))
            if "open" in include and w:
                bits.append(("в работе: " if ru else "in progress: ") + ", ".join(map(short, w)))
            if "done" in include and d:
                bits.append(("сделано: " if ru else "done: ") + ", ".join(map(short, d)))
            lines.append({"text": f"{n} — " + "; ".join(bits) + ".", "tone": "over" if o else "done" if len(d) == len(mine) else ""})
    elif fmt == "mail":
        lines.append({"text": (f"Коллеги, итоги по задачам за {_period_text(lo, hi, ru)}." if ru
                               else f"Hello all, here is where our tasks stand for {_period_text(lo, hi, ru)}."), "tone": ""})
        if "done" in include:
            lines.append({"text": (f"Сделано ({len(done)}): " if ru else f"Done ({len(done)}): ")
                          + ("; ".join(t["what"] for t in done) or "—") + ".", "tone": ""})
        if "open" in include:
            lines.append({"text": (f"В работе ({len(open_)}): " if ru else f"In progress ({len(open_)}): ")
                          + ("; ".join(f"{t['what']} — {who(t)}, {day(t)}" for t in open_) or "—") + ".", "tone": ""})
        if "over" in include:
            lines.append({"text": (f"Просрочено ({len(over)}): " if ru else f"Overdue ({len(over)}): ")
                          + ("; ".join(f"{t['what']} — {who(t)}, {day(t)}" for t in over) or "—") + ".", "tone": ""})
    else:
        lines.append({"text": (f"Закрыто {len(done)} из {len(scope)}, в работе {len(open_)}, просрочено {len(over)}." if ru
                               else f"{len(done)} of {len(scope)} closed, {len(open_)} in progress, {len(over)} overdue."), "tone": ""})
        if "over" in include and over:
            lines.append({"text": ("Просрочено: " if ru else "Overdue: ") + "; ".join(f"{short(t)} — {who(t)}" for t in over) + ".", "tone": "over"})
        if "done" in include and done:
            lines.append({"text": ("Сделано: " if ru else "Done: ") + ", ".join(map(short, done)) + ".", "tone": "done"})
        if "open" in include and open_:
            nearest = sorted(open_, key=lambda t: t["due_date"])[:3]
            lines.append({"text": ("Ближайшие: " if ru else "Next: ") + ", ".join(f"{short(t)} ({day(t)})" for t in nearest) + ".", "tone": ""})
    title = ("Сводка за " if ru else "Summary for ") + _period_text(lo, hi, ru)
    return {"title": title, "lines": lines, "text": title + "\n\n" + "\n\n".join(x["text"] for x in lines),
            "counts": {"all": len(scope), "done": len(done), "open": len(open_), "over": len(over)}}


def _period_text(lo: str, hi: str, ru: bool) -> str:
    a, b = date.fromisoformat(lo), date.fromisoformat(hi)
    gen = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря")
    if not ru:
        return f"{a.strftime('%b')} {a.day} – {b.strftime('%b')} {b.day}"
    if a.month == b.month and a.year == b.year:
        return f"{a.day}–{b.day} {gen[b.month - 1]}"
    return f"{a.day} {gen[a.month - 1]} – {b.day} {gen[b.month - 1]}"


def report_by_model(facts: Dict[str, Any], model_name: Optional[str] = None) -> Dict[str, Any]:
    """The same summary told by the analysis model from its facts (only them: the facts go in, the
    model writes the sentences)."""
    from app.llm import target

    llm = target(model_name)
    text = llm.chat(_REPORT_SYSTEM, facts["text"]).strip()
    if not text:
        return facts
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    return {**facts, "lines": [{"text": p, "tone": ""} for p in paragraphs], "text": facts["title"] + "\n\n" + "\n\n".join(paragraphs),
            "model": llm.label}


def rename_person(meeting_id: int, old: str, new: str) -> int:
    """A speaker renamed (or merged into another) in a recording: its tasks follow, as assignee and
    as the one they are for. Tasks are kept by name, so the old name would stay otherwise."""
    old, new = (old or "").strip(), (new or "").strip()
    if not old or not new or old == new:
        return 0
    _init()
    with _db_lock:
        conn = get_connection()
        try:
            # compared here: SQLite's NOCASE folds Latin letters only, not Cyrillic
            n, key = 0, old.casefold()
            for r in conn.execute("SELECT id, who, to_whom FROM commitments WHERE meeting_id = ?", (meeting_id,)).fetchall():
                who = new if (r["who"] or "").strip().casefold() == key else r["who"]
                to = new if (r["to_whom"] or "").strip().casefold() == key else r["to_whom"]
                if (who, to) != (r["who"], r["to_whom"]):
                    conn.execute("UPDATE commitments SET who = ?, to_whom = ? WHERE id = ?", (who, to, r["id"]))
                    n += 1
            conn.commit()
        finally:
            conn.close()
    return n


def rename_people(meeting_id: int, changes: Dict[str, str]) -> int:
    """Several speakers of a recording renamed at once (split anew: «Участник 2» is «Участник 3» now and
    «Участник 3» is «Участник 2»): each task takes the new name of its person, read before any is changed."""
    keyed = {(o or "").strip().casefold(): (n or "").strip() for o, n in (changes or {}).items()
             if (o or "").strip() and (n or "").strip() and (o or "").strip() != (n or "").strip()}
    if not keyed:
        return 0
    _init()
    with _db_lock:
        conn = get_connection()
        try:
            n = 0
            for r in conn.execute("SELECT id, who, to_whom FROM commitments WHERE meeting_id = ?", (meeting_id,)).fetchall():
                who = keyed.get((r["who"] or "").strip().casefold(), r["who"])
                to = keyed.get((r["to_whom"] or "").strip().casefold(), r["to_whom"])
                if (who, to) != (r["who"], r["to_whom"]):
                    conn.execute("UPDATE commitments SET who = ?, to_whom = ? WHERE id = ?", (who, to, r["id"]))
                    n += 1
            conn.commit()
        finally:
            conn.close()
    return n


def set_status(commitment_id: int, status: str) -> None:
    if status not in ("open", "done"):
        raise ValueError("Неизвестное состояние")
    _init()
    with _db_lock:
        conn = get_connection()
        conn.execute("UPDATE commitments SET status = ?, done_at = ? WHERE id = ?",
                     (status, datetime.now().isoformat(timespec="seconds") if status == "done" else "", commitment_id))
        conn.commit()
        conn.close()


DISMISSED_EXAMPLES = 8  # the latest deleted tasks shown to the model


def _dismissed(meeting_id: int) -> List[Dict[str, Any]]:
    _init()
    return _rows("SELECT who, what, quote, at FROM commitments_dismissed WHERE meeting_id = ?", (meeting_id,))


def _was_dismissed(item: Dict[str, Any], dismissed: List[Dict[str, Any]]) -> bool:
    quote = (item.get("quote") or "").strip().casefold()
    return any((quote and quote == (d["quote"] or "").strip().casefold())
               or _norm_what(item.get("what")) == _norm_what(d["what"])
               or _same_task(item, d) for d in dismissed)


def _dismissed_examples() -> str:
    """The tasks the user deleted lately, as the model's examples of what is not a task here."""
    _init()
    rows = _rows("SELECT meeting_id, what FROM commitments_dismissed ORDER BY id DESC LIMIT ?", (DISMISSED_EXAMPLES,))
    whats = [r["what"].strip()[:120] for r in rows if (r["what"] or "").strip()]
    if not whats:
        return ""
    return ("\nЭтот пользователь раньше удалял такие найденные задачи как НЕ задачи — похожее не включай: "
            + "; ".join(f"«{w}»" for w in whats) + ".")


def delete_for_meeting(meeting_id: int) -> int:
    """The promises the model found in one recording (the "Clear" button of its Promises section). The
    tasks added or changed by hand stay, as on a new extraction (extract)."""
    _init()
    with _db_lock:
        conn = get_connection()
        n = conn.execute("DELETE FROM commitments WHERE meeting_id = ? AND source != 'manual' AND edited = 0",
                         (meeting_id,)).rowcount
        conn.commit()
        conn.close()
    return n


def _due(x: Dict[str, Any]) -> str:
    """The task's due: the date set by hand (or read from the words) first, the words of the recording otherwise. A
    task added or given a date by hand has no words: its date was left out of the exports (found in an audit)."""
    return str(x.get("due_date") or x.get("due") or "")


def as_text(items: List[Dict[str, Any]]) -> str:
    """For prompts: '- Анна → клиенту: презентация (к пятнице) — «Встреча», 2026-10-14'."""
    out = []
    for x in items:
        who = x["who"] + (f" → {x['to_whom']}" if x.get("to_whom") else "")
        due = f" ({_due(x)})" if _due(x) else ""
        out.append(f"- {who}: {x['what']}{due} — «{x.get('meeting_title', '')}», {x.get('meeting_date', '')}")
    return "\n".join(out)


def export_text(items: List[Dict[str, Any]], fmt: str, lang: str = "ru") -> str:
    """md: Markdown tasks (Obsidian, Notion, any notes app); todoist: Todoist's CSV import;
    csv: a table (Notion database, Excel)."""
    import csv
    import io

    if fmt == "md":
        lines = []
        for x in items:
            box = "[x]" if x.get("status") == "done" else "[ ]"
            who = x["who"] + (f" → {x['to_whom']}" if x.get("to_whom") else "")
            due = f" 📅 {_due(x)}" if _due(x) else ""
            lines.append(f"- {box} {who}: {x['what']}{due} — {x.get('meeting_title', '')} ({x.get('meeting_date', '')})")
        return "\n".join(lines) + "\n"
    buf = io.StringIO()
    w = csv.writer(buf)
    if fmt == "todoist":
        w.writerow(["TYPE", "CONTENT", "DESCRIPTION", "PRIORITY", "INDENT", "AUTHOR", "RESPONSIBLE", "DATE", "DATE_LANG", "TIMEZONE"])
        for x in items:
            w.writerow(["task", _cell(f"{x['what']} ({x['who']})"), _cell(f"{x.get('meeting_title', '')}, {x.get('meeting_date', '')}"),
                        4, 1, "", "", _cell(_due(x)), "ru" if lang == "ru" else "en", ""])
    else:
        w.writerow(["Задача" if lang == "ru" else "Task", "Кто" if lang == "ru" else "Who", "Кому" if lang == "ru" else "For",
                    "Срок" if lang == "ru" else "Due", "Встреча" if lang == "ru" else "Meeting",
                    "Дата" if lang == "ru" else "Date", "Выполнено" if lang == "ru" else "Done"])
        for x in items:
            w.writerow([_cell(x["what"]), _cell(x["who"]), _cell(x.get("to_whom") or ""), _cell(_due(x)),
                        _cell(x.get("meeting_title", "")), x.get("meeting_date", ""),
                        "да" if x.get("status") == "done" and lang == "ru" else "yes" if x.get("status") == "done" else ""])
    return buf.getvalue()


def _cell(value: Any) -> str:
    """A text cell of the table that Excel shows as text: a task said in a meeting or the title of an
    invitation (written by whoever sent it) starting with = + - @ would be run as a formula when the file is
    opened (=WEBSERVICE("http://…"&A2) sends the neighbouring cells away)."""
    text = str(value or "")
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text
