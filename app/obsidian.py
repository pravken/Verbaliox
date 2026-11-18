"""
Notes in an Obsidian vault: one Markdown file per recording with YAML properties, the overview,
tasks, chapters and the transcript (each part can be switched off in the settings).

The file is named by a template, "{date} {title}" by default, where the date is when the meeting
took place (the file date of an imported recording). The note's path is remembered, so a later
export (after renaming, a new summary) updates the same note, and a new title renames it instead of
leaving a copy behind. Exports run automatically after processing when "obsidian_auto" is on.
"""

import re

from app.grounding import readable_summaries
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.audio_utils import format_timestamp

_INVALID = re.compile(r'[\\/:*?"<>|\x00-\x1f#^\[\]]')
_lock = threading.Lock()

_LABELS = {
    "ru": {"summary": "Резюме", "overview": "Обзор", "tasks": "Задачи", "chapters": "Главы", "transcript": "Расшифровка",
           "participants": "Участники", "untitled": "Запись", "notes": "Заметки со встречи", "promises": "Задачи по людям",
           "contents": "Содержание", "people": "Участники"},
    "en": {"summary": "Summary", "overview": "Overview", "tasks": "Tasks", "chapters": "Chapters", "transcript": "Transcript",
           "participants": "Participants", "untitled": "Recording", "notes": "Notes from the meeting", "promises": "Tasks by person",
           "contents": "Contents", "people": "Participants"},
}

# Every other section the analysis can make, under its own heading, in this order; the user's templates
# (tpl:<id>) by their names, then anything else that is there (asked by the user: the note has all of it)
_MORE = {
    "ru": {"decisions": "Решения", "followup": "Письмо после встречи", "notes": "Конспект", "since_last": "С прошлой встречи",
           "custom": "Ответ на вопрос", "mfu": "Что важно"},
    "en": {"decisions": "Decisions", "followup": "Follow-up email", "notes": "Notes", "since_last": "Since the last meeting",
           "custom": "Answer", "mfu": "What matters"},
}
_SHOWN_ELSEWHERE = {"tldr", "protocol", "tasks", "chapters", "error"}

# The name of each section's marks (asked by the user: «read only the tasks», an agent finds them by this name,
# listed in the note's properties); the same in every language, never translated
# «notes» (the synopsis) would read like the mark of the user's own notes, <!-- verbaliox:notes -->
_SECTION_IDS = {"followup": "followup_email", "custom": "answer", "mfu": "what_matters", "notes": "synopsis"}


def section_id(key: str) -> str:
    """tpl:12 → template_12, followup → followup_email; letters, digits and «_» only."""
    key = _SECTION_IDS.get(key, key)
    return re.sub(r"[^a-z0-9_]+", "_", key.replace("tpl:", "template_").lower()).strip("_") or "section"


_STATS = {
    "ru": {"line": "Говорили {talk} из {dur} · тишина {silence}% · реплик {turns}, в среднем {avg}",
           "cols": ("Участник", "Время", "Доля", "", "Реплик", "Слов/мин", "Вопросов", "Перебивал"),
           "mono": "Самые длинные монологи", "inter": "Кто кого перебивал"},
    "en": {"line": "Talk {talk} of {dur} · silence {silence}% · {turns} turns, {avg} on average",
           "cols": ("Participant", "Time", "Share", "", "Turns", "Words/min", "Questions", "Interrupted"),
           "mono": "Longest monologues", "inter": "Who interrupted whom"},
}


def _duration(sec: float) -> str:
    sec = int(round(sec or 0))
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}" if sec >= 3600 else f"{sec // 60}:{sec % 60:02d}"


def _talk_stats(m: Dict[str, Any], lang: str, link) -> List[str]:
    """The «Участники» page of the app as text (asked by the user): who spoke how long, a bar of their share,
    turns, pace, questions, interruptions; the longest monologues link to their place in the transcript."""
    from app.analytics import conversation_analytics

    a = conversation_analytics(m)
    if not a["speakers"]:
        return []
    T = _STATS[lang]
    out = [T["line"].format(talk=_duration(a["talk_seconds"]), dur=_duration(a["duration"]), silence=str(a["silence_share"]).replace(".", ","),
                            turns=a["turns"], avg=_duration(a["avg_turn"])), ""]
    out += ["| " + " | ".join(T["cols"]) + " |", "|" + "---|" * len(T["cols"])]
    for r in a["speakers"]:
        cells = round(r["share"] / 5)
        bar = "█" * cells + "░" * (20 - cells)
        out.append(f"| {r['name']} | {_duration(r['seconds'])} | {str(r['share']).replace('.', ',')}% | `{bar}` | {r['turns']} | "
                   f"{r['wpm'] if r['wpm'] is not None else '—'} | {r['questions']} | {r['interruptions']} |")
    out.append("")
    if a["longest_monologues"]:
        out += [f"**{T['mono']}:**", ""]
        out += [f"- {link(x['start'])} {x['name']} — {_duration(x['seconds'])}" for x in a["longest_monologues"]]
        out.append("")
    segs = sorted(m.get("segments") or [], key=lambda x: float(x.get("start") or 0))
    names = {k: (v or {}).get("name") or k for k, v in (m.get("speakers") or {}).items()}
    pairs: Dict[tuple, int] = {}
    for prev, cur in zip(segs, segs[1:]):
        if prev.get("speaker") != cur.get("speaker") and float(cur.get("start") or 0) < float(prev.get("end") or 0) - 0.2:
            key = (names.get(cur.get("speaker"), cur.get("speaker")), names.get(prev.get("speaker"), prev.get("speaker")))
            pairs[key] = pairs.get(key, 0) + 1
    if pairs:
        out += [f"**{T['inter']}:**", ""]
        out += [f"- {a_} → {b_}: {n}" for (a_, b_), n in sorted(pairs.items(), key=lambda kv: -kv[1])[:6]]
        out.append("")
    return out


def _more_sections(summaries: Dict[str, Any], lang: str) -> List[tuple]:
    """[(key, heading, markdown)] of the sections of the analysis besides the overview, tasks and chapters."""
    try:
        from app.database import summary_templates

        names = {f"tpl:{t['id']}": t["name"] for t in summary_templates()}
    except Exception:
        names = {}
    labels = _MORE[lang]
    keys = [k for k in summaries if k not in _SHOWN_ELSEWHERE and not str(k).startswith("_")
            and isinstance(summaries[k], str) and summaries[k].strip()]
    order = list(labels) + sorted(k for k in keys if k.startswith("tpl:"))
    keys.sort(key=lambda k: (order.index(k) if k in order else len(order), k))
    return [(k, labels.get(k) or names.get(k) or (k[4:] if k.startswith("tpl:") else k), summaries[k]) for k in keys]


def _settings() -> Dict[str, str]:
    from app.database import get_all_settings

    return get_all_settings()


def _on(settings: Dict[str, str], key: str, default: str = "true") -> bool:
    return (settings.get(key) or default).lower() == "true"


def meeting_datetime(m: Dict[str, Any]) -> datetime:
    for raw in (m.get("recorded_at"), m.get("created_at")):
        try:
            return datetime.strptime(str(raw or "")[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    return datetime.now()


def safe_filename(name: str, limit: int = 150) -> str:
    """A file name Windows, macOS and Obsidian links all accept."""
    name = _INVALID.sub(" ", name or "")
    name = re.sub(r"\s+", " ", name).strip().strip(".")
    if re.fullmatch(r"(?i)(con|prn|aux|nul|com\d|lpt\d)", name):
        name = f"_{name}"
    return name[:limit].rstrip(" .") or "note"


def feature_names(m: Dict[str, Any]) -> List[str]:
    """The names of the features the recording is about, its first one first."""
    ids = m.get("features")
    if ids is None and m.get("id"):
        try:
            from app.features import feature_map

            ids = feature_map([int(m["id"])]).get(int(m["id"]), [])
        except Exception:
            ids = []
    if not ids:
        return []
    try:
        from app.features import list_features

        by_id = {f["id"]: f["name"] for f in list_features()}
    except Exception:
        return []
    return [by_id[i] for i in ids if by_id.get(i)]


def note_filename(m: Dict[str, Any], template: str = "") -> str:
    dt = meeting_datetime(m)
    template = (template or "{date} {title}").strip() or "{date} {title}"
    feature = (feature_names(m) or [""])[0] if "{feature}" in template else ""
    if not feature:  # no feature: «{feature} — » goes with its dash, not only the word
        template = re.sub(r"\{feature\}\s*[-–—_.,:]*\s*", "", template)
    name = (
        template.replace("{date}", dt.strftime("%Y-%m-%d"))
        .replace("{time}", dt.strftime("%H-%M"))
        .replace("{title}", m.get("title") or "")
        .replace("{lang}", (m.get("language") or "").upper())
        .replace("{feature}", feature)
    )
    # a recording without a feature: «{feature} — {title}» must not start with a dash
    name = re.sub(r"^[\s\-–—_.,]+|[\s\-–—_.,]+$", "", name)
    return safe_filename(name) + ".md"


def feature_tag(name: str) -> str:
    """An Obsidian tag of a feature: no spaces or signs a tag cannot hold («Туманы на картах» → «Туманы-на-картах»)."""
    tag = re.sub(r"[^\w/-]+", "-", name.strip(), flags=re.UNICODE).strip("-/")
    return tag if tag and not tag.isdigit() else ""


def _yaml_str(value: Any) -> str:
    s = str(value if value is not None else "")
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'


def _demote(md: str, levels: int = 1) -> str:
    """Headings of a summary sit below the note's own '## ' sections."""
    out = []
    in_code = False
    for line in (md or "").splitlines():
        if line.lstrip().startswith("```"):
            in_code = not in_code
        if not in_code and re.match(r"^#{1,5}\s", line):
            line = "#" * levels + line
        out.append(line)
    return "\n".join(out).strip()


# The parts of a note for a program that reads many of them (asked by the user: an agent reads the analysis
# and leaves the transcript out): HTML comments, not shown by Obsidian. Each section has its own pair too,
# <!-- verbaliox:<id>:start --> … <!-- verbaliox:<id>:end -->, its id listed in the properties (section_mark)
ANALYSIS_START, ANALYSIS_END = "<!-- verbaliox:analysis:start -->", "<!-- verbaliox:analysis:end -->"
TRANSCRIPT_START, TRANSCRIPT_END = "<!-- verbaliox:transcript:start -->", "<!-- verbaliox:transcript:end -->"


def build_note(m: Dict[str, Any], settings: Optional[Dict[str, str]] = None) -> str:
    settings = settings or _settings()
    lang = "en" if (m.get("language") or "") == "en" else "ru"
    L = _LABELS[lang]
    dt = meeting_datetime(m)
    speakers = m.get("speakers") or {}
    segments = m.get("segments") or []
    summaries = readable_summaries(m)
    names = [s.get("name") or k for k, s in speakers.items()]
    features = feature_names(m)

    props = [
        "---",
        f"title: {_yaml_str(m.get('title') or L['untitled'])}",
        f"date: {dt.strftime('%Y-%m-%d')}",
        f"time: {_yaml_str(dt.strftime('%H:%M'))}",
        f"duration: {_yaml_str(format_timestamp(m.get('duration') or 0.0))}",
        f"language: {_yaml_str(m.get('language') or '')}",
        "participants:",
        *[f"  - {_yaml_str(n)}" for n in names],
        f"source: {_yaml_str(m.get('filename') or '')}",
        *(["features:", *[f"  - {_yaml_str(f)}" for f in features]] if features else []),
        "tags:",
        "  - verbaliox",
        "  - meeting",
        *[f"  - {_yaml_str(t)}" for t in dict.fromkeys(feature_tag(f) for f in features) if t],
        f"verbaliox_id: {int(m.get('id') or 0)}",
        "---",
        "",
        f"# {m.get('title') or L['untitled']}",
        "",
    ]
    if names:
        props += [f"**{L['participants']}:** " + ", ".join(names), ""]
    body: List[str] = []
    headings: List[str] = []
    with_text = _on(settings, "obsidian_transcript") and bool(segments)
    starts = [float(seg.get("start") or 0.0) for seg in segments]
    anchors: Dict[int, str] = {}  # the transcript's lines a chapter or a moment of the analysis points to

    sections: List[tuple] = []  # (id, heading) in the order of the note

    def add(to: List[str], sid: str, title: str, *lines: str) -> None:
        """A section between its marks; its heading goes into the contents (Obsidian takes [[#heading]];
        these signs would break the link)."""
        title = re.sub(r"[\[\]|#^]+", " ", title).strip() or "—"
        if any(s == sid for s, _ in sections):
            sid = f"{sid}_{len(sections) + 1}"
        headings.append(title)
        sections.append((sid, title))
        to += [f"<!-- verbaliox:{sid}:start -->", f"## {title}", "", *lines, f"<!-- verbaliox:{sid}:end -->", ""]

    def moments(md: str) -> str:
        """«[00:18]» or «00:18» of a chapter, «[12:34]» in the analysis: a link to that line of the transcript
        (asked by the user: from a chapter straight to the text). Only with the transcript in the note."""
        if not with_text:
            return md

        def link(mt: "re.Match") -> str:
            parts = [int(x) for x in mt.group(2).split(":")]
            sec = parts[0] * 3600 + parts[1] * 60 + parts[2] if len(parts) == 3 else parts[0] * 60 + parts[1]
            i = max(0, next((k for k, st in enumerate(starts) if st > sec + 0.5), len(starts)) - 1)
            anchors[i] = f"t{i}"
            return f"{mt.group(1)}[[#^t{i}|{mt.group(2)}]]"
        return re.sub(r"(^|[\s(\[])\[?(\d{1,2}:\d{2}(?::\d{2})?)\]?(?=[\s).,;:]|$)", link, md, flags=re.M)

    if (m.get("user_notes") or "").strip():
        add(body, "meeting_notes", L["notes"], m["user_notes"].strip(), "")
    if _on(settings, "obsidian_summary"):
        if summaries.get("tldr"):
            add(body, "summary", L["summary"], moments(_demote(summaries["tldr"])), "")
        if summaries.get("protocol"):
            add(body, "overview", L["overview"], moments(_demote(summaries["protocol"])), "")
    try:
        from app import commitments

        promised = commitments.for_meetings([int(m["id"])]) if m.get("id") else []
    except Exception:
        promised = []
    if promised:
        add(body, "tasks_by_person", L["promises"], commitments.export_text(promised, "md").strip(), "")
    if _on(settings, "obsidian_tasks") and summaries.get("tasks"):
        add(body, "tasks", L["tasks"], _tasks_as_checklist(_demote(summaries["tasks"])), "")
    if _on(settings, "obsidian_chapters") and summaries.get("chapters"):
        add(body, "chapters", L["chapters"], moments(_demote(summaries["chapters"])), "")
    if _on(settings, "obsidian_stats") and segments:
        def at(sec: float) -> str:  # a moment of the transcript, a link to its line when the transcript is there
            stamp = format_timestamp(sec)
            return moments(f"[{stamp}]") if with_text else f"`{stamp}`"
        stats = _talk_stats(m, lang, at)
        if stats:
            add(body, "participants", L["people"], *stats)
    if _on(settings, "obsidian_more"):  # the decisions, the letter, the notes, the user's templates, the answers
        for key, heading, md in _more_sections(summaries, lang):
            add(body, section_id(key), heading, moments(_demote(md)), "")
    if body:
        body = [ANALYSIS_START, "", *body, ANALYSIS_END, ""]
    if with_text:
        lines: List[str] = []
        for i, seg in enumerate(segments):
            spk = speakers.get(seg.get("speaker") or "", {}).get("name") or seg.get("speaker") or ""
            mark = f" ^{anchors[i]}" if i in anchors else ""  # a block id: a chapter's link lands on this line
            lines += [f"**{spk}** `{format_timestamp(seg.get('start') or 0.0)}` {(seg.get('text') or '').strip()}{mark}", ""]
        add(body, "transcript", L["transcript"], *lines)
    if sections:
        # the list of the marks for a program or an agent (asked by the user: «read only the tasks»): each
        # section is between <!-- verbaliox:<id>:start --> and <!-- verbaliox:<id>:end -->; the comments
        # themselves are not written here, so splitting the note on a mark finds it once
        props[props.index("---", 1):props.index("---", 1)] = [
            "section_mark: \"each section is between the HTML comments verbaliox:<id>:start and verbaliox:<id>:end; "
            "all the analysis between verbaliox:analysis:start and verbaliox:analysis:end; "
            "the user's own notes after verbaliox:notes to the end\"",
            "sections:",
            *[f"  - {_yaml_str(f'{sid}: {title}')}" for sid, title in sections],
        ]
    if len(headings) > 1:  # the note's contents: a click goes to the section (the transcript included)
        props += [f"**{L['contents']}:** " + " · ".join(f"[[#{h}]]" for h in headings), ""]
    return "\n".join(props + body).rstrip() + "\n"


def _tasks_as_checklist(md: str) -> str:
    """'- do X' lines become Obsidian tasks ('- [ ] do X'), so they show up in task queries."""
    return "\n".join(re.sub(r"^(\s*)[-*]\s+(?!\[[ xX]\])", r"\1- [ ] ", ln) for ln in md.splitlines())


def vault_dir(settings: Optional[Dict[str, str]] = None) -> Optional[Path]:
    settings = settings or _settings()
    vault = (settings.get("obsidian_vault") or "").strip()
    if not vault:
        return None
    sub = (settings.get("obsidian_subfolder") or "").strip().strip("\\/")
    parts = [safe_filename(p, 80) for p in re.split(r"[\\/]+", sub) if p.strip()] if sub else []
    return Path(vault).expanduser().joinpath(*parts)


def _prepare(meeting_id: int, generate: bool, settings: Dict[str, str]) -> Dict[str, Any]:
    """Makes what the note needs and is missing: a title from the content, the overview and tasks."""
    from app.database import get_meeting, save_meeting_results

    m = get_meeting(meeting_id) or {}
    if not generate or not m.get("segments"):
        return m
    from app.database import is_local_only
    from app.ollama_client import generate_meeting_summary

    summaries = dict(m.get("summaries") or {})
    changed = False
    wanted = ["protocol"] if _on(settings, "obsidian_summary") else []
    if _on(settings, "obsidian_tasks"):
        wanted.append("tasks")
    for key in wanted:
        if summaries.get(key):
            continue
        try:
            from app.grounding import maybe_ground
            from app.features import note_for as features_note_for
            from app.people import meeting_roster
            from app.meeting_context import note_for_summary as meeting_context_note

            summaries[key] = maybe_ground(generate_meeting_summary(
                segments=m["segments"], speakers=m.get("speakers") or {}, template_key=key,
                answer_lang=m.get("language") or "ru",
                local_only=is_local_only(m), user_notes=m.get("user_notes") or "", mfu=m.get("mfu") or "", features_note=features_note_for(m),
                context_note=meeting_context_note({**m, "summaries": summaries}, key),
                participants=meeting_roster(m),
            ), key, m)
            changed = True
        except Exception as e:
            print(f"[obsidian] {key} for meeting {meeting_id} failed: {e}", flush=True)
            break  # Ollama is not available: the note is written with what there is
    if changed:
        from app.database import merge_summaries

        merge_summaries(meeting_id, {k: summaries[k] for k in wanted if summaries.get(k)})
        m = get_meeting(meeting_id) or m
    return m


def export_meeting(meeting_id: int, generate: bool = False, in_job: bool = False, explicit: bool = True) -> Path:
    """Writes (or updates) the note of a recording; returns its path. `in_job`: called by the
    transcription job itself, when the transcript is saved but the status is not "completed" yet."""
    from app.database import get_meeting, update_meeting_fields

    settings = _settings()
    folder = vault_dir(settings)
    if folder is None:
        raise ValueError("Папка хранилища Obsidian не выбрана в настройках")
    with _lock:
        m = _prepare(meeting_id, generate and _on(settings, "obsidian_generate"), settings)
        if not m:
            raise LookupError("Встреча не найдена")
        if (m.get("status") != "completed" and not in_job) or not m.get("segments"):
            raise ValueError("Запись ещё не расшифрована")
        if _on(settings, "obsidian_feature_folders"):
            # a folder per feature (asked by the user): the notes of one feature together, its first one
            feature = (feature_names(m) or [""])[0]
            if feature:
                folder = folder / safe_filename(feature, 80)
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / note_filename(m, settings.get("obsidian_filename") or "")
        old = Path(m.get("obsidian_path") or "")
        if old.name and old.is_file() and old.resolve() != target.resolve() and not target.exists():
            # The title (or the template) changed: move the note instead of leaving the old one
            old.replace(target)
        elif target.exists() and (not old.name or old.resolve() != target.resolve()) and not _is_ours(target, meeting_id):
            # Another note already has this name: never overwrite it
            target = _unique(target)
        existing = target.read_text(encoding="utf-8", errors="replace") if target.is_file() else ""
        ours, notes = split_user_notes(existing)
        if in_job is False and not explicit and existing and m.get("obsidian_hash") and _hash(ours) != m["obsidian_hash"]:
            # Changed in Obsidian above the user's section: an automatic update must not undo that
            print(f"[obsidian] {target.name} was edited in Obsidian: not updated automatically", flush=True)
            return target
        body = build_note(m, settings).rstrip() + "\n"
        target.write_text(body + "\n" + (notes or _notes_section(m)), encoding="utf-8")
        update_meeting_fields(meeting_id, obsidian_path=str(target), obsidian_hash=_hash(body))
        return target


# The end of every note belongs to the user: Verbaliox rewrites what is above this heading and
# keeps everything from it on (tasks ticked, own notes)
NOTES_MARKER = "<!-- verbaliox:notes -->"
FORMER_NOTES_MARKER = "<!-- verbascribe:notes -->"  # notes written while the program was called VerbaScribe


def _notes_section(m: Dict[str, Any]) -> str:
    head = "## My notes" if (m.get("language") or "") == "en" else "## Мои заметки"
    return f"{NOTES_MARKER}\n{head}\n\n"


def split_user_notes(text: str) -> tuple:
    """(the part Verbaliox wrote, the user's section from the marker on, or "")."""
    i = text.find(NOTES_MARKER)
    if i < 0 and FORMER_NOTES_MARKER in text:
        text = text.replace(FORMER_NOTES_MARKER, NOTES_MARKER, 1)
        i = text.find(NOTES_MARKER)
    if i < 0:
        return text.rstrip() + "\n" if text else "", ""
    return text[:i].rstrip() + "\n", text[i:]


def _hash(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def _is_ours(path: Path, meeting_id: int) -> bool:
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:2000]
    except OSError:
        return False
    # verbascribe_id: a note written while the program had its former name
    return re.search(rf"^verba(?:liox|scribe)_id:\s*{int(meeting_id)}\s*$", head, re.MULTILINE) is not None


def _unique(path: Path) -> Path:
    for i in range(2, 1000):
        cand = path.with_name(f"{path.stem} ({i}){path.suffix}")
        if not cand.exists():
            return cand
    return path


def auto_export_enabled(settings: Optional[Dict[str, str]] = None) -> bool:
    settings = settings or _settings()
    return _on(settings, "obsidian_auto", "false") and bool((settings.get("obsidian_vault") or "").strip())


def refresh_if_exported(meeting_id: int) -> None:
    """After a rename or anything the analysis made: write the note in the background (auto-export on)."""
    from app.database import get_meeting

    m = get_meeting(meeting_id)
    # a recording whose note was never written gets it now (a section made later, a recording older than the
    # setting): with auto-export on, the note always has what the recording has (asked by the user)
    if not m or not auto_export_enabled() or m.get("status") != "completed" or not m.get("segments"):
        return

    def _run() -> None:
        try:
            export_meeting(meeting_id, generate=False, explicit=False)
        except Exception:
            traceback.print_exc()

    threading.Thread(target=_run, daemon=True, name="obsidian_refresh").start()


# --- Every recording at once: when auto-export is turned on, or on request («Сохранить все записи») ---
_all_state: Dict[str, Any] = {"active": False, "done": 0, "total": 0, "failed": 0}


def export_all_status() -> Dict[str, Any]:
    return dict(_all_state)


def export_all(missing_only: bool = False) -> Dict[str, Any]:
    """Writes the note of every transcribed recording in the background (the existing ones updated, the user's
    edits above their section kept: explicit=False). missing_only: only the recordings without a note yet."""
    from app.database import list_meetings

    if _all_state["active"]:
        return export_all_status()
    if vault_dir() is None:
        raise ValueError("Папка хранилища Obsidian не выбрана в настройках")
    ids = [m["id"] for m in list_meetings() if m.get("status") == "completed" and m.get("has_transcript")
           and not (missing_only and m.get("obsidian_path") and Path(m["obsidian_path"]).is_file())]
    _all_state.update(active=True, done=0, total=len(ids), failed=0)

    def run() -> None:
        try:
            for mid in ids:
                try:
                    export_meeting(mid, generate=False, explicit=False)
                except Exception as e:
                    _all_state["failed"] += 1
                    print(f"[obsidian] meeting {mid}: {e}", flush=True)
                _all_state["done"] += 1
            print(f"[obsidian] {_all_state['done'] - _all_state['failed']} of {len(ids)} note(s) written", flush=True)
        finally:
            _all_state["active"] = False

    threading.Thread(target=run, daemon=True, name="obsidian_export_all").start()
    return export_all_status()
