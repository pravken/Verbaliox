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

import bisect
import re
import threading
import time
import traceback
from datetime import date, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

CACHE_SEC = 15 * 60
# Outlook that failed (not set up, waiting for a password) is not started again every 15 minutes,
# even by a forced read: each start may put its window in front of the user. A read the user asked for
# (events(user=True): «Проверить» in Settings) starts it at once; a forced read alone, after an error other
# than the timeout (OUTLOOK_TIMEOUT), too.
OUTLOOK_RETRY_SEC = 6 * 60 * 60
OUTLOOK_TIMEOUT = "Outlook не ответил за"
# While a meeting starts within the hour, the calendar is read again this often (refresh_async, by the loop of
# app/brief_notice.py): a meeting moved or cancelled in Outlook leaves the strip and «Сегодня» sooner
# (reported by the user: a moved meeting stayed in place and its reminder still came)
SOON_CACHE_SEC = 5 * 60
SOON_HOURS = 1
# at: the last read tried, ok_at: the last read that succeeded (time.time())
_cache: Dict[str, Any] = {"source": "", "at": 0.0, "ok_at": 0.0, "events": [], "error": ""}
_reading = threading.Event()  # a read of refresh_async is running
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

class _FileZone(tzinfo):
    """A zone described in the file itself (VTIMEZONE), for a name neither IANA nor Windows knows
    («Customized Time Zone» of Outlook): its standard offset, and its summer one between the yearly
    changes the file gives (RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU at the time of its DTSTART)."""

    def __init__(self) -> None:
        self.std_off: Optional[timedelta] = None
        self.summer_off: Optional[timedelta] = None
        self.rules: Dict[str, tuple] = {}  # "STANDARD"/"DAYLIGHT" -> (month, nth, weekday, hour, minute)

    @staticmethod
    def _change(year: int, rule: tuple) -> datetime:
        import calendar

        month, nth, wd, hour, minute = rule
        days = [d for d in range(1, calendar.monthrange(year, month)[1] + 1) if calendar.weekday(year, month, d) == wd]
        # «-2SU»: the last but one (it was taken for the last: an audit); a place the month has not: the last
        day = days[nth - 1] if 0 < nth <= len(days) else days[nth] if -len(days) <= nth < 0 else days[-1]
        return datetime(year, month, day, hour, minute)

    def _summer(self, dt: datetime) -> bool:
        if self.summer_off is None or "DAYLIGHT" not in self.rules or "STANDARD" not in self.rules:
            return False
        wall = dt.replace(tzinfo=None)
        on, off = self._change(wall.year, self.rules["DAYLIGHT"]), self._change(wall.year, self.rules["STANDARD"])
        return on <= wall < off if on < off else not (off <= wall < on)  # the south: summer over the new year

    def utcoffset(self, dt):
        return (self.summer_off if self._summer(dt) else self.std_off) or timedelta(0)

    def dst(self, dt):
        return (self.summer_off - self.std_off) if self._summer(dt) and self.std_off is not None else timedelta(0)

    def tzname(self, dt):
        return None


# Filled by parse(): the zones of the file being read
_FILE_ZONES: Dict[str, _FileZone] = {}


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
    fz = _FILE_ZONES.get(name)
    return fz if fz is not None and fz.std_off is not None else None


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


def _join(value: str) -> str:
    from app.meeting_join import find

    return find(_unescape(value))


def _split_property(line: str) -> Tuple[str, str]:
    """NAME;PARAMS and the value: at the first colon outside quotes (TZID="(UTC+01:00) Amsterdam")."""
    quoted = False
    for i, ch in enumerate(line):
        if ch == '"':
            quoted = not quoted
        elif ch == ":" and not quoted:
            return line[:i], line[i + 1:]
    return line, ""


def parse(text: str) -> List[Dict[str, Any]]:
    """Events as dicts: {uid, title, start, end, attendees, rrule, exdates, all_day, location, online, join}.
    `online`: the event has a link (in its place, description or URL): a call, not a room; `join`: the
    link to its call (Teams, Zoom, Meet, Webex: app/meeting_join.py), "" when none is known."""
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
        if cur is None and zone and zone_part in ("STANDARD", "DAYLIGHT"):
            fz = _FILE_ZONES.setdefault(zone, _FileZone())
            key, _, val = line.partition(":")
            key, val = key.upper(), val.strip()
            if key == "TZOFFSETTO":
                m = re.fullmatch(r"([+-])(\d\d)(\d\d)", val)
                if m:
                    off = (-1 if m.group(1) == "-" else 1) * timedelta(hours=int(m.group(2)), minutes=int(m.group(3)))
                    if zone_part == "STANDARD":
                        fz.std_off = off
                    else:
                        fz.summer_off = off
            elif key == "DTSTART":
                fz._at = re.match(r"\d{8}T(\d\d)(\d\d)", val)
                fz._at_part = zone_part
            elif key == "RRULE":
                r = {k.upper(): v for k, v in (p.split("=", 1) for p in val.split(";") if "=" in p)}
                bd = re.fullmatch(r"([+-]?\d)?(MO|TU|WE|TH|FR|SA|SU)", r.get("BYDAY", "").upper())
                at = getattr(fz, "_at", None) if getattr(fz, "_at_part", "") == zone_part else None
                if r.get("BYMONTH", "").isdigit() and bd:
                    nth = int(bd.group(1) or 1)
                    fz.rules[zone_part] = (int(r["BYMONTH"]), nth, _DAYS[bd.group(2)],
                                           int(at.group(1)) if at else 2, int(at.group(2)) if at else 0)
            continue
        if line == "BEGIN:VEVENT":
            cur = {"uid": "", "title": "", "start": None, "end": None, "attendees": [], "rrule": "", "exdates": [],
                   "all_day": False, "status": "", "location": "", "online": False, "join": "", "recurrence_id": None}
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
        head, value = _split_property(line)
        name, _, params = head.partition(";")
        name = name.upper()
        if name == "SUMMARY":
            cur["title"] = _unescape(value).strip()
        elif name == "UID":
            cur["uid"] = value.strip()
        elif name == "LOCATION":
            cur["location"] = _unescape(value).strip()[:200]
            cur["online"] = cur["online"] or bool(_LINK_RE.search(value))
            cur["join"] = cur["join"] or _join(value)
        elif name in ("DESCRIPTION", "URL") or name.endswith("MEETINGURL") or name == "X-GOOGLE-CONFERENCE":
            cur["online"] = cur["online"] or bool(_LINK_RE.search(value))
            # the meeting URL of the service first; the description's link only when there is no other
            found = _join(value)
            if found and (not cur["join"] or name != "DESCRIPTION"):
                cur["join"] = found
        elif name == "STATUS":
            cur["status"] = value.strip()
        elif name in ("DTSTART", "DTEND"):
            dt = _parse_dt(value, params)
            cur["start" if name == "DTSTART" else "end"] = dt
            if name == "DTSTART" and ("VALUE=DATE" in params.upper() or re.fullmatch(r"\d{8}", value.strip())):
                cur["all_day"] = True
            zm = re.search(r'TZID=("[^"]+"|[^;:]+)', params)
            if name == "DTSTART" and zm and dt is not None and not value.strip().endswith("Z"):
                tz = _zone(zm.group(1))
                if tz is not None:  # a series repeats at its wall time there, across its own summer time
                    try:
                        cur["tz"], cur["src_start"] = tz, datetime.strptime(value.strip()[:15], "%Y%m%dT%H%M%S")
                    except ValueError:
                        pass
            elif name == "DTSTART" and dt is not None and value.strip().endswith("Z") and not cur.get("all_day"):
                # A series given in UTC repeats at the same UTC time: expanded at a fixed local wall time
                # it was an hour off after the viewer's clocks changed
                try:
                    cur["tz"], cur["src_start"] = timezone.utc, datetime.strptime(value.strip()[:15], "%Y%m%dT%H%M%S")
                except ValueError:
                    pass
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
    series: Dict[str, List[Dict[str, Any]]] = {}  # by UID: one pass, not every event for every moved one
    for ev in events:
        if ev["rrule"] and not ev.get("recurrence_id"):
            series.setdefault(ev["uid"], []).append(ev)
    for uid, when in moved:
        if when is None:
            continue
        for ev in series.get(uid, ()):
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
    parsed = list(dict.fromkeys(parsed))  # «MO,MO,MO…» repeated thousands of times is one Monday
    setpos = sorted({int(x) for x in rule.get("BYSETPOS", "").split(",") if re.fullmatch(r"[+-]?\d{1,3}", x.strip() or "x")})

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
        tz = ev.get("tz")
        if tz is not None and ev.get("rrule") and ev.get("src_start"):
            # Expanded at the wall time of the event's zone, then each meeting brought to local time: a
            # Berlin series seen from Moscow moves by an hour when Berlin changes its clocks, not before
            def wall(local: datetime) -> datetime:
                return local.astimezone(tz).replace(tzinfo=None)

            dur = ev["end"] - ev["start"]
            src = {**ev, "start": ev["src_start"], "end": ev["src_start"] + dur, "exdates": [wall(x) for x in ev["exdates"]]}
            found: List[Dict[str, Any]] = []
            _expand(src, wall(start) - timedelta(days=1), wall(end) + timedelta(days=1), found, to_wall=wall)
            for o in found:
                s_local = o["start"].replace(tzinfo=tz).astimezone().replace(tzinfo=None)
                if s_local + dur > start and s_local < end:
                    out.append({**ev, "start": s_local, "end": s_local + dur})
            return out
        _expand(ev, start, end, out)
    except (ValueError, OverflowError):
        pass
    return out


def _expand(ev: Dict[str, Any], start: datetime, end: datetime, out: List[Dict[str, Any]], to_wall=None) -> None:
    """to_wall: the series is walked at its zone's wall time; UNTIL (local time here) is brought to it."""
    dur = ev["end"] - ev["start"]
    exdates = sorted(ev["exdates"])  # looked up by bisection: thousands of them made every meeting slow

    def excluded(s: datetime) -> bool:
        i = bisect.bisect_left(exdates, s - timedelta(seconds=60))
        return i < len(exdates) and abs((s - exdates[i]).total_seconds()) < 60

    def add(s: datetime) -> None:
        if s + dur > start and s < end and not excluded(s):
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
    if until is not None:
        # found in the audit: a date alone («UNTIL=20261104») takes in that whole day, its meeting too;
        # a UTC time (local here) is the series' wall time in its zone, or its last meeting was lost
        if len(rule["UNTIL"].strip()) == 8:
            until = until.replace(hour=23, minute=59, second=59)
        elif to_wall is not None and rule["UNTIL"].strip().upper().endswith("Z"):
            until = to_wall(until)
    # each day once: «MO» repeated thousands of times in one event made as many meetings a week (found in the audit)
    days = sorted({_DAYS[d[-2:]] for d in rule.get("BYDAY", "").upper().split(",") if d[-2:] in _DAYS})
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
            for d in days:
                s = week_start + timedelta(days=d)
                s = s.replace(hour=ev["start"].hour, minute=ev["start"].minute, second=ev["start"].second)
                if s < ev["start"] or s >= limit or (count is not None and n >= count):
                    continue
                n += 1
                add(s)
            cursor = week_start + timedelta(weeks=step)
            cursor = cursor.replace(hour=ev["start"].hour, minute=ev["start"].minute, second=ev["start"].second)
            continue
        if freq != "MONTHLY" or cursor.day == ev["start"].day:  # no 31st this month: none that month
            n += 1
            add(cursor)
        if freq == "DAILY":
            cursor += timedelta(days=step)
        elif freq == "WEEKLY":
            cursor += timedelta(weeks=step)
        elif freq == "MONTHLY":
            month = cursor.month - 1 + step
            year = cursor.year + month // 12
            try:  # the day of the first meeting each time: after a short month, the 31st again
                cursor = cursor.replace(year=year, month=month % 12 + 1, day=ev["start"].day)
            except ValueError:  # the 31st in a short month: skipped, as calendars do
                cursor = cursor.replace(year=year, month=month % 12 + 1, day=28)
        elif freq == "YEARLY":
            # a series from 29 February meets in the leap years only (found in the audit: it raised and the
            # whole series was lost)
            year = cursor.year + step
            for _ in range(8):
                try:
                    cursor = ev["start"].replace(year=year)
                    break
                except ValueError:
                    year += step
            else:
                break
        else:
            break


def _source() -> str:
    from app.database import get_all_settings

    return (get_all_settings().get("calendar_ics") or "").strip()


def _load_text(source: str) -> str:
    if re.match(r"^(https?|webcal)://", source, re.I):
        import httpx

        from app.applog import hide_in_log

        url = re.sub(r"^webcal://", "https://", source, flags=re.I)
        hide_in_log(source)  # an error of the request (a traceback) would write the link with its secret
        hide_in_log(url)
        deadline = time.time() + 60
        data = bytearray()
        with httpx.Client(timeout=15.0, follow_redirects=True) as c:
            with c.stream("GET", url) as r:
                hide_in_log(str(r.url))  # where a redirect led
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


def events(force: bool = False, cached: bool = False, user: bool = False,
           max_age: Optional[float] = None) -> List[Dict[str, Any]]:
    """force: read again now (a page refreshing its calendar). user: the user asked for it by an action of
    their own, so a failed Outlook is tried again at once (OUTLOOK_RETRY_SEC). cached: only what was read
    already, never a read now (Outlook through PowerShell takes up to 90 s, a link up to 60 s): for callers
    holding a lock others wait on. max_age: read again when the last read is older (CACHE_SEC by default)."""
    force = force or user
    age = CACHE_SEC if max_age is None else max(0.0, max_age)
    source = _source()
    if not source:
        return []
    with _lock:
        if cached:
            return list(_cache["events"]) if _cache["source"] == source else []
        fresh = _cache["source"] == source and time.time() - _cache["at"] < age
        if fresh and not force:
            return list(_cache["events"])
        if (source.lower() == "outlook" and _cache["source"] == source and _cache["error"]
                and not _cache["error"].startswith("Классический Outlook не настроен")  # checked without starting it
                and not user and not (force and not _cache["error"].startswith(OUTLOOK_TIMEOUT))
                and time.time() - _cache["at"] < OUTLOOK_RETRY_SEC):
            return list(_cache["events"])
    try:
        with _fetch_lock:  # Outlook (PowerShell) and links take seconds: one read at a time
            with _lock:
                if _cache["source"] == source and time.time() - _cache["at"] < age and not force:
                    return list(_cache["events"])
            if source.lower() == "outlook":  # the classic Outlook of this computer (app/calendar_outlook.py)
                from app import calendar_outlook

                parsed = calendar_outlook.fetch()
            else:
                parsed = parse(_load_text(source))
        with _lock:
            now = time.time()
            _cache.update(source=source, at=now, ok_at=now, events=parsed, error="")
        return parsed
    except Exception as e:
        with _lock:
            if _cache["source"] != source:
                # another calendar's events are not this one's: after switching to a link that fails,
                # the previous calendar went on showing until the next read
                _cache["events"] = []
                _cache["ok_at"] = 0.0
            _cache.update(source=source, at=time.time(), error=str(e)[:200])
            return list(_cache["events"])


def refresh_async(max_age: float) -> bool:
    """Reads the calendar in a thread of its own when the last read is older than max_age seconds: no caller
    waits for Outlook (up to 90 s). False when a read of this kind is running already."""
    if _reading.is_set():
        return False
    _reading.set()

    def run() -> None:
        try:
            events(max_age=max_age)
        except Exception:
            traceback.print_exc()
        finally:
            _reading.clear()

    threading.Thread(target=run, daemon=True, name="calendar_read").start()
    return True


def read_state() -> Dict[str, Any]:
    """When the calendar was read last (tried, succeeded: time.time()) and whether a read is running."""
    source = _source()
    with _lock:
        same = bool(source) and _cache["source"] == source
        return {"at": _cache["at"] if same else 0.0, "ok_at": _cache["ok_at"] if same else 0.0,
                "reading": _reading.is_set() or _fetch_lock.locked()}


def status() -> Dict[str, Any]:
    with _lock:
        return {"source": _cache["source"], "error": _cache["error"], "count": len(_cache["events"])}


def window(start: datetime, end: datetime, cached: bool = False) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for ev in events(cached=cached):
        if ev["all_day"]:
            continue
        out.extend(occurrences(ev, start, end))
    return sorted(out, key=lambda e: e["start"])


def current_meeting(at: Optional[datetime] = None, cached: bool = False) -> Optional[Dict[str, Any]]:
    """The meeting going on now (or starting within 10 minutes): the shortest one if several. cached: by the
    calendar read already, without reading it now (events)."""
    at = at or datetime.now()
    found = [e for e in window(at - timedelta(hours=12), at + timedelta(minutes=10), cached=cached)
             if e["start"] - timedelta(minutes=10) <= at < e["end"] and is_meeting(e)]
    return min(found, key=lambda e: e["end"] - e["start"]) if found else None


def upcoming(hours: int = 36, limit: int = 8) -> List[Dict[str, Any]]:
    now = datetime.now()
    return [{"title": e["title"], "start": e["start"].isoformat(timespec="minutes"), "end": e["end"].isoformat(timespec="minutes"),
             "attendees": e["attendees"][:20], "join": e.get("join", "")}
            for e in [e for e in window(now - timedelta(minutes=30), now + timedelta(hours=hours)) if is_meeting(e)][:limit] if e["end"] > now]


# A calendar block this long or longer (a night, a day off, a reminder) is no meeting
BLOCK_HOURS = 6


def event_key(e: Dict[str, Any]) -> str:
    return f"{e.get('uid') or e['title']}|{e['start'].isoformat(timespec='minutes')}"


def is_meeting(e: Dict[str, Any], ignored: Optional[List[Dict[str, str]]] = None) -> bool:
    """A meeting to count, to record, to pause the analysis for: not a long block, not one the user said is
    no meeting (asked by the user: «не считать встречей», one or a whole series; meet_ignore)."""
    if e["end"] - e["start"] >= timedelta(hours=BLOCK_HOURS):
        return False
    if ignored is None:
        import json

        from app.database import get_all_settings

        try:
            ignored = json.loads(get_all_settings().get("meet_ignore") or "[]")
        except ValueError:
            ignored = []
    key, series = event_key(e), (e.get("uid") or e["title"])
    return not any((x.get("key") and x["key"] == key) or (not x.get("key") and x.get("id") == series) for x in ignored or [])


def day(start: datetime, end: datetime) -> List[Dict[str, Any]]:
    """The meetings between start and end (a working day, maybe past midnight), for the home page.
    `key` names one meeting of a series: its id and its start."""
    return [{"key": f"{e['uid'] or e['title']}|{e['start'].isoformat(timespec='minutes')}", "title": e["title"],
             "start": e["start"].isoformat(timespec="minutes"), "end": e["end"].isoformat(timespec="minutes"),
             "attendees": e["attendees"][:20], "location": e.get("location", ""), "online": bool(e.get("online")),
             "join": e.get("join", "")}
            for e in window(start, end)]


def apply_to_recording(meeting_id: int, started_at: Optional[datetime] = None, title: str = "",
                       names: Optional[List[str]] = None, call_app: str = "") -> bool:
    """A recording made during a calendar meeting: its title and participants come from the event, when
    the recording is that meeting (app/calendar_match.py): a person who called meanwhile is not its invitees.
    `title`, `names`, `call_app`: what the recording itself says (its title, the people heard, the call's app)."""
    import json

    from app import calendar_match
    from app.database import get_meeting, update_meeting_fields

    if not _source():
        return False
    ev = current_meeting(started_at)
    m = get_meeting(meeting_id)
    if not ev or not m:
        return False
    names = names or []
    verdict = calendar_match.verdict(ev, title, names, call_app)
    print(f"[calendar] meeting {meeting_id} during a calendar event: {verdict}", flush=True)
    fields: Dict[str, Any] = {"calendar_json": json.dumps({
        "title": ev["title"], "attendees": ev["attendees"][:30], "online": bool(ev.get("online")), "call_app": call_app,
        "recorded_title": m.get("title") or "", "sure": verdict != "unknown", "match": verdict != "no"}, ensure_ascii=False)}
    if verdict == "no":
        named = calendar_match.call_title(names, "en" if (m.get("language") or "") == "en" else "ru")
        from app.ollama_client import is_generic_title

        if named and m.get("title_is_default") and is_generic_title(m.get("title") or ""):
            fields.update(title=named[:300], title_is_default=0)  # without names: named by its content later
        update_meeting_fields(meeting_id, **fields)
        return False
    if ev["title"] and m.get("title_is_default"):
        fields.update(title=ev["title"][:300], title_is_default=0)
    if ev["attendees"]:
        head = ("Участники по календарю: " if (m.get("language") or "ru") != "en" else "Participants (calendar): ") + ", ".join(ev["attendees"][:30])
        notes = (m.get("user_notes") or "").strip()
        if head not in notes:
            fields["user_notes"] = (head + ("\n" + notes if notes else ""))[:50000]
    update_meeting_fields(meeting_id, **fields)
    return len(fields) > 1  # the title or the participants written, not the record of the match alone
