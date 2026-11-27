"""«Фоновая обработка» (app/queue_window.py): the automatic work of the queue starts only when the computer is free
(no input for a while, or the other programs' load low for 2 minutes) or by the schedule (asked by the user:
«работаю — всё зависает»). What the user starts by hand, «Начать сейчас» and «Свести сейчас» are not held."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import functools
import threading
import unittest
from datetime import datetime
from unittest import mock

from app import meeting_guard, procstat, queue_window
from app.database import create_meeting, init_db, update_settings
from app.settings_schema import clean

try:
    from app import transcriber
except ImportError:  # the release CI runs without the app's packages
    transcriber = None

SETTINGS = {"queue_when": "idle", "queue_idle_min": "5", "queue_cpu_max": "30", "queue_gpu_max": "30",
            "queue_from": "19:00", "queue_to": "08:00"}


def _at(hh: int, mm: int = 0) -> float:
    return datetime(2026, 11, 27, hh, mm).timestamp()


class ScheduleTest(unittest.TestCase):
    def test_a_window_across_midnight(self):
        start, end = 19 * 60, 8 * 60
        for hh, inside in ((18, False), (19, True), (23, True), (0, True), (7, True), (8, False), (12, False)):
            self.assertEqual(queue_window.in_schedule(datetime(2026, 11, 27, hh, 30 if hh == 7 else 0), start, end), inside, hh)

    def test_a_window_within_the_day_and_the_whole_day(self):
        self.assertTrue(queue_window.in_schedule(datetime(2026, 11, 27, 13, 0), 12 * 60, 14 * 60))
        self.assertFalse(queue_window.in_schedule(datetime(2026, 11, 27, 14, 0), 12 * 60, 14 * 60))
        self.assertTrue(queue_window.in_schedule(datetime(2026, 11, 27, 3, 0), 600, 600))

    def test_the_next_start(self):
        self.assertEqual(queue_window.next_start(datetime(2026, 11, 27, 10, 0), 19 * 60), datetime(2026, 11, 27, 19, 0))
        self.assertEqual(queue_window.next_start(datetime(2026, 11, 27, 19, 30), 19 * 60), datetime(2026, 11, 28, 19, 0))

    def test_the_schedule_holds_until_its_start(self):
        s = dict(SETTINGS, queue_when="schedule")
        held = queue_window.decide(s, _at(10), idle=10_000, low_since=_at(9))  # free does not count here
        self.assertEqual(held["kind"], "schedule")
        self.assertEqual(held["from"], "19:00")
        self.assertEqual(held["until"], _at(19))
        self.assertEqual(queue_window.decide(s, _at(22), idle=0, low_since=0), {})
        self.assertEqual(queue_window.decide(s, _at(3), idle=0, low_since=0), {})


class FreeTest(unittest.TestCase):
    def test_always_holds_nothing(self):
        self.assertEqual(queue_window.decide(dict(SETTINGS, queue_when="always"), _at(10), idle=0, low_since=0), {})

    def test_free_by_input(self):
        self.assertEqual(queue_window.decide(SETTINGS, _at(10), idle=60, low_since=0), {"kind": "idle"})
        self.assertEqual(queue_window.decide(SETTINGS, _at(10), idle=5 * 60, low_since=0), {})
        self.assertEqual(queue_window.decide(dict(SETTINGS, queue_idle_min="15"), _at(10), idle=5 * 60, low_since=0),
                         {"kind": "idle"})

    def test_free_by_a_low_load_for_two_minutes(self):
        now = _at(10)
        self.assertEqual(queue_window.decide(SETTINGS, now, idle=3, low_since=now - 60), {"kind": "idle"})
        self.assertEqual(queue_window.decide(SETTINGS, now, idle=3, low_since=now - 121), {})

    def test_nothing_measurable_is_free(self):
        self.assertEqual(queue_window.decide(SETTINGS, _at(10), idle=None, low_since=0, measured=False), {})
        self.assertEqual(queue_window.decide(SETTINGS, _at(10), idle=None, low_since=0, measured=True), {"kind": "idle"})

    def test_either_tells_both(self):
        s = dict(SETTINGS, queue_when="idle_or_schedule")
        held = queue_window.decide(s, _at(10), idle=3, low_since=0)
        self.assertEqual((held["kind"], held["from"]), ("idle", "19:00"))
        self.assertEqual(queue_window.decide(s, _at(10), idle=600, low_since=0), {})
        self.assertEqual(queue_window.decide(s, _at(20), idle=3, low_since=0), {})

    def test_the_run_of_low_looks(self):
        with mock.patch.dict(queue_window._state, {"low_since": 0.0, "measured": False}):
            queue_window.note(SETTINGS, 100.0, cpu=10.0, gpu=None)  # no video card: the processor alone
            queue_window.note(SETTINGS, 115.0, cpu=12.0, gpu=5.0)
            self.assertEqual(queue_window._state["low_since"], 100.0)
            queue_window.note(SETTINGS, 130.0, cpu=None, gpu=None)  # not read: breaks nothing
            self.assertEqual(queue_window._state["low_since"], 100.0)
            queue_window.note(SETTINGS, 145.0, cpu=10.0, gpu=80.0)  # a game on the video card
            self.assertEqual(queue_window._state["low_since"], 0.0)
            queue_window.note(SETTINGS, 160.0, cpu=50.0, gpu=0.0)
            self.assertEqual(queue_window._state["low_since"], 0.0)
            queue_window.note(SETTINGS, 175.0, cpu=5.0, gpu=0.0)
            self.assertEqual(queue_window._state["low_since"], 175.0)


class OwnLoadTest(unittest.TestCase):
    """The program's own processes (this one, ffmpeg and the workers it started, Ollama) are no user's load."""

    def setUp(self):
        queue_window._prev.update(sys=None, own={}, at=0.0)
        self.addCleanup(queue_window._prev.update, sys=None, own={}, at=0.0)

    def test_the_tree_of_the_program(self):
        parents = {10: 1, 11: 10, 12: 11, 20: 1, 21: 20}
        self.assertEqual(sorted(procstat.descendants(10, parents)), [10, 11, 12])

    def test_the_processor_less_the_program(self):
        cpu = {10: 0.0, 11: 0.0, 99: 0.0}
        clock = [1000.0]
        with mock.patch("app.sysinfo._cpu_times", side_effect=[(0, 0), (40, 100)]), \
                mock.patch("app.procstat.cpu_seconds", side_effect=lambda pid: cpu.get(pid)), \
                mock.patch("app.queue_window.time.monotonic", side_effect=lambda: clock[0]), \
                mock.patch("os.cpu_count", return_value=4):
            self.assertIsNone(queue_window._cpu_other({10, 11}))  # the first look: nothing to compare
            clock[0] += 10.0
            cpu.update({10: 12.0, 11: 4.0, 99: 30.0})  # 16 s of 40 processor-seconds: 40 % of the computer
            other = queue_window._cpu_other({10, 11})
        self.assertAlmostEqual(other, 20.0)  # 60 % in all, 40 % of it the program's own

    def test_the_video_card_less_the_program(self):
        with mock.patch("app.vram.gpu_utilization", return_value=70), \
                mock.patch("app.vram.gpu_process_utilization", return_value={10: 60, 77: 10}):
            self.assertEqual(queue_window._gpu_other({10}), 10.0)

    def test_no_video_card(self):
        with mock.patch("app.vram.gpu_utilization", return_value=None):
            self.assertIsNone(queue_window._gpu_other({10}))

    def test_the_share_unknown_while_the_program_works_on_it(self):
        with mock.patch("app.vram.gpu_utilization", return_value=90), \
                mock.patch("app.vram.gpu_process_utilization", return_value=None), \
                mock.patch("app.queue_window._own_busy_on_gpu", return_value=True):
            self.assertIsNone(queue_window._gpu_other({10}))  # this look counts the processor only
        with mock.patch("app.vram.gpu_utilization", return_value=90), \
                mock.patch("app.vram.gpu_process_utilization", return_value=None), \
                mock.patch("app.queue_window._own_busy_on_gpu", return_value=False):
            self.assertEqual(queue_window._gpu_other({10}), 90.0)


class SettingsTest(unittest.TestCase):
    def test_validation(self):
        self.assertEqual(clean("queue_when", "idle_or_schedule"), "idle_or_schedule")
        with self.assertRaises(ValueError):
            clean("queue_when", "sometimes")
        self.assertEqual(clean("queue_from", "8:30"), "08:30")
        self.assertEqual(clean("queue_to", "23:59"), "23:59")
        for bad in ("24:00", "7", "19-00", "ab:cd"):
            with self.assertRaises(ValueError):
                clean("queue_from", bad)
        self.assertEqual(clean("queue_cpu_max", "200"), "95")
        self.assertEqual(clean("queue_idle_min", "0"), "1")

    def test_defaults_keep_todays_behaviour(self):
        init_db()
        update_settings({"queue_when": "always"})
        self.assertEqual(queue_window.mode(), "always")
        self.assertEqual(meeting_guard.window_hold(), {})


class HoldStateTest(unittest.TestCase):
    def setUp(self):
        init_db()
        meeting_guard._state.update(busy="", ended=0.0, looked=True)
        self.addCleanup(update_settings, {"queue_when": "always"})

    def test_the_reason_for_the_page(self):
        update_settings({"queue_when": "idle"})
        with mock.patch("app.queue_window._idle_seconds", return_value=10.0), \
                mock.patch.dict(queue_window._state, {"low_since": 0.0, "measured": True}):
            self.assertEqual(meeting_guard.hold_state(), {"kind": "idle"})
            with mock.patch("app.queue_window._idle_seconds", return_value=3600.0):
                self.assertEqual(meeting_guard.hold_state(), {})
        update_settings({"queue_when": "schedule", "queue_from": "19:00", "queue_to": "08:00"})
        state = meeting_guard.hold_state(_at(10))
        self.assertEqual((state["kind"], state["from"], state["left"]), ("schedule", "19:00", 9 * 3600))

    def test_a_meeting_comes_first(self):
        update_settings({"queue_when": "schedule"})
        meeting_guard._state.update(busy="recording")
        self.addCleanup(meeting_guard._state.update, busy="")
        self.assertEqual(meeting_guard.hold_state(_at(10))["kind"], "meeting")


@unittest.skipIf(transcriber is None, "app dependencies not installed")
class QueueTest(unittest.TestCase):
    def setUp(self):
        init_db()
        self.window = {"kind": "idle"}
        p = mock.patch("app.meeting_guard.window_hold", side_effect=lambda now=None: dict(self.window))
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch("app.transcriber._meeting_holds", return_value=False)
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch("app.transcriber._waits_for_captions", return_value=False)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(transcriber._forced.clear)
        self.addCleanup(transcriber._manual.clear)
        self.addCleanup(transcriber._window_said.__setitem__, 0, "")

    def test_which_jobs_wait(self):
        auto = create_meeting(title="Обзор", filename="a.wav", media_path="a.wav")["id"]
        by_hand = create_meeting(title="Импорт", filename="b.wav", media_path="b.wav")["id"]
        transcriber._manual.add(by_hand)
        self.assertTrue(transcriber._waits_for_window(transcriber._run_job, (auto,)))
        self.assertFalse(transcriber._waits_for_window(transcriber._run_job, (by_hand,)))
        side = transcriber._run_side_job
        self.assertTrue(transcriber._waits_for_window(side, (auto, "completed", transcriber._analysis_runner, False)))
        self.assertFalse(transcriber._waits_for_window(side, (auto, "completed", transcriber._analysis_runner, True)))
        self.assertFalse(transcriber._waits_for_window(side, (auto, "completed", transcriber._translate_runner, "en", None, False)))
        transcriber._forced.add(auto)  # «Начать сейчас»
        self.assertFalse(transcriber._waits_for_window(transcriber._run_job, (auto,)))

    def test_the_queue_holds_the_automatic_one_and_starts_it_when_free(self):
        auto = create_meeting(title="Обзор", filename="a.wav", media_path="a.wav")["id"]
        by_hand = create_meeting(title="Импорт", filename="b.wav", media_path="b.wav")["id"]
        transcriber._manual.add(by_hand)
        ex = transcriber._PriorityExecutor()
        ran = {auto: threading.Event(), by_hand: threading.Event()}
        with mock.patch("app.transcriber._run_job", side_effect=lambda mid, **k: ran[mid].set()) as run_job:
            ex.submit(functools.partial(run_job, token=1), auto, priority=0)
            ex.submit(functools.partial(run_job, token=2), by_hand, priority=0)
            self.assertTrue(ran[by_hand].wait(3))  # asked for by hand: at once
            self.assertFalse(ran[auto].wait(0.5))
            self.assertEqual(transcriber.window_holds(), "idle")
            self.window = {}
            ex.wake()  # app/queue_window.tick wakes the queue when the computer is free
            self.assertTrue(ran[auto].wait(3))

    def test_run_now_lets_it_go(self):
        mid = create_meeting(title="Обзор", filename="a.wav", media_path="a.wav")["id"]
        with transcriber._jobs_lock:
            transcriber._active_jobs.add(mid)
        self.addCleanup(transcriber._active_jobs.discard, mid)
        transcriber._window_said[0] = "idle"
        self.assertTrue(transcriber.run_now(mid))
        self.assertIn(mid, transcriber._forced)
        self.assertFalse(transcriber._waits_for_window(transcriber._run_job, (mid,)))

    def test_the_queue_window_says_why_it_waits(self):
        auto = create_meeting(title="Обзор", filename="a.wav", media_path="a.wav")["id"]
        by_hand = create_meeting(title="Импорт", filename="b.wav", media_path="b.wav")["id"]
        transcriber._manual.add(by_hand)
        with transcriber._jobs_lock:
            tokens = [transcriber._queue_add(auto, "transcribe"), transcriber._queue_add(by_hand, "transcribe")]
        self.addCleanup(lambda: transcriber._queue.__setitem__(
            slice(None), [q for q in transcriber._queue if q.get("n") not in tokens]))
        with mock.patch("app.transcriber.waits_for_captions", return_value=False):
            items = {q["id"]: q for q in transcriber.queue_snapshot()}
            self.assertTrue(items[auto]["window"])
            self.assertFalse(items[by_hand]["window"])
            self.window = {}
            self.assertFalse(next(q for q in transcriber.queue_snapshot() if q["id"] == auto)["window"])


@unittest.skipIf(transcriber is None, "app dependencies not installed")
class MixWaitTest(unittest.TestCase):
    """The mix of the tracks waits as the queue does; «Свести сейчас» lets it go."""

    def test_the_mix_waits_and_says_why(self):
        from app import app_status
        from app import main  # noqa: F401 - the routers are made with the app
        from app.api import recording

        mid = 424242
        wake = threading.Event()
        window = [{"kind": "schedule", "from": "19:00", "until": _at(19), "left": 100}]
        with recording._mix_lock:
            recording._mixes[mid] = {"wake": wake}
        self.addCleanup(recording._mixes.pop, mid, None)
        done = []
        with mock.patch("app.meeting_guard.hold_until", return_value=None), \
                mock.patch("app.meeting_guard.window_hold", side_effect=lambda: window[0]), \
                mock.patch("app.database.update_meeting_progress") as progress:
            t = threading.Thread(target=lambda: done.append(recording._wait_for_meeting_end(mid)))
            t.start()
            for _ in range(100):
                if mid in app_status.mix_wait:
                    break
                wake.wait(0.02)
            self.assertEqual(app_status.mix_wait.get(mid), 0.0)
            self.assertEqual(app_status.mix_why.get(mid), {"kind": "schedule", "from": "19:00"})
            self.assertTrue(recording.mix_now(mid))
            t.join(3)
        self.assertEqual(done, [True])
        self.assertIn(mock.call(mid, stage_text="Сведение дорожек: ждёт расписания"), progress.call_args_list)
        self.assertNotIn(mid, app_status.mix_wait)


if __name__ == "__main__":
    unittest.main()
