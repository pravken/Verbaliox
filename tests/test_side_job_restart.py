"""A dub, translation, cut or subtitles job cut off by a crash: the next start gives the recording back the
status it had before the job, not «completed» — a cancelled recording looked finished, and the retention
setting deleted its sound (found in an audit)."""

import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest
from unittest import mock

from app import main, transcriber
from app.database import create_meeting, get_meeting, init_db, update_meeting_progress


class SideJobRestartTest(unittest.TestCase):
    def setUp(self):
        init_db()

    def _queued(self, status, enqueue):
        m = create_meeting("Отменённая запись", "a.m4a", "/nonexistent/a.m4a")
        update_meeting_progress(m["id"], status=status)
        self.addCleanup(lambda: transcriber._active_jobs.discard(m["id"]))
        self.addCleanup(lambda: transcriber._queue.__setitem__(slice(None), [q for q in transcriber._queue if q["id"] != m["id"]]))
        with mock.patch.object(transcriber, "_submit_job"), mock.patch.object(transcriber, "_publish_queue_changed"):
            self.assertTrue(enqueue(m["id"]))
        return m["id"]

    def test_a_cut_on_a_cancelled_recording(self):
        mid = self._queued("cancelled", lambda i: transcriber.enqueue_cut_job(i, "clean", [(0.0, 1.0)], False, "/nonexistent/o.m4a"))
        self.assertEqual(get_meeting(mid)["status"], "rendering")
        self.assertEqual(main._status_before_side_job(mid), "cancelled")  # what the start sets after a crash

    def test_a_dub_on_a_recording_not_transcribed(self):
        mid = self._queued("added", lambda i: transcriber.enqueue_dub_job(i, "en"))
        self.assertEqual(get_meeting(mid)["status"], "dubbing")
        self.assertEqual(main._status_before_side_job(mid), "added")

    def test_a_recording_never_given_a_side_job(self):
        m = create_meeting("Старая запись", "b.m4a", "/nonexistent/b.m4a")
        update_meeting_progress(m["id"], status="translating")  # left by a version that did not keep it
        self.assertEqual(main._status_before_side_job(m["id"]), "completed")


if __name__ == "__main__":
    unittest.main()
