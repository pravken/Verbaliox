"""
The dashboard (the «Дэшборд» tab): what the library holds for a period, for its widgets in one request.

`build(period, feature_id)` gives the week (Monday to Sunday), the month or the quarter around today,
the period before it for comparison, and optionally only the recordings and tasks of one feature:
the numbers of the period, the meeting hours by day (week) or by week (month, quarter), every feature
with its meetings, tasks and the last eight weeks, the people met most, the decisions of the analyses,
the user's open tasks and the latest recordings. The week's calendar comes from /api/calendar/range.

Only the user's own tasks are counted and shown (asked by the user: the others' tasks are kept on the
Tasks page as they were found, not tracked here). Whose they are comes from «Это я» (my_name); without it
`needs_me` asks the page to have it set.
"""

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

PERIODS = ("week", "month", "quarter")
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


def _outcomes(ids: List[int], me: set) -> Dict[int, Dict[str, Any]]:
    """What _facts needs of each recording, in one reading: the protocol of its analysis, its series, and
    with «Это я» set the talk of each speaker (start, end and text of its lines, without their words).
    get_meeting for each meeting of a quarter read whole transcripts with every word, its versions and
    translations: seconds for a large library."""
    from app.database import _db_lock, _list_speakers, _loads_dict, _num, get_connection

    out: Dict[int, Dict[str, Any]] = {}
    with _db_lock:
        conn = get_connection()
        try:
            for i in range(0, len(ids), 500):  # SQLite's limit on the number of parameters
                part = ids[i:i + 500]
                marks = ",".join("?" * len(part))
                for r in conn.execute(f"SELECT id, series_id, speakers_json, summaries_json FROM meetings WHERE id IN ({marks})", part):
                    out[r["id"]] = {"series_id": r["series_id"], "protocol": _loads_dict(r["summaries_json"]).get("protocol") or "",
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


def _dull_series(meetings: List[Dict[str, Any]], me: set, fmap: Dict[int, List[int]]) -> List[Dict[str, Any]]:
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
        rows = [r for r in _meeting_rows(last, me, fmap) if r["analysed"]]
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
    if period == "month":
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


def build(period: str = "week", feature_id: Optional[int] = None, today: Optional[date] = None) -> Dict[str, Any]:
    from app import commitments
    from app.database import fill_durations, list_meetings
    from app.features import decisions_of, feature_map, list_features
    from app.people import canonical, my_names
    from app.voice_profiles import is_default_name

    period = period if period in PERIODS else "week"
    today = today or date.today()
    start, end, prev = _bounds(period, today)
    fmap = feature_map()
    library = list_meetings()
    meetings = [m for m in library if _counted(m)]
    if feature_id:
        meetings = [m for m in meetings if feature_id in fmap.get(m["id"], [])]
    now = [m for m in meetings if start <= _day(m) < end]
    before = [m for m in meetings if prev <= _day(m) < start]
    fill_durations(now + before)

    tasks = commitments.all_tasks()
    if feature_id:
        tasks = [t for t in tasks if feature_id in fmap.get(t["meeting_id"], [])]
    iso = today.isoformat()
    me = set(my_names())
    is_mine = lambda t: (t.get("who") or "").strip().lower() in me  # noqa: E731
    mine = [t for t in tasks if t.get("status") != "done" and is_mine(t)] if me else []
    over = [t for t in mine if t.get("due_date") and t["due_date"] < iso]

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

    # hours by day (a week) or by week (a month, a quarter)
    buckets: List[Dict[str, Any]] = []
    if period == "week":
        for i in range(7):
            d = start + timedelta(days=i)
            ms = [m for m in now if _day(m) == d]
            if i < 5 or ms:  # the weekend only when something was recorded on it
                buckets.append({"key": d.isoformat(), "kind": "day", "hours": round(sum(float(m.get("duration") or 0) for m in ms) / 3600, 2),
                                "meetings": [{"id": m["id"], "title": m.get("title") or ""} for m in ms]})
    else:
        w = start - timedelta(days=start.weekday())
        while w < end:
            ms = [m for m in now if w <= _day(m) < w + timedelta(days=7)]
            buckets.append({"key": max(w, start).isoformat(), "kind": "week", "hours": round(sum(float(m.get("duration") or 0) for m in ms) / 3600, 2),
                            "meetings": [{"id": m["id"], "title": m.get("title") or ""} for m in ms][:12]})
            w += timedelta(days=7)

    # every feature: its meetings of the period, its open tasks, the last eight weeks, its last meeting
    week0 = today - timedelta(days=today.weekday())
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

    # the people met most in the period, with the open tasks on them
    met: Dict[str, Dict[str, Any]] = {}
    try:
        from app.people import _rows

        rows = _rows()
    except Exception:
        rows = []
    for m in now:
        seen = set()
        for sp in (m.get("speakers") or {}).values():
            n = (sp or {}).get("name") if isinstance(sp, dict) else ""
            if not n or is_default_name(n):
                continue
            n = canonical(n, rows)
            if n.lower() in seen or n.lower() in me:
                continue
            seen.add(n.lower())
            e = met.setdefault(n.lower(), {"name": n, "color": (sp or {}).get("color") or "", "meetings": 0})
            e["meetings"] += 1
    people = sorted(met.values(), key=lambda x: (-x["meetings"], x["name"].lower()))[:8]

    def task_brief(t: Dict[str, Any]) -> Dict[str, Any]:
        return {"id": t["id"], "what": t.get("what") or "", "who": t.get("who") or "", "due_date": t.get("due_date") or "",
                "meeting_id": t.get("meeting_id") or 0, "meeting_title": t.get("meeting_title") or "",
                "features": fmap.get(t.get("meeting_id") or 0, [])}

    focus = sorted(mine, key=lambda t: (not (t.get("due_date") and t["due_date"] < iso), t.get("due_date") or "9999", t["id"]))
    recent = sorted(meetings, key=lambda x: str(x.get("recorded_at") or x.get("created_at") or ""), reverse=True)[:8]
    return {
        "period": period, "start": start.isoformat(), "end": end.isoformat(), "today": iso, "feature": feature_id,
        "kpi": {"meetings": len(now), "meetings_before": len(before),
                "hours": round(sum(float(m.get("duration") or 0) for m in now) / 3600, 1),
                "hours_before": round(sum(float(m.get("duration") or 0) for m in before) / 3600, 1),
                "open": len(mine), "overdue": len(over), "decisions": len(decisions),
                "decision_meetings": len({d["meeting_id"] for d in decisions}),
                "useless": len(useless), "useless_hours": round(sum(r["duration"] for r in useless) / 3600, 1),
                "waiting": len(waiting), "waiting_overdue": sum(1 for t in waiting if t.get("due_date") and t["due_date"] < iso)},
        "waiting": [dict(task_brief(t), days=_days_open(t, today)) for t in sorted(
            waiting, key=lambda t: (not (t.get("due_date") and t["due_date"] < iso), t.get("due_date") or "9999", t["id"]))[:8]],
        "buckets": buckets, "features": feats, "people": people,
        "decisions": decisions[:12], "tasks": [task_brief(t) for t in focus[:10]], "needs_me": not me,
        "dull_series": _dull_series(meetings, me, fmap),
        "recent": [{"id": m["id"], "title": m.get("title") or "", "date": _day(m).isoformat(), "duration": m.get("duration") or 0,
                    "status": m.get("status"), "has_summary": bool(m.get("has_summary")), "features": fmap.get(m["id"], [])}
                   for m in recent],
    }


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
           today: Optional[date] = None) -> Dict[str, Any]:
    """What a widget of the dashboard holds in full (asked by the user: a number could not be opened):
    meetings (each with its decisions, tasks, the user's share of the talk, «без итогов» reasons), useless
    (only those), decisions (all of the period), tasks (the user's, open and done), waiting (promised to
    the user), person (the meetings with someone and the tasks between them)."""
    from app import commitments
    from app.database import fill_durations, list_meetings
    from app.features import feature_map
    from app.people import canonical, my_names

    kind = kind if kind in DETAILS else "meetings"
    period = period if period in PERIODS else "week"
    today = today or date.today()
    start, end, _prev = _bounds(period, today)
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
        out["by_feature"] = [{"feature": k, "hours": round(v / 3600, 1)} for k, v in sorted(by_feature.items(), key=lambda kv: -kv[1])]
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
    # a person: every meeting they spoke in (any period), the tasks on them and theirs to the user
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
