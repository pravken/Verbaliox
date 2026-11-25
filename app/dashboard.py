"""
The dashboard (the «Дэшборд» tab): what the library holds for a period, for its widgets in one request.

`build(period, feature_id)` gives the week (Monday to Sunday), the month, the quarter or the year around today
or around a past day (`at`: the page goes back period by period; a past period is complete), the period before
it or the same days a year earlier for comparison, and optionally only the recordings and tasks of one feature:
the numbers of the period, the meeting hours by day (week) or by week (month, quarter), every feature
with its meetings, tasks and the last eight weeks, the people met most, the decisions of the analyses,
the user's open tasks and the latest recordings. The week's calendar comes from /api/calendar/range.

Only the user's own tasks are counted and shown (asked by the user: the others' tasks are kept on the
Tasks page as they were found, not tracked here). Whose they are comes from «Это я» (my_name); without it
`needs_me` asks the page to have it set.
"""

import json
from datetime import date, datetime, time, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

PERIODS = ("week", "month", "quarter", "year")
# what the figures are compared with: the period before, or the same days a year earlier
COMPARE = ("prev", "year")
DETAILS = ("meetings", "useless", "decisions", "tasks", "waiting", "person")
# «Без итогов» (asked by the user): an analysed meeting this long with no decision and no task; one where
# the user said almost nothing; a series whose meetings of the period all ended so
NO_OUTCOME_MIN_SEC = 10 * 60
SILENT_SHARE = 5.0  # % of the talk
SILENT_MIN_SEC = 30 * 60
SERIES_MIN = 3
# «Серии без результатов» (asked by the user): a series whose last analysed meetings, this many at least in a row,
# gave no decision and no task, looked at among its last SERIES_LOOK meetings (whatever the period)
SERIES_LOOK = 6
# «Статистика»: each figure with its trend over this many periods (the current one last); for the year as many
# years as there are data, this many at most
HISTORY_N = 6


# «Время во встречах»: one rule for «Статистика» (its hours, the share of the working time and the time without
# meetings), the hours by day of «Время во встречах» and «Нагрузка недели» (static/js/dashboard.js dbDayHours).
# The time of a day taken by meetings, overlaps counted once: the recordings (from their start, for their
# length) and the calendar's meetings (not those of a whole day, not those the user said are no meeting, not a
# block of calendar_ics.BLOCK_HOURS or longer), of these only the part gone by. A recording made during a calendar
# meeting adds only what lies outside it. With a feature chosen only its recordings count: the calendar knows no
# features. Found in the audit: «Статистика» summed the recordings (three of a minute at once: «0,1 ч») while
# «Нагрузка недели» counted them once («0 ч»), side by side.
def _start_of(m: Dict[str, Any]) -> Optional[datetime]:
    """When a recording began, as local time without a zone (as /api/calendar/range gives it), or None."""
    raw = str(m.get("recorded_at") or m.get("created_at") or "")
    try:
        t = datetime.fromisoformat(raw.replace("Z", "+00:00")) if raw else None
    except ValueError:
        return None
    if t and t.tzinfo:
        t = t.astimezone().replace(tzinfo=None)
    return t


def _calendar_spans(a: date, b: date, today: date) -> List[Tuple[datetime, datetime]]:
    """The calendar's meetings of the days a…b (b exclusive) as (start, end), cut at the moment gone by: now for
    the current day, the end of `today` for a day counted as of the past. Empty without a calendar."""
    try:
        from app import calendar_ics
        from app.database import get_all_settings

        if not calendar_ics._source():
            return []
        try:
            ignored = json.loads(get_all_settings().get("meet_ignore") or "[]")
        except ValueError:
            ignored = []
        cut = datetime.now() if today >= date.today() else datetime.combine(today + timedelta(days=1), time())
        return [(e["start"], min(e["end"], cut))
                for e in calendar_ics.window(datetime.combine(a, time()), datetime.combine(b, time()))
                if e["start"] < cut and calendar_ics.is_meeting(e, ignored)]
    except Exception:  # an unreadable calendar leaves the recordings
        return []


def busy_days(meetings: List[Dict[str, Any]], a: date, b: date, today: date, calendar: bool = True) -> Dict[date, float]:
    """{day: seconds in meetings} of the days a…b (b exclusive), by the rule above."""
    spans: List[Tuple[datetime, datetime]] = []
    for m in meetings:
        s, dur = _start_of(m), float(m.get("duration") or 0)
        if s and dur > 0:
            spans.append((s, s + timedelta(seconds=dur)))
    if calendar:
        spans += _calendar_spans(a, b, today)
    by_day: Dict[date, List[Tuple[datetime, datetime]]] = {}
    for s, e in spans:
        if e > s and a <= s.date() < b:
            by_day.setdefault(s.date(), []).append((s, e))
    out: Dict[date, float] = {}
    for d, part in by_day.items():
        total, end = 0.0, None
        for s, e in sorted(part):
            if end is None or s > end:
                total, end = total + (e - s).total_seconds(), e
            elif e > end:
                total, end = total + (e - end).total_seconds(), e
        out[d] = total
    return out


def _hours(busy: Dict[date, float], a: date, b: date) -> float:
    """The hours in meetings of the days a…b (b exclusive), to the minute: the page writes less than 0,1 h in
    minutes («6 мин»), not «0,1 ч» or «0 ч»."""
    return round(sum(v for d, v in busy.items() if a <= d < b) / 3600, 2)


def _outcomes(ids: List[int], me: set) -> Dict[int, Dict[str, Any]]:
    """What _facts needs of each recording, in one reading: the protocol of its analysis, its series, and
    with «Это я» set the talk of each speaker (start, end and text of its lines, without their words).
    get_meeting for each meeting of a quarter read whole transcripts with every word, its versions and
    translations: seconds for a large library."""
    from app.database import _db_lock, _list_speakers, _num, get_connection
    from app.speaker_refs import resolve_raw

    out: Dict[int, Dict[str, Any]] = {}
    with _db_lock:
        conn = get_connection()
        try:
            for i in range(0, len(ids), 500):  # SQLite's limit on the number of parameters
                part = ids[i:i + 500]
                marks = ",".join("?" * len(part))
                for r in conn.execute(f"SELECT id, series_id, speakers_json, summaries_json FROM meetings WHERE id IN ({marks})", part):
                    out[r["id"]] = {"series_id": r["series_id"], "protocol": resolve_raw(r["summaries_json"], r["speakers_json"]).get("protocol") or "",
                                    "speakers": _list_speakers(r["id"], r["speakers_json"] or "{}") if me else {}, "lines": []}
                if not me:
                    continue
                for r in conn.execute(
                        "SELECT meeting_id, json_extract(data, '$.speaker') AS speaker, json_extract(data, '$.start') AS start, "
                        "json_extract(data, '$.end') AS end, json_extract(data, '$.text') AS text FROM segments "
                        f"WHERE meeting_id IN ({marks}) AND json_valid(data) ORDER BY meeting_id, pos", part):
                    if r["meeting_id"] in out:
                        out[r["meeting_id"]]["lines"].append(
                            {"speaker": r["speaker"], "start": _num(r["start"]), "end": _num(r["end"]), "text": r["text"]})
        finally:
            conn.close()
    return out


def _facts(m: Dict[str, Any], got: Dict[str, Any], me: set, task_counts: Dict[int, int]) -> Dict[str, Any]:
    """What a meeting gave: its decisions, its tasks, the user's share of the talk, and why it may be one
    «без итогов» (reasons: no_outcome, silent; series is added over the period). `m` is the row of the
    library list, `got` what _outcomes read of it."""
    from app.features import decisions_of

    protocol = got.get("protocol") or ""
    decisions = decisions_of(protocol)
    duration = float(m.get("duration") or 0)
    share = None
    if me and got.get("lines"):
        try:
            from app.analytics import conversation_analytics

            rows = conversation_analytics({"duration": duration, "segments": got["lines"],
                                           "speakers": got.get("speakers") or {}})["speakers"]
            if rows:
                share = round(sum(float(r["share"]) for r in rows if str(r.get("name") or "").strip().lower() in me), 1)
        except Exception:
            share = None
    reasons = []
    if protocol and duration >= NO_OUTCOME_MIN_SEC and not decisions and not task_counts.get(m.get("id") or 0):
        reasons.append("no_outcome")
    if share is not None and duration >= SILENT_MIN_SEC and share < SILENT_SHARE:
        reasons.append("silent")
    return {"decisions": decisions, "tasks": task_counts.get(m.get("id") or 0, 0), "my_share": share,
            "analysed": bool(protocol), "reasons": reasons}


def _series_reasons(rows: List[Dict[str, Any]]) -> None:
    """A series whose meetings of the period (three at least) all ended without a decision or a task."""
    by: Dict[int, List[Dict[str, Any]]] = {}
    for r in rows:
        if r.get("series_id"):
            by.setdefault(r["series_id"], []).append(r)
    for group in by.values():
        if len(group) >= SERIES_MIN and all("no_outcome" in r["reasons"] for r in group):
            for r in group:
                r["reasons"].append("series")


def _dull_series(meetings: List[Dict[str, Any]], fmap: Dict[int, List[int]]) -> List[Dict[str, Any]]:
    """The series giving nothing lately: their newest analysed meetings, SERIES_MIN or more in a row, ended
    without a decision or a task. Most such meetings first."""
    try:
        from app.series import list_series

        names = {s["id"]: s.get("name") or "" for s in list_series()}
    except Exception:
        names = {}
    by: Dict[int, List[Dict[str, Any]]] = {}
    for m in meetings:
        if m.get("series_id"):
            by.setdefault(m["series_id"], []).append(m)
    out = []
    for sid, group in by.items():
        if len(group) < SERIES_MIN:
            continue
        last = sorted(group, key=lambda x: str(x.get("recorded_at") or x.get("created_at") or ""), reverse=True)[:SERIES_LOOK]
        # without the user's share of the talk: only «no_outcome» counts here, and the share read every line of
        # these meetings (audit K21: half the time of the dashboard)
        rows = [r for r in _meeting_rows(last, set(), fmap) if r["analysed"]]
        streak = 0
        for r in rows:  # newest first
            if "no_outcome" not in r["reasons"]:
                break
            streak += 1
        if streak >= SERIES_MIN:
            out.append({"series_id": sid, "name": names.get(sid) or rows[0]["title"], "streak": streak,
                        "hours": round(sum(r["duration"] for r in rows[:streak]) / 3600, 1),
                        "last": {"id": rows[0]["id"], "title": rows[0]["title"], "date": rows[0]["date"]}})
    out.sort(key=lambda x: (-x["streak"], -x["hours"]))
    return out[:6]


def _bounds(period: str, today: date) -> Tuple[date, date, date]:
    """(start, end exclusive, start of the period before) of the period around today."""
    if period == "year":
        start = date(today.year, 1, 1)
        end = date(today.year + 1, 1, 1)
        prev = date(today.year - 1, 1, 1)
    elif period == "month":
        start = today.replace(day=1)
        end = (start + timedelta(days=32)).replace(day=1)
        prev = (start - timedelta(days=1)).replace(day=1)
    elif period == "quarter":
        q = (today.month - 1) // 3
        start = date(today.year, q * 3 + 1, 1)
        end = date(today.year + (q == 3), (q * 3 + 3) % 12 + 1, 1)
        prev = date(start.year - (q == 0), ((q - 1) % 4) * 3 + 1, 1)
    else:
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=7)
        prev = start - timedelta(days=7)
    return start, end, prev


def _periods_back(period: str, start: date, n: int = HISTORY_N) -> List[Tuple[date, date]]:
    """(start, end exclusive) of the n periods up to the current one (whose start is given), oldest first."""
    out = [(start, _bounds(period, start)[1])]
    while len(out) < n:
        s, e, _prev = _bounds(period, out[0][0] - timedelta(days=1))
        out.insert(0, (s, e))
    return out


def _year_ago(d: date) -> date:
    """The same day a year earlier (the 29th of February: the 28th)."""
    try:
        return d.replace(year=d.year - 1)
    except ValueError:
        return d.replace(year=d.year - 1, day=28)


def anchor(period: str, at: Optional[date], today: date) -> Tuple[date, date, date, date, bool]:
    """(start, end exclusive, start of the period before, the day «as of», past) of the period around `at`
    (today when none or later). A past period is complete: what counts the days gone by counts all of them
    (as of its last day); the current one goes up to today."""
    start, end, prev = _bounds(period, min(at or today, today))
    past = end <= today
    return start, end, prev, (end - timedelta(days=1)) if past else today, past


def _work_days(a: date, b: date, today: date, off: Dict[str, str]) -> int:
    """The working days (Monday to Friday, not a holiday or a day off) of a…b; the days after today are left out."""
    n, d = 0, a
    while d < b and d <= today:
        if d.weekday() < 5 and d.isoformat() not in off:
            n += 1
        d += timedelta(days=1)
    return n


def _protocols(ids: List[int]) -> Dict[int, str]:
    """The protocol of each recording's analysis, without reading anything else of it (the speakers named
    in it by their current names, app/speaker_refs)."""
    from app.database import _db_lock, _loads_dict, get_connection
    from app.speaker_refs import has_marks, resolve_text

    out: Dict[int, str] = {}
    if not ids:
        return out
    with _db_lock:
        conn = get_connection()
        try:
            for i in range(0, len(ids), 500):  # SQLite's limit on the number of parameters
                part = ids[i:i + 500]
                for r in conn.execute("SELECT id, CASE WHEN json_valid(summaries_json) THEN json_extract(summaries_json, '$.protocol') END, "
                                      f"speakers_json FROM meetings WHERE id IN ({','.join('?' * len(part))})", part):
                    text = r[1] if isinstance(r[1], str) else ""
                    out[r[0]] = resolve_text(text, _loads_dict(r[2])) if has_marks(text) else text
        finally:
            conn.close()
    return out


def _history(period: str, start: date, today: date, meetings: List[Dict[str, Any]], tasks: List[Dict[str, Any]],
             me: set, people_of: Callable[[Dict[str, Any]], set], calendar: bool = True) -> Dict[str, Any]:
    """«Статистика»: the figures (_figures) of the last HISTORY_N periods up to the one starting at `start`,
    oldest first; the years only from the first one with a recording or a task."""
    spans = _periods_back(period, start)
    first = _first_day(meetings, tasks)
    if period == "year":
        spans = [s for s in spans if first and s[1] > first] or spans[-1:]
    values = _figures(spans, today, meetings, tasks, me, people_of, first, calendar)
    return {"starts": [a.isoformat() for a, _e in spans], "norm": values.pop("_norm"), "values": values}


def _first_day(meetings: List[Dict[str, Any]], tasks: List[Dict[str, Any]]) -> Optional[date]:
    """The first day with a recording or a task (None with neither): the working time before it is unknown."""
    days = [d for d in (_day(m) for m in meetings) if d] + [
        date.fromisoformat(str(t.get("created_at"))[:10]) for t in tasks if _iso_day(t.get("created_at"))]
    return min(days) if days else None


def _iso_day(v: Any) -> bool:
    try:
        date.fromisoformat(str(v or "")[:10])
        return True
    except ValueError:
        return False


def _figures(spans: List[Tuple[date, date]], today: date, meetings: List[Dict[str, Any]], tasks: List[Dict[str, Any]],
             me: set, people_of: Callable[[Dict[str, Any]], set], first_day: Optional[date] = None,
             calendar: bool = True) -> Dict[str, Any]:
    """Every figure of each span (start, end exclusive), in their order, from what build has loaded
    already (the library list, the tasks) and the protocols of those meetings: no transcript is read.
    «Встречи без итогов» counts the analysed meetings with no decision and no task here; build puts the
    current period's figures (with the silent meetings and the series) in the last place.
    The hours in meetings follow the one rule of busy_days (overlaps once, the calendar's meetings with the
    recordings unless `calendar` is off). The share of the working time: the meeting hours of the working days
    against the norm of a day (the reminder's hours, 8 without it) times the working days gone by; the time without
    meetings is the rest.
    A span that ends before `first_day` (the first day with a recording or a task), or any span with no data
    at all, has neither: None, not 2088 hours «without meetings» of a year never recorded."""
    from app.database import fill_durations
    from app.features import decisions_of

    first, last = spans[0][0], spans[-1][1]
    inside = [m for m in meetings if first <= _day(m) < last]
    fill_durations(inside)
    busy = busy_days(inside, first, last, today, calendar)
    protocols = _protocols([m["id"] for m in inside])
    task_n: Dict[int, int] = {}
    for t in tasks:
        task_n[t.get("meeting_id") or 0] = task_n.get(t.get("meeting_id") or 0, 0) + 1
    try:
        from app import holidays_cal

        off = holidays_cal.between(first, last)
    except Exception:
        off = {}
    try:
        from app import worktime

        norm = worktime.remind_hours() or 8.0
    except Exception:
        norm = 8.0
    low = lambda v: (v or "").strip().lower()  # noqa: E731
    mine = [t for t in tasks if me and low(t.get("who")) in me]
    waiting = [t for t in tasks if me and low(t.get("to_whom")) in me and low(t.get("who")) not in me]

    values: Dict[str, List[float]] = {k: [] for k in ("meetings", "hours", "share", "focus", "mine", "closed", "waiting",
                                                       "decisions", "useless", "avg", "people")}
    for a, b in spans:
        ms = [m for m in inside if a <= _day(m) < b]
        sec = sum(float(m.get("duration") or 0) for m in ms)  # the recordings' own length: their average
        known = first_day is not None and b > first_day
        work_h = _work_days(a, b, today, off) * norm if known else 0.0
        on_work = sum(v for d, v in busy.items()
                      if a <= d < b and d.weekday() < 5 and d.isoformat() not in off and d <= today) / 3600
        decided = useless = 0
        names: set = set()
        for m in ms:
            p = protocols.get(m["id"]) or ""
            n = len(decisions_of(p)) if p else 0
            decided += n
            if p and float(m.get("duration") or 0) >= NO_OUTCOME_MIN_SEC and not n and not task_n.get(m["id"]):
                useless += 1
            names |= people_of(m)
        values["meetings"].append(len(ms))
        values["hours"].append(_hours(busy, a, b))
        values["share"].append((round(min(100.0, on_work / work_h * 100)) if work_h else 0) if known else None)
        values["focus"].append(round(max(0.0, work_h - on_work), 1) if known else None)
        values["mine"].append(sum(1 for t in mine if _open_at(t, b)))
        values["closed"].append(sum(1 for t in mine if t.get("status") == "done"
                                    and a.isoformat() <= str(t.get("done_at") or "")[:10] < b.isoformat()))
        values["waiting"].append(sum(1 for t in waiting if _open_at(t, b)))
        values["decisions"].append(decided)
        values["useless"].append(useless)
        values["avg"].append(round(sec / 60 / len(ms)) if ms else 0)
        values["people"].append(len(names))
    values["_norm"] = norm  # type: ignore[assignment]
    return values


class _Names:
    """The people of the meetings by their names in the people list (a name looked up once), the user left out."""

    def __init__(self, me: set):
        from app.people import canonical
        from app.voice_profiles import is_default_name

        try:
            from app.people import _rows

            self.rows = _rows()
        except Exception:
            self.rows = []
        self.me, self.known, self._canonical, self._default = me, {}, canonical, is_default_name

    def name_of(self, n: str) -> str:
        if n not in self.known:
            self.known[n] = self._canonical(n, self.rows)
        return self.known[n]

    def _speakers(self, m: Dict[str, Any]):
        for sp in (m.get("speakers") or {}).values():
            n = (sp or {}).get("name") if isinstance(sp, dict) else ""
            if n and not self._default(n) and self.name_of(n).lower() not in self.me:
                yield self.name_of(n), sp

    def people_of(self, m: Dict[str, Any]) -> set:
        return {n.lower() for n, _sp in self._speakers(m)}

    def most(self, meetings: List[Dict[str, Any]], n: int = 8) -> List[Dict[str, Any]]:
        """The people met most: their meetings together and the hours of those meetings."""
        met: Dict[str, Dict[str, Any]] = {}
        for m in meetings:
            seen = set()
            for name, sp in self._speakers(m):
                if name.lower() in seen:
                    continue
                seen.add(name.lower())
                e = met.setdefault(name.lower(), {"name": name, "color": (sp or {}).get("color") or "", "meetings": 0, "hours": 0.0})
                e["meetings"] += 1
                e["hours"] += float(m.get("duration") or 0) / 3600
        for e in met.values():
            e["hours"] = round(e["hours"], 2)  # to the minute: the page writes less than 0,1 h in minutes
        return sorted(met.values(), key=lambda x: (-x["meetings"], x["name"].lower()))[:n]


def people(start: date, end: date, feature_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """«Частые участники» of start…end (end not included): the widget has a period of its own."""
    from app.database import fill_durations, list_meetings
    from app.features import feature_map
    from app.people import my_names

    meetings = [m for m in list_meetings() if _counted(m) and start <= _day(m) < end]
    if feature_id:
        fmap = feature_map()
        meetings = [m for m in meetings if feature_id in fmap.get(m["id"], [])]
    fill_durations(meetings)
    return _Names(set(my_names())).most(meetings)


def _day(m: Dict[str, Any]) -> Optional[date]:
    raw = str(m.get("recorded_at") or m.get("created_at") or "")[:10]
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _counted(m: Dict[str, Any]) -> bool:
    """A recording that counts as a meeting: a failed one does not, one whose transcription was cancelled
    does (the meeting took place; it was left out, and its hours with it)."""
    return bool(_day(m)) and m.get("status") != "failed"


def build(period: str = "week", feature_id: Optional[int] = None, today: Optional[date] = None,
          at: Optional[date] = None, compare: str = "prev") -> Dict[str, Any]:
    """The widgets' data of the period around `at` (today when none). A past period is counted as of its last
    day (the working days, the user's open tasks at its end); the task lists stay those open now. `compare`:
    the figures against the period before («prev») or the same days a year earlier («year»)."""
    from app import commitments
    from app.database import fill_durations, list_meetings
    from app.features import decisions_of, feature_map, list_features
    from app.people import my_names

    period = period if period in PERIODS else "week"
    compare = compare if compare in COMPARE else "prev"
    today = today or date.today()
    start, end, prev, asof, past = anchor(period, at, today)
    # the span compared with: the period before, or the same days a year earlier
    cmp_a, cmp_b = (_year_ago(start), _year_ago(end)) if compare == "year" else (prev, start)
    fmap = feature_map()
    library = list_meetings()
    meetings = [m for m in library if _counted(m)]
    # the recordings of the period a feature filter leaves out: said under the figures (reported by the user:
    # «three meetings went by and the figures are zeros» — they had not the feature chosen)
    outside = 0
    if feature_id:
        outside = sum(1 for m in meetings if start <= _day(m) < end and feature_id not in fmap.get(m["id"], []))
        meetings = [m for m in meetings if feature_id in fmap.get(m["id"], [])]
    now = [m for m in meetings if start <= _day(m) < end]
    before = [m for m in meetings if cmp_a <= _day(m) < cmp_b]
    fill_durations(now + before)
    # the hours in meetings by one rule (busy_days): the calendar's meetings too, unless a feature is chosen
    cal = not feature_id
    busy, busy_before = busy_days(now, start, end, today, cal), busy_days(before, cmp_a, cmp_b, today, cal)
    hours = lambda a, b: _hours(busy, a, b)  # noqa: E731

    tasks = commitments.all_tasks()
    if feature_id:
        tasks = [t for t in tasks if feature_id in fmap.get(t["meeting_id"], [])]
    iso = today.isoformat()
    me = set(my_names())
    is_mine = lambda t: (t.get("who") or "").strip().lower() in me  # noqa: E731
    mine = [t for t in tasks if t.get("status") != "done" and is_mine(t)] if me else []
    over = [t for t in mine if t.get("due_date") and t["due_date"] < iso]
    # a past period: the user's tasks open at its end, overdue by its last day
    mine_then = [t for t in tasks if is_mine(t) and _open_at(t, end)] if me else []
    over_then = [t for t in mine_then if t.get("due_date") and t["due_date"] < asof.isoformat()]

    # the decisions of the period's analyses, newest first, and what each meeting gave (_facts)
    decisions: List[Dict[str, Any]] = []
    rows = _meeting_rows(now, me, fmap)
    for r in rows:
        for text in r.pop("decision_texts"):
            decisions.append({"text": text, "meeting_id": r["id"], "title": r["title"], "date": r["date"]})
    useless = [r for r in rows if r["reasons"]]
    # promised to the user by someone else, still open («Ожидаю от других»)
    waiting = [t for t in tasks if t.get("status") != "done" and (t.get("to_whom") or "").strip().lower() in me
               and not is_mine(t)] if me else []

    waiting_then = [t for t in tasks if _open_at(t, end) and (t.get("to_whom") or "").strip().lower() in me
                    and not is_mine(t)] if me else []

    # hours by day (a week), by week (a month, a quarter) or by month (a year)
    buckets: List[Dict[str, Any]] = []
    if period == "year":
        for k in range(12):
            a, b = date(start.year, k + 1, 1), date(start.year + (k == 11), (k + 1) % 12 + 1, 1)
            ms = [m for m in now if a <= _day(m) < b]
            buckets.append({"key": a.isoformat(), "kind": "month", "hours": hours(a, b),
                            "meetings": [{"id": m["id"], "title": m.get("title") or ""} for m in ms][:12]})
    elif period == "week":
        for i in range(7):
            d = start + timedelta(days=i)
            ms = [m for m in now if _day(m) == d]
            if i < 5 or ms or busy.get(d):  # the weekend only when something was recorded on it
                buckets.append({"key": d.isoformat(), "kind": "day", "hours": hours(d, d + timedelta(days=1)),
                                "meetings": [{"id": m["id"], "title": m.get("title") or ""} for m in ms]})
    else:
        w = start - timedelta(days=start.weekday())
        while w < end:
            ms = [m for m in now if w <= _day(m) < w + timedelta(days=7)]
            buckets.append({"key": max(w, start).isoformat(), "kind": "week", "hours": hours(max(w, start), min(w + timedelta(days=7), end)),
                            "meetings": [{"id": m["id"], "title": m.get("title") or ""} for m in ms][:12]})
            w += timedelta(days=7)

    # every feature: its meetings of the period, its open tasks, the last eight weeks, its last meeting
    week0 = asof - timedelta(days=asof.weekday())
    all_meetings = meetings if not feature_id else [m for m in library if _day(m)]
    feats = []
    all_tasks = commitments.all_tasks() if feature_id else tasks
    for f in list_features():
        if feature_id and f["id"] != feature_id:
            continue
        own = [m for m in all_meetings if f["id"] in fmap.get(m["id"], [])]
        if not own:
            continue
        own_tasks = [t for t in all_tasks if f["id"] in fmap.get(t["meeting_id"], []) and t.get("status") != "done"
                     and me and is_mine(t)]
        spark = []
        for k in range(7, -1, -1):
            a = week0 - timedelta(days=7 * k)
            spark.append(sum(1 for m in own if a <= _day(m) < a + timedelta(days=7)))
        last = max(own, key=lambda x: str(x.get("recorded_at") or x.get("created_at") or ""))
        feats.append({"id": f["id"], "name": f["name"], "color": f.get("color") or "",
                      "meetings": sum(1 for m in own if start <= _day(m) < end), "open": len(own_tasks),
                      "overdue": sum(1 for t in own_tasks if t.get("due_date") and t["due_date"] < iso),
                      "spark": spark, "last": {"id": last["id"], "title": last.get("title") or "", "date": _day(last).isoformat()}})
    feats.sort(key=lambda x: (-x["meetings"], -x["open"], x["name"].lower()))

    # the people met most in the period
    names = _Names(me)
    people = names.most(now)
    history = _history(period, start, asof, meetings, tasks, me, names.people_of, cal)
    hv = history["values"]  # the current period: as the widgets count it (a past one: its tasks open at its end)
    hv["meetings"][-1], hv["mine"][-1] = len(now), len(mine_then if past else mine)
    hv["waiting"][-1] = len(waiting_then if past else waiting)
    hv["hours"][-1] = hours(start, end)
    hv["decisions"][-1], hv["useless"][-1] = len(decisions), len(useless)
    # what each figure is compared with: the period before in the trend, or the same days a year earlier
    if compare == "year":
        got = _figures([(cmp_a, cmp_b)], _year_ago(asof), meetings, tasks, me, names.people_of, _first_day(meetings, tasks), cal)
        history["before"] = {k: v[0] for k, v in got.items() if k != "_norm"}
    else:
        history["before"] = {k: v[-2] for k, v in hv.items() if len(v) > 1}
        # the current period counts its working time up to today: the time without meetings is set against the same
        # days of the period before, not all of it («−16,1 ч к прошлой неделе» in red on a Wednesday: audit)
        if not past and history["before"].get("focus") is not None:
            same = _figures([(cmp_a, cmp_b)], cmp_a + (asof - start), meetings, tasks, me, names.people_of,
                            _first_day(meetings, tasks), cal)
            history["before"]["focus"] = same["focus"][0]
    history["compare"] = {"kind": compare, "start": cmp_a.isoformat(), "end": cmp_b.isoformat()}

    def task_brief(t: Dict[str, Any]) -> Dict[str, Any]:
        return {"id": t["id"], "what": t.get("what") or "", "who": t.get("who") or "", "due_date": t.get("due_date") or "",
                "meeting_id": t.get("meeting_id") or 0, "meeting_title": t.get("meeting_title") or "",
                "features": fmap.get(t.get("meeting_id") or 0, [])}

    focus = sorted(mine, key=lambda t: (not (t.get("due_date") and t["due_date"] < iso), t.get("due_date") or "9999", t["id"]))
    recent = sorted((m for m in meetings if _day(m) < end), key=lambda x: str(x.get("recorded_at") or x.get("created_at") or ""),
                    reverse=True)[:8]
    return {
        "period": period, "start": start.isoformat(), "end": end.isoformat(), "today": iso, "feature": feature_id,
        "past": past, "asof": asof.isoformat(), "compare": compare,
        "outside": outside,
        "kpi": {"meetings": len(now), "meetings_before": len(before),
                "hours": hours(start, end), "hours_before": _hours(busy_before, cmp_a, cmp_b),
                "open": len(mine_then if past else mine), "overdue": len(over_then if past else over), "decisions": len(decisions),
                "decision_meetings": len({d["meeting_id"] for d in decisions}),
                "useless": len(useless), "useless_hours": round(sum(r["duration"] for r in useless) / 3600, 1),
                "waiting": len(waiting_then if past else waiting),
                "waiting_overdue": sum(1 for t in (waiting_then if past else waiting) if t.get("due_date") and t["due_date"] < asof.isoformat())},
        "waiting": [dict(task_brief(t), days=_days_open(t, today)) for t in sorted(
            waiting, key=lambda t: (not (t.get("due_date") and t["due_date"] < iso), t.get("due_date") or "9999", t["id"]))[:8]],
        "history": history,
        "buckets": buckets, "features": feats, "people": people,
        "decisions": decisions[:12], "tasks": [task_brief(t) for t in focus[:10]], "needs_me": not me,
        "dull_series": _dull_series(meetings, fmap),
        "recent": [{"id": m["id"], "title": m.get("title") or "", "date": _day(m).isoformat(), "duration": m.get("duration") or 0,
                    "status": m.get("status"), "has_summary": bool(m.get("has_summary")), "features": fmap.get(m["id"], [])}
                   for m in recent],
    }


def _open_at(t: Dict[str, Any], end: date) -> bool:
    """A task open at the end of a period (made before it, not done by then)."""
    made, done = str(t.get("created_at") or "")[:10], str(t.get("done_at") or "")[:10]
    if made and made >= end.isoformat():
        return False
    return t.get("status") != "done" or (bool(done) and done >= end.isoformat())


def _days_open(t: Dict[str, Any], today: date) -> int:
    raw = str(t.get("meeting_date") or t.get("created_at") or "")[:10]
    try:
        return max(0, (today - date.fromisoformat(raw)).days)
    except ValueError:
        return 0


def _meeting_rows(meetings: List[Dict[str, Any]], me: set, fmap: Dict[int, List[int]]) -> List[Dict[str, Any]]:
    """Each meeting with what it gave (_facts), newest first; «decision_texts» for the caller to take."""
    from app import commitments

    counts: Dict[int, int] = {}
    for t in commitments.for_meetings([m["id"] for m in meetings]) if meetings else []:
        counts[t["meeting_id"]] = counts.get(t["meeting_id"], 0) + 1
    got = _outcomes([m["id"] for m in meetings], me) if meetings else {}
    rows = []
    for m in sorted(meetings, key=lambda x: str(x.get("recorded_at") or x.get("created_at") or ""), reverse=True):
        if m["id"] not in got:  # deleted meanwhile
            continue
        f = _facts(m, got[m["id"]], me, counts)
        rows.append({"id": m["id"], "title": m.get("title") or "", "date": _day(m).isoformat(),
                     "time": str(m.get("recorded_at") or "")[11:16], "duration": float(m.get("duration") or 0),
                     "features": fmap.get(m["id"], []), "series_id": got[m["id"]]["series_id"],
                     "decisions": len(f["decisions"]), "tasks": f["tasks"], "my_share": f["my_share"],
                     "analysed": f["analysed"], "reasons": f["reasons"], "decision_texts": f["decisions"]})
    _series_reasons(rows)
    return rows


def detail(kind: str, period: str = "week", feature_id: Optional[int] = None, person: str = "",
           today: Optional[date] = None, at: Optional[date] = None) -> Dict[str, Any]:
    """What a widget of the dashboard holds in full (asked by the user: a number could not be opened):
    meetings (each with its decisions, tasks, the user's share of the talk, «без итогов» reasons), useless
    (only those), decisions (all of the period), tasks (the user's, open and done), waiting (promised to
    the user), person (the meetings with someone and the tasks between them)."""
    from app import commitments
    from app.database import fill_durations, list_meetings
    from app.features import feature_map
    from app.people import _rows as directory_rows, canonical as canonical_of, my_names

    kind = kind if kind in DETAILS else "meetings"
    period = period if period in PERIODS else "week"
    today = today or date.today()
    start, end, _prev, _asof, _past = anchor(period, at, today)
    fmap = feature_map()
    me = set(my_names())
    meetings = [m for m in list_meetings() if _counted(m)]
    if feature_id:
        meetings = [m for m in meetings if feature_id in fmap.get(m["id"], [])]
    now = [m for m in meetings if start <= _day(m) < end]
    fill_durations(now)
    out: Dict[str, Any] = {"kind": kind, "period": period, "start": start.isoformat(), "end": end.isoformat(),
                           "feature": feature_id, "needs_me": not me}
    tasks = commitments.all_tasks()
    if feature_id:
        tasks = [t for t in tasks if feature_id in fmap.get(t["meeting_id"], [])]
    brief = lambda t: {"id": t["id"], "what": t.get("what") or "", "who": t.get("who") or "",  # noqa: E731
                       "to": t.get("to_whom") or "", "status": t.get("status") or "open", "due_date": t.get("due_date") or "",
                       "meeting_id": t.get("meeting_id") or 0, "meeting_title": t.get("meeting_title") or "",
                       "meeting_date": str(t.get("meeting_date") or "")[:10], "at": t.get("at"),
                       "features": fmap.get(t.get("meeting_id") or 0, []), "days": _days_open(t, today)}
    if kind in ("meetings", "useless", "decisions"):
        rows = _meeting_rows(now, me, fmap)
        if kind == "decisions":
            out["decisions"] = [{"text": d, "meeting_id": r["id"], "title": r["title"], "date": r["date"],
                                 "features": r["features"]} for r in rows for d in r["decision_texts"]]
            return out
        for r in rows:
            r.pop("decision_texts", None)
        if kind == "useless":
            rows = [r for r in rows if r["reasons"]]
        out["meetings"] = rows
        out["hours"] = round(sum(r["duration"] for r in rows) / 3600, 1)
        by_feature: Dict[int, float] = {}
        for r in rows:
            for fid in r["features"] or [0]:
                by_feature[fid] = by_feature.get(fid, 0.0) + r["duration"]
        out["by_feature"] = [{"feature": k, "hours": round(v / 3600, 2)} for k, v in sorted(by_feature.items(), key=lambda kv: -kv[1])]
        return out
    is_mine = lambda t: (t.get("who") or "").strip().lower() in me  # noqa: E731
    order = lambda t: (t.get("status") == "done", not (t.get("due_date") and t["due_date"] < today.isoformat()),  # noqa: E731
                       t.get("due_date") or "9999", t["id"])
    if kind == "tasks":
        out["tasks"] = [brief(t) for t in sorted((t for t in tasks if me and is_mine(t)), key=order)]
        return out
    if kind == "waiting":
        out["tasks"] = [brief(t) for t in sorted((t for t in tasks if me and t.get("status") != "done" and not is_mine(t)
                                                  and (t.get("to_whom") or "").strip().lower() in me), key=order)]
        return out
    # a person: every meeting they spoke in (any period), the tasks on them and theirs to the user. The directory is
    # read once (audit K21: canonical() read it, with two connections, for each speaker of each recording and each
    # task: 5 s for a library of 1200 recordings)
    rows_dir = directory_rows()
    canonical = lambda n: canonical_of(n, rows_dir)  # noqa: E731
    name = canonical(person.strip()) if person.strip() else ""
    out["person"] = name
    low = name.lower()
    seen = []
    for m in sorted(meetings, key=lambda x: str(x.get("recorded_at") or x.get("created_at") or ""), reverse=True):
        names = {canonical(str((sp or {}).get("name") or "")).lower() for sp in (m.get("speakers") or {}).values() if isinstance(sp, dict)}
        if low and low in names:
            seen.append({"id": m["id"], "title": m.get("title") or "", "date": _day(m).isoformat(), "duration": float(m.get("duration") or 0)})
    out["meetings"] = seen[:50]
    out["meetings_total"] = len(seen)
    out["owes_me"] = [brief(t) for t in sorted((t for t in tasks if t.get("status") != "done"
                                               and canonical((t.get("who") or "").strip()).lower() == low), key=order)]
    out["i_owe"] = [brief(t) for t in sorted((t for t in tasks if t.get("status") != "done" and is_mine(t)
                                             and canonical((t.get("to_whom") or "").strip()).lower() == low), key=order)]
    return out
