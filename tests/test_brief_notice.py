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


if __name__ == "__main__":
    unittest.main()
