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

    def test_idle_speech_models_go_before_an_analysis_model(self):
        from app import asr_onnx, live

        worker = mock.MagicMock()
        worker.proc.poll.return_value = None
        with self._stage("summarizing"), mock.patch.object(live, "has_sessions", return_value=False), \
                mock.patch.object(live, "_worker", worker), \
                mock.patch.object(transcriber, "whisper_cache_key", return_value=("large-v3", "cuda", "float16")), \
                mock.patch.object(transcriber, "release_whisper_model") as rel, \
                mock.patch.object(asr_onnx, "loaded_models", return_value=[]), \
                mock.patch("app.diarizer.ecapa_loaded_on", return_value=None):
            self.assertEqual(vram.release_idle_speech_models(), ["whisper", "live"])
        rel.assert_called_once()
        worker._kill.assert_called_once()  # the captions' worker kept its Whisper after the recording
        with self._stage("transcribing"), mock.patch.object(transcriber, "release_whisper_model") as rel:
            self.assertEqual(vram.release_idle_speech_models(), [])  # in use: left alone
        rel.assert_not_called()

    def test_the_video_memory_left_to_the_system_is_not_counted_as_free(self):
        card = mock.patch.object(vram, "gpu_memory", return_value={"total_gb": 7.6, "free_gb": 6.0, "used_gb": 1.6})
        with card, mock.patch.object(vram, "ollama_loaded", return_value=[]):
            with mock.patch.object(vram, "_vram_reserve", return_value=0.0):
                self.assertTrue(vram.room_for_analysis("gemma4:e4b"))
            with mock.patch.object(vram, "_vram_reserve", return_value=0.5):
                self.assertFalse(vram.room_for_analysis("gemma4:e4b"))  # 5.5 GB left for 5.8: one at a time
                self.assertTrue(vram.room_for_analysis("gemma4:e2b"))

    def test_gemma4_and_speech_share_a_card_of_8_gb(self):
        card = lambda total, free: mock.patch.object(vram, "gpu_memory", return_value={  # noqa: E731
            "total_gb": total, "free_gb": free, "used_gb": total - free})
        no_reserve = mock.patch.object(vram, "_vram_reserve", return_value=0.0)
        no_reserve.start()
        self.addCleanup(no_reserve.stop)
        with mock.patch.object(vram, "ollama_loaded", return_value=[]):
            with card(7.6, 6.0):
                self.assertTrue(vram.room_for_analysis("gemma4:e4b"))
                self.assertFalse(vram.room_for_analysis("qwen3:8b"))  # not measured to share: alone as before
            with card(7.6, 4.0):
                self.assertFalse(vram.room_for_analysis("gemma4:e4b"))  # Whisper takes the room now
                self.assertTrue(vram.room_for_analysis("gemma4:e2b"))
            with card(6.0, 5.0):
                self.assertFalse(vram.room_for_analysis("gemma4:e2b"))  # a 6 GB card: one at a time
            with mock.patch.object(vram, "gpu_memory", return_value=None):
                self.assertFalse(vram.room_for_analysis("gemma4:e2b"))
        with card(7.6, 1.0), mock.patch.object(vram, "ollama_loaded", return_value=[{"name": "gemma4:e4b"}]):
            self.assertTrue(vram.room_for_analysis("gemma4:e4b"))  # already in the memory with the speech model
            self.assertFalse(vram.room_for_speech(3.0))  # and no room for one more speech model
        with card(10.0, 4.0):
            with mock.patch.object(vram, "ollama_loaded", return_value=[{"name": "gemma4:e4b"}]):
                self.assertTrue(vram.room_for_speech(3.0))
                self.assertFalse(vram.room_for_speech(5.0))  # large-v3 does not fit next to it
            with mock.patch.object(vram, "ollama_loaded", return_value=[{"name": "qwen3:8b"}]):
                self.assertFalse(vram.room_for_speech(3.0))

    def test_speech_models_stay_when_the_analysis_model_fits(self):
        from app import live

        with self._stage("summarizing"), mock.patch.object(live, "has_sessions", return_value=False), \
                mock.patch.object(vram, "room_for_analysis", return_value=True), \
                mock.patch.object(transcriber, "whisper_cache_key", return_value=("x", "cuda", "f")), \
                mock.patch.object(transcriber, "release_whisper_model") as rel:
            self.assertEqual(vram.release_idle_speech_models("gemma4:e4b"), [])
        rel.assert_not_called()
        with mock.patch.object(vram, "room_for_speech", return_value=True), \
                mock.patch.object(vram, "ollama_release_others") as others, \
                mock.patch.object(vram, "ollama_loaded", return_value=[{"name": "gemma4:e4b"}]):
            transcriber._release_analysis_models(3.0)
        others.assert_not_called()  # the analysis model stays next to GigaAM

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
        # a click on the notification opens the studio while recording, the recording once saved
        self.assertEqual((a["target"], b["target"]), ("studio", "last"))
        self.assertEqual(app_status.take_notices(), [])  # shown once
        self.assertLessEqual(len(a["title"]), 63)
        self.assertLessEqual(len(a["text"]), 255)


class AfterWorkUnloadTest(unittest.TestCase):
    """The analysis model leaves the memory once its work is done (app/ollama_client.py)."""

    def test_unloaded_after_the_last_answer_not_between_answers(self):
        import time

        from app import ollama_client as oc

        with mock.patch.object(oc, "AFTER_WORK_UNLOAD_SEC", 0.2), mock.patch.object(oc, "_speech_job_waits", return_value=True), \
                mock.patch("app.vram.ollama_release_others", return_value=["qwen3.5:4b"]) as rel:
            oc._work_started()
            oc._work_done()          # an overview asks again at once: the timer is put off
            oc._work_started()
            time.sleep(0.35)
            rel.assert_not_called()  # an answer is being written
            oc._work_done()
            time.sleep(0.4)
            rel.assert_called_once_with()

    def test_without_a_transcription_waiting_the_model_stays_for_the_next_question(self):
        import time

        from app import ollama_client as oc

        with mock.patch.object(oc, "AFTER_WORK_UNLOAD_SEC", 0.1), mock.patch.object(oc, "_speech_job_waits", return_value=False), \
                mock.patch("app.vram.ollama_release_others", return_value=[]) as rel:
            oc._work_started()
            oc._work_done()
            time.sleep(0.3)
            rel.assert_not_called()  # the idle setting (keep_alive) decides when it goes


class SpeakerMarksTest(unittest.TestCase):
    """«Сейчас говорит» marked in the studio names the voices (app/transcriber.apply_speaker_marks)."""

    def test_the_voice_heard_at_the_marks_gets_the_name(self):
        speakers = {f"SPEAKER_0{i}": {"name": f"Участник {i + 1}"} for i in range(3)}
        segments = [{"start": 0, "end": 10, "speaker": "SPEAKER_00"}, {"start": 10, "end": 20, "speaker": "SPEAKER_01"},
                    {"start": 20, "end": 30, "speaker": "SPEAKER_02"}, {"start": 30, "end": 40, "speaker": "SPEAKER_01"}]
        marks = [{"at": 12, "name": "Марина"}, {"at": 35, "name": "Марина"}, {"at": 3, "name": "Павел"},
                 {"at": 22, "name": "Марина"},   # a slip: outvoted by the other two
                 {"at": 41.5, "name": "Борис"}]   # just after the last phrase: its speaker, already Марина's
        self.assertEqual(transcriber.apply_speaker_marks(speakers, segments, marks), 2)
        self.assertEqual(speakers["SPEAKER_01"]["name"], "Марина")
        self.assertEqual(speakers["SPEAKER_00"]["name"], "Павел")
        self.assertEqual(speakers["SPEAKER_02"]["name"], "Участник 3")  # one name per voice


class TeamsMarksByWordsTest(unittest.TestCase):
    """A Teams caption line names the voice of the phrase with its words, even when it lags behind."""

    def test_the_words_win_over_the_moment(self):
        speakers = {"SPEAKER_00": {"name": "Участник 1"}, "SPEAKER_01": {"name": "Участник 2"}}
        segments = [{"start": 0, "end": 6, "speaker": "SPEAKER_00", "text": "Мы можем сейчас контур сделать? Да вот примерный контур."},
                    {"start": 6, "end": 12, "speaker": "SPEAKER_01", "text": "Горящей земли, а потом будем отрезать кусочками."}]
        # the caption of the first phrase came late: its moment falls on the second one
        marks = [{"at": 8.0, "name": "Pavel Orlov", "text": "Мы можем сейчас контур сделать? Да вот вот примерный контур вот."}]
        self.assertEqual(transcriber.apply_speaker_marks(speakers, segments, marks), 1)
        self.assertEqual(speakers["SPEAKER_00"]["name"], "Pavel Orlov")
        self.assertEqual(speakers["SPEAKER_01"]["name"], "Участник 2")
