import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import threading
import time
import unittest
from unittest import mock

from app.database import init_db, update_settings

try:
    from app import asr_onnx, economy, meeting_guard, transcriber
except ImportError:  # the release CI runs without the app's packages
    economy = None


@unittest.skipIf(economy is None, "app dependencies not installed")
class EconomyTest(unittest.TestCase):
    """Asked by the user: from the tray icon, a mode where only recording works and no model loads the computer."""

    def setUp(self):
        init_db()

    def tearDown(self):
        update_settings({"economy_mode": "false", "cpu_threads": "auto"})
        transcriber.wake_queue()

    def test_the_queue_waits_and_the_analysis_too(self):
        with mock.patch("app.idle_unload.unload_now"), mock.patch("app.live.stop_all"), mock.patch("app.meeting_guard.kick"):
            economy.set_mode(True)
        self.assertEqual(meeting_guard.busy(), "economy")
        ran = threading.Event()
        transcriber._executor.submit(ran.set, priority=2)
        self.assertFalse(ran.wait(0.5))  # recording only: the job waits
        with mock.patch("app.meeting_guard.kick"):
            economy.set_mode(False)
        self.assertTrue(ran.wait(3))  # and starts when the mode ends
        self.assertEqual(meeting_guard.busy(), "")

    def test_a_waiting_analysis_can_be_cancelled_and_the_recording_unlocked(self):
        from app.database import create_meeting, get_meeting, update_meeting_progress

        mid = create_meeting(title="Синк", filename="a.wav", media_path="")["id"]
        update_meeting_progress(mid, status="completed", progress=100)
        meeting_guard.defer(mid)
        with mock.patch("app.idle_unload.unload_now"), mock.patch("app.live.stop_all"), mock.patch("app.meeting_guard.kick"):
            economy.set_mode(True)
        self.assertTrue(transcriber.enqueue_analysis_job(mid))
        self.assertTrue(transcriber.is_job_active(mid))
        self.assertTrue(transcriber.cancel_waiting(mid))  # waiting in the economy mode: out at once
        self.assertFalse(transcriber.is_job_active(mid))
        self.assertEqual(get_meeting(mid)["status"], "completed")
        self.assertNotIn(mid, meeting_guard.pending())
        self.assertFalse(transcriber.enqueue_whisper_preload())  # nothing is loaded ahead either
        with mock.patch("app.meeting_guard.kick"):
            economy.set_mode(False)
        time.sleep(0.3)  # the dropped job is skipped by the worker
        self.assertEqual(get_meeting(mid)["status"], "completed")

    def test_the_whole_queue_paused_and_cancelled_at_once(self):
        """Asked by the user: with many files waiting, «Пауза» and «Отменить все» for the whole queue."""
        from app.database import create_meeting, get_meeting, update_meeting_progress

        ids = []
        for i in range(3):
            mid = create_meeting(title=f"Файл {i}", filename="a.wav", media_path="")["id"]
            update_meeting_progress(mid, status="completed", progress=100)
            meeting_guard.defer(mid)
            ids.append(mid)
        transcriber.pause_queue(True)
        try:
            for mid in ids:
                self.assertTrue(transcriber.enqueue_analysis_job(mid))
            time.sleep(0.3)
            self.assertTrue(all(transcriber.is_job_active(m) for m in ids))  # paused: none of them started
            self.assertEqual(transcriber.cancel_all()["dropped"], 3)
            self.assertFalse(any(transcriber.is_job_active(m) for m in ids))
            self.assertEqual([get_meeting(m)["status"] for m in ids], ["completed"] * 3)
        finally:
            transcriber.pause_queue(False)
        time.sleep(0.3)  # the dropped jobs are skipped by the worker when it goes on
        self.assertEqual(transcriber.queue_snapshot(), [])

    def test_processor_threads(self):
        with mock.patch("os.cpu_count", return_value=20):
            self.assertEqual(asr_onnx.cpu_threads({"cpu_threads": "auto"}), 8)  # not all 20 (100 % in a meeting)
            self.assertEqual(asr_onnx.cpu_threads({"cpu_threads": "4"}), 4)
            self.assertEqual(asr_onnx.cpu_threads({"cpu_threads": "all"}), 20)
        with mock.patch("os.cpu_count", return_value=4):
            self.assertEqual(asr_onnx.cpu_threads({}), 2)


if __name__ == "__main__":
    unittest.main()
