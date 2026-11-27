import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import threading
import time
import unittest
from unittest import mock

from app import app_status, cancel_scope, meeting_guard
from app.database import create_meeting, init_db, save_meeting_results, update_meeting_progress, update_settings

try:
    from app import transcriber
except ImportError:  # the release CI runs without the app's packages
    transcriber = None


def _meeting():
    m = create_meeting(title="Синк", filename="a.wav", media_path="a.wav")
    save_meeting_results(m["id"], segments=[{"id": 1, "start": 0.0, "end": 3.0, "speaker": "S0", "text": "Привет"}],
                         speakers={"S0": {"name": "Анна"}}, summaries={}, language="ru")
    update_meeting_progress(m["id"], status="completed", progress=100)
    return m["id"]


class MeetingGuardTest(unittest.TestCase):
    """Meeting after meeting, the analysis of the last one slowed the computer during the next (reported by
    the user): while the app records, or the calendar has a meeting, the analysis waits and its model goes."""

    def setUp(self):
        init_db()
        update_settings({"analysis_after_meetings": "true"})
        app_status.set_recording(False)
        meeting_guard._state.update(busy="", quiet_since=0.0)
        for mid in meeting_guard.pending():
            meeting_guard.done(mid)
        self.no_calendar = mock.patch("app.calendar_ics.current_meeting", return_value=None)
        self.no_calendar.start()

    def tearDown(self):
        self.no_calendar.stop()
        app_status.set_recording(False)

    def test_a_recording_or_the_calendar_is_a_meeting(self):
        self.assertEqual(meeting_guard.busy(), "")
        app_status.set_recording(True)
        self.assertEqual(meeting_guard.busy(), "recording")
        update_settings({"analysis_after_meetings": "false"})
        self.assertEqual(meeting_guard.busy(), "")  # switched off: the analysis never waits
        update_settings({"analysis_after_meetings": "true"})
        app_status.set_recording(False)
        with mock.patch("app.calendar_ics.current_meeting", return_value={"title": "Планёрка"}):
            self.assertEqual(meeting_guard.busy(), "calendar")

    def test_a_meeting_breaks_the_analysis_off_unloads_the_model_and_it_runs_after(self):
        mid = _meeting()
        result = {}

        def analysis():
            # as a job of the queue does (_queue_start): a thread id is reused, an abort of an earlier thread
            # with the same id must not end this one before the meeting begins
            cancel_scope.reset(threading.get_ident())
            with meeting_guard.guard(mid):
                try:
                    cancel_scope.call(lambda: time.sleep(5))
                except cancel_scope.Aborted:
                    result["aborted"] = True

        meeting_guard.check(now=1000.0)  # no meeting yet
        worker = threading.Thread(target=analysis)
        worker.start()
        for _ in range(100):  # the analysis has begun
            with meeting_guard._lock:
                if mid in meeting_guard._running:
                    break
            time.sleep(0.02)
        app_status.set_recording(True)
        # only the models this app loaded go (another program's stays), and gently
        loaded = [{"name": "gemma4:e4b"}, {"name": "someone-elses:7b"}]
        with mock.patch("app.vram.ollama_loaded", return_value=loaded), \
                mock.patch("app.vram.ollama_unload", return_value=[]) as unload, \
                mock.patch("app.idle_unload._ollama_used", {"gemma4:e4b"}):
            self.assertEqual(meeting_guard.check(now=1010.0), "recording")
            meeting_guard.check(now=1030.0)  # still going: unloaded once, when it began
        worker.join(3)
        self.assertTrue(result.get("aborted"))
        self.assertTrue(meeting_guard.interrupted(mid))
        unload.assert_called_once_with(["gemma4:e4b"], force=False)
        meeting_guard.clear_interrupted(mid)
        cancel_scope.reset(worker.ident)

        meeting_guard.defer(mid)
        app_status.set_recording(False)
        with mock.patch("app.transcriber.enqueue_analysis_job") as enqueue, \
                mock.patch("app.transcriber.is_job_active", return_value=False):
            meeting_guard.check(now=1100.0)
            meeting_guard.check(now=1100.0 + meeting_guard.QUIET_SEC - 1)
            enqueue.assert_not_called()  # the next meeting may start right after: a short wait first
            meeting_guard.check(now=1100.0 + meeting_guard.QUIET_SEC + 1)
            enqueue.assert_called_once_with(mid, False)

    def test_a_calendar_event_alone_takes_no_model_from_the_users_work(self):
        meeting_guard.check(now=1000.0)
        with mock.patch("app.calendar_ics.current_meeting", return_value={"title": "Планёрка"}), \
                mock.patch("app.vram.ollama_unload") as unload:
            self.assertEqual(meeting_guard.check(now=1010.0), "calendar")
        unload.assert_not_called()  # no automatic analysis was running: nothing to free

    @unittest.skipIf(transcriber is None, "app dependencies not installed")
    def test_the_waiting_analysis_runs_only_without_a_meeting(self):
        mid = _meeting()
        meeting_guard.defer(mid)
        with mock.patch.object(transcriber, "_auto_analysis") as run:
            app_status.set_recording(True)
            self.assertIn("после окончания встречи", transcriber._analysis_runner(mid))
            run.assert_not_called()
            self.assertEqual(meeting_guard.pending(), [mid])
            app_status.set_recording(False)
            with mock.patch.object(transcriber, "_after_transcription", return_value=[]), \
                    mock.patch("app.llm.available", return_value=True):
                self.assertEqual(transcriber._analysis_runner(mid), "Анализ готов")
            run.assert_called_once()
        self.assertEqual(meeting_guard.pending(), [])

    @unittest.skipIf(transcriber is None, "app dependencies not installed")
    def test_an_asked_analysis_stays_asked_across_a_meeting(self):
        """«Обработать всё» asked for the analysis; a meeting deferred it: after the meeting it runs as asked
        (with «Анализ после расшифровки» off it was skipped and marked done)."""
        mid = _meeting()
        meeting_guard.defer(mid)  # an automatic mark first: the request does not lose it, nor the reverse
        with mock.patch.object(transcriber, "_auto_analysis") as run:
            app_status.set_recording(True)
            self.assertIn("после окончания встречи", transcriber._analysis_runner(mid, True))
            run.assert_not_called()
            meeting_guard.defer(mid)
            self.assertEqual(meeting_guard.pending_asked(), [(mid, True)])
            app_status.set_recording(False)
            meeting_guard.check(now=5000.0)
            with mock.patch("app.transcriber.enqueue_analysis_job", return_value=True) as enqueue, \
                    mock.patch("app.transcriber.is_job_active", return_value=False):
                meeting_guard.check(now=5000.0 + meeting_guard.QUIET_SEC + 1)
            enqueue.assert_called_once_with(mid, True)
            with mock.patch("app.database.get_all_settings", return_value={"auto_summary": "false"}), \
                    mock.patch.object(transcriber, "_after_transcription", return_value=[]), \
                    mock.patch("app.llm.available", return_value=True):
                transcriber._analysis_runner(*enqueue.call_args.args)
            run.assert_called_once()
        self.assertEqual(meeting_guard.pending(), [])

    def test_a_mark_of_an_older_database_gets_the_asked_column(self):
        from app.database import _db_lock, get_connection

        mid = _meeting()
        with _db_lock:
            conn = get_connection()
            conn.execute("DROP TABLE IF EXISTS deferred_analysis")
            conn.execute("CREATE TABLE deferred_analysis (meeting_id INTEGER PRIMARY KEY, since TEXT NOT NULL)")
            conn.execute("INSERT INTO deferred_analysis VALUES (?, datetime('now'))", (mid,))
            conn.commit()
            conn.close()
        self.assertEqual(meeting_guard.pending_asked(), [(mid, False)])
        meeting_guard.defer(mid, asked=True)
        self.assertEqual(meeting_guard.pending_asked(), [(mid, True)])
        meeting_guard.done(mid)


if __name__ == "__main__":
    unittest.main()


@unittest.skipIf(transcriber is None, "app dependencies not installed")
class TranscriptionWaitsForTheMeetingTest(unittest.TestCase):
    """Reported by the user: a recording ended as the next meeting began; its transcription loaded Parakeet
    and the speaker models during the call, the computer froze and the screen could not be shared, though
    «Не мешать на встречах» was on. The transcription and the mix wait for the end of the meeting now."""

    def setUp(self):
        init_db()
        update_settings({"analysis_after_meetings": "true"})
        app_status.set_recording(False)
        meeting_guard._state.update(busy="", quiet_since=0.0, ended=0.0, looked=True)

    def tearDown(self):
        meeting_guard._state.update(busy="", ended=0.0)
        app_status.set_recording(False)
        transcriber.wake_queue()

    def test_the_queue_holds_transcriptions_during_a_meeting_and_two_minutes_after(self):
        with mock.patch("app.calendar_ics.current_meeting", return_value=None):
            app_status.set_recording(True)
            meeting_guard.check(now=1000.0)
            self.assertTrue(meeting_guard.holds_queue(now=1000.0))
            app_status.set_recording(False)
            with mock.patch("app.transcriber.wake_queue"):
                meeting_guard.check(now=2000.0)  # the meeting ended
            self.assertTrue(meeting_guard.holds_queue(now=2000.0 + meeting_guard.QUIET_SEC - 1))  # the next one may start
            self.assertFalse(meeting_guard.holds_queue(now=2000.0 + meeting_guard.QUIET_SEC + 1))
            update_settings({"analysis_after_meetings": "false"})
            app_status.set_recording(True)
            meeting_guard.check(now=3000.0)
            self.assertFalse(meeting_guard.holds_queue(now=3000.0))  # switched off: nothing waits
            app_status.set_recording(False)

    def test_before_its_first_look_it_asks_at_once(self):
        """Just started (a recording recovered after a restart in a meeting): not «no meeting» until the poll."""
        meeting_guard._state.update(looked=False)
        with mock.patch("app.calendar_ics.current_meeting", return_value={"title": "Демо"}):
            self.assertTrue(meeting_guard.holds_queue())
        with mock.patch("app.calendar_ics.current_meeting", return_value=None):
            self.assertFalse(meeting_guard.holds_queue())

    def test_before_its_first_look_the_calendar_is_not_read_under_the_queue_lock(self):
        """Found in the review: the queue asks under its lock, and a calendar read then (Outlook up to 90 s, a
        link up to 60 s) held every new job. Only the calendar read already counts."""
        from datetime import datetime, timedelta

        from app import calendar_ics

        meeting_guard._state.update(looked=False)
        now = datetime.now()
        ev = {"uid": "1", "title": "Планёрка", "start": now - timedelta(minutes=5), "end": now + timedelta(minutes=25),
              "attendees": ["Анна", "Борис"], "rrule": "", "exdates": [], "all_day": False, "status": "",
              "location": "", "join": "https://teams.microsoft.com/l/meetup-join/x", "online": True}
        saved = dict(calendar_ics._cache)
        try:
            with mock.patch.object(calendar_ics, "_source", return_value="outlook"), \
                 mock.patch("app.calendar_outlook.fetch", side_effect=AssertionError("read under the lock")), \
                 mock.patch.object(calendar_ics, "_load_text", side_effect=AssertionError("read under the lock")):
                calendar_ics._cache.update(source="", at=0.0, events=[], error="")
                self.assertFalse(meeting_guard.holds_queue())  # nothing read yet: no meeting known
                calendar_ics._cache.update(source="outlook", at=0.0, events=[ev], error="")  # read, now stale
                self.assertTrue(meeting_guard.holds_queue())
        finally:
            calendar_ics._cache.clear()
            calendar_ics._cache.update(saved)

    def test_a_transcription_waits_and_a_job_asked_by_hand_goes_on(self):
        transcribed, by_hand = threading.Event(), threading.Event()

        def _preload_whisper():  # named as the queue's own model load: a job of the transcription
            transcribed.set()

        import functools

        # a transcription as the queue holds it (functools.partial with its token)
        self.assertTrue(transcriber._waits_for_meeting(functools.partial(transcriber._run_job, token=1)))
        self.assertFalse(transcriber._waits_for_meeting(functools.partial(transcriber._run_dub_job, token=1)))
        with mock.patch("app.meeting_guard.holds_queue", return_value=True):
            transcriber._executor.submit(_preload_whisper)
            transcriber._executor.submit(by_hand.set, priority=2)
            self.assertTrue(by_hand.wait(3))  # a translation or a dub asked for is not held back
            self.assertFalse(transcribed.wait(0.5))
            self.assertTrue(transcriber.meeting_holds())
        transcriber.wake_queue()
        self.assertTrue(transcribed.wait(7))  # the meeting is over: it runs
        self.assertFalse(transcriber.meeting_holds())

    def test_a_meeting_releases_the_speech_models_nemotron_too(self):
        from app import nemotron_diar

        nemotron_diar._model.update(model=object(), processor=object(), device="cpu")
        try:
            with mock.patch("app.calendar_ics.current_meeting", return_value=None), \
                    mock.patch("app.transcriber.running_job_kind", return_value=""), \
                    mock.patch("app.hardware.clear_vram"):
                app_status.set_recording(True)
                meeting_guard.check(now=5000.0)
            self.assertFalse(nemotron_diar.loaded())  # it stayed in memory until the app ended before
        finally:
            nemotron_diar._model.update(model=None, processor=None, device=None)
            app_status.set_recording(False)

    def test_the_mix_waits_for_the_end_of_the_meeting(self):
        from app import main  # noqa: F401 - app/api/recording.py is loaded by it
        from app.api import recording

        answers = iter([0.0, 0.0, None])
        me = threading.get_ident()
        mine = []  # time.sleep is global: background threads of other tests sleep through the same mock
        with mock.patch("app.meeting_guard.hold_until", side_effect=lambda: next(answers)), \
                mock.patch("time.sleep", side_effect=lambda s: threading.get_ident() == me and mine.append(s)), \
                mock.patch("app.database.update_meeting_progress") as progress:
            self.assertTrue(recording._wait_for_meeting_end(7))
        self.assertEqual(len(mine), 2)
        self.assertEqual(progress.call_args_list[0].kwargs["stage_text"], "Сведение дорожек: начнётся после встречи")


class LeftEarlyTest(unittest.TestCase):
    """Asked by the user: a meeting left before its end in the calendar held the mix until that end."""

    def setUp(self):
        from app import meeting_guard

        self.addCleanup(meeting_guard._left.clear)
        self.event = {"title": "Планёрка", "uid": "u1", "start": __import__("datetime").datetime(2026, 11, 23, 11, 0)}

    def test_a_stopped_recording_ends_the_calendar_meeting_unless_a_call_goes_on(self):
        from app import app_status, meeting_guard

        with mock.patch("app.calendar_ics.current_meeting", return_value=self.event), \
                mock.patch.object(meeting_guard, "enabled", return_value=True), \
                mock.patch("app.economy.on", return_value=False):
            app_status.set_recording(True)
            self.assertEqual(meeting_guard.busy(), "recording")
            app_status.set_recording(False)  # stopped before the calendar's end
            with mock.patch.object(meeting_guard, "_in_call", return_value=False):
                self.assertEqual(meeting_guard.busy(), "")  # left: nothing holds the mix
            with mock.patch.object(meeting_guard, "_in_call", return_value=True):
                self.assertEqual(meeting_guard.busy(), "call")  # still in the call: it holds
            other = dict(self.event, uid="u2")
            with mock.patch("app.calendar_ics.current_meeting", return_value=other), \
                    mock.patch.object(meeting_guard, "_in_call", return_value=False):
                self.assertEqual(meeting_guard.busy(), "calendar")  # another meeting, not left

    def test_the_next_meeting_due_soon_is_not_taken_for_left(self):
        """Stopping the recording of a meeting minutes before the next one: the calendar's «current» meeting is
        the next one (due within 10 minutes), and it was taken for left before it began."""
        import datetime as dt

        from app import meeting_guard

        now = dt.datetime(2026, 11, 23, 10, 55)
        upcoming = dict(self.event, start=dt.datetime(2026, 11, 23, 11, 0))
        with mock.patch("app.calendar_ics.current_meeting", return_value=upcoming):
            meeting_guard.recording_ended(now=now.timestamp())
        self.assertEqual(meeting_guard._left, {})
        begun = dict(self.event, start=dt.datetime(2026, 11, 23, 10, 30))
        with mock.patch("app.calendar_ics.current_meeting", return_value=begun):
            meeting_guard.recording_ended(now=now.timestamp())
        self.assertEqual(len(meeting_guard._left), 1)


class CallHoldsTest(unittest.TestCase):
    """Asked by the user: a transcription began during a meeting that was neither recorded nor in the calendar."""

    def test_a_call_app_on_the_microphone_is_a_meeting(self):
        from app import meeting_guard

        with mock.patch("app.calendar_ics.current_meeting", return_value=None), \
                mock.patch.object(meeting_guard, "enabled", return_value=True), \
                mock.patch("app.economy.on", return_value=False):
            with mock.patch.object(meeting_guard, "_in_call", return_value=True):
                self.assertEqual(meeting_guard.busy(), "call")
            with mock.patch.object(meeting_guard, "_in_call", return_value=False):
                self.assertEqual(meeting_guard.busy(), "")


class RunNowTest(unittest.TestCase):
    """Only the user's «Да» lets a transcription go during a meeting."""

    def test_a_forced_transcription_does_not_wait(self):
        from app import transcriber

        self.assertTrue(transcriber._waits_for_meeting(transcriber._run_job, (77,)))
        self.assertFalse(transcriber.run_now(77))  # not queued: nothing to let go
        with transcriber._jobs_lock:
            transcriber._active_jobs.add(77)
        self.addCleanup(transcriber._active_jobs.discard, 77)
        self.addCleanup(transcriber._forced.discard, 77)
        self.assertTrue(transcriber.run_now(77))
        self.assertFalse(transcriber._waits_for_meeting(transcriber._run_job, (77,)))
        self.assertTrue(transcriber._waits_for_meeting(transcriber._run_job, (78,)))


@unittest.skipIf(transcriber is None, "app dependencies not installed")
class VoiceNoteIsNoMeetingTest(unittest.TestCase):
    """Reported by the user: a voice note of a minute, recorded by hand with no call and no meeting in the
    calendar, held the queue («ждёт конца встречи») while it recorded and 2 minutes after. Only a recording of a
    meeting (a call or the calendar started it, or it follows a Teams meeting) holds it now."""

    def setUp(self):
        init_db()
        update_settings({"analysis_after_meetings": "true"})
        app_status.set_recording(False)
        meeting_guard._state.update(busy="", quiet_since=0.0, ended=0.0, ended_kind="", looked=True)
        for p in (mock.patch("app.calendar_ics.current_meeting", return_value=None),
                  mock.patch.object(meeting_guard, "_in_call", return_value=False),
                  mock.patch("app.economy.on", return_value=False),
                  mock.patch("app.transcriber.wake_queue")):
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        meeting_guard._state.update(busy="", ended=0.0, ended_kind="")
        app_status.set_recording(False)

    def test_a_voice_note_holds_nothing_and_starts_no_pause(self):
        app_status.set_recording(True, meeting=False)
        self.assertEqual(meeting_guard.busy(), "")
        meeting_guard.check(now=1000.0)
        self.assertFalse(meeting_guard.holds_queue(now=1000.0))
        self.assertEqual(meeting_guard.hold_state(now=1000.0), {})
        app_status.set_recording(False)
        meeting_guard.check(now=1060.0)  # stopped after a minute
        self.assertFalse(meeting_guard.holds_queue(now=1061.0))  # no pause of 2 minutes after it
        self.assertIsNone(meeting_guard.hold_until(now=1061.0))
        self.assertEqual(meeting_guard.hold_state(now=1061.0), {})

    def test_a_recording_of_a_meeting_holds_and_starts_the_pause(self):
        app_status.set_recording(True, meeting=True)
        self.assertEqual(meeting_guard.busy(), "recording")
        meeting_guard.check(now=1000.0)
        self.assertTrue(meeting_guard.holds_queue(now=1000.0))
        self.assertEqual(meeting_guard.hold_state(now=1000.0), {"kind": "meeting", "reason": "recording"})
        app_status.set_recording(False)
        meeting_guard.check(now=2000.0)
        self.assertTrue(meeting_guard.holds_queue(now=2000.0 + 20))
        st = meeting_guard.hold_state(now=2000.0 + 20)
        self.assertEqual(st, {"kind": "pause", "until": 2000.0 + meeting_guard.QUIET_SEC,
                              "left": int(meeting_guard.QUIET_SEC) - 20, "reason": "recording"})
        self.assertEqual(meeting_guard.hold_state(now=2000.0 + meeting_guard.QUIET_SEC + 1), {})

    def test_a_voice_note_found_to_follow_a_teams_meeting_becomes_one(self):
        """The page says it again once the recording follows a Teams meeting: it holds from then on, its start kept."""
        app_status.set_recording(True, meeting=False)
        since = app_status._ui["since"]
        app_status.set_recording(True, meeting=True)
        self.assertEqual(app_status._ui["since"], since)
        self.assertEqual(meeting_guard.busy(), "recording")

    def test_an_older_page_saying_nothing_is_taken_for_a_meeting(self):
        from app import main  # noqa: F401 - app/api/recording.py is loaded by it
        from app.api.recording import UiStatePayload

        payload = UiStatePayload(recording=True)
        self.assertIsNone(payload.meeting)
        app_status.set_recording(payload.recording, payload.meeting)
        self.assertEqual(meeting_guard.busy(), "recording")

    def test_a_call_and_the_calendar_still_hold_during_a_voice_note(self):
        app_status.set_recording(True, meeting=False)
        with mock.patch.object(meeting_guard, "_in_call", return_value=True):
            self.assertEqual(meeting_guard.busy(), "call")
        with mock.patch("app.calendar_ics.current_meeting", return_value={"title": "Планёрка"}):
            self.assertEqual(meeting_guard.busy(), "calendar")

    def test_the_pause_follows_a_call_but_not_recording_only(self):
        with mock.patch.object(meeting_guard, "_in_call", return_value=True):
            meeting_guard.check(now=1000.0)
        meeting_guard.check(now=1100.0)  # the call is over
        self.assertEqual(meeting_guard.hold_state(now=1110.0)["reason"], "call")
        meeting_guard._state.update(busy="", ended=0.0, ended_kind="")
        with mock.patch("app.economy.on", return_value=True):
            meeting_guard.check(now=3000.0)
        meeting_guard.check(now=3100.0)  # «Только запись» is off: no meeting was going on
        self.assertIsNone(meeting_guard.hold_until(now=3101.0))


@unittest.skipIf(transcriber is None, "app dependencies not installed")
class QueuePausedApiTest(unittest.TestCase):
    """The queue's window says whether a meeting goes on or the pause after it, with the time left."""

    def setUp(self):
        from app import main  # noqa: F401 - app/api/media.py is loaded by it
        from app.api import media

        self.api = media.api_queue_paused
        self.addCleanup(transcriber._held_said.__setitem__, 0, transcriber._held_said[0])

    def test_nothing_held(self):
        transcriber._held_said[0] = False
        r = self.api()
        self.assertEqual(r["hold"], {})
        self.assertFalse(r["meeting"])

    def test_a_meeting_and_the_pause_after_it(self):
        transcriber._held_said[0] = True
        with mock.patch("app.meeting_guard.hold_state", return_value={"kind": "meeting", "reason": "call"}):
            r = self.api()
        self.assertTrue(r["meeting"])
        self.assertEqual(r["hold"], {"kind": "meeting", "reason": "call"})
        meeting_guard._state.update(busy="", ended=time.time() - 20, ended_kind="calendar", looked=True)
        self.addCleanup(meeting_guard._state.update, ended=0.0, ended_kind="")
        r = self.api()
        self.assertEqual(r["hold"]["kind"], "pause")
        self.assertEqual(r["hold"]["reason"], "calendar")
        self.assertTrue(meeting_guard.QUIET_SEC - 22 <= r["hold"]["left"] <= meeting_guard.QUIET_SEC - 19)
        self.assertGreater(r["hold"]["until"], time.time())
