"""No two copies of Parakeet fp32 at once (bench-report/asr-2026-11-check.md, «Что обсудить», item 2): while live
captions recognize with a model, a transcription that would load the same files on the processor waits for their end;
with a video card it runs there at once, and «Начать сейчас» lets it go."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import functools
import threading
import unittest
from unittest import mock

from app.database import create_meeting, init_db, update_meeting_fields, update_settings

try:
    from app import asr_onnx, transcriber
except ImportError:  # the release CI runs without the app's packages
    transcriber = None


def _meeting(model: str, language: str = "en") -> int:
    m = create_meeting(title="Обзор", filename="a.wav", media_path="a.wav", language=language, model_name=model)
    update_meeting_fields(m["id"], language_choice=language)
    return m["id"]


@unittest.skipIf(transcriber is None, "app dependencies not installed")
class CaptionsHoldTest(unittest.TestCase):
    def setUp(self):
        init_db()
        update_settings({"whisper_model": "parakeet-v3", "speech_model_ru": "gigaam-v3", "language": "auto"})
        self.captions = {"parakeet-v3"}
        self.gpu = False
        for target, value in (("app.live.has_sessions", lambda: bool(self.captions)),
                              ("app.live.onnx_models_in_use", lambda: set(self.captions)),
                              ("app.onnx_gpu.gpu_for_job", lambda model: self.gpu)):
            p = mock.patch(target, side_effect=value)
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(transcriber._forced.clear)
        self.addCleanup(transcriber._forced_captions.clear)
        self.addCleanup(transcriber._held_said.__setitem__, 0, transcriber._held_said[0])
        transcriber._held_said[0] = False

    def test_parakeet_shares_its_copy_gigaam_does_not(self):
        self.assertTrue(asr_onnx.shares_live_copy("parakeet-v3"))  # both copies fp32 of the same files
        with mock.patch("app.asr_onnx._has_files", return_value=True):
            self.assertFalse(asr_onnx.shares_live_copy("gigaam-v3"))  # CTC int8 by phrases, RNN-T int8 in the queue
        self.assertFalse(asr_onnx.shares_live_copy("large-v3-turbo"))

    def test_waits_while_captions_use_its_model_on_the_processor(self):
        mid = _meeting("parakeet-v3")
        self.assertTrue(transcriber.waits_for_captions(mid))
        self.gpu = True  # the video card takes it: no wait
        self.assertFalse(transcriber.waits_for_captions(mid))
        self.gpu = False
        self.captions = {"gigaam-v3"}  # Russian captions by phrases: another model
        self.assertFalse(transcriber.waits_for_captions(mid))
        self.captions = set()  # the captions ended
        self.assertFalse(transcriber.waits_for_captions(mid))

    def test_the_model_of_the_job_as_known_before_it_starts(self):
        self.assertEqual(transcriber._job_model(_meeting("gigaam-v3", "ru")), "gigaam-v3")
        self.assertEqual(transcriber._job_model(_meeting("auto", "ru")), "gigaam-v3")
        self.assertEqual(transcriber._job_model(_meeting("auto", "en")), "parakeet-v3")
        # «auto» speech: the main model hears the language first, so it is the one loaded
        self.assertEqual(transcriber._job_model(_meeting("auto", "auto")), "parakeet-v3")
        self.assertEqual(transcriber._job_model(_meeting("canary-v2")), "parakeet-v3")  # a removed model
        self.assertFalse(transcriber.waits_for_captions(_meeting("auto", "ru")))  # GigaAM: no second Parakeet

    def test_the_queue_holds_it_and_starts_it_when_the_captions_end(self):
        mid = _meeting("parakeet-v3")
        ex = transcriber._PriorityExecutor()
        ran, by_hand = threading.Event(), threading.Event()
        # the transcription as the queue holds it: functools.partial with its token
        with mock.patch("app.transcriber._run_job", side_effect=lambda *a, **k: ran.set()) as run_job:
            ex.submit(functools.partial(run_job, token=1), mid, priority=0)
            ex.submit(by_hand.set, priority=2)
            self.assertTrue(by_hand.wait(3))  # a dub or a translation goes first
            self.assertFalse(ran.wait(0.5))
            self.assertIn(mid, transcriber._captions_held)
            self.captions = set()
            ex.wake()  # live._captions_ended wakes the queue
            self.assertTrue(ran.wait(3))
        self.assertNotIn(mid, transcriber._captions_held)

    def test_a_video_card_takes_it_at_once(self):
        mid = _meeting("parakeet-v3")
        self.gpu = True
        ex = transcriber._PriorityExecutor()
        ran = threading.Event()
        with mock.patch("app.transcriber._run_job", side_effect=lambda *a, **k: ran.set()) as run_job:
            ex.submit(functools.partial(run_job, token=1), mid, priority=0)
            self.assertTrue(ran.wait(3))
        self.assertNotIn(mid, transcriber._captions_held)

    def test_run_now_lets_it_go(self):
        mid = _meeting("parakeet-v3")
        with transcriber._jobs_lock:
            transcriber._active_jobs.add(mid)
        self.addCleanup(transcriber._active_jobs.discard, mid)
        self.assertTrue(transcriber.waits_for_captions(mid))
        self.assertTrue(transcriber.run_now(mid))
        self.assertFalse(transcriber.waits_for_captions(mid))

    def test_during_a_meeting_run_now_lets_go_of_the_meeting_first(self):
        mid = _meeting("parakeet-v3")
        with transcriber._jobs_lock:
            transcriber._active_jobs.add(mid)
        self.addCleanup(transcriber._active_jobs.discard, mid)
        transcriber._held_said[0] = True  # the window says «ждёт конца встречи»
        self.assertTrue(transcriber.run_now(mid))
        self.assertIn(mid, transcriber._forced)
        self.assertTrue(transcriber.waits_for_captions(mid))  # now it says «ждёт окончания субтитров»
        self.assertTrue(transcriber.run_now(mid))
        self.assertFalse(transcriber.waits_for_captions(mid))

    def test_the_queue_window_says_why_it_waits(self):
        mid = _meeting("parakeet-v3")
        with transcriber._jobs_lock:
            token = transcriber._queue_add(mid, "transcribe")
        self.addCleanup(lambda: transcriber._queue.__setitem__(
            slice(None), [q for q in transcriber._queue if q.get("n") != token]))
        item = next(q for q in transcriber.queue_snapshot() if q["id"] == mid)
        self.assertEqual(item["hold"], "captions")
        self.assertFalse(item["forced"])
        self.captions = set()
        item = next(q for q in transcriber.queue_snapshot() if q["id"] == mid)
        self.assertEqual(item["hold"], "")

    def test_the_end_of_the_captions_wakes_the_queue(self):
        from app import live

        with mock.patch("app.transcriber.wake_queue") as wake, mock.patch("app.idle_unload.work_done"):
            live._captions_ended()
        wake.assert_called_once()

    def test_release_live_drops_only_the_captions_copy(self):
        with asr_onnx._lock:
            asr_onnx._loaded.update({"parakeet-v3@live": object(), "parakeet-v3": object()})
        self.addCleanup(asr_onnx.release, "parakeet-v3")
        self.assertTrue(asr_onnx.release_live("parakeet-v3"))
        self.assertEqual(asr_onnx.copies(), ["parakeet-v3"])
        self.assertFalse(asr_onnx.release_live("parakeet-v3"))


if __name__ == "__main__":
    unittest.main()
