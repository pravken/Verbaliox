"""What Windows shows from the tray side follows the UI language (app/ui_lang.py): the tray's notices and
menu, toasts, meeting reminders. The language is chosen when a text is shown, not at import."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import os
import unittest
from unittest import mock

from app import app_status, paths, ui_lang


def set_lang(lang):
    """As the page does it (POST /api/ui/lang)."""
    import app.main  # noqa: F401 - the routes load through the app
    from app.api.recording import UiLangPayload, api_ui_lang

    paths.DATA_DIR.mkdir(parents=True, exist_ok=True)
    return api_ui_lang(UiLangPayload(lang=lang))["lang"]


class UiLangTest(unittest.TestCase):
    def tearDown(self):
        try:
            (paths.DATA_DIR / ui_lang.FILE_NAME).unlink()
        except OSError:
            pass
        app_status.take_notices()

    def test_russian_until_the_page_chooses(self):
        try:
            (paths.DATA_DIR / ui_lang.FILE_NAME).unlink()
        except OSError:
            pass
        self.assertEqual(ui_lang.current(), "ru")
        self.assertEqual(ui_lang.tr("Готово", "Ready"), "Готово")

    def test_the_page_switches_it_and_the_next_text_follows(self):
        self.assertEqual(set_lang("en"), "en")
        self.assertEqual((paths.DATA_DIR / "ui-lang.txt").read_text(encoding="utf-8"), "en")
        self.assertEqual(ui_lang.tr("Готово", "Ready"), "Ready")
        self.assertEqual(set_lang("ru"), "ru")
        self.assertEqual(ui_lang.tr("Готово", "Ready"), "Готово")
        self.assertEqual(set_lang("de"), "ru")  # anything else is Russian

    def test_the_file_is_read_again_only_when_it_changes(self):
        set_lang("en")
        self.assertTrue(ui_lang.is_en())
        path = paths.DATA_DIR / ui_lang.FILE_NAME
        with mock.patch("pathlib.Path.read_text", side_effect=AssertionError("read again")):
            self.assertTrue(ui_lang.is_en())  # unchanged: from the cache
        path.write_text("ru", encoding="utf-8")  # changed outside (the launcher, another process)
        st = path.stat()
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
        self.assertEqual(ui_lang.current(), "ru")

    def test_counts(self):
        set_lang("en")
        self.assertEqual(ui_lang.count(1, "минуту", "минуты", "минут", "minute", "minutes"), "1 minute")
        self.assertEqual(ui_lang.count(5, "минуту", "минуты", "минут", "minute", "minutes"), "5 minutes")
        set_lang("ru")
        self.assertEqual(ui_lang.count(22, "минуту", "минуты", "минут", "minute", "minutes"), "22 минуты")


class NoticesTest(unittest.TestCase):
    def tearDown(self):
        set_lang("ru")
        app_status.take_notices()

    def test_auto_recording_notice(self):
        set_lang("en")
        with mock.patch("app.database.get_all_settings", return_value={"record_hotkey": "Ctrl+Alt+R"}):
            a = app_status.auto_recording_notice(True, "call", "Microsoft Teams")
        self.assertEqual(a["title"], "● Recording")
        self.assertEqual(a["text"], "Microsoft Teams · call\nTo stop: Ctrl+Alt+R or in the Verbaliox window")
        b = app_status.auto_recording_notice(False, "calendar", "Weekly sync")
        self.assertEqual((b["title"], b["text"]), ("Recording saved", "Weekly sync · sent for transcription"))
        set_lang("ru")
        b = app_status.auto_recording_notice(False, "calendar", "Планёрка")
        self.assertEqual((b["title"], b["text"]), ("Запись сохранена", "Планёрка · отправлена на расшифровку"))

    def test_tooltip(self):
        job = [{"state": "running", "kind": "transcribe", "title": "Weekly sync", "progress": 40},
               {"state": "waiting", "kind": "dub", "title": "x"}]
        with mock.patch("app.transcriber.queue_snapshot", return_value=job):
            set_lang("en")
            self.assertEqual(app_status.snapshot()["text"], "Transcription: Weekly sync · 40% · queued: 1")
            set_lang("ru")
            self.assertEqual(app_status.snapshot()["text"], "Распознавание: Weekly sync · 40% · в очереди: 1")
        with mock.patch("app.transcriber.queue_snapshot", return_value=[]), \
                mock.patch.object(app_status, "background", return_value=[]):
            set_lang("en")
            self.assertEqual(app_status.snapshot()["text"], "Ready")

    def test_meeting_reminder(self):
        from app import brief_notice

        set_lang("en")
        self.assertEqual(brief_notice._ahead_text(58), "In 58 seconds")
        self.assertEqual(brief_notice._ahead_text(60), "In 1 minute")
        set_lang("ru")
        self.assertEqual(brief_notice._ahead_text(120), "Через 2 минуты")

    def test_toast_close_button(self):
        from app import toast

        set_lang("en")
        xml = toast.toast_xml("Starting now", "Click to join", [("Join", "msteams:/l/x")])
        self.assertIn('content="Join"', xml)
        self.assertIn('content="Close"', xml)
        set_lang("ru")
        self.assertIn('content="Закрыть"', toast.toast_xml("a", "b", []))

    def test_dictation_note(self):
        from app import dictation

        set_lang("en")
        # no translator of the captions: the test never asks (or starts) an Ollama of the computer it runs on
        with mock.patch("app.live_translate.phrase_language", return_value="ru"), \
                mock.patch("app.live_translate.translation_model", return_value=None), \
                mock.patch("app.llm.target", side_effect=RuntimeError("Ollama is off")):
            text, note = dictation.translate("привет", "en")
        self.assertEqual((text, note), ("привет", "Translation unavailable: Ollama is off"))


class TrayTest(unittest.TestCase):
    def setUp(self):
        import run
        from app.database import init_db

        init_db()
        self.run = run
        tc = run.TrayController.__new__(run.TrayController)
        tc._status = {"state": "idle", "text": "", "recording": False}
        tc._mf_default, tc._mf_grayed = 0x1000, 0x1
        tc._hotkey_spec, tc._dictation_spec = "Ctrl+Alt+R", "Ctrl+Alt+D"
        tc.tray = mock.Mock()
        tc._quiet = lambda: False
        tc._window_in_front = lambda: False
        self.tc = tc

    def tearDown(self):
        set_lang("ru")

    def test_the_menu_is_relabelled_at_its_next_opening(self):
        set_lang("en")
        labels = [label for label, _cmd, _f in self.tc.menu_items() if label]
        self.assertEqual(labels, ["Open Verbaliox", "● Start recording\tCtrl+Alt+R", "Record with preset",
                                  "Dictation\tCtrl+Alt+D", "Do not disturb in meetings", "Recording only", "Exit"])
        presets = next(cmd for label, cmd, _f in self.tc.menu_items() if label == "Record with preset")
        self.assertIn(("Call  ★", "record:call", 0), presets)
        set_lang("ru")
        self.assertEqual(self.tc.menu_items()[0][0], "Открыть Verbaliox")

    def test_job_done_notice(self):
        set_lang("en")
        self.tc._job_finished({"id": 7, "kind": "transcribe"}, {"id": 7, "title": "Weekly sync", "status": "done"})
        self.tc.tray.notify.assert_called_with("Transcription complete", "Weekly sync", warning=False,
                                               target="meeting:7:transcribe")
        self.tc._job_finished({"id": 7, "kind": "dub"}, {"id": 7, "title": "Weekly sync", "status": "failed"})
        self.tc.tray.notify.assert_called_with("Dubbing: failed", "Weekly sync", warning=True, target="meeting:7:dub")
        set_lang("ru")
        self.tc._job_finished({"id": 7, "kind": "transcribe"}, {"id": 7, "title": "Планёрка", "status": "done"})
        self.tc.tray.notify.assert_called_with("Распознавание завершено", "Планёрка", warning=False,
                                               target="meeting:7:transcribe")

    def test_hotkey_failure_notice(self):
        from app.hotkey import dictation_hotkey_state, hotkey_state, translate_hotkey_state

        set_lang("en")
        saved = [dict(s) for s in (hotkey_state, dictation_hotkey_state, translate_hotkey_state)]
        try:
            hotkey_state.update(ok=False, spec="Ctrl+Alt+R", error="Сочетание уже занято другой программой")
            dictation_hotkey_state.update(ok=True)
            translate_hotkey_state.update(ok=True)
            self.tc._warn_hotkey_failures()
        finally:
            for s, old in zip((hotkey_state, dictation_hotkey_state, translate_hotkey_state), saved):
                s.clear()
                s.update(old)
        self.tc.tray.notify.assert_called_once_with(
            "The recording hotkey does not work",
            "Ctrl+Alt+R: Another program already uses this combination. It can be changed in Settings → Recording",
            warning=True, target="settings:hotkeys")
        self.assertEqual(self.run.hotkey_error_text(
            "На раскладке клавиатуры это сочетание (AltGr) печатает «ł» — выберите другое"),
            "On a keyboard layout this combination (AltGr) types “ł”: choose another one")

    def test_hotkey_result_notice(self):
        set_lang("en")
        self.tc._hotkey_wait = (False, 0)
        self.tc._check_hotkey_result({"recording": True})
        self.tc.tray.notify.assert_called_with("Recording started", "Press Ctrl+Alt+R to stop", warning=False,
                                               target="studio")


if __name__ == "__main__":
    unittest.main()
