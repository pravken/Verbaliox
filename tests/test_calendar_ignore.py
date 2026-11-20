import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import json
import unittest
from datetime import datetime, timedelta

try:
    from app import calendar_ics
    from app.database import init_db, update_settings
except ImportError:  # the release CI runs without the app's packages
    calendar_ics = None


@unittest.skipIf(calendar_ics is None, "app dependencies not installed")
class NoMeetingTest(unittest.TestCase):
    """Asked by the user: a calendar event can be no meeting (this one or its whole series), and a block over a
    night is none: not counted, not recorded, no pause of the analysis (app/calendar_ics.is_meeting)."""

    def setUp(self):
        init_db()

    def tearDown(self):
        update_settings({"meet_ignore": "[]"})

    def _ev(self, uid, title, start, minutes):
        return {"uid": uid, "title": title, "start": start, "end": start + timedelta(minutes=minutes), "attendees": []}

    def test_long_blocks_and_the_events_said_to_be_none(self):
        at = datetime(2026, 11, 20, 17, 0)
        sync, night, other = self._ev("s1", "Синк", at, 30), self._ev("n1", "The End", at, 15 * 60 + 30), self._ev("o1", "Демо", at, 60)
        self.assertTrue(calendar_ics.is_meeting(sync))
        self.assertFalse(calendar_ics.is_meeting(night))  # a night is no meeting
        update_settings({"meet_ignore": json.dumps([{"id": "", "key": calendar_ics.event_key(sync), "title": "Синк"}])})
        self.assertFalse(calendar_ics.is_meeting(sync))
        self.assertTrue(calendar_ics.is_meeting(self._ev("s1", "Синк", at + timedelta(days=7), 30)))  # only that one
        update_settings({"meet_ignore": json.dumps([{"id": "o1", "key": "", "title": "Демо"}])})
        self.assertFalse(calendar_ics.is_meeting(self._ev("o1", "Демо", at + timedelta(days=7), 60)))  # the whole series
        self.assertTrue(calendar_ics.is_meeting(sync))
        from app.settings_schema import clean

        with self.assertRaises(ValueError):
            clean("meet_ignore", "{}")  # the API refuses what is not a list of events


if __name__ == "__main__":
    unittest.main()
