import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest
from pathlib import Path
from unittest import mock

from app.settings_schema import clean

ROOT = Path(__file__).resolve().parent.parent


class StudioEntryTest(unittest.TestCase):
    """Asked by the user: the way to the studio (the captions and the text of a running recording) was not obvious. The
    recording capsule leads there, a hint under it is shown once (a setting, not the page's localStorage), and the
    tray menu has the studio while recording."""

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

    def _tray(self, recording):
        import run

        tc = run.TrayController.__new__(run.TrayController)
        tc._status = {"state": "recording" if recording else "idle", "text": "Идёт запись 00:12" if recording else "",
                      "recording": recording}
        tc._mf_default, tc._mf_grayed = 0x1000, 0x1
        tc._hotkey_spec, tc._dictation_spec = "Ctrl+Alt+R", "Ctrl+Alt+D"
        return tc

    def test_the_tray_has_the_studio_under_the_status_while_recording(self):
        items = self._tray(True).menu_items()
        labels = [label for label, _cmd, _f in items]
        self.assertEqual(labels[:3], ["Открыть Verbaliox", "Идёт запись 00:12", "Студия: субтитры и текст"])
        self.assertEqual(items[2][1], "studio")
        self.assertNotIn("studio", [cmd for _l, cmd, _f in self._tray(False).menu_items()])

    def test_the_tray_studio_opens_the_window_on_the_studio(self):
        tc = self._tray(True)
        tc.open_target = mock.Mock()
        tc.on_command("studio")
        tc.open_target.assert_called_once_with("studio")


if __name__ == "__main__":
    unittest.main()
