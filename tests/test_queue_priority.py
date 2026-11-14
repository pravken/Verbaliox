"""A meeting just recorded is transcribed before a dub or a translation queued earlier."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import threading
import unittest

try:
    from app import transcriber
except ImportError:  # app dependencies are not installed (e.g. in the release CI job)
    transcriber = None


@unittest.skipIf(transcriber is None, "app dependencies not installed")
class PriorityTest(unittest.TestCase):
    def test_higher_priority_first_and_in_order_within(self):
        ex = transcriber._PriorityExecutor()
        gate, ran = threading.Event(), []
        ex.submit(lambda: gate.wait(5), priority=0)  # the job running now is never interrupted
        futs = [ex.submit(ran.append, name, priority=p) for name, p in
                [("dub", 3), ("translate", 2), ("meeting A", 0), ("meeting B", 0), ("resplit", 1)]]
        gate.set()
        for f in futs:
            f.result(5)
        self.assertEqual(ran, ["meeting A", "meeting B", "resplit", "translate", "dub"])

    def test_an_error_stays_in_its_future(self):
        ex = transcriber._PriorityExecutor()
        with self.assertRaises(ZeroDivisionError):
            ex.submit(lambda: 1 / 0).result(5)
        self.assertEqual(ex.submit(lambda: 7).result(5), 7)  # the worker goes on

    def test_jobs_get_their_kind_priority(self):
        self.assertEqual(transcriber._job_priority(transcriber._run_job, (1,)), 0)
        self.assertEqual(transcriber._job_priority(transcriber._run_dub_job, (1, "en", "completed")), 3)
        self.assertEqual(transcriber._job_priority(transcriber._run_side_job, (1, "completed", transcriber._translate_runner)), 2)
        self.assertEqual(transcriber._job_priority(transcriber._run_side_job, (1, "completed", transcriber._resplit_runner)), 1)


if __name__ == "__main__":
    unittest.main()
