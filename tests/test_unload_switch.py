"""«Unload» as a switch (app/vram.py): a model the running job does not use goes at once; one in use
goes once the work is stopped."""

import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest
from unittest import mock

try:
    from app import transcriber, vram
except ImportError:  # app dependencies are not installed
    vram = None


@unittest.skipIf(vram is None, "app dependencies not installed")
class UnloadSwitchTest(unittest.TestCase):
    def _stage(self, stage):
        return mock.patch.object(vram, "job_stage", return_value=stage)

    def test_whisper_goes_while_the_overview_is_written(self):
        with self._stage("summarizing"), mock.patch.object(transcriber, "release_whisper_model") as rel, \
                mock.patch.object(vram, "vram_snapshot", return_value={}):
            vram.unload("whisper")
        rel.assert_called_once()

    def test_whisper_in_use_is_refused_without_stop(self):
        with self._stage("transcribing"), mock.patch.object(transcriber, "release_whisper_model") as rel:
            with self.assertRaises(RuntimeError):
                vram.unload("whisper")
        rel.assert_not_called()

    def test_stop_cancels_the_work_then_unloads(self):
        # stop_work ends the job: the stage is gone when unload looks
        with self._stage(None), mock.patch.object(vram, "stop_work") as stop, \
                mock.patch.object(transcriber, "release_whisper_model") as rel, \
                mock.patch.object(vram, "vram_snapshot", return_value={}):
            vram.unload("whisper", stop=True)
        stop.assert_called_once()
        rel.assert_called_once()

    def test_one_analysis_model_at_a_time(self):
        from app import live

        asked = []
        client = mock.MagicMock()
        client.__enter__.return_value.post.side_effect = lambda url, json: asked.append(json["model"])
        loaded = [{"name": "qwen3:8b"}, {"name": "bge-m3:latest"}, {"name": "gemma3"}]
        with mock.patch.object(vram, "ollama_loaded", return_value=loaded), \
                mock.patch.object(live, "has_sessions", return_value=False), \
                mock.patch.object(vram.httpx, "Client", return_value=client):
            self.assertEqual(vram.ollama_release_others(keep="gemma3:latest"), ["qwen3:8b", "bge-m3:latest"])
        self.assertEqual(asked, ["qwen3:8b", "bge-m3:latest"])
        with mock.patch.object(vram, "ollama_loaded", return_value=loaded), \
                mock.patch.object(live, "has_sessions", return_value=True):
            self.assertEqual(vram.ollama_release_others(), [])  # live captions translate meanwhile

    def test_stop_all_jobs_cancels_queued_and_running(self):
        with transcriber._jobs_lock:
            transcriber._active_jobs.update({901, 902})
        try:
            self.assertEqual(transcriber.stop_all_jobs(), 2)
            self.assertTrue(transcriber._cancel_wanted(901) and transcriber._cancel_wanted(902))
        finally:
            with transcriber._jobs_lock:
                transcriber._active_jobs.difference_update({901, 902})
                transcriber._cancel_requested.difference_update({901, 902})


if __name__ == "__main__":
    unittest.main()


class AutoRecordNoticeTest(unittest.TestCase):
    """A recording the app starts or stops by itself gets a short Windows notification (run.py shows it)."""

    def test_start_and_stop_are_announced(self):
        from app import app_status
        from app.database import init_db, update_settings

        init_db()
        update_settings({"record_hotkey": "Ctrl+Alt+R"})
        app_status.take_notices()
        app_status.auto_recording_notice(True, "call", "Microsoft Teams")
        app_status.auto_recording_notice(False, "calendar", "Планёрка")
        a, b = app_status.take_notices()
        self.assertEqual(a["title"], "● Идёт запись")
        self.assertIn("Microsoft Teams · звонок", a["text"])
        self.assertIn("Ctrl+Alt+R", a["text"])
        self.assertEqual(b["title"], "Запись сохранена")
        self.assertIn("Планёрка", b["text"])
        self.assertEqual(app_status.take_notices(), [])  # shown once
        self.assertLessEqual(len(a["title"]), 63)
        self.assertLessEqual(len(a["text"]), 255)
