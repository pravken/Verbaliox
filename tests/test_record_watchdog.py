"""The watchdog of a recording (app/api/recording.py): the page gone before «Стоп», the recording is saved
with its notes; after a crash its parts are paired into one recording."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import json
import time
import unittest
from unittest import mock

try:
    from app import main  # noqa: F401 - the routers are made with the app
    from app.api import recording
    from app.database import get_meeting, init_db
except ImportError:  # app dependencies are not installed (e.g. in the release CI job)
    recording = None


@unittest.skipIf(recording is None, "app dependencies not installed")
class WatchdogTest(unittest.TestCase):
    def tearDown(self):
        from app import app_status

        app_status.mixing.clear()  # the mix itself is not run here

    def setUp(self):
        init_db()
        self.dir = recording._recordings_dir()
        self.dir.mkdir(parents=True, exist_ok=True)

    def _page(self, pid):
        part = self.dir / f".page_{pid}.webm.part"
        part.write_bytes(b"x" * 8192)
        recording._page_recordings[pid] = part
        return part

    def test_a_page_gone_is_saved_with_its_notes(self):
        self._page("pg1")
        payload = recording.RecordFinishPayload(title="Планёрка", page_id="pg1", has_mic=True, notes="Решили: релиз в пятницу")
        recording.api_record_heartbeat(payload)
        self.assertTrue((self.dir / ".rec_pg1.json").is_file())
        self.assertEqual(recording.save_orphans(older_than=60), 0)  # it still records
        mixes = []
        with mock.patch.object(recording, "_mix_in_background", side_effect=lambda mid, *a: mixes.append(a)), \
                mock.patch("app.calendar_ics.apply_to_recording"):
            recording._beats["pg1"] = time.time() - 600
            self.assertEqual(recording.save_orphans(older_than=60), 1)
        # found in the audit: the notes' file stays while the mix runs (a crash then recovers the recording
        # whole) and goes when the mix is over
        self.assertTrue((self.dir / ".rec_pg1.json").exists())
        recording._end_session(mixes[0][-1])
        self.assertFalse((self.dir / ".rec_pg1.json").exists())
        self.assertNotIn("pg1", recording._page_recordings)

    def test_a_recording_is_dated_by_its_start_not_its_stop(self):
        """Found in the audit: «Стоп» at 11:01 dated a 10:00 meeting's recording 11:01 (the calendar, the day)."""
        from datetime import datetime

        self._page("pg3")
        start = time.time() - 3600
        payload = recording.RecordFinishPayload(title="Синк", page_id="pg3", has_mic=True, started_at=start)
        with mock.patch.object(recording, "_mix_in_background"), mock.patch("app.calendar_ics.apply_to_recording"):
            mid = recording.finish_recording(payload)["created"][0]["id"]
        self.assertEqual(get_meeting(mid)["recorded_at"], datetime.fromtimestamp(start).strftime("%Y-%m-%d %H:%M:%S"))

    def test_a_page_opening_does_not_finish_a_recording_whose_heartbeat_is_late(self):
        self._page("pg3")
        payload = recording.RecordFinishPayload(title="Созвон", page_id="pg3", has_mic=True)
        recording.api_record_heartbeat(payload)
        try:
            recording._beats["pg3"] = time.time() - 20  # two beats late: still recording
            got = recording.api_save_orphans(recording.OrphanPayload(older_than=12))  # an older page asks for 12 s
            self.assertEqual(got, {"saved": 0})
            self.assertIn("pg3", recording._beats)
        finally:
            recording._beats.pop("pg3", None)
            recording._page_recordings.pop("pg3", None)
            (self.dir / ".rec_pg3.json").unlink(missing_ok=True)

    def test_after_a_crash_the_parts_become_one_recording_with_notes(self):
        page = self.dir / ".page_pg2.webm.part"
        page.write_bytes(b"x" * 8192)
        system = self.dir / "system_pg2.wav"
        system.write_bytes(b"y" * 8192)
        (self.dir / ".rec_pg2.json").write_text(json.dumps({
            "payload": {"title": "Созвон", "page_id": "pg2", "capture_id": "cap2", "notes": "заметка", "has_mic": True},
            "paths": {"page": str(page), "system": str(system), "system_started": 1.0}}), encoding="utf-8")
        made = []
        with mock.patch.object(recording, "_mix_in_background", side_effect=lambda mid, *a: (made.append((mid, a)), recording._end_session(a[-1]))), \
                mock.patch("app.calendar_ics.apply_to_recording"):
            used = recording.recover_sessions()
        self.assertEqual({p.name for p in used}, {page.name, system.name})
        self.assertEqual(len(made), 1)
        m = get_meeting(made[0][0])
        self.assertEqual((m["title"], m["user_notes"]), ("Созвон", "заметка"))
        self.assertFalse((self.dir / ".rec_pg2.json").exists())
        page.unlink(missing_ok=True)
        system.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
