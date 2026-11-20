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

    def test_a_job_queued_after_a_cancelled_one_of_higher_priority_runs_and_the_cancelled_does_not(self):
        # the executor takes jobs by priority: a translation (2) given after a cancelled dub (3) of the
        # same recording comes up first; it must run, and the cancelled dub must not
        database.init_db()
        a = database.create_meeting("Первая", "a.wav", "a.wav")["id"]
        b = database.create_meeting("Вторая", "b.wav", "b.wav")["id"]
        release, ran = threading.Event(), []

        def job(mid):
            ran.append(("transcribe", mid))
            release.wait(5)

        def translate(mid, lang):
            ran.append(("translate", mid))
            return "готово"

        def dub(meeting, lang, progress, check):
            ran.append(("dub", meeting["id"]))
            return {"path": "x.wav"}

        with mock.patch.object(transcriber, "_process_meeting_job", job), \
                mock.patch.object(transcriber, "_run_pending_exports"), \
                mock.patch.object(transcriber, "release_whisper_model"), \
                mock.patch.object(transcriber, "save_meeting_dub"), \
                mock.patch.object(transcriber, "clear_vram"), \
                mock.patch("app.dubbing.run_dub_job", dub):
            transcriber.enqueue_meeting_job(a)
            for _ in range(50):
                if ran:
                    break
                threading.Event().wait(0.05)
            self.assertTrue(transcriber.enqueue_dub_job(b, "en"))
            self.assertTrue(transcriber.cancel_waiting(b))
            self.assertTrue(transcriber._enqueue_side_job(b, "translate", "en", "translating", "в очереди", translate, "en"))
            release.set()
            transcriber._executor.submit(lambda: None, priority=9).result(5)
        self.assertEqual(ran, [("transcribe", a), ("translate", b)])
        self.assertFalse(transcriber.is_job_active(b))


if __name__ == "__main__":
    unittest.main()
