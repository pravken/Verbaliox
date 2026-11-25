import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest

from app.settings_schema import as_int, clean, clean_all


class SettingsSchemaTest(unittest.TestCase):
    def test_switches_and_numbers(self):
        self.assertEqual(clean("auto_summary", True), "true")
        self.assertEqual(clean("auto_summary", "False"), "false")
        self.assertEqual(clean("num_speakers", "3"), "3")
        self.assertEqual(clean("num_speakers", 99), "20")
        self.assertEqual(clean("idle_unload_minutes", ""), "0")
        for key, bad in (("auto_summary", "yes"), ("num_speakers", "x"), ("date_folders", "x")):
            with self.assertRaises(ValueError):
                clean(key, bad)
        self.assertEqual(as_int("x", 0), 0)
        self.assertEqual(as_int("2.0", 0), 2)

    def test_addresses(self):
        self.assertEqual(clean("ollama_url", "http://192.168.1.5:11434"), "http://192.168.1.5:11434")
        for key, bad in (("ollama_url", "file:///etc/passwd"), ("ollama_url", "javascript:alert(1)"),
                         ("ollama_url", "http://user:pw@host")):
            with self.assertRaises(ValueError):
                clean(key, bad)

    def test_ollama_in_clear_text_only_on_this_computer_or_the_local_network(self):
        for ok in ("http://127.0.0.1:11434", "http://localhost:11434", "http://10.0.0.7:11434", "http://nas:11434",
                   "http://ollama.lan:11434", "http://box.local:11434", "https://ollama.example.com"):
            self.assertEqual(clean("ollama_url", ok), ok)
        for bad in ("http://ollama.example.com:11434", "http://8.8.8.8:11434"):  # the transcripts would cross the internet unencrypted
            with self.assertRaises(ValueError):
                clean("ollama_url", bad)

    def test_keys_the_program_writes_itself_are_refused(self):
        for key in ("clean_exit", "interrupted_job_runs", "economy_until", "summary_templates"):
            with self.assertRaises(ValueError):
                clean(key, "1")

    def test_calendar_and_folders(self):
        ics = tests.temp_dir(self) / "c.ics"
        ics.write_text("BEGIN:VCALENDAR\nEND:VCALENDAR\n")
        self.assertEqual(clean("calendar_ics", str(ics)), str(ics))
        self.assertEqual(clean("calendar_ics", "webcal://example.com/c.ics"), "webcal://example.com/c.ics")
        self.assertEqual(clean("calendar_ics", "outlook"), "outlook")
        self.assertEqual(clean("calendar_ics", ""), "")
        with self.assertRaises(ValueError):
            clean("calendar_ics", "/etc/hostname")  # not a calendar: never read
        self.assertEqual(clean("recordings_dir", "C:\\Users\\Анна\\Записи"), "C:\\Users\\Анна\\Записи")
        with self.assertRaises(ValueError):
            clean("recordings_dir", "relative\\folder")

    def test_other_keys(self):
        self.assertEqual(clean_all({"record_presets": '[{"id":"a"}]'}), {"record_presets": '[{"id":"a"}]'})
        with self.assertRaises(ValueError):
            clean("Bad Key", "x")
        with self.assertRaises(ValueError):
            clean("summary_templates", "x" * (300 * 1024))


class SettingsCacheTest(unittest.TestCase):
    """The settings are read once and kept until they are changed."""

    def test_read_once_copied_and_changed_by_update(self):
        from unittest import mock

        from app import database

        database.init_db()
        database.update_settings({"cache_probe": "a"})
        self.assertEqual(database.get_all_settings()["cache_probe"], "a")
        mine = database.get_all_settings()
        mine["cache_probe"] = "changed by a caller"
        with mock.patch.object(database, "get_connection", side_effect=AssertionError("read again")):
            self.assertEqual(database.get_all_settings()["cache_probe"], "a")  # kept, and not the caller's copy
        self.assertEqual(database.update_settings({"cache_probe": "b"})["cache_probe"], "b")
        self.assertEqual(database.get_all_settings()["cache_probe"], "b")
        # a change of the table by other means (a restored backup, the start) is read again after forget_settings
        conn = database.get_connection()
        conn.execute("UPDATE settings SET value = 'c' WHERE key = 'cache_probe'")
        conn.commit()
        conn.close()
        database.init_db()
        self.assertEqual(database.get_all_settings()["cache_probe"], "c")


if __name__ == "__main__":
    unittest.main()


class CaptionsDefaultTest(unittest.TestCase):
    """Asked by the user: captions load a recognition model, so a recording starts without them unless the
    user asked for them; a choice already made is kept by an update."""

    def test_off_for_a_new_install_kept_when_set(self):
        from app import database

        database.init_db()
        with database._db_lock:
            conn = database.get_connection()
            conn.execute("DELETE FROM settings WHERE key = 'live_captions_auto'")
            conn.commit()
            conn.close()
        database.init_db()  # a first start: the default is written
        self.assertEqual(database.get_all_settings()["live_captions_auto"], "false")
        database.update_settings({"live_captions_auto": "true"})
        database.init_db()  # an update: the user's choice stays
        self.assertEqual(database.get_all_settings()["live_captions_auto"], "true")
        database.update_settings({"live_captions_auto": "false"})
