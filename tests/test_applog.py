"""The log files of the data folder do not grow without end."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import applog


class SideLogsTest(unittest.TestCase):
    def test_crash_and_update_logs_keep_their_newest_part(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(applog, "LOG_DIR", Path(d)), \
                mock.patch.object(applog, "SIDE_LOG_MAX", 1000), mock.patch.object(applog, "SIDE_LOG_KEEP", 300):
            big = "".join(f"line {i:04d}\n" for i in range(500)).encode()
            (Path(d) / "update.log").write_bytes(big)
            (Path(d) / "crash.log").write_bytes(b"small\n")
            applog.trim_side_logs()
            kept = (Path(d) / "update.log").read_bytes()
            self.assertLessEqual(len(kept), 300)
            self.assertTrue(kept.startswith(b"line ") and kept.endswith(b"line 0499\n"), kept[:40])
            self.assertEqual((Path(d) / "crash.log").read_bytes(), b"small\n")
            applog.trim_side_logs()  # nothing to trim, no file missing is an error
            self.assertEqual((Path(d) / "update.log").read_bytes(), kept)


if __name__ == "__main__":
    unittest.main()


class ScrubTest(unittest.TestCase):
    """The log is sent with a problem report: no user name, e-mail, token or call link in it."""

    def test_personal_data_is_cut(self):
        from app.applog import scrub

        line = (r'File "C:\Users\Test User\AppData\Local\Verbaliox\app.py" '
                "mail someone@example.com /?token=abc123&x=1 https://teams.microsoft.com/l/meetup-join/19abc")
        out = scrub(line)
        for gone in ("Test User", "someone@example.com", "abc123", "meetup-join"):
            self.assertNotIn(gone, out)
        self.assertIn(r"C:\Users\<user>\AppData", out)
        self.assertEqual(scrub("3/4 done, 12 s"), "3/4 done, 12 s")

    def test_one_time_addresses_cookies_and_bearer_tokens_are_cut(self):
        from app.applog import scrub

        out = scrub("GET /?boot=Zk3_-q9 Cookie: vs_session_8765=s3cr3t; Authorization: Bearer eyJhbGc.x-y_z")
        for gone in ("Zk3_-q9", "s3cr3t", "eyJhbGc"):
            self.assertNotIn(gone, out)

    def test_the_head_of_the_log_hides_the_windows_user(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(applog, "LOG_DIR", Path(tmp)), mock.patch.object(applog, "LOG_FILE", Path(tmp) / "v.log"), \
                mock.patch.object(applog.sys, "executable", r"C:\Users\Test User\Verbaliox\.venv\Scripts\python.exe"), \
                mock.patch.object(applog, "_file", None), mock.patch.object(applog.faulthandler, "enable"), \
                mock.patch.object(applog.sys, "stdout"), mock.patch.object(applog.sys, "stderr"):
            applog.start_file_log()
            applog._file.close()
            head = (Path(tmp) / "v.log").read_text(encoding="utf-8")
        self.assertNotIn("Test User", head)
        self.assertIn(r"C:\Users\<user>", head)

    def test_calendar_links_are_cut(self):
        """A traceback of the calendar's reading prints its link; the secret is in the path or the query."""
        from app.applog import scrub

        links = [
            "https://calendar.google.com/calendar/ical/team%40example.com/private-0a1b2c3d4e5f/basic.ics",
            "webcal://example.com/feeds/secret-feed-42.ics?v=2",
            "https://outlook.office365.com/owa/calendar/abc/def0123/reachcalendar.ics",
            "https://calendar.example.ru/export/ics.xml?private_token=f00ba4&tz_id=Europe/Moscow",
            "https://cloud.example.com/remote.php/dav/public-calendars/Zx9Qk2?export",
        ]
        for link in links[:4]:
            out = scrub(f"httpx.HTTPStatusError: Client error '404 Not Found' for url '{link}'")
            self.assertIn("<calendar link>", out, link)
            for gone in ("private-0a1b2c3d4e5f", "secret-feed-42", "def0123", "f00ba4"):
                self.assertNotIn(gone, out)
        self.assertEqual(scrub("see https://example.com/docs/page"), "see https://example.com/docs/page")

    def test_the_calendar_link_of_the_settings_is_cut_whatever_its_form(self):
        from app import applog

        link = "https://cloud.example.com/remote.php/dav/public-calendars/Zx9Qk2?export"
        self.addCleanup(applog._HIDDEN.clear)
        applog.hide_in_log(link)
        applog.hide_in_log("abc")  # too short: never hidden
        out = applog.scrub(f"ConnectError for url '{link}' abc")
        self.assertNotIn("Zx9Qk2", out)
        self.assertIn("<calendar link>", out)
        self.assertTrue(out.endswith(" abc"))
