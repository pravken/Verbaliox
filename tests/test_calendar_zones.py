"""Calendar events of other zones, moved meetings of a series, «the first Monday of the month»."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import os
import time
import unittest
from datetime import datetime, timezone

from app import calendar_ics

try:
    from zoneinfo import ZoneInfo

    ZoneInfo("Europe/Moscow")
except Exception:  # no tz database here (Windows without tzdata)
    ZoneInfo = None


def _local(dt_utc: datetime) -> datetime:
    return dt_utc.astimezone().replace(tzinfo=None)


def _one(body: str):
    return calendar_ics.parse("BEGIN:VCALENDAR\n" + body + "END:VCALENDAR\n")


@unittest.skipIf(ZoneInfo is None, "no time zone database")
class ZonesTest(unittest.TestCase):
    def test_a_windows_zone_name_of_outlook(self):
        ev = _one('BEGIN:VEVENT\nUID:w\nSUMMARY:Созвон\nDTSTART;TZID="Russian Standard Time":20261116T120000\nEND:VEVENT\n')[0]
        self.assertEqual(ev["start"], _local(datetime(2026, 11, 16, 9, 0, tzinfo=timezone.utc)))

    def test_an_iana_zone(self):
        ev = _one("BEGIN:VEVENT\nUID:b\nSUMMARY:Sync\nDTSTART;TZID=Europe/Berlin:20261116T100000\nEND:VEVENT\n")[0]
        self.assertEqual(ev["start"], _local(datetime(2026, 11, 16, 9, 0, tzinfo=timezone.utc)))

    def test_a_zone_described_in_the_file(self):
        ev = _one("BEGIN:VTIMEZONE\nTZID:Customized Time Zone\nBEGIN:STANDARD\nDTSTART:16010101T000000\nTZOFFSETFROM:+0400\n"
                  "TZOFFSETTO:+0400\nEND:STANDARD\nEND:VTIMEZONE\n"
                  "BEGIN:VEVENT\nUID:c\nSUMMARY:X\nDTSTART;TZID=Customized Time Zone:20261116T130000\nEND:VEVENT\n")[0]
        self.assertEqual(ev["start"], _local(datetime(2026, 11, 16, 9, 0, tzinfo=timezone.utc)))

    def test_a_berlin_series_seen_from_another_zone_follows_berlin_summer_time(self):
        evs = _one("BEGIN:VEVENT\nUID:z\nSUMMARY:Sync\nDTSTART;TZID=Europe/Berlin:20260914T100000\n"
                   "DTEND;TZID=Europe/Berlin:20260914T103000\nRRULE:FREQ=WEEKLY;BYDAY=MO\nEND:VEVENT\n")
        got = [o["start"] for o in calendar_ics.occurrences(evs[0], datetime(2026, 10, 19), datetime(2026, 11, 3))]
        want = [_local(datetime(2026, 10, 19, 8, 0, tzinfo=timezone.utc)), _local(datetime(2026, 10, 26, 9, 0, tzinfo=timezone.utc)),
                _local(datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc))]
        self.assertEqual(got, want)

    def test_a_file_zone_with_summer_time_and_a_colon_in_its_name(self):
        ev = _one('BEGIN:VTIMEZONE\nTZID:(UTC+01:00) Amsterdam\nBEGIN:STANDARD\nDTSTART:16010101T030000\nTZOFFSETFROM:+0200\n'
                  'TZOFFSETTO:+0100\nRRULE:FREQ=YEARLY;BYDAY=-1SU;BYMONTH=10\nEND:STANDARD\nBEGIN:DAYLIGHT\n'
                  'DTSTART:16010101T020000\nTZOFFSETFROM:+0100\nTZOFFSETTO:+0200\nRRULE:FREQ=YEARLY;BYDAY=-1SU;BYMONTH=3\n'
                  'END:DAYLIGHT\nEND:VTIMEZONE\n'
                  'BEGIN:VEVENT\nUID:c\nSUMMARY:X\nDTSTART;TZID="(UTC+01:00) Amsterdam":20260715T100000\nEND:VEVENT\n')[0]
        self.assertEqual(ev["start"], _local(datetime(2026, 7, 15, 8, 0, tzinfo=timezone.utc)))


    @unittest.skipUnless(hasattr(time, "tzset"), "the process zone cannot be changed here")
    def test_a_utc_series_keeps_its_utc_time_across_the_viewers_summer_time(self):
        # seen from Berlin: 09:00 local (UTC+2) before the change, 08:00 (UTC+1) after it
        old = os.environ.get("TZ")
        os.environ["TZ"] = "Europe/Berlin"
        time.tzset()
        try:
            evs = _one("BEGIN:VEVENT\nUID:u\nSUMMARY:Sync\nDTSTART:20260914T070000Z\nDTEND:20260914T073000Z\n"
                       "RRULE:FREQ=WEEKLY;BYDAY=MO;UNTIL=20261102T070000Z\nEND:VEVENT\n")
            got = [o["start"] for o in calendar_ics.occurrences(evs[0], datetime(2026, 10, 19), datetime(2026, 11, 10))]
        finally:
            if old is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = old
            time.tzset()
        self.assertEqual(got, [datetime(2026, 10, 19, 9, 0), datetime(2026, 10, 26, 8, 0), datetime(2026, 11, 2, 8, 0)])


class SeriesTest(unittest.TestCase):
    def test_a_moved_meeting_is_not_shown_twice(self):
        evs = _one("BEGIN:VEVENT\nUID:s\nSUMMARY:Weekly sync\nDTSTART:20261102T100000\nDTEND:20261102T103000\n"
                   "RRULE:FREQ=WEEKLY;BYDAY=MO\nEND:VEVENT\n"
                   "BEGIN:VEVENT\nUID:s\nSUMMARY:Weekly sync (moved)\nRECURRENCE-ID:20261116T100000\n"
                   "DTSTART:20261116T150000\nDTEND:20261116T153000\nEND:VEVENT\n"
                   "BEGIN:VEVENT\nUID:s\nRECURRENCE-ID:20261123T100000\nDTSTART:20261123T100000\nSTATUS:CANCELLED\nEND:VEVENT\n")
        day = [o for ev in evs for o in calendar_ics.occurrences(ev, datetime(2026, 11, 16), datetime(2026, 11, 24))]
        self.assertEqual(sorted((o["start"], o["title"]) for o in day),
                         [(datetime(2026, 11, 16, 15, 0), "Weekly sync (moved)")])

    def test_the_first_monday_of_the_month(self):
        ev = _one("BEGIN:VEVENT\nUID:m\nSUMMARY:Ретро\nDTSTART:20261005T110000\nDTEND:20261005T120000\n"
                  "RRULE:FREQ=MONTHLY;BYDAY=1MO\nEND:VEVENT\n")[0]
        got = [o["start"] for o in calendar_ics.occurrences(ev, datetime(2026, 10, 1), datetime(2027, 1, 1))]
        self.assertEqual(got, [datetime(2026, 10, 5, 11), datetime(2026, 11, 2, 11), datetime(2026, 12, 7, 11)])

    def test_the_last_friday_by_setpos(self):
        ev = _one("BEGIN:VEVENT\nUID:f\nSUMMARY:Итоги\nDTSTART:20261030T160000\nDTEND:20261030T170000\n"
                  "RRULE:FREQ=MONTHLY;BYDAY=FR;BYSETPOS=-1;COUNT=2\nEND:VEVENT\n")[0]
        got = [o["start"] for o in calendar_ics.occurrences(ev, datetime(2026, 10, 1), datetime(2027, 1, 1))]
        self.assertEqual(got, [datetime(2026, 10, 30, 16), datetime(2026, 11, 27, 16)])

    def test_the_31st_comes_back_after_a_short_month(self):
        ev = _one("BEGIN:VEVENT\nUID:d\nSUMMARY:Отчёт\nDTSTART:20270131T100000\nDTEND:20270131T110000\n"
                  "RRULE:FREQ=MONTHLY\nEND:VEVENT\n")[0]
        got = [o["start"].date().isoformat() for o in calendar_ics.occurrences(ev, datetime(2027, 1, 1), datetime(2027, 6, 1))]
        self.assertEqual(got, ["2027-01-31", "2027-03-31", "2027-05-31"])


    # Found in the audit
    def test_a_series_from_29_february_meets_in_leap_years(self):
        ev = _one("BEGIN:VEVENT\nUID:f\nSUMMARY:X\nDTSTART:20240229T100000\nDTEND:20240229T110000\nRRULE:FREQ=YEARLY\nEND:VEVENT\n")[0]
        got = [o["start"].date().isoformat() for o in calendar_ics.occurrences(ev, datetime(2024, 1, 1), datetime(2033, 1, 1))]
        self.assertEqual(got, ["2024-02-29", "2028-02-29", "2032-02-29"])

    def test_until_a_date_takes_in_that_day(self):
        ev = _one("BEGIN:VEVENT\nUID:u\nSUMMARY:X\nDTSTART:20261021T100000\nDTEND:20261021T110000\n"
                  "RRULE:FREQ=WEEKLY;UNTIL=20261104\nEND:VEVENT\n")[0]
        got = [o["start"].date().isoformat() for o in calendar_ics.occurrences(ev, datetime(2026, 10, 1), datetime(2026, 12, 1))]
        self.assertEqual(got, ["2026-10-21", "2026-10-28", "2026-11-04"])

    def test_until_in_utc_keeps_the_last_meeting_of_a_berlin_series(self):
        ev = _one("BEGIN:VEVENT\nUID:g\nSUMMARY:Sync\nDTSTART;TZID=Europe/Berlin:20261019T100000\n"
                  "DTEND;TZID=Europe/Berlin:20261019T103000\nRRULE:FREQ=WEEKLY;UNTIL=20261102T090000Z\nEND:VEVENT\n")[0]
        got = [o["start"] for o in calendar_ics.occurrences(ev, datetime(2026, 10, 1), datetime(2026, 12, 1))]
        self.assertEqual(got[-1], _local(datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)))
        self.assertEqual(len(got), 3)



class FileZoneChangeTest(unittest.TestCase):
    """The yearly change of a zone described in the file (VTIMEZONE): «-2SU» is the last Sunday but one, not the
    last (found in an audit)."""

    def test_counted_from_the_end_of_the_month(self):
        change = calendar_ics._FileZone._change
        self.assertEqual(change(2026, (10, -1, 6, 3, 0)), datetime(2026, 10, 25, 3, 0))  # the last Sunday
        self.assertEqual(change(2026, (10, -2, 6, 3, 0)), datetime(2026, 10, 18, 3, 0))  # the last but one
        self.assertEqual(change(2026, (3, 2, 6, 2, 0)), datetime(2026, 3, 8, 2, 0))  # the second
        self.assertEqual(change(2026, (3, 5, 6, 2, 0)), datetime(2026, 3, 29, 2, 0))  # no fifth Sunday: the last


if __name__ == "__main__":
    unittest.main()
