"""A Whisper load asked while the queue is paused or waits for the end of a meeting (found in an audit): the worker
would not take it, and the load waiting counted as running work (running_job_kind «other») the whole time, so
no model was unloaded for idleness, memory or «Только запись». It is refused instead."""

import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest
from unittest import mock

from app import economy, meeting_guard, transcriber


class PreloadWhileWaitingTest(unittest.TestCase):
    def _asked(self):
        with mock.patch.object(economy, "on", return_value=False), \
                mock.patch.object(transcriber._executor, "submit") as submit:
            ok = transcriber.enqueue_whisper_preload("large-v3-turbo")
        if ok:  # the worker is faked: what it would set back when done
            with transcriber._jobs_lock:
                transcriber._preloading = False
                transcriber._preloading_name = None
        return ok, submit.call_count

    def test_a_paused_queue(self):
        transcriber.pause_queue(True)
        self.addCleanup(transcriber.pause_queue, False)
        self.assertEqual(self._asked(), (False, 0))
        self.assertIsNone(transcriber.running_job_kind())

    def test_a_meeting_holding_the_transcriptions(self):
        with mock.patch.object(meeting_guard, "holds_queue", return_value=True):
            self.assertEqual(self._asked(), (False, 0))
        self.assertIsNone(transcriber.running_job_kind())

    def test_an_idle_queue_loads_it(self):
        with mock.patch.object(meeting_guard, "holds_queue", return_value=False):
            self.assertEqual(self._asked(), (True, 1))


if __name__ == "__main__":
    unittest.main()
