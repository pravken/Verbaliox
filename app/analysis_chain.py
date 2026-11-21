"""
The analysis of a recording in steps, so its parts cannot disagree (Настройки → ИИ-анализ → «Анализ по шагам»,
on by default since the measurement in bench-report/analysis-chain.md):

1. the decisions and the open questions, read from the transcript alone;
2. the tasks (commitments.extract), read from the whole transcript (the decisions as hints narrowed the search);
3. the protocol, told both; its «Решения», «Открытые вопросы» and «Следующие шаги» are then written from
   steps 1 and 2 by the program, not by the model, so they are the same lists word for word.

The program writes those sections only in a Russian or English protocol (the headings it knows); in another
language the model's sections stay. Without the setting the analysis is as before, and in both cases
`sync_next_steps` adds a task found later to the end of the protocol's «Следующие шаги».
"""

import difflib
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.meeting_context import _RESULT_HEADS

_WORDS = {
    "ru": {"decisions": ("## Решения", "Решений не принималось"),
           "open": ("## Открытые вопросы", "Открытых вопросов нет"),
           "next": ("## Следующие шаги", "Следующие шаги не назывались"),
           "due": "срок", "next_given": "Следующие шаги (найденные задачи)"},
    "en": {"decisions": ("## Decisions", "No decisions were made"),
           "open": ("## Open questions", "No open questions"),
           "next": ("## Next steps", "No next steps were named"),
           "due": "due", "next_given": "Next steps (the tasks found)"},
}
_HEADINGS = {k: v[0] for k, v in _WORDS["ru"].items() if isinstance(v, tuple)}  # tools/llm_bench.py reads it


def _lang(answer_lang: Optional[str]) -> Optional[str]:
    """"ru" or "en" when the program knows that protocol's headings; None for another language the protocol
    is asked in (German, Ukrainian...). "auto" or an unknown code: Russian, as the prompts are."""
    from app.ollama_client import _LANG_PHRASES

    base = str(answer_lang or "ru").split("-")[0].lower()
    if base in _WORDS:
        return base
    return None if base in _LANG_PHRASES else "ru"


def enabled(settings: Optional[Dict[str, str]] = None) -> bool:
    if settings is None:
        from app.database import get_all_settings

        settings = get_all_settings()
    return (settings.get("analysis_chain") or "true").lower() == "true"


def task_items(meeting_id: int, answer_lang: Optional[str] = None) -> List[Dict[str, str]]:
    """The tasks of a recording: {"line": «Кто: что (срок: …)» as the protocol lists them, "what": the task alone}."""
    from app import commitments

    due_word = _WORDS[_lang(answer_lang) or "ru"]["due"]
    out = []
    for t in commitments.for_meetings([meeting_id]):
        what = str(t.get("what") or "").strip()
        if t.get("status") == "deleted" or not what:
            continue
        who = (t.get("who") or "").strip()
        due = (t.get("due_date") or t.get("due") or "").strip()
        out.append({"line": (f"{who}: " if who else "") + what + (f" ({due_word}: {due})" if due else ""), "what": what})
    return out


def task_lines(meeting_id: int, answer_lang: Optional[str] = None) -> List[str]:
    return [x["line"] for x in task_items(meeting_id, answer_lang)]


# A section's own heading: «## …» or a bold line; not the title «# …», not a topic's «### …»
_SECTION_HEAD = re.compile(r"^\s{0,3}(##\s|\*\*[^*]+\*\*:?\s*$)")
_TOP_HEAD = re.compile(r"^\s{0,3}(#{1,2}\s|\*\*[^*]+\*\*:?\s*$)")
_SUB_HEAD = re.compile(r"^\s{0,3}#{3,6}\s")
_LEVEL12 = re.compile(r"^\s{0,3}#{1,2}\s")
_POINT = re.compile(r"^(\s*)(?:[-*+]|\d+[.)])\s+(.*\S)")


def _section_bounds(src: List[str], key: str) -> Optional[Tuple[int, int]]:
    """(heading line, end) of a result section. A «### Решение проблемы с кэшем» topic is not it, nor a bold
    line under such a topic, nor the title «# Протокол: решение по договору» (each was taken for it, and
    what followed was replaced: found by the audits). The section ends at the next «#»/«##» heading (or, for
    a bold heading, the next bold one); «###» and bold lines inside it («### Ольга») stay in it."""
    under_topic = False
    for i, line in enumerate(src):
        if _SUB_HEAD.match(line):
            under_topic = True
            continue
        if _LEVEL12.match(line):
            under_topic = False
        if not _SECTION_HEAD.match(line) or under_topic or not _RESULT_HEADS[key].match(line):
            continue
        bold = line.lstrip().startswith("**")
        end = next((j for j in range(i + 1, len(src)) if _LEVEL12.match(src[j]) or (bold and _TOP_HEAD.match(src[j]))),
                   len(src))
        return i, end
    return None


def section_points(md: str, key: str) -> List[str]:
    """The top-level points of a result section, its «###» or bold sub-headings read through («## Решения /
    **Бюджет** / - Утвердили» was read as no decision: found by an audit)."""
    src = (md or "").splitlines()
    found = _section_bounds(src, key)
    if not found:
        return []
    out = []
    for line in src[found[0] + 1:found[1]]:
        m = _POINT.match(line)
        if m and len(m.group(1).replace("\t", "    ")) < 2:
            out.append(m.group(2).strip())
    return out


def _section_text(md: str, key: str) -> str:
    src = (md or "").splitlines()
    found = _section_bounds(src, key)
    return "\n".join(src[found[0] + 1:found[1]]) if found else ""


def _insert_section(src: List[str], key: str, body: List[str], lang: str) -> str:
    block = [_WORDS[lang][key][0]] + body + [""]
    topics = next((i for i, line in enumerate(src) if re.match(r"^\s{0,3}##\s+(Обсуждение|Discussion)", line, re.I)), None)
    if topics is None:
        return "\n".join(src + [""] + block).strip() + "\n"
    return "\n".join(src[:topics] + block + src[topics:])


def replace_section(md: str, key: str, lines: List[str], lang: str = "ru") -> str:
    """The protocol with one result section («Решения», «Открытые вопросы», «Следующие шаги») holding
    exactly these points; a protocol without that section gets it before «Обсуждение по темам»."""
    lang = _lang(lang) or "ru"
    body = [f"- {x}" for x in lines] if lines else [_WORDS[lang][key][1]]
    src = (md or "").splitlines()
    found = _section_bounds(src, key)
    if found is None:
        return _insert_section(src, key, body, lang)
    start, end = found
    return "\n".join(src[:start + 1] + body + ([""] if end < len(src) else []) + src[end:])


_NONE_RE = re.compile(r"не\s+принимал|не\s+назывались|вопросов\s+нет|\bнет\b|\bnone\b|\bno\s+(decisions|open|next)", re.I)


def _says_none(text: str) -> bool:
    return bool(_NONE_RE.search(str(text or "")))


def append_to_section(md: str, key: str, lines: List[str]) -> str:
    """The protocol with these points added at the end of a result section; what the section had (prose,
    nested points, «### Ольга», a hand edit) stays as it is. A section that only said «none» gets the points
    instead. A protocol without that section (another language, a hand edit) is left as it is: a Russian
    section was put into a German protocol (found by an audit)."""
    if not lines:
        return md
    src = (md or "").splitlines()
    found = _section_bounds(src, key)
    if found is None:
        return md
    start, end = found
    points = [f"- {x}" for x in lines]
    inside = [x for x in src[start + 1:end] if x.strip()]
    if len(inside) == 1 and not _POINT.match(inside[0]) and _says_none(inside[0]):
        return "\n".join(src[:start + 1] + points + [x for x in src[start + 1:end] if not x.strip()] + src[end:])
    last = max((j for j in range(start, end) if src[j].strip()), default=start)
    return "\n".join(src[:last + 1] + points + src[last + 1:])


def _norm(s: str) -> str:
    s = re.sub(r"\[\d{1,2}:\d{2}(?::\d{2})?\]|\((?:срок|due):[^)]*\)", " ", str(s or ""))
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
        if not np:
            continue
        if norm in np or difflib.SequenceMatcher(a=norm, b=np).ratio() >= 0.6:
            return True
        if stems and len(stems & set(_stems(p))) >= max(2, round(0.7 * len(stems))):
            return True
    return False


def sync_next_steps(meeting_id: int) -> int:
    """The tasks missing from the protocol's «Следующие шаги» are added at its end (none is taken away and
    the rest stays as written: a step may be a team's or an organizer's, a line may be the user's own).
    Returns how many were added."""
    from app.database import change_summaries, get_meeting

    m = get_meeting(meeting_id) or {}
    items = task_items(meeting_id, m.get("language"))
    added: List[str] = []

    def change(summaries: Dict[str, Any]) -> Dict[str, Any]:
        proto = summaries.get("protocol")
        if not isinstance(proto, str) or not proto.strip():
            return {}
        # every line of the section, not only its top points: a step under «### Ольга» counts
        lines = [ln for ln in _section_text(proto, "next").splitlines() if ln.strip()]
        missing = [x["line"] for x in items if not _listed(x["what"], lines)]
        new = append_to_section(proto, "next", missing)
        if new == proto:
            return {}
        added.extend(missing)
        return {"protocol": new}

    change_summaries(meeting_id, change)  # read and written under one lock: a hand edit saved meanwhile stays
    if not added:
        return 0
    try:
        from app.obsidian import refresh_if_exported

        refresh_if_exported(meeting_id)
    except Exception as e:
        print(f"[analysis_chain] obsidian: {e}", flush=True)
    return len(added)


def run(meeting_id: int, model_name: Optional[str] = None, answer_lang: Optional[str] = None,
        find_tasks: bool = True, stage: Optional[Callable[[str], None]] = None,
        **summary_kwargs: Any) -> str:
    """The protocol made in steps (see above). The tasks are saved on the way; the protocol is returned
    for the caller to save, already checked against the transcript (the caller does not check it again)."""
    from app import commitments
    from app.database import get_meeting
    from app.features import note_for as features_note_for
    from app.grounding import maybe_ground
    from app.ollama_client import generate_meeting_summary

    say = stage or (lambda _text: None)
    m = get_meeting(meeting_id)
    if not m or not m.get("segments"):
        raise ValueError("Нет текста записи")
    answer_lang = answer_lang or m.get("language") or "ru"
    lang = _lang(answer_lang)
    common = dict(
        segments=m["segments"], speakers=m.get("speakers") or {}, model_name=model_name,
        answer_lang=answer_lang,
        user_notes=m.get("user_notes") or "", mfu=m.get("mfu") or "", features_note=features_note_for(m),
        part_notes={},  # a long recording's parts are read once for both requests, not twice
    )
    try:  # who was there, their names written right
        from app.people import meeting_roster

        common["participants"] = meeting_roster(m)
    except Exception:
        pass
    common.update(summary_kwargs)

    say("Анализ по шагам: решения и открытые вопросы...")
    # checked against the transcript like the protocol: its points go into the protocol after that check
    decisions_md = maybe_ground(generate_meeting_summary(template_key="decisions", **common), "protocol", m)
    found = {key: section_points(decisions_md, key) for key in ("decisions", "open")}

    tasks_found = False
    if find_tasks:
        say("Анализ по шагам: задачи...")
        try:  # without the tasks the protocol is still made (its next steps: the tasks found before)
            # No hints: the decisions given as hints narrowed the search to them (recall 0.20 against 0.39
            # without, bench-report/analysis-chain.md, «Перемер после правок»)
            commitments.extract(meeting_id, model_name)
            tasks_found = True
        except Exception as e:
            print(f"[analysis_chain] tasks of meeting {meeting_id}: {e}", flush=True)
    tasks = task_lines(meeting_id, answer_lang)

    say("Анализ по шагам: протокол...")
    words = _WORDS[lang or "ru"]
    given = []
    for key in ("decisions", "open"):
        if found[key]:
            given.append(f"{words[key][0][3:]}:\n" + "\n".join(f"- {x}" for x in found[key]))
    if tasks:
        given.append(f"{words['next_given']}:\n" + "\n".join(f"- {x}" for x in tasks))
    fill = ("Разделы «Решения», «Открытые вопросы» и «Следующие шаги» программа заполнит сама — в них перенеси "
            "только то, что ниже, без новых пунктов. ") if lang else "Перенеси их в соответствующие разделы без новых пунктов. "
    note = ("Решения, открытые вопросы и задачи этой встречи уже найдены по той же расшифровке и проверены. " + fill
            + "Твоя главная работа — «Краткое содержание» (согласованное с этими итогами) и «Обсуждение по темам».\n\n"
            + "\n\n".join(given)) if given else ""
    protocol = generate_meeting_summary(template_key="protocol", context_note=note, **common)
    # The model's text is checked against the transcript here, before the program's lists go in: a task
    # written in Russian in an English protocol was marked «[?]» (bench-report/analysis-chain.md)
    protocol = maybe_ground(protocol, "protocol", m)
    if not lang:  # headings the program does not know: the model's sections stay (found by an audit)
        return protocol
    # A list the program knows replaces the model's; «none» only when step 1 said so (its answer in another
    # form would otherwise blank the model's decisions), and the next steps only from a search that ran
    # (with the task search off, or failed, the model's own steps stay: found by the audits)
    for key in ("decisions", "open"):
        if found[key] or _says_none(_section_text(decisions_md, key)):
            protocol = replace_section(protocol, key, found[key], lang)
    if tasks or tasks_found:
        protocol = replace_section(protocol, "next", tasks, lang)
    return protocol
