import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest
from unittest import mock

from fastapi import HTTPException

from app.settings_schema import clean

KEYS = ("live_whisper_model", "live_translate_model_quality", "live_translate_model_fast", "live_translate_to",
        "live_speed", "live_captions_auto")


class LivePrefsTest(unittest.TestCase):
    """Asked by the user: the captions switched on in the studio, the caption model and the translation model stay as
    chosen. They are settings (the page's localStorage is per port and was lost), Settings shows the same values."""

    def setUp(self):
        from app import database

        database.init_db()
        self._saved = {k: v for k, v in database.get_all_settings().items() if k in KEYS}

    def tearDown(self):
        from app import database

        with database._db_lock:
            conn = database.get_connection()
            conn.execute(f"DELETE FROM settings WHERE key IN ({','.join('?' * len(KEYS))})", KEYS)
            conn.commit()
            conn.close()
        database.update_settings(self._saved)

    def _session(self, speed="quality", translate_to=None):
        from app import live

        with mock.patch.object(live, "caption_onnx_model", return_value=None):
            return live.LiveSession("ru", translate_to, speed=speed)

    def test_schema(self):
        self.assertEqual(clean("live_speed", "fast"), "fast")
        self.assertEqual(clean("live_translate_to", ""), "")
        self.assertEqual(clean("live_translate_to", "auto"), "auto")
        self.assertEqual(clean("live_translate_to", "en"), "en")
        self.assertEqual(clean("live_translate_model_fast", ""), "")
        for key, bad in (("live_speed", "slow"), ("live_translate_to", "xx-zz"), ("live_translate_model_quality", "a b"),
                         ("live_whisper_model", "someone/any-repo")):
            with self.assertRaises(ValueError):
                clean(key, bad)

    def test_old_settings_have_no_language_or_mode(self):
        """Absent until chosen: the page takes what an earlier version kept in its localStorage once."""
        from app import database

        database.init_db()
        s = database.get_all_settings()
        self.assertNotIn("live_translate_to", s)
        self.assertNotIn("live_speed", s)
        self.assertEqual(s["live_translate_model_quality"], "")

    def test_session_starts_with_saved_translation_model_of_its_mode(self):
        from app.database import update_settings

        update_settings({"live_translate_model_quality": "qwen3:8b", "live_translate_model_fast": "gemma4:e2b"})
        self.assertEqual(self._session("quality").state()["translate_choice"], "qwen3:8b")
        s = self._session("fast")
        self.assertEqual(s.state()["translate_choice"], "gemma4:e2b")
        s.configure(None, "quality")  # the mode switched: the model saved for it
        self.assertEqual(s.state()["translate_choice"], "qwen3:8b")

    def test_choice_in_studio_saved_for_the_mode_in_use(self):
        from app.database import get_all_settings

        s = self._session("fast")
        s.translator = mock.Mock()
        s.set_translate_model("gemma4:e2b")
        self.assertEqual(get_all_settings()["live_translate_model_fast"], "gemma4:e2b")
        self.assertEqual(get_all_settings()["live_translate_model_quality"], "")
        s.translator.reload_model.assert_called_once_with()
        s.set_translate_model("", "quality")  # «Авто» of «Качество», chosen with the mode
        self.assertEqual(get_all_settings()["live_translate_model_quality"], "")
        self.assertEqual(get_all_settings()["live_translate_model_fast"], "gemma4:e2b")
        self.assertEqual(s.speed, "quality")
        s.translator.configure.assert_called_with(speed="quality")
        # the next session of «Скорость» takes it
        self.assertEqual(self._session("fast").state()["translate_choice"], "gemma4:e2b")

    def test_config_endpoint_saves_and_refuses_bad_names(self):
        import app.main  # noqa: F401 - the routers are imported by the app
        from app import live
        from app.api.recording import LiveConfigPayload, api_live_config
        from app.database import get_all_settings

        s = self._session("quality")
        with mock.patch.object(live, "get_session", return_value=s), \
             mock.patch.object(live, "caption_onnx_model", return_value=None):
            api_live_config(s.id, LiveConfigPayload(caption_model="large-v3-turbo", translate_model="qwen3:8b", speed="quality"))
            self.assertEqual(get_all_settings()["live_whisper_model"], "large-v3-turbo")
            self.assertEqual(get_all_settings()["live_translate_model_quality"], "qwen3:8b")
            for bad in (LiveConfigPayload(caption_model="someone/any-repo"), LiveConfigPayload(translate_model="a b")):
                with self.assertRaises(HTTPException) as e:
                    api_live_config(s.id, bad)
                self.assertEqual(e.exception.status_code, 400)
        self.assertEqual(get_all_settings()["live_whisper_model"], "large-v3-turbo")

    def test_settings_endpoint_keeps_studio_choices(self):
        import app.main  # noqa: F401 - the routers are imported by the app
        from app.api.system import SettingsUpdatePayload, api_update_settings
        from app.database import get_all_settings

        api_update_settings(SettingsUpdatePayload(settings={
            "live_captions_auto": "true", "live_translate_to": "auto", "live_speed": "fast",
            "live_translate_model_fast": "gemma4:e2b", "live_whisper_model": "large-v3-turbo"}))
        s = get_all_settings()
        self.assertEqual((s["live_captions_auto"], s["live_translate_to"], s["live_speed"], s["live_translate_model_fast"],
                          s["live_whisper_model"]), ("true", "auto", "fast", "gemma4:e2b", "large-v3-turbo"))
        with self.assertRaises(HTTPException):
            api_update_settings(SettingsUpdatePayload(settings={"live_speed": "slow"}))

    def test_settings_change_reaches_running_captions(self):
        import app.main  # noqa: F401 - the routers are imported by the app
        from app import live
        from app.api.system import SettingsUpdatePayload, api_update_settings

        s = self._session("fast")
        s.translator = mock.Mock()
        with mock.patch.dict(live._sessions, {s.id: s}):
            api_update_settings(SettingsUpdatePayload(settings={"live_translate_model_fast": "gemma4:e2b"}))
        self.assertEqual(s.state()["translate_choice"], "gemma4:e2b")
        s.translator.reload_model.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
