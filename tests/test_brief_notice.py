"""Before a calendar meeting that continues a series: what is open from last time (app/series.py,
app/brief_notice.py)."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest
from datetime import datetime, timedelta
from unittest import mock

try:
    from app import app_status, brief_notice, series
    from app.database import create_meeting, init_db, update_meeting_fields, update_meeting_progress
except ImportError:  # app dependencies are not installed (e.g. in the release CI job)
    series = None


@unittest.skipIf(series is None, "app dependencies not installed")
class BeforeMeetingTest(unittest.TestCase):
    def test_a_meeting_of_a_series_is_told_about_once(self):
        init_db()
        m = create_meeting("Планёрка отдела 12.11", "a.wav", "a.wav")
        sid = series.create_series("Планёрка отдела")
        update_meeting_fields(m["id"], series_id=sid)
        update_meeting_progress(m["id"], status="completed")
        info = series.before_meeting("Планёрка отдела 19.11", [])
        self.assertEqual(info["series_id"], sid)
        self.assertEqual(info["last"]["id"], m["id"])
        self.assertEqual((info["open_tasks"], info["tasks"]), (0, []))  # the tasks themselves for the dashboard
        self.assertIsNone(series.before_meeting("Совсем другое", []))

        now = datetime(2026, 11, 19, 9, 55)
        ev = {"uid": "u1", "title": "Планёрка отдела 19.11", "start": now + timedelta(minutes=5),
              "end": now + timedelta(minutes=35), "attendees": []}
        app_status.take_notices()
        with mock.patch("app.calendar_ics.window", return_value=[ev]), \
                mock.patch("app.database.get_all_settings", return_value={"calendar_ics": "outlook"}):
            self.assertEqual(brief_notice.check(now), 1)
            self.assertEqual(brief_notice.check(now), 0)  # once
        notes = app_status.take_notices()
        self.assertEqual(notes[-1]["target"], f"brief:series:{sid}")
        self.assertIn("10:00", notes[-1]["title"])


@unittest.skipIf(series is None, "app dependencies not installed")
class JoinTest(unittest.TestCase):
    """Asked by the user: the notice before a meeting joins its call on a click, without looking for the
    meeting in the calendar (app/meeting_join.py)."""

    TEAMS = "https://teams.microsoft.com/l/meetup-join/19%3ameeting_abc%40thread.v2/0?context=%7b%22Tid%22%7d"

    def test_the_link_of_a_call_is_found_and_only_such_links(self):
        from app import meeting_join

        self.assertEqual(meeting_join.find(f"Join: <{self.TEAMS}> or call +1"), self.TEAMS)
        self.assertEqual(meeting_join.find("https://us02web.zoom.us/j/8123456?pwd=x."), "https://us02web.zoom.us/j/8123456?pwd=x")
        self.assertEqual(meeting_join.find("https://meet.google.com/abc-defg-hij"), "https://meet.google.com/abc-defg-hij")
        self.assertEqual(meeting_join.find("https://evil.example.com/teams.microsoft.com/l/meetup-join/x"), "")
        self.assertEqual(meeting_join.service(self.TEAMS), "Teams")
        with mock.patch("webbrowser.open") as op:
            self.assertIsNone(meeting_join.open_link("https://example.com/x"))
            op.assert_not_called()
            self.assertTrue(meeting_join.open_link("https://meet.google.com/abc-defg-hij"))
            op.assert_called_once()

    def test_an_ics_event_carries_its_link_and_the_notice_joins_it(self):
        from app import calendar_ics

        ics = ("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:j1\r\nSUMMARY:Синк с командой\r\nDTSTART:20261119T100000\r\n"
               "DTEND:20261119T103000\r\nLOCATION:Microsoft Teams Meeting\r\n"
               f"DESCRIPTION:Присоединиться: {self.TEAMS}\\nКод: 123\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
        ev = calendar_ics.parse(ics)[0]
        self.assertEqual(ev["join"], self.TEAMS)
        self.assertTrue(ev["online"])
        init_db()
        app_status.take_notices()
        now = datetime(2026, 11, 19, 9, 55)
        with mock.patch("app.calendar_ics.window", return_value=[ev]), \
                mock.patch("app.database.get_all_settings", return_value={"calendar_ics": "outlook"}):
            self.assertEqual(brief_notice.check(now), 1)
        note = app_status.take_notices()[-1]
        self.assertEqual(note["target"], f"join:{self.TEAMS}")
        self.assertIn("Teams", note["text"])

    def test_a_meeting_without_link_or_history_is_still_reminded_unless_turned_off(self):
        now = datetime(2026, 11, 19, 13, 55)
        ev = {"uid": "r1", "title": "Встреча без ссылки", "start": now + timedelta(minutes=5),
              "end": now + timedelta(minutes=35), "attendees": [], "join": ""}
        init_db()
        app_status.take_notices()
        with mock.patch("app.calendar_ics.window", return_value=[ev]), \
                mock.patch("app.database.get_all_settings", return_value={"calendar_ics": "outlook", "meet_notify": "false"}):
            self.assertEqual(brief_notice.check(now), 0)
        with mock.patch("app.calendar_ics.window", return_value=[ev]), \
                mock.patch("app.database.get_all_settings", return_value={"calendar_ics": "outlook"}):
            self.assertEqual(brief_notice.check(now), 1)
        self.assertEqual(app_status.take_notices()[-1]["target"], "dashboard")


if __name__ == "__main__":
    unittest.main()
