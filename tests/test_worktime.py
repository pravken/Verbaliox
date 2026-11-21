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
class AppsTest(unittest.TestCase):
    """Asked by the user: where the working time goes, by program; off until turned on, only names."""

    def setUp(self):
        init_db()
        with worktime._conn() as conn:
            conn.execute("DELETE FROM work_minutes")
        worktime.clear_apps()
        update_settings({"worktime_track": "true", "work_remind_hours": "0", "apps_track": "false"})

    def _tick(self, at, app="outlook", idle=10, meeting=False):
        with mock.patch.object(worktime, "_in_call", return_value=False), mock.patch.object(worktime, "_recording", return_value=meeting), \
                mock.patch.object(worktime, "foreground_app", return_value=app) as fg:
            worktime.check(at, idle=idle)
        return fg

    def test_off_by_default_nothing_is_noted_and_the_program_is_not_even_asked(self):
        fg = self._tick(datetime(2026, 11, 19, 10, 0))
        fg.assert_not_called()
        self.assertEqual(worktime.apps(date(2026, 11, 19), date(2026, 11, 20)), {})

    def test_on_the_worked_minutes_go_to_the_program_in_front_and_a_meeting_to_meeting(self):
        update_settings({"apps_track": "true"})
        t = datetime(2026, 11, 19, 10, 0)
        for m in range(30):
            self._tick(t + timedelta(minutes=m), "outlook")
        for m in range(30, 40):
            self._tick(t + timedelta(minutes=m), "chrome")
        for m in range(40, 50):
            self._tick(t + timedelta(minutes=m), "ms-teams", idle=900, meeting=True)  # a recording: no input needed
        self._tick(t + timedelta(minutes=60), "excel", idle=900)  # away: no minute
        self.assertEqual(worktime.apps(date(2026, 11, 19), date(2026, 11, 20)), {"outlook": 30, "chrome": 10, worktime.MEETING: 10})
        worktime.clear_apps()
        self.assertEqual(worktime.apps(date(2026, 11, 19), date(2026, 11, 20)), {})
        self.assertEqual(worktime.app_name("ms-teams"), "Teams")
        self.assertEqual(worktime.app_name("someapp"), "someapp")

    def test_an_unknown_program_still_counts_the_minute_as_work(self):
        update_settings({"apps_track": "true"})
        self._tick(datetime(2026, 11, 19, 11, 0), None)
        self.assertIn("2026-11-19", worktime.days(date(2026, 11, 19), date(2026, 11, 20)))
        self.assertEqual(worktime.apps(date(2026, 11, 19), date(2026, 11, 20)), {})

    def test_the_route_gives_the_period_and_the_one_before_and_deletes(self):
        from fastapi.testclient import TestClient

        from app import main

        update_settings({"apps_track": "true"})
        self._tick(datetime(2026, 11, 19, 10, 0), "outlook")
        self._tick(datetime(2026, 11, 12, 10, 0), "outlook")
        self._tick(datetime(2026, 11, 12, 10, 1), "outlook")
        c = TestClient(main.app, base_url="http://127.0.0.1:8790")
        c.cookies.set("vs_session_8790", main.SESSION_TOKEN)
        r = c.get("/api/worktime/apps", params={"start": "2026-11-16", "end": "2026-11-23"}).json()
        self.assertTrue(r["enabled"])
        self.assertEqual(r["apps"], [{"app": "outlook", "name": "Outlook", "minutes": 1, "before": 2}])
        self.assertEqual(c.get("/api/worktime/apps", params={"start": "2026-11-23", "end": "2026-11-16"}).status_code, 400)
        # the widget's own period «Год»: a year is taken, more is not
        self.assertEqual(c.get("/api/worktime/apps", params={"start": "2026-01-01", "end": "2027-01-01"}).status_code, 200)
        self.assertEqual(c.get("/api/worktime/apps", params={"start": "2025-01-01", "end": "2027-01-01"}).status_code, 400)
        self.assertEqual(c.delete("/api/worktime/apps").status_code, 200)
        self.assertEqual(worktime.apps(date(2026, 11, 1), date(2026, 11, 30)), {})


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
