"""The mix of a stopped recording and «Не мешать на встречах» (app/api/recording.py): a short recording is mixed
at once, a long one waits QUIET_SEC after the meeting with a countdown on its card, and a recording deleted while
its mix waits or runs leaves no track, file or recording behind (reported by the user: two short recordings
stood at 1 % «после встречи» for two minutes and could not be deleted meanwhile)."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import json
import threading
import time
import unittest
from unittest import mock

try:
    from app import main  # noqa: F401 - the routers are made with the app
    from app.api import recording
    from app.api.library import api_delete_meeting
    from app.database import get_meeting, init_db, list_meetings
except ImportError:  # app dependencies are not installed (e.g. in the release CI job)
    recording = None

from app import app_status, meeting_guard


class HoldUntilTest(unittest.TestCase):
    def setUp(self):
        self.saved = dict(meeting_guard._state)

    def tearDown(self):
        meeting_guard._state.clear()
        meeting_guard._state.update(self.saved)

    def test_the_hold_ends_quiet_sec_after_the_meeting(self):
        meeting_guard._state.update(looked=True, busy="recording", ended=0.0)
        self.assertEqual(meeting_guard.hold_until(now=1000.0), 0.0)  # a meeting goes on: its end is not known
        meeting_guard._state.update(busy="", ended=1000.0)
        self.assertEqual(meeting_guard.hold_until(now=1030.0), 1000.0 + meeting_guard.QUIET_SEC)
        self.assertTrue(meeting_guard.holds_queue(now=1030.0))
        self.assertIsNone(meeting_guard.hold_until(now=1000.0 + meeting_guard.QUIET_SEC + 1))
        self.assertFalse(meeting_guard.holds_queue(now=1000.0 + meeting_guard.QUIET_SEC + 1))

    def test_recording_only_does_not_hold_the_mix(self):
        meeting_guard._state.update(looked=True, busy="economy", ended=0.0)
        self.assertIsNone(meeting_guard.hold_until(now=1000.0))


@unittest.skipIf(recording is None, "app dependencies not installed")
class MixWaitTest(unittest.TestCase):
    def setUp(self):
        init_db()
        self.dir = recording._recordings_dir()
        self.dir.mkdir(parents=True, exist_ok=True)
        self.calendar = mock.patch("app.calendar_ics.apply_to_recording")
        self.calendar.start()
        self.threads = []

    def tearDown(self):
        self.calendar.stop()
        for t in self.threads:
            t.join(5)

    def _finish(self, pid, seconds, **extra):
        """A recording of `seconds` stopped: its page part, the mix thread started."""
        page = self.dir / f".page_{pid}.webm.part"
        page.write_bytes(b"x" * 8192)
        recording._page_recordings[pid] = page
        payload = recording.RecordFinishPayload(title="Синк", page_id=pid, has_mic=True, started_at=time.time() - seconds)
        recording.api_record_heartbeat(payload)  # its notes' file, as the page keeps it
        started = []
        real = threading.Thread

        def spy(*a, **kw):
            t = real(*a, **kw)
            if kw.get("name") == "record_mix":
                started.append(t)
            return t

        with mock.patch.object(recording, "_recorded_seconds", return_value=seconds), \
                mock.patch.object(recording, "_mix_parts", side_effect=lambda *a, **kw: extra["mix"](*a)), \
                mock.patch("app.api.recording.threading.Thread", side_effect=spy):
            mid = recording.finish_recording(payload)["created"][0]["id"]
        self.threads += started
        return mid, page, started[0] if started else None

    def _mixed(self, page, *_):
        dest = self.dir / f"{page.name}.m4a"
        dest.write_bytes(b"m" * 100)
        return {"dest": dest, "has_video": False, "cleanup": [page]}

    def test_a_short_recording_is_mixed_at_once(self):
        with mock.patch.object(meeting_guard, "hold_until", return_value=0.0) as held, \
                mock.patch.object(recording, "enqueue_meeting_job") as enqueue:
            mid, page, thread = self._finish("mw1", 12.7, mix=lambda p, page, *a: self._mixed(page))
            thread.join(5)
        held.assert_not_called()  # the meeting going on (its own recording) is not waited for
        m = get_meeting(mid)
        self.assertEqual(m["status"], "queued")
        enqueue.assert_called_once_with(mid)
        self.assertNotIn(mid, app_status.mixing)
        from app.database import delete_meeting

        self.assertTrue(delete_meeting(mid))

    def test_a_long_recording_waits_with_a_countdown(self):
        until = time.time() + 100
        answers = iter([until, until, None])
        progress = []
        from app import database

        orig = database.update_meeting_progress

        def watch(mid, **kw):
            progress.append((kw.get("stage_text"), app_status.mix_state(mid).get("mix_wait")))
            return orig(mid, **kw)

        m = database.create_meeting(title="Долгая", filename="d", media_path="", source="recording")
        self.addCleanup(database.delete_meeting, m["id"])
        recording._mixes[m["id"]] = {"wake": threading.Event(), "delete": None, "seconds": 600.0}
        app_status.mixing.add(m["id"])
        try:
            with mock.patch.object(meeting_guard, "hold_until", side_effect=lambda: next(answers)), \
                    mock.patch.object(database, "update_meeting_progress", side_effect=watch), \
                    mock.patch.object(recording._mixes[m["id"]]["wake"], "wait") as waited:
                self.assertTrue(recording._wait_for_meeting_end(m["id"], 600.0))
                fields = database._mix_fields(m["id"])
        finally:
            app_status.mixing.discard(m["id"])
            recording._mixes.pop(m["id"], None)
        self.assertEqual(waited.call_count, 2)
        self.assertEqual(progress[0], ("Сведение дорожек: пауза на случай следующей встречи", until))
        self.assertEqual(progress[-1][0], "Сведение дорожек записи...")
        self.assertEqual(fields, {"mix_wait": None, "mix_deleting": False})  # the countdown is over
        self.assertNotIn(m["id"], app_status.mix_wait)

    def test_a_meeting_going_on_says_after_the_meeting(self):
        from app import database

        answers = iter([0.0, None])
        m = database.create_meeting(title="Долгая", filename="d", media_path="", source="recording")
        self.addCleanup(database.delete_meeting, m["id"])
        seen = []
        with mock.patch.object(meeting_guard, "hold_until", side_effect=lambda: next(answers)), \
                mock.patch("time.sleep"), \
                mock.patch.object(database, "update_meeting_progress", side_effect=lambda mid, **kw: seen.append(kw["stage_text"])):
            recording._wait_for_meeting_end(m["id"], None)  # not known how long: taken for a long one
        self.assertEqual(seen[0], "Сведение дорожек: начнётся после встречи")

    def test_the_list_shows_the_wait(self):
        from app import database

        m = database.create_meeting(title="Ждёт", filename="w", media_path="", source="recording")
        self.addCleanup(database.delete_meeting, m["id"])
        database.update_meeting_progress(m["id"], status="mixing", progress=1)
        app_status.mixing.add(m["id"])
        app_status.mix_wait[m["id"]] = 1234.0
        try:
            row = next(r for r in list_meetings() if r["id"] == m["id"])
            self.assertEqual((row["mix_wait"], row["mix_deleting"]), (1234.0, False))
            self.assertEqual(get_meeting(m["id"])["mix_wait"], 1234.0)
        finally:
            app_status.mixing.discard(m["id"])
            app_status.mix_wait.pop(m["id"], None)

    def test_deleting_while_the_mix_waits_leaves_nothing(self):
        mixed = []
        with mock.patch.object(meeting_guard, "hold_until", return_value=0.0), \
                mock.patch.object(recording, "enqueue_meeting_job") as enqueue:
            mid, page, thread = self._finish("mw2", 600, mix=lambda *a: mixed.append(a))
            for _ in range(100):
                if mid in app_status.mix_wait:
                    break
                time.sleep(0.02)
            self.assertIn(mid, app_status.mix_wait)
            self.assertEqual(api_delete_meeting(mid), {"ok": True})
            thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(mixed, [])  # nothing was mixed
        enqueue.assert_not_called()
        self.assertIsNone(get_meeting(mid))
        self.assertFalse(page.exists())
        self.assertFalse((self.dir / ".rec_mw2.json").exists())
        self.assertNotIn(mid, app_status.mixing)
        self.assertNotIn(mid, recording._mixes)

    def test_deleting_during_the_mix_deletes_it_once_mixed(self):
        go, inside, made = threading.Event(), threading.Event(), []

        def slow_mix(p, page, *a):
            inside.set()
            go.wait(5)
            made.append(self._mixed(page))
            return made[-1]

        with mock.patch.object(meeting_guard, "hold_until", return_value=None), \
                mock.patch.object(recording, "enqueue_meeting_job") as enqueue:
            mid, page, thread = self._finish("mw3", 600, mix=slow_mix)
            self.assertTrue(inside.wait(5))
            got = api_delete_meeting(mid)
            self.assertEqual(got, {"ok": True, "later": True, "detail": "Запись удалится, как только сведутся дорожки"})
            self.assertIsNotNone(get_meeting(mid))  # still mixing: it goes when the mix is over
            self.assertTrue(get_meeting(mid)["mix_deleting"])
            # a restart now deletes it instead of bringing it back
            self.assertTrue(json.loads((self.dir / ".rec_mw3.json").read_text(encoding="utf-8"))["delete"])
            go.set()
            thread.join(5)
        enqueue.assert_not_called()
        self.assertIsNone(get_meeting(mid))
        self.assertFalse(made[0]["dest"].exists())
        self.assertFalse(page.exists())
        self.assertFalse((self.dir / ".rec_mw3.json").exists())
        self.assertNotIn(mid, app_status.mixing)

    def test_a_restart_after_a_deletion_during_the_mix_brings_nothing_back(self):
        from app import database

        page = self.dir / ".page_mw4.webm.part"
        page.write_bytes(b"x" * 8192)
        system = self.dir / "system_mw4.wav"
        system.write_bytes(b"y" * 8192)
        m = database.create_meeting(title="Удалена", filename="u", media_path="", source="recording")
        database.update_meeting_progress(m["id"], status="mixing", progress=40)
        (self.dir / ".rec_mw4.json").write_text(json.dumps({
            "delete": True, "meeting_id": m["id"], "paths": {"page": str(page), "system": str(system)}}), encoding="utf-8")
        with mock.patch.object(recording, "finish_recording") as finish:
            used = recording.recover_sessions()
        finish.assert_not_called()
        self.assertEqual({p.name for p in used}, {page.name, system.name})  # not recovered one by one either
        self.assertFalse(page.exists())
        self.assertFalse(system.exists())
        self.assertIsNone(get_meeting(m["id"]))
        self.assertFalse((self.dir / ".rec_mw4.json").exists())

    def test_a_recording_not_being_mixed_is_deleted_as_before(self):
        from app import database

        m = database.create_meeting(title="Обычная", filename="o", media_path="")
        self.assertIsNone(recording.delete_when_mixed(m["id"], {}))
        self.assertEqual(api_delete_meeting(m["id"]), {"ok": True})
        self.assertIsNone(get_meeting(m["id"]))


@unittest.skipIf(recording is None, "app dependencies not installed")
class RecordedSecondsTest(unittest.TestCase):
    def test_by_the_page_clock_and_unknown_after_a_crash(self):
        p = recording.RecordFinishPayload(title="x", started_at=time.time() - 90)
        self.assertAlmostEqual(recording._recorded_seconds(p, None), 90, delta=2)
        self.assertIsNone(recording._recorded_seconds(p, {"page": "a"}))
        self.assertIsNone(recording._recorded_seconds(recording.RecordFinishPayload(title="x"), None))


if __name__ == "__main__":
    unittest.main()
