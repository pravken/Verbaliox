import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest
from pathlib import Path

from app.settings_schema import clean

ROOT = Path(__file__).resolve().parent.parent


class StudioEntryTest(unittest.TestCase):
    """Asked by the user: the way to the studio (the captions and the text of a running recording) was not obvious. The
    recording capsule leads there, and a hint under it is shown once (a setting, not the page's localStorage)."""

    def test_the_hint_is_shown_until_closed_once(self):
        from app import database

        database.init_db()
        saved = database.get_all_settings().get("hint_studio_entry_seen")
        with database._db_lock:
            conn = database.get_connection()
            conn.execute("DELETE FROM settings WHERE key = 'hint_studio_entry_seen'")
            conn.commit()
            conn.close()
        try:
            database.init_db()
            self.assertEqual(database.get_all_settings()["hint_studio_entry_seen"], "false")
            database.update_settings({"hint_studio_entry_seen": clean("hint_studio_entry_seen", "true")})
            database.init_db()  # the next start keeps it
            self.assertEqual(database.get_all_settings()["hint_studio_entry_seen"], "true")
        finally:
            database.update_settings({"hint_studio_entry_seen": saved or "false"})

    def test_the_hint_setting_is_a_switch(self):
        self.assertEqual(clean("hint_studio_entry_seen", True), "true")
        with self.assertRaises(ValueError):
            clean("hint_studio_entry_seen", "maybe")

    def test_the_page_reads_and_saves_the_setting(self):
        shell = (ROOT / "static" / "js" / "shell.js").read_text(encoding="utf-8")
        self.assertIn("hint_studio_entry_seen !== 'true'", shell)
        self.assertIn("saveUiSetting('hint_studio_entry_seen', 'true')", shell)
        self.assertNotIn("localStorage", shell[shell.index("function recStudioHintSync"):shell.index("function recStudioChip")])



if __name__ == "__main__":
    unittest.main()
