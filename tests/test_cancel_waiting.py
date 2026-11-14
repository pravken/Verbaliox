"""«Отменить» on a recording waiting in the queue takes effect at once, not when the job before it ends."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import threading
import unittest
from unittest import mock

try:
    from app import database, transcriber
except ImportError:  # app dependencies are not installed (e.g. in the release CI job)
    transcriber = None


@unittest.skipIf(transcriber is None, "app dependencies not installed")
class CancelWaitingTest(unittest.TestCase):
    def test_a_waiting_job_leaves_the_queue_at_once_and_never_runs(self):
        database.init_db()
        a = database.create_meeting("Первая", "a.wav", "a.wav")["id"]
        b = database.create_meeting("Вторая", "b.wav", "b.wav")["id"]
        release, ran = threading.Event(), []

        def job(mid):
            ran.append(mid)
            if mid == a:
                release.wait(5)

        with mock.patch.object(transcriber, "_process_meeting_job", job), \
                mock.patch.object(transcriber, "_run_pending_exports"), \
                mock.patch.object(transcriber, "release_whisper_model"):
            transcriber.enqueue_meeting_job(a)
            transcriber.enqueue_meeting_job(b)
            for _ in range(50):
                if ran:
                    break
                threading.Event().wait(0.05)
            self.assertFalse(transcriber.cancel_waiting(a))  # running: cancelled the usual way
            self.assertTrue(transcriber.cancel_waiting(b))
            self.assertEqual(database.get_meeting(b)["status"], "cancelled")
            self.assertFalse(transcriber.is_job_active(b))  # can be deleted or started again now
            release.set()
            transcriber._executor.submit(lambda: None).result(5)
        self.assertEqual(ran, [a])


if __name__ == "__main__":
    unittest.main()
