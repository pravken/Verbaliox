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


def build(period: str = "week", feature_id: Optional[int] = None, today: Optional[date] = None) -> Dict[str, Any]:
    from app import commitments
    from app.database import list_meetings
    from app.features import decisions_of, feature_map, list_features
    from app.people import canonical, my_names
    from app.voice_profiles import is_default_name

    period = period if period in PERIODS else "week"
    today = today or date.today()
    start, end, prev = _bounds(period, today)
    fmap = feature_map()
    meetings = [m for m in list_meetings() if _day(m) and m.get("status") not in ("failed", "cancelled")]
    if feature_id:
        meetings = [m for m in meetings if feature_id in fmap.get(m["id"], [])]
    now = [m for m in meetings if start <= _day(m) < end]
    before = [m for m in meetings if prev <= _day(m) < start]

    tasks = commitments.all_tasks()
    if feature_id:
        tasks = [t for t in tasks if feature_id in fmap.get(t["meeting_id"], [])]
    iso = today.isoformat()
    me = set(my_names())
    is_mine = lambda t: (t.get("who") or "").strip().lower() in me  # noqa: E731
    mine = [t for t in tasks if t.get("status") != "done" and is_mine(t)] if me else []
    over = [t for t in mine if t.get("due_date") and t["due_date"] < iso]

    # the decisions of the period's analyses, newest first
    decisions: List[Dict[str, Any]] = []
    for m in sorted(now, key=lambda x: str(x.get("recorded_at") or x.get("created_at") or ""), reverse=True):
        try:
            from app.database import get_meeting

            full = get_meeting(m["id"]) or {}
        except Exception:
            continue
        for text in decisions_of((full.get("summaries") or {}).get("protocol") or ""):
            decisions.append({"text": text, "meeting_id": m["id"], "title": m.get("title") or "", "date": _day(m).isoformat()})

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
    all_meetings = meetings if not feature_id else [m for m in list_meetings() if _day(m)]
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
                "decision_meetings": len({d["meeting_id"] for d in decisions})},
        "buckets": buckets, "features": feats, "people": people,
        "decisions": decisions[:12], "tasks": [task_brief(t) for t in focus[:10]], "needs_me": not me,
        "recent": [{"id": m["id"], "title": m.get("title") or "", "date": _day(m).isoformat(), "duration": m.get("duration") or 0,
                    "status": m.get("status"), "has_summary": bool(m.get("has_summary")), "features": fmap.get(m["id"], [])}
                   for m in recent],
    }
