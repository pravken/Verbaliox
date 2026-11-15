"""
One context for every analysis of a recording: what its other tabs already found goes into the request of
the next one, so the protocol, the tasks, the short summary and the follow-up email tell the same story.

- for a summary (any tab): the tasks found in this recording (who, what, due);
- for a tab other than the protocol: the protocol's «Решения», «Открытые вопросы» and «Следующие шаги»;
- for the tasks (commitments.extract): the protocol's decisions and next steps, as hints to check against
  the transcript like the organizer's MFU — a decision that is an action becomes a task.

Without a protocol or tasks yet the note is empty and nothing changes.
"""

import re
from typing import Any, Dict, List

CONTEXT_MAX_CHARS = 3000
TASKS_MAX = 30

_ANY_HEAD = re.compile(r"^\s{0,3}(#{1,6}\s|\*\*[^*]+\*\*:?\s*$)")
_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*\S)")
# The protocol's sections that are its result (app/ollama_client.SUMMARY_TEMPLATES["protocol"])
_RESULT_HEADS = {
    "decisions": re.compile(r"^\s{0,3}(#{1,6}\s*|\*\*).*(решени|договор|decision|agreed)", re.I),
    "open": re.compile(r"^\s{0,3}(#{1,6}\s*|\*\*).*(открыт\w* вопрос|нерешён|open question|unresolved)", re.I),
    "next": re.compile(r"^\s{0,3}(#{1,6}\s*|\*\*).*(следующ\w* шаг|next step|action item)", re.I),
}
_LABELS = {"decisions": "Решения", "open": "Открытые вопросы", "next": "Следующие шаги"}


def protocol_points(protocol_md: str) -> Dict[str, List[str]]:
    """The points of the protocol's result sections: {"decisions": [...], "open": [...], "next": [...]}."""
    out: Dict[str, List[str]] = {k: [] for k in _RESULT_HEADS}
    inside = None
    for line in str(protocol_md or "").splitlines():
        if _ANY_HEAD.match(line):
            inside = next((k for k, rx in _RESULT_HEADS.items() if rx.match(line)), None)
            continue
        m = _BULLET.match(line) if inside else None
        if m:
            out[inside].append(m.group(1).strip())
    return out


def _protocol_note(meeting: Dict[str, Any], keys=("decisions", "open", "next")) -> str:
    points = protocol_points(((meeting.get("summaries") or {}).get("protocol")) or "")
    parts = [f"{_LABELS[k]}:\n" + "\n".join(f"- {p}" for p in points[k][:15]) for k in keys if points[k]]
    return "\n".join(parts)


def _tasks_note(meeting_id: int) -> str:
    try:
        from app import commitments

        tasks = [t for t in commitments.for_meetings([meeting_id]) if t.get("status") != "deleted"][:TASKS_MAX]
    except Exception:
        return ""
    lines = []
    for t in tasks:
        who = (t.get("who") or "").strip() or "не назначено"
        due = (t.get("due_date") or t.get("due") or "").strip()
        lines.append(f"- {who}: {t.get('what') or ''}" + (f" (срок: {due})" if due else ""))
    return "\n".join(lines)


def note_for_summary(meeting: Dict[str, Any], template_key: str) -> str:
    """What the other tabs found, for a summary of this recording ('' when nothing yet)."""
    if not meeting or template_key == "chapters":  # the chapters follow the clock, not the result
        return ""
    parts = []
    tasks = _tasks_note(int(meeting.get("id") or 0)) if meeting.get("id") else ""
    if tasks:
        parts.append("Задачи, уже найденные в этой встрече (сверяй с ними «Следующие шаги» и поручения; "
                     "не придумывай других):\n" + tasks)
    if template_key != "protocol":
        proto = _protocol_note(meeting)
        if proto:
            parts.append("Протокол этой встречи (по той же расшифровке) отметил:\n" + proto)
    return "\n\n".join(parts)[:CONTEXT_MAX_CHARS]


def note_for_tasks(meeting: Dict[str, Any], protocol_md: str = "") -> str:
    """The protocol's decisions and next steps, as hints for finding the tasks ('' without a protocol).
    protocol_md: another text with those sections (the decisions of the analysis in steps, app/analysis_chain)."""
    source = {"summaries": {"protocol": protocol_md}} if protocol_md else meeting
    proto = _protocol_note(source, keys=("decisions", "next"))
    if not proto:
        return ""
    # Said as an addition: a list read as «the tasks are these» narrowed the search to it (bench-report/analysis-chain.md)
    return ("Сначала найди задачи по всей расшифровке, как обычно: список ниже их не заменяет и не ограничивает. "
            "Затем проверь и его: протокол этой встречи (составлен по той же расшифровке) отметил решения и "
            "следующие шаги. Если из пункта следует конкретное действие, которое кто-то должен сделать, и его ещё "
            "нет среди найденных, выпиши его задачей — только если оно действительно прозвучало в расшифровке, с "
            "цитатой из неё:\n" + proto)[:CONTEXT_MAX_CHARS]
