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

    def test_processor_threads(self):
        with mock.patch("os.cpu_count", return_value=20):
            self.assertEqual(asr_onnx.cpu_threads({"cpu_threads": "auto"}), 8)  # not all 20 (100 % in a meeting)
            self.assertEqual(asr_onnx.cpu_threads({"cpu_threads": "4"}), 4)
            self.assertEqual(asr_onnx.cpu_threads({"cpu_threads": "all"}), 20)
        with mock.patch("os.cpu_count", return_value=4):
            self.assertEqual(asr_onnx.cpu_threads({}), 2)


if __name__ == "__main__":
    unittest.main()
