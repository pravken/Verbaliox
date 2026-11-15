"""
The analysis of a recording in steps, so its parts cannot disagree (Настройки → ИИ-анализ → «Анализ по шагам»,
on by default since the measurement in bench-report/analysis-chain.md):

1. the decisions and the open questions, read from the transcript alone;
2. the tasks (commitments.extract), with those decisions as hints;
3. the protocol, told both; its «Решения», «Открытые вопросы» and «Следующие шаги» are then written from
   steps 1 and 2 by the program, not by the model, so they are the same lists word for word.

Without the setting the analysis is as before, and in both cases `sync_next_steps` adds to the protocol's
«Следующие шаги» a task found later (the tasks found again on their own), so the overview never lacks one.
"""

import difflib
import re
from typing import Any, Callable, Dict, List, Optional

from app.meeting_context import _ANY_HEAD, _RESULT_HEADS, protocol_points

_NONE_LINES = {
    "decisions": "Решений не принималось",
    "open": "Открытых вопросов нет",
    "next": "Следующие шаги не назывались",
}
_HEADINGS = {"decisions": "## Решения", "open": "## Открытые вопросы", "next": "## Следующие шаги"}


def enabled(settings: Optional[Dict[str, str]] = None) -> bool:
    if settings is None:
        from app.database import get_all_settings

        settings = get_all_settings()
    return (settings.get("analysis_chain") or "true").lower() == "true"


def task_items(meeting_id: int) -> List[Dict[str, str]]:
    """The tasks of a recording: {"line": «Кто: что (срок: …)» as the protocol lists them, "what": the task alone}."""
    from app import commitments

    out = []
    for t in commitments.for_meetings([meeting_id]):
        what = str(t.get("what") or "").strip()
        if t.get("status") == "deleted" or not what:
            continue
        who = (t.get("who") or "").strip()
        due = (t.get("due_date") or t.get("due") or "").strip()
        out.append({"line": (f"{who}: " if who else "") + what + (f" (срок: {due})" if due else ""), "what": what})
    return out


def task_lines(meeting_id: int) -> List[str]:
    return [x["line"] for x in task_items(meeting_id)]


def replace_section(md: str, key: str, lines: List[str]) -> str:
    """The protocol with one result section («Решения», «Открытые вопросы», «Следующие шаги») holding
    exactly these points; a protocol without that section gets it before «Обсуждение по темам»."""
    body = [f"- {x}" for x in lines] if lines else [_NONE_LINES[key]]
    src = (md or "").splitlines()
    start = next((i for i, line in enumerate(src) if _ANY_HEAD.match(line) and _RESULT_HEADS[key].match(line)), None)
    if start is not None:
        end = next((j for j in range(start + 1, len(src)) if _ANY_HEAD.match(src[j]) and not src[j].lstrip().startswith("###")),
                   len(src))
        new = src[:start + 1] + body + ([""] if end < len(src) else []) + src[end:]
        return "\n".join(new)
    block = [_HEADINGS[key]] + body + [""]
    topics = next((i for i, line in enumerate(src) if re.match(r"^\s{0,3}##\s+(Обсуждение|Discussion)", line, re.I)), None)
    if topics is None:
        return "\n".join(src + [""] + block).strip() + "\n"
    return "\n".join(src[:topics] + block + src[topics:])


def _norm(s: str) -> str:
    s = re.sub(r"\[\d{1,2}:\d{2}(?::\d{2})?\]|\(срок:[^)]*\)", " ", str(s or ""))
    return " ".join(re.sub(r"[^\w\s]", " ", s.casefold()).split())


def _stems(s: str) -> List[str]:
    return [w[:5] for w in _norm(s).split() if len(w) >= 3]


def _listed(what: str, points: List[str]) -> bool:
    """A task (its «what», without who and due date) already among the protocol's next steps, written there
    in other words perhaps («Ольга встретится с группой» for «встретиться с группой»)."""
    norm, stems = _norm(what), set(_stems(what))
    if not norm:
        return True
    for p in points:
        np = _norm(p)
        if norm in np or difflib.SequenceMatcher(a=norm, b=np).ratio() >= 0.6:
            return True
        if stems and len(stems & set(_stems(p))) >= max(2, round(0.7 * len(stems))):
            return True
    return False


def sync_next_steps(meeting_id: int) -> int:
    """The tasks missing from the protocol's «Следующие шаги» are added to it (none is taken away: a step
    the protocol has may be a team's or an organizer's). Returns how many were added."""
    from app.database import get_meeting, merge_summaries

    m = get_meeting(meeting_id) or {}
    proto = (m.get("summaries") or {}).get("protocol")
    if not isinstance(proto, str) or not proto.strip():
        return 0
    points = protocol_points(proto)["next"]
    missing = [x["line"] for x in task_items(meeting_id) if not _listed(x["what"], points)]
    if not missing:
        return 0
    merge_summaries(meeting_id, {"protocol": replace_section(proto, "next", points + missing)})
    try:
        from app.obsidian import refresh_if_exported

        refresh_if_exported(meeting_id)
    except Exception as e:
        print(f"[analysis_chain] obsidian: {e}", flush=True)
    return len(missing)


def run(meeting_id: int, model_name: Optional[str] = None, answer_lang: Optional[str] = None,
        find_tasks: bool = True, stage: Optional[Callable[[str], None]] = None,
        **summary_kwargs: Any) -> str:
    """The protocol made in steps (see above). The tasks are saved on the way; the protocol is returned
    for the caller to save, as a protocol made in one go would be."""
    from app import commitments
    from app.database import get_meeting, is_local_only
    from app.features import note_for as features_note_for
    from app.meeting_context import note_for_tasks
    from app.ollama_client import generate_meeting_summary

    say = stage or (lambda _text: None)
    m = get_meeting(meeting_id)
    if not m or not m.get("segments"):
        raise ValueError("Нет текста записи")
    common = dict(
        segments=m["segments"], speakers=m.get("speakers") or {}, model_name=model_name,
        answer_lang=answer_lang or m.get("language") or "ru", local_only=is_local_only(m),
        user_notes=m.get("user_notes") or "", mfu=m.get("mfu") or "", features_note=features_note_for(m),
    )
    try:  # who was there, their names written right
        from app.people import meeting_roster

        common["participants"] = meeting_roster(m)
    except Exception:
        pass
    common.update(summary_kwargs)

    say("Анализ по шагам: решения и открытые вопросы...")
    decisions_md = generate_meeting_summary(template_key="decisions", **common)
    found = protocol_points(decisions_md)

    if find_tasks:
        say("Анализ по шагам: задачи...")
        try:  # without the tasks the protocol is still made (its next steps: the tasks found before)
            commitments.extract(meeting_id, model_name, hints=note_for_tasks({}, protocol_md=decisions_md))
        except Exception as e:
            print(f"[analysis_chain] tasks of meeting {meeting_id}: {e}", flush=True)
    tasks = task_lines(meeting_id)

    say("Анализ по шагам: протокол...")
    given = []
    for key in ("decisions", "open"):
        if found[key]:
            given.append(f"{_HEADINGS[key][3:]}:\n" + "\n".join(f"- {x}" for x in found[key]))
    if tasks:
        given.append("Следующие шаги (найденные задачи):\n" + "\n".join(f"- {x}" for x in tasks))
    note = ("Решения, открытые вопросы и задачи этой встречи уже найдены по той же расшифровке и проверены. "
            "Разделы «Решения», «Открытые вопросы» и «Следующие шаги» программа заполнит сама — в них "
            "перенеси только то, что ниже, без новых пунктов. Твоя главная работа — «Краткое содержание» "
            "(согласованное с этими итогами) и «Обсуждение по темам».\n\n" + "\n\n".join(given)) if given else ""
    protocol = generate_meeting_summary(template_key="protocol", context_note=note, **common)
    protocol = replace_section(protocol, "decisions", found["decisions"])
    protocol = replace_section(protocol, "open", found["open"])
    return replace_section(protocol, "next", tasks)
