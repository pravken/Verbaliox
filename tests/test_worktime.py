import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest
from datetime import date, datetime, timedelta
from unittest import mock

try:
    from app import app_status, worktime
    from app.database import get_connection, init_db, update_settings
except ImportError:  # the release CI runs without the app's packages
    worktime = None


@unittest.skipIf(worktime is None, "app dependencies not installed")
class WorkTimeTest(unittest.TestCase):
    """Asked by the user: how long the working day lasted, and a reminder when 8 hours are worked."""

    def setUp(self):
        init_db()
        with worktime._conn() as conn:
            conn.execute("DELETE FROM work_minutes")
        update_settings({"worktime_track": "true", "work_remind_hours": "8", "work_reminded_day": ""})
        app_status.take_notices()

    def test_minutes_with_input_count_and_short_pauses_are_work(self):
        day = datetime(2026, 11, 19, 9, 0)
        with mock.patch.object(worktime, "_in_call", return_value=False), mock.patch.object(worktime, "_recording", return_value=False):
            for m in range(0, 60):          # 09:00–09:59 at the keyboard
                worktime.check(day + timedelta(minutes=m), idle=10)
            for m in range(70, 120):        # a 10-minute pause, then on to 10:59
                worktime.check(day + timedelta(minutes=m), idle=10)
            self.assertFalse(worktime.check(day + timedelta(minutes=125), idle=900))  # away
            for m in range(180, 200):       # back after lunch: 12:00–12:19
                worktime.check(day + timedelta(minutes=m), idle=10)
        s = worktime.days(date(2026, 11, 19), date(2026, 11, 20))["2026-11-19"]
        self.assertEqual((s["start"], s["end"]), ("09:00", "12:20"))
        self.assertEqual(s["worked"], 120 + 20)  # the 10-minute pause counts, the lunch does not
        self.assertEqual(s["breaks"], 200 - 140)

    def test_a_call_or_a_recording_counts_without_input_and_the_night_belongs_to_the_day_before(self):
        with mock.patch.object(worktime, "_in_call", return_value=True), mock.patch.object(worktime, "_recording", return_value=False):
            self.assertTrue(worktime.check(datetime(2026, 11, 20, 1, 30), idle=3600))
        self.assertIn("2026-11-19", worktime.days(date(2026, 11, 19), date(2026, 11, 21)))

    def test_the_norm_is_told_once_a_day(self):
        start = datetime(2026, 11, 18, 9, 0)
        with mock.patch.object(worktime, "_in_call", return_value=False), mock.patch.object(worktime, "_recording", return_value=False):
            with worktime._conn() as conn:
                conn.executemany("INSERT INTO work_minutes (day, minute) VALUES (?, ?)", [("2026-11-18", 300 + m) for m in range(479)])
            worktime.check(start + timedelta(minutes=479), idle=5)
            worktime.check(start + timedelta(minutes=480), idle=5)
        notes = app_status.take_notices()
        self.assertEqual(len(notes), 1)
        self.assertIn("8 ч", notes[0]["title"])
        update_settings({"worktime_track": "false"})
        self.assertFalse(worktime.check(start + timedelta(minutes=490), idle=5))


@unittest.skipIf(worktime is None, "app dependencies not installed")
class ApiTest(unittest.TestCase):
    def test_the_routes_of_worktime_holidays_and_join(self):
        from fastapi.testclient import TestClient

        from app import main

        init_db()
        c = TestClient(main.app, base_url="http://127.0.0.1:8790")
        c.cookies.set("vs_session_8790", main.SESSION_TOKEN)
        r = c.get("/api/worktime", params={"start": "2026-11-16", "end": "2026-11-23"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("days", r.json())
        self.assertEqual(c.get("/api/worktime", params={"start": "2026-11-23", "end": "2026-11-16"}).status_code, 400)
        r = c.get("/api/holidays/countries")
        self.assertEqual(r.status_code, 200)
        self.assertIn("countries", r.json())
        self.assertEqual(c.post("/api/meeting/join", json={"url": "https://example.com/x"}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
