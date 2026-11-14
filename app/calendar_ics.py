"""
The user's calendar, read from an iCalendar file or link, or (source "outlook") from the classic
Outlook on this computer (app/calendar_outlook.py) (Outlook: "Publish calendar" / save as
.ics; Google Calendar: "Secret address in iCal format"; any CalDAV app's export). Read only, kept
on this computer; nothing is ever sent.

What it gives:
- a recording made during a meeting gets the meeting's title and its participants (in "My notes"),
- the upcoming meetings, with the brief before the meeting of their series.

A small parser on purpose (no dependency): events, folded lines, UTC / floating / TZID times
(TZID is read as local time when the zone is unknown), all-day events, and the common recurrence
rules (DAILY / WEEKLY / MONTHLY with INTERVAL, BYDAY, COUNT, UNTIL, EXDATE).
"""

import re
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

CACHE_SEC = 15 * 60
_cache: Dict[str, Any] = {"source": "", "at": 0.0, "events": [], "error": ""}
_lock = threading.Lock()
_fetch_lock = threading.Lock()
_DAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
MAX_BYTES = 5 * 2**20  # a calendar link that answers more than this is not read further
MAX_INTERVAL = 1000    # INTERVAL of a recurrence rule; larger (or not a number) means "repeats once"


def _unfold(text: str) -> List[str]:
    out: List[str] = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line[:1] in (" ", "\t") and out:
            out[-1] += line[1:]
        elif line:
            out.append(line)
    return out


def _unescape(v: str) -> str:
    return v.replace("\\n", "\n").replace("\\N", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


# Outlook names zones the Windows way («Russian Standard Time»); zoneinfo knows the IANA names only
# (from CLDR windowsZones, the zones people meet in)
WINDOWS_ZONES = {
    "dateline standard time": "Etc/GMT+12", "utc-11": "Etc/GMT+11", "hawaiian standard time": "Pacific/Honolulu",
    "alaskan standard time": "America/Anchorage", "pacific standard time": "America/Los_Angeles",
    "us mountain standard time": "America/Phoenix", "mountain standard time": "America/Denver",
    "central america standard time": "America/Guatemala", "central standard time": "America/Chicago",
    "central standard time (mexico)": "America/Mexico_City", "canada central standard time": "America/Regina",
    "sa pacific standard time": "America/Bogota", "eastern standard time": "America/New_York",
    "us eastern standard time": "America/Indianapolis", "venezuela standard time": "America/Caracas",
    "atlantic standard time": "America/Halifax", "sa western standard time": "America/La_Paz",
    "pacific sa standard time": "America/Santiago", "newfoundland standard time": "America/St_Johns",
    "e. south america standard time": "America/Sao_Paulo", "argentina standard time": "America/Buenos_Aires",
    "sa eastern standard time": "America/Cayenne", "greenland standard time": "America/Godthab",
    "montevideo standard time": "America/Montevideo", "utc-02": "Etc/GMT+2", "azores standard time": "Atlantic/Azores",
    "cape verde standard time": "Atlantic/Cape_Verde", "utc": "Etc/UTC", "coordinated universal time": "Etc/UTC",
    "gmt standard time": "Europe/London", "greenwich standard time": "Atlantic/Reykjavik",
    "morocco standard time": "Africa/Casablanca", "w. europe standard time": "Europe/Berlin",
    "central europe standard time": "Europe/Budapest", "romance standard time": "Europe/Paris",
    "central european standard time": "Europe/Warsaw", "w. central africa standard time": "Africa/Lagos",
    "jordan standard time": "Asia/Amman", "gtb standard time": "Europe/Bucharest",
    "middle east standard time": "Asia/Beirut", "egypt standard time": "Africa/Cairo",
    "e. europe standard time": "Europe/Chisinau", "syria standard time": "Asia/Damascus",
    "south africa standard time": "Africa/Johannesburg", "fle standard time": "Europe/Kiev",
    "israel standard time": "Asia/Jerusalem", "kaliningrad standard time": "Europe/Kaliningrad",
    "libya standard time": "Africa/Tripoli", "arabic standard time": "Asia/Baghdad",
    "turkey standard time": "Europe/Istanbul", "arab standard time": "Asia/Riyadh",
    "belarus standard time": "Europe/Minsk", "russian standard time": "Europe/Moscow",
    "e. africa standard time": "Africa/Nairobi", "volgograd standard time": "Europe/Volgograd",
    "iran standard time": "Asia/Tehran", "arabian standard time": "Asia/Dubai",
    "astrakhan standard time": "Europe/Astrakhan", "azerbaijan standard time": "Asia/Baku",
    "russia time zone 3": "Europe/Samara", "mauritius standard time": "Indian/Mauritius",
    "saratov standard time": "Europe/Saratov", "georgian standard time": "Asia/Tbilisi",
    "caucasus standard time": "Asia/Yerevan", "afghanistan standard time": "Asia/Kabul",
    "west asia standard time": "Asia/Tashkent", "ekaterinburg standard time": "Asia/Yekaterinburg",
    "pakistan standard time": "Asia/Karachi", "qyzylorda standard time": "Asia/Qyzylorda",
    "india standard time": "Asia/Calcutta", "sri lanka standard time": "Asia/Colombo",
    "nepal standard time": "Asia/Katmandu", "central asia standard time": "Asia/Almaty",
    "bangladesh standard time": "Asia/Dhaka", "omsk standard time": "Asia/Omsk",
    "myanmar standard time": "Asia/Rangoon", "se asia standard time": "Asia/Bangkok",
    "altai standard time": "Asia/Barnaul", "w. mongolia standard time": "Asia/Hovd",
    "north asia standard time": "Asia/Krasnoyarsk", "n. central asia standard time": "Asia/Novosibirsk",
    "tomsk standard time": "Asia/Tomsk", "china standard time": "Asia/Shanghai",
    "north asia east standard time": "Asia/Irkutsk", "singapore standard time": "Asia/Singapore",
    "w. australia standard time": "Australia/Perth", "taipei standard time": "Asia/Taipei",
    "ulaanbaatar standard time": "Asia/Ulaanbaatar", "transbaikal standard time": "Asia/Chita",
    "tokyo standard time": "Asia/Tokyo", "north korea standard time": "Asia/Pyongyang",
    "korea standard time": "Asia/Seoul", "yakutsk standard time": "Asia/Yakutsk",
    "cen. australia standard time": "Australia/Adelaide", "aus central standard time": "Australia/Darwin",
    "e. australia standard time": "Australia/Brisbane", "aus eastern standard time": "Australia/Sydney",
    "west pacific standard time": "Pacific/Port_Moresby", "tasmania standard time": "Australia/Hobart",
    "vladivostok standard time": "Asia/Vladivostok", "russia time zone 10": "Asia/Srednekolymsk",
    "magadan standard time": "Asia/Magadan", "sakhalin standard time": "Asia/Sakhalin",
    "central pacific standard time": "Pacific/Guadalcanal", "russia time zone 11": "Asia/Kamchatka",
    "new zealand standard time": "Pacific/Auckland", "utc+12": "Etc/GMT-12", "fiji standard time": "Pacific/Fiji",
    "tonga standard time": "Pacific/Tongatapu", "samoa standard time": "Pacific/Apia",
    "line islands standard time": "Pacific/Kiritimati",
}

# Zones described in the file itself (VTIMEZONE): their standard offset, for a name neither IANA nor
# Windows knows («Customized Time Zone» of Outlook). Filled by parse()
_FILE_ZONES: Dict[str, timedelta] = {}


def _zone(name: str):
    from zoneinfo import ZoneInfo

    name = name.strip().strip('"')
    try:
        return ZoneInfo(name)
    except Exception:
        pass
    iana = WINDOWS_ZONES.get(name.lower())
    if iana:
        try:
            return ZoneInfo(iana)
        except Exception:
            pass
    offset = _FILE_ZONES.get(name)
    return timezone(offset) if offset is not None else None


def _parse_dt(value: str, params: str) -> Optional[datetime]:
    """Local naive datetime of DTSTART/DTEND/EXDATE values."""
    v = value.strip()
    try:
        if "VALUE=DATE" in params.upper() or re.fullmatch(r"\d{8}", v):
            d = datetime.strptime(v[:8], "%Y%m%d")
            return d
        if v.endswith("Z"):
            return datetime.strptime(v[:15], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
        dt = datetime.strptime(v[:15], "%Y%m%dT%H%M%S")
        m = re.search(r'TZID=("[^"]+"|[^;:]+)', params)
        if m:
            tz = _zone(m.group(1))
            if tz is None:
                return dt  # a zone nobody knows: taken as local time
            return dt.replace(tzinfo=tz).astimezone().replace(tzinfo=None)
        return dt
    # A date the calendar cannot have (year 99999, beyond 9999 in UTC); on Windows also a local time
    # outside the C library's range (from year 3001), which raises OSError instead
    except (ValueError, OverflowError, OSError):
        return None


_LINK_RE = re.compile(r"https?://", re.I)


def parse(text: str) -> List[Dict[str, Any]]:
    """Events as dicts: {uid, title, start, end, attendees, rrule, exdates, all_day, location, online}.
    `online`: the event has a link (in its place, description or URL): a call, not a room."""
    events: List[Dict[str, Any]] = []
    cur: Optional[Dict[str, Any]] = None
    moved: List[tuple] = []  # (uid, the time of the series it replaces): a moved or cancelled meeting
    zone, zone_part = "", ""
    _FILE_ZONES.clear()
    for line in _unfold(text):
        if line == "BEGIN:VTIMEZONE":
            zone, zone_part = "", ""
            continue
        if line in ("BEGIN:STANDARD", "BEGIN:DAYLIGHT"):
            zone_part = line.split(":", 1)[1]
            continue
        if line == "END:VTIMEZONE":
            zone = ""
            continue
        if cur is None and line.upper().startswith("TZID:"):
            zone = line.split(":", 1)[1].strip()
            continue
        if cur is None and zone and zone_part == "STANDARD" and line.upper().startswith("TZOFFSETTO:"):
            m = re.fullmatch(r"([+-])(\d\d)(\d\d)", line.split(":", 1)[1].strip())
            if m:
                sign = -1 if m.group(1) == "-" else 1
                _FILE_ZONES[zone] = sign * timedelta(hours=int(m.group(2)), minutes=int(m.group(3)))
            continue
        if line == "BEGIN:VEVENT":
            cur = {"uid": "", "title": "", "start": None, "end": None, "attendees": [], "rrule": "", "exdates": [],
                   "all_day": False, "status": "", "location": "", "online": False, "recurrence_id": None}
            continue
        if line == "END:VEVENT":
            if cur and cur["recurrence_id"] and cur["uid"]:
                moved.append((cur["uid"], cur["recurrence_id"]))
            if cur and cur["start"] and cur["status"].upper() != "CANCELLED":
                if not cur["end"] or cur["end"] < cur["start"]:
                    try:
                        cur["end"] = cur["start"] + (timedelta(days=1) if cur["all_day"] else timedelta(hours=1))
                    except OverflowError:
                        cur = None
                if cur:
                    events.append(cur)
            cur = None
            continue
        if cur is None or ":" not in line:
            continue
        head, value = line.split(":", 1)
        name, _, params = head.partition(";")
        name = name.upper()
        if name == "SUMMARY":
            cur["title"] = _unescape(value).strip()
        elif name == "UID":
            cur["uid"] = value.strip()
        elif name == "LOCATION":
            cur["location"] = _unescape(value).strip()[:200]
            cur["online"] = cur["online"] or bool(_LINK_RE.search(value))
        elif name in ("DESCRIPTION", "URL") or name.endswith("MEETINGURL") or name == "X-GOOGLE-CONFERENCE":
            cur["online"] = cur["online"] or bool(_LINK_RE.search(value))
        elif name == "STATUS":
            cur["status"] = value.strip()
        elif name in ("DTSTART", "DTEND"):
            dt = _parse_dt(value, params)
            cur["start" if name == "DTSTART" else "end"] = dt
            if name == "DTSTART" and ("VALUE=DATE" in params.upper() or re.fullmatch(r"\d{8}", value.strip())):
                cur["all_day"] = True
        elif name == "RRULE":
            cur["rrule"] = value.strip()
        elif name == "RECURRENCE-ID":
            cur["recurrence_id"] = _parse_dt(value, params)
        elif name == "EXDATE":
            for v in value.split(","):
                dt = _parse_dt(v, params)
                if dt:
                    cur["exdates"].append(dt)
        elif name == "ATTENDEE":
            m = re.search(r'CN="?([^";:]+)"?', params)
            who = (m.group(1) if m else value.replace("mailto:", "").replace("MAILTO:", "")).strip()
            if who and who not in cur["attendees"]:
                cur["attendees"].append(who)
    # A meeting of a series moved to another time (or cancelled) comes as its own event with the
    # series' UID: the series no longer has it at its usual time
    for uid, when in moved:
        if when is None:
            continue
        for ev in events:
            if ev["uid"] == uid and ev["rrule"] and not ev.get("recurrence_id"):
                ev["exdates"].append(when)
    return events


def _number(value: str, default: int) -> int:
    return int(value) if value.strip().isdigit() else default


def _month_rule(rule: Dict[str, str]):
    """For FREQ=MONTHLY with BYDAY (1MO, -1FR, or MO with BYSETPOS=1): the days of a month it gives, as a
    function of (year, month). None for a rule by the day of the month (the usual walk does that)."""
    import calendar

    tokens = [t.strip().upper() for t in rule.get("BYDAY", "").split(",") if t.strip()]
    parsed = []
    for t in tokens:
        m = re.fullmatch(r"([+-]?\d{1,2})?(MO|TU|WE|TH|FR|SA|SU)", t)
        if m:
            parsed.append((int(m.group(1)) if m.group(1) else None, _DAYS[m.group(2)]))
    if not parsed:
        return None
    setpos = [int(x) for x in rule.get("BYSETPOS", "").split(",") if re.fullmatch(r"[+-]?\d{1,3}", x.strip() or "x")]

    def days(year: int, month: int) -> List[int]:
        total = calendar.monthrange(year, month)[1]
        out = set()
        for nth, wd in parsed:
            all_wd = [d for d in range(1, total + 1) if calendar.weekday(year, month, d) == wd]
            if nth is None:
                out.update(all_wd)
            elif 0 < abs(nth) <= len(all_wd):
                out.add(all_wd[nth - 1] if nth > 0 else all_wd[nth])
        ordered = sorted(out)
        if setpos:
            ordered = sorted({ordered[p - 1] if p > 0 else ordered[p] for p in setpos if 0 < abs(p) <= len(ordered)})
        return ordered

    return days


def occurrences(ev: Dict[str, Any], start: datetime, end: datetime) -> List[Dict[str, Any]]:
    """The times the event happens between start and end (recurrence expanded). A rule that makes no
    sense (a date past the year 9999, an INTERVAL that is not a number) ends the series there."""
    out: List[Dict[str, Any]] = []
    try:
        _expand(ev, start, end, out)
    except (ValueError, OverflowError):
        pass
    return out


def _expand(ev: Dict[str, Any], start: datetime, end: datetime, out: List[Dict[str, Any]]) -> None:
    dur = ev["end"] - ev["start"]

    def add(s: datetime) -> None:
        if s + dur > start and s < end and not any(abs((s - x).total_seconds()) < 60 for x in ev["exdates"]):
            out.append({**ev, "start": s, "end": s + dur})

    rule = {k.upper(): v for k, v in (p.split("=", 1) for p in ev["rrule"].split(";") if "=" in p)} if ev["rrule"] else {}
    if not rule:
        add(ev["start"])
        return
    freq = rule.get("FREQ", "").upper()
    step = _number(rule.get("INTERVAL", "1"), 1)
    if not 1 <= step <= MAX_INTERVAL:
        add(ev["start"])
        return
    count = int(rule["COUNT"]) if rule.get("COUNT", "").isdigit() else None
    until = _parse_dt(rule["UNTIL"], "") if rule.get("UNTIL") else None
    days = [_DAYS[d[-2:]] for d in rule.get("BYDAY", "").upper().split(",") if d[-2:] in _DAYS]
    n = 0
    cursor = ev["start"]
    limit = min(end, until + timedelta(seconds=1)) if until else end
    # A long series (a daily stand-up since years) starts its walk next to the window, not at its
    # first meeting: whole periods before the window are skipped by arithmetic
    period = {"DAILY": timedelta(days=step), "WEEKLY": timedelta(weeks=step)}.get(freq)
    if period is not None and count is None and cursor + dur < start:
        skip = (start - dur - cursor) // period
        if freq == "WEEKLY" and days:
            week_start = cursor - timedelta(days=cursor.weekday())
            cursor = (week_start + skip * period).replace(hour=ev["start"].hour, minute=ev["start"].minute,
                                                          second=ev["start"].second)
            if cursor < ev["start"]:
                cursor = ev["start"]
        else:
            cursor += skip * period
    month_days = _month_rule(rule) if freq == "MONTHLY" else None
    for _ in range(5000):
        if cursor >= limit or (count is not None and n >= count):
            break
        if month_days:  # «the first Monday», «the last Friday» of the month
            for d in month_days(cursor.year, cursor.month):
                s = cursor.replace(day=d)
                if s < ev["start"] or s >= limit or (count is not None and n >= count):
                    continue
                n += 1
                add(s)
            month = cursor.month - 1 + step
            cursor = cursor.replace(year=cursor.year + month // 12, month=month % 12 + 1, day=1)
            continue
        if freq == "WEEKLY" and days:
            week_start = cursor - timedelta(days=cursor.weekday())
            for d in sorted(days):
                s = week_start + timedelta(days=d)
                s = s.replace(hour=ev["start"].hour, minute=ev["start"].minute, second=ev["start"].second)
                if s < ev["start"] or s >= limit or (count is not None and n >= count):
                    continue
                n += 1
                add(s)
            cursor = week_start + timedelta(weeks=step)
            cursor = cursor.replace(hour=ev["start"].hour, minute=ev["start"].minute, second=ev["start"].second)
            continue
        n += 1
        add(cursor)
        if freq == "DAILY":
            cursor += timedelta(days=step)
        elif freq == "WEEKLY":
            cursor += timedelta(weeks=step)
        elif freq == "MONTHLY":
            month = cursor.month - 1 + step
            year = cursor.year + month // 12
            try:
                cursor = cursor.replace(year=year, month=month % 12 + 1)
            except ValueError:  # the 31st in a short month: skipped, as calendars do
                cursor = cursor.replace(year=year, month=month % 12 + 1, day=28)
        elif freq == "YEARLY":
            cursor = cursor.replace(year=cursor.year + step)
        else:
            break


def _source() -> str:
    from app.database import get_all_settings

    return (get_all_settings().get("calendar_ics") or "").strip()


def _load_text(source: str) -> str:
    if re.match(r"^(https?|webcal)://", source, re.I):
        import httpx

        url = re.sub(r"^webcal://", "https://", source, flags=re.I)
        deadline = time.time() + 60
        data = bytearray()
        with httpx.Client(timeout=15.0, follow_redirects=True) as c:
            with c.stream("GET", url) as r:
                r.raise_for_status()
                for chunk in r.iter_bytes():
                    data += chunk
                    if len(data) > MAX_BYTES:
                        raise ValueError("Календарь по ссылке больше 5 МБ")
                    if time.time() > deadline:
                        raise TimeoutError("Календарь по ссылке не загрузился за минуту")
        return bytes(data).decode("utf-8", errors="replace")
    p = Path(source)
    if p.stat().st_size > MAX_BYTES:
        raise ValueError("Файл календаря больше 5 МБ")
    return p.read_text(encoding="utf-8", errors="replace")


def events(force: bool = False) -> List[Dict[str, Any]]:
    source = _source()
    if not source:
        return []
    with _lock:
        fresh = _cache["source"] == source and time.time() - _cache["at"] < CACHE_SEC
        if fresh and not force:
            return list(_cache["events"])
    try:
        with _fetch_lock:  # Outlook (PowerShell) and links take seconds: one read at a time
            with _lock:
                if _cache["source"] == source and time.time() - _cache["at"] < CACHE_SEC and not force:
                    return list(_cache["events"])
            if source.lower() == "outlook":  # the classic Outlook of this computer (app/calendar_outlook.py)
                from app import calendar_outlook

                parsed = calendar_outlook.fetch()
            else:
                parsed = parse(_load_text(source))
        with _lock:
            _cache.update(source=source, at=time.time(), events=parsed, error="")
        return parsed
    except Exception as e:
        with _lock:
            _cache.update(source=source, at=time.time(), error=str(e)[:200])
            return list(_cache["events"])


def status() -> Dict[str, Any]:
    with _lock:
        return {"source": _cache["source"], "error": _cache["error"], "count": len(_cache["events"])}


def window(start: datetime, end: datetime) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for ev in events():
        if ev["all_day"]:
            continue
        out.extend(occurrences(ev, start, end))
    return sorted(out, key=lambda e: e["start"])


def current_meeting(at: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """The meeting going on now (or starting within 10 minutes): the shortest one if several."""
    at = at or datetime.now()
    found = [e for e in window(at - timedelta(hours=12), at + timedelta(minutes=10))
             if e["start"] - timedelta(minutes=10) <= at < e["end"]]
    return min(found, key=lambda e: e["end"] - e["start"]) if found else None


def upcoming(hours: int = 36, limit: int = 8) -> List[Dict[str, Any]]:
    now = datetime.now()
    return [{"title": e["title"], "start": e["start"].isoformat(timespec="minutes"), "end": e["end"].isoformat(timespec="minutes"),
             "attendees": e["attendees"][:20]}
            for e in window(now - timedelta(minutes=30), now + timedelta(hours=hours))[:limit] if e["end"] > now]


def day(start: datetime, end: datetime) -> List[Dict[str, Any]]:
    """The meetings between start and end (a working day, maybe past midnight), for the home page.
    `key` names one meeting of a series: its id and its start."""
    return [{"key": f"{e['uid'] or e['title']}|{e['start'].isoformat(timespec='minutes')}", "title": e["title"],
             "start": e["start"].isoformat(timespec="minutes"), "end": e["end"].isoformat(timespec="minutes"),
             "attendees": e["attendees"][:20], "location": e.get("location", ""), "online": bool(e.get("online"))}
            for e in window(start, end)]


def apply_to_recording(meeting_id: int, started_at: Optional[datetime] = None) -> bool:
    """A recording made during a calendar meeting: its title and participants come from the event."""
    from app.database import get_meeting, update_meeting_fields

    if not _source():
        return False
    ev = current_meeting(started_at)
    m = get_meeting(meeting_id)
    if not ev or not m:
        return False
    fields: Dict[str, Any] = {}
    if ev["title"] and m.get("title_is_default"):
        fields.update(title=ev["title"][:300], title_is_default=0)
    if ev["attendees"]:
        head = ("Участники по календарю: " if (m.get("language") or "ru") != "en" else "Participants (calendar): ") + ", ".join(ev["attendees"][:30])
        notes = (m.get("user_notes") or "").strip()
        if head not in notes:
            fields["user_notes"] = (head + ("\n" + notes if notes else ""))[:50000]
    if fields:
        update_meeting_fields(meeting_id, **fields)
    return bool(fields)
