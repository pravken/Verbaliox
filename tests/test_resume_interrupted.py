"""A recording whose processing ended together with the program is taken up again at the next start, but
not for ever: a file that crashes the program itself is marked failed after two such ends."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest

try:
    from app import database, main
except ImportError:  # app dependencies are not installed (e.g. in the release CI job)
    main = None


@unittest.skipIf(main is None, "app dependencies not installed")
class ResumeInterruptedTest(unittest.TestCase):
    def setUp(self):
        database.init_db()
        database.update_settings({main.INTERRUPTED_KEY: "{}", main.CLEAN_EXIT_KEY: "0"})

    def tearDown(self):
        database.update_settings({main.INTERRUPTED_KEY: "{}"})

    def _start(self):
        return main._interrupted_to_resume(database.list_meetings())

    def test_a_job_ending_with_the_program_twice_is_marked_failed(self):
        crash = database.create_meeting("Сломанный файл", "c.wav", "c.wav")["id"]
        waiting = database.create_meeting("В очереди", "q.wav", "q.wav")["id"]
        database.update_meeting_progress(crash, status="transcribing", progress=30)
        database.update_meeting_progress(waiting, status="queued", progress=0)
        got = self._start()
        self.assertIn(crash, got)  # the first time: queued again
        self.assertIn(waiting, got)
        database.update_meeting_progress(crash, status="diarizing", progress=60)  # and it ended again
        got = self._start()
        self.assertNotIn(crash, got)
        self.assertIn(waiting, got)  # never begun: not counted
        m = database.get_meeting(crash)
        self.assertEqual(m["status"], "failed")
        self.assertEqual(m["error_message"], main.INTERRUPTED_TEXT)

    def test_ends_by_quitting_are_no_crash(self):
        """Found in review: quitting or switching the computer off twice during a long transcription marked it
        failed. An end the server saw itself (CLEAN_EXIT_KEY) is not counted."""
        mid = database.create_meeting("Длинная запись", "l.wav", "l.wav")["id"]
        for _ in range(3):
            database.update_meeting_progress(mid, status="transcribing", progress=30)
            database.update_settings({main.CLEAN_EXIT_KEY: "1"})  # the program ended by itself
            self.assertIn(mid, self._start())
        self.assertEqual(database.get_meeting(mid)["status"], "transcribing")

    def test_a_job_that_finished_is_counted_afresh(self):
        mid = database.create_meeting("Встреча", "a.wav", "a.wav")["id"]
        database.update_meeting_progress(mid, status="transcribing", progress=30)
        self.assertIn(mid, self._start())
        database.update_meeting_progress(mid, status="completed", progress=100)
        self._start()  # done: its count goes
        database.update_meeting_progress(mid, status="transcribing", progress=30)
        self.assertIn(mid, self._start())

    def test_an_interrupted_analysis_keeps_the_transcript(self):
        """Found in review: «summarizing» (the analysis after the transcript, or an analysis job of a finished
        recording) was queued again as a transcription: the whole recording recognized anew, its corrections
        replaced. The transcript stays and the analysis is marked to be done again."""
        from app import meeting_guard

        mid = database.create_meeting("Разбор", "s.wav", "s.wav")["id"]
        database.save_meeting_results(mid, segments=[{"id": 1, "start": 0, "end": 1, "text": "исправлено", "speaker": "SPEAKER_00"}])
        database.update_meeting_progress(mid, status="summarizing", progress=90)
        meeting_guard.done(mid)
        self.assertNotIn(mid, self._start())
        m = database.get_meeting(mid)
        self.assertEqual(m["status"], "completed")
        self.assertEqual(m["segments"][0]["text"], "исправлено")
        self.assertIn(mid, meeting_guard.pending())
        meeting_guard.done(mid)
        # a recording without a transcript in that state (none such is made now) is still taken up again
        bare = database.create_meeting("Без текста", "b.wav", "b.wav")["id"]
        database.update_meeting_progress(bare, status="summarizing", progress=90)
        self.assertIn(bare, self._start())


if __name__ == "__main__":
    unittest.main()
