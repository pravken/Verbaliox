import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import threading
import time
import unittest
from unittest import mock

try:
    from app import idle_unload, live, transcriber
    from app.database import create_meeting, init_db, update_settings
    from app.live_translate import LiveTranslator
except ImportError:  # the release CI runs without the app's packages
    idle_unload = None


def _no_ollama():
    """Nothing here reaches an Ollama, the real one of the computer the tests run on included."""
    return [mock.patch("app.vram.ollama_loaded", side_effect=AssertionError("Ollama asked")),
            mock.patch("app.vram.ollama_unload", side_effect=AssertionError("Ollama asked")),
            mock.patch.object(idle_unload.httpx, "Client", side_effect=AssertionError("Ollama asked"))]


@unittest.skipIf(idle_unload is None, "app dependencies not installed")
class UnloadAfterWorkTest(unittest.TestCase):
    """The analysis model stayed in the video memory 10 minutes after a processing, and live captions with
    translation that began meanwhile found 0.4 GB left on a card of 10 GB (measured on the user's computer)."""

    def setUp(self):
        init_db()
        update_settings({"idle_unload_minutes": "10", "ollama_model": "gemma4:e4b"})
        idle_unload._after_work = None
        idle_unload._interactive.clear()
        self.patches = _no_ollama() + [
            mock.patch.object(idle_unload, "_ollama_used", {"gemma4:e4b", "hy-mt3:7b"}),
            mock.patch.object(transcriber, "running_job_kind", return_value=None),
            mock.patch("app.ollama_client.analysis_running", return_value=[]),
            mock.patch.object(live, "has_sessions", return_value=False),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        idle_unload._after_work = None
        idle_unload._interactive.clear()

    def test_everything_goes_a_minute_after_the_processing(self):
        idle_unload.work_done("the processing finished")
        at = idle_unload._after_work[0]
        with mock.patch.object(idle_unload, "unload_now", return_value={"released": ["whisper"]}) as unload:
            self.assertIsNone(idle_unload.tick(now=at + 30))
            unload.assert_not_called()
            self.assertLessEqual(idle_unload.status()["unload_in_sec"], 60)
            idle_unload.tick(now=at + idle_unload.AFTER_WORK_SEC + 1)
            unload.assert_called_once_with(keep=[])
            self.assertIsNone(idle_unload._after_work)
            idle_unload.tick(now=at + 2 * idle_unload.AFTER_WORK_SEC)  # once
            unload.assert_called_once()

    def test_a_use_within_the_minute_cancels_it(self):
        idle_unload.work_done("the processing finished")
        at = idle_unload._after_work[0]
        idle_unload.touch()  # a new job, a question
        with mock.patch.object(idle_unload, "unload_now") as unload:
            idle_unload.tick(now=at + idle_unload.AFTER_WORK_SEC + 1)
        unload.assert_not_called()

    def test_the_captions_own_use_does_not_cancel_it(self):
        idle_unload.work_done("the processing finished")
        idle_unload.touch(captions=True)
        idle_unload.touch("hy-mt3:7b", captions=True)
        self.assertIsNotNone(idle_unload._after_work)

    def test_never_with_the_setting_off(self):
        update_settings({"idle_unload_minutes": "0"})
        idle_unload.work_done("the processing finished")
        self.assertIsNone(idle_unload._after_work)

    def test_a_job_running_at_the_end_of_the_minute_keeps_the_models(self):
        idle_unload.work_done("the processing finished")
        at = idle_unload._after_work[0]
        with mock.patch.object(transcriber, "running_job_kind", return_value="transcribe"), \
                mock.patch.object(idle_unload, "unload_now") as unload:
            idle_unload.tick(now=at + idle_unload.AFTER_WORK_SEC + 1)
        unload.assert_not_called()
        self.assertIsNone(idle_unload._after_work)  # the idle limit counts from the end of it

    def test_a_question_of_the_user_keeps_its_model_for_the_idle_limit(self):
        idle_unload.touch("gemma4:e4b")  # a question to the assistant: not a queued job
        self.assertEqual(idle_unload.ollama_keep_alive(), "10m")
        idle_unload.work_done("the processing finished")
        at = idle_unload._after_work[0]
        with mock.patch.object(idle_unload, "unload_now", return_value={"released": ["whisper"]}) as unload:
            idle_unload.tick(now=at + idle_unload.AFTER_WORK_SEC + 1)
        unload.assert_called_once_with(keep=["gemma4:e4b"])
        # later than the idle limit it goes too
        idle_unload._interactive["gemma4:e4b"] = time.time() - 11 * 60
        idle_unload.work_done("the processing finished")
        at = idle_unload._after_work[0]
        with mock.patch.object(idle_unload, "unload_now", return_value={"released": []}) as unload:
            idle_unload.tick(now=at + idle_unload.AFTER_WORK_SEC + 1)
        unload.assert_called_once_with(keep=[])

    def test_unload_now_leaves_the_kept_model(self):
        posted = []
        client = mock.MagicMock()
        client.__enter__.return_value.post.side_effect = lambda url, json: posted.append(json["model"])
        with mock.patch.object(idle_unload, "release_speech_models", return_value=[]), \
                mock.patch("app.vram.ollama_loaded", return_value=[{"name": "gemma4:e4b"}, {"name": "hy-mt3:7b"}]), \
                mock.patch.object(idle_unload.httpx, "Client", return_value=client):
            out = idle_unload.unload_now(keep=["gemma4:e4b"])
        self.assertEqual(posted, ["hy-mt3:7b"])
        self.assertEqual(out["released"], ["hy-mt3:7b"])

    def test_captions_open_at_the_end_of_the_minute_keep_their_models(self):
        idle_unload.work_done("the processing finished")
        at = idle_unload._after_work[0]
        with mock.patch.object(live, "has_sessions", return_value=True), \
                mock.patch.object(idle_unload, "free_for_captions", return_value=["gemma4:e4b"]) as free, \
                mock.patch.object(idle_unload, "unload_now") as unload:
            idle_unload.tick(now=at + idle_unload.AFTER_WORK_SEC + 1)
        free.assert_called_once()
        unload.assert_not_called()


@unittest.skipIf(idle_unload is None, "app dependencies not installed")
class NoGapBetweenTranscriptionAndAnalysisTest(unittest.TestCase):
    def setUp(self):
        init_db()
        update_settings({"idle_unload_minutes": "10"})
        idle_unload._after_work = None
        idle_unload._interactive.clear()

    def test_the_automatic_analysis_runs_in_the_job_so_nothing_is_unloaded_before_it(self):
        mid = create_meeting(title="Тест", filename="a.wav", media_path="a.wav")["id"]
        seen = {}

        def job(meeting_id):
            # the transcription is done; the analysis begins a moment later in the same job
            seen["mark_after_transcription"] = idle_unload._after_work
            with mock.patch.object(idle_unload, "unload_now") as unload:
                idle_unload.tick(now=time.time() + 3600)  # even long after: a job runs
            seen["unloaded"] = unload.called
            idle_unload.touch("gemma4:e4b")  # the analysis model asked from the job
            seen["keep_alive"] = idle_unload.ollama_keep_alive()

        with mock.patch.object(transcriber, "_process_meeting_job", side_effect=job), \
                mock.patch.object(transcriber, "release_whisper_model"), \
                mock.patch("app.asr_onnx.release_gpu"), \
                mock.patch("app.pending_exports.process"), \
                mock.patch.object(transcriber, "_publish_queue_changed"):
            with transcriber._jobs_lock:
                transcriber._active_jobs.add(mid)
                transcriber._queue_add(mid, "transcribe")
            transcriber._run_job(mid)
        self.assertIsNone(seen["mark_after_transcription"])
        self.assertFalse(seen["unloaded"])
        self.assertNotIn("gemma4:e4b", idle_unload._interactive)  # a queued job's use is no question of the user
        self.assertEqual(seen["keep_alive"], f"{idle_unload.BACKGROUND_KEEP_ALIVE_MIN}m")
        self.assertIsNotNone(idle_unload._after_work)  # the queue empty: the minute starts now
        self.assertEqual(idle_unload._after_work[1], "the processing finished")
        idle_unload._after_work = None

    def test_no_mark_while_another_job_waits(self):
        with transcriber._jobs_lock:
            n = transcriber._queue_add(999_001, "translate")
        try:
            transcriber._work_done_if_idle()
            self.assertIsNone(idle_unload._after_work)
        finally:
            with transcriber._jobs_lock:
                transcriber._queue[:] = [q for q in transcriber._queue if q.get("n") != n]


@unittest.skipIf(idle_unload is None, "app dependencies not installed")
class CaptionsFreeTheCardTest(unittest.TestCase):
    def setUp(self):
        init_db()
        update_settings({"idle_unload_minutes": "10", "ollama_model": "gemma4:e4b"})
        self.patches = [
            mock.patch.object(idle_unload, "_ollama_used", {"gemma4:e4b", "hy-mt3:7b", "hy-mt3:1.8b"}),
            mock.patch("app.vram.ollama_loaded", return_value=[{"name": "gemma4:e4b"}, {"name": "hy-mt3:7b"},
                                                                {"name": "users-own:7b"}]),
            mock.patch.object(idle_unload.httpx, "Client", side_effect=AssertionError("Ollama asked")),
            mock.patch("app.ollama_client.analysis_running", return_value=[]),
            mock.patch.object(transcriber, "running_job_kind", return_value=None),
            mock.patch.object(live, "translator_models", return_value={"hy-mt3:7b"}),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()

    def test_the_analysis_model_and_the_queue_speech_models_go(self):
        with mock.patch("app.vram.ollama_unload", return_value=[]) as unload, \
                mock.patch.object(idle_unload, "release_speech_models", return_value=["whisper"]) as speech:
            out = idle_unload.free_for_captions("live captions started")
        unload.assert_called_once_with(["gemma4:e4b"], force=False)  # not the translator, not the user's own
        speech.assert_called_once()
        self.assertEqual(out, ["whisper", "gemma4:e4b"])

    def test_not_during_a_running_analysis(self):
        with mock.patch("app.ollama_client.analysis_running", return_value=["gemma4:e4b"]), \
                mock.patch("app.vram.ollama_unload") as unload, \
                mock.patch.object(idle_unload, "release_speech_models", return_value=[]):
            idle_unload.free_for_captions("live captions started")
        unload.assert_not_called()

    def test_not_between_two_answers_of_the_automatic_analysis(self):
        from app import meeting_guard

        with mock.patch.dict(meeting_guard._running, {1: threading.get_ident()}), \
                mock.patch("app.vram.ollama_unload") as unload, \
                mock.patch.object(idle_unload, "release_speech_models", return_value=[]):
            idle_unload.free_for_captions("live captions started")
        unload.assert_not_called()

    def test_speech_models_stay_for_a_running_job(self):
        with mock.patch.object(transcriber, "running_job_kind", return_value="transcribe"), \
                mock.patch("app.vram.ollama_unload", return_value=[]), \
                mock.patch.object(idle_unload, "release_speech_models") as speech:
            idle_unload.free_for_captions("live captions started")
        speech.assert_not_called()

    def test_the_captions_own_gigaam_stays(self):
        from app import asr_onnx

        with mock.patch.object(live, "has_sessions", return_value=True), \
                mock.patch.object(live, "onnx_models_in_use", return_value={"gigaam-v3"}), \
                mock.patch.object(transcriber, "whisper_cache_key", return_value=None), \
                mock.patch("app.vram.ecapa_loaded_on", return_value=None), \
                mock.patch("app.nemotron_diar.loaded", return_value=False), \
                mock.patch.dict(asr_onnx._loaded, {"gigaam-v3@live": 1, "gigaam-v3": 2, "gigaam-v3@gpu": 3,
                                                   "parakeet-v3@live": 4}, clear=True):
            out = idle_unload.release_speech_models()
            self.assertEqual(asr_onnx.copies(), ["gigaam-v3@live"])  # the queue's copies and the unused one go
        self.assertEqual(out, ["onnx"])

    def test_a_session_start_and_its_end(self):
        with mock.patch.object(idle_unload, "captions_started") as started, \
                mock.patch.object(idle_unload, "work_done") as done, \
                mock.patch.object(live, "_caption_worker"), \
                mock.patch.object(live, "caption_onnx_model", return_value=None):
            s = live.start_session("ru", None)
            started.assert_called_once()
            done.assert_not_called()
            live.stop_session(s.id)
        done.assert_called_once_with("live captions ended")


@unittest.skipIf(idle_unload is None, "app dependencies not installed")
class TranslatorSwitchTest(unittest.TestCase):
    def setUp(self):
        init_db()
        update_settings({"ollama_model": "gemma4:e4b"})
        self.patches = [
            mock.patch("app.vram.ollama_loaded", return_value=[{"name": "hy-mt3:7b"}, {"name": "hy-mt3:1.8b"},
                                                                {"name": "gemma4:e4b"}]),
            mock.patch("app.ollama_client.analysis_running", return_value=[]),
            mock.patch.object(transcriber, "running_job_kind", return_value=None),
            mock.patch.object(live, "translator_models", return_value={"hy-mt3:1.8b"}),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()

    def test_the_previous_translator_goes(self):
        with mock.patch("app.vram.ollama_unload", return_value=[]) as unload:
            self.assertTrue(idle_unload.translator_switched("hy-mt3:7b", "hy-mt3:1.8b"))
        unload.assert_called_once_with(["hy-mt3:7b"], force=False)

    def test_not_one_another_session_uses_nor_the_same(self):
        with mock.patch("app.vram.ollama_unload") as unload, \
                mock.patch.object(live, "translator_models", return_value={"hy-mt3:7b"}):
            self.assertFalse(idle_unload.translator_switched("hy-mt3:7b", "hy-mt3:1.8b"))
            self.assertFalse(idle_unload.translator_switched("hy-mt3:1.8b", "hy-mt3:1.8b"))
        unload.assert_not_called()

    def test_not_the_analysis_model_while_an_analysis_runs(self):
        with mock.patch("app.vram.ollama_unload") as unload, \
                mock.patch.object(transcriber, "running_job_kind", return_value="analysis"):
            self.assertFalse(idle_unload.translator_switched("gemma4:e4b", "hy-mt3:1.8b"))
        unload.assert_not_called()

    def test_the_caption_translator_asks_for_it_when_its_model_changes(self):
        t = LiveTranslator.__new__(LiveTranslator)  # no thread, no Ollama
        t._model, t._loaded, t.ready, t.error = None, None, False, ""
        with mock.patch.object(LiveTranslator, "_resolve_model", side_effect=["hy-mt3:7b", "hy-mt3:1.8b"]), \
                mock.patch.object(LiveTranslator, "_chat", return_value="ok"), \
                mock.patch.object(idle_unload, "translator_switched") as switched:
            t._ensure_ready()
            switched.assert_not_called()  # the first model: nothing before it
            t._model, t.ready = None, False  # «Быстро» chosen (LiveTranslator.configure)
            t._ensure_ready()
        switched.assert_called_once_with("hy-mt3:7b", "hy-mt3:1.8b")


if __name__ == "__main__":
    unittest.main()
