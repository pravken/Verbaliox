import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import shutil
import time
import unittest
from unittest import mock

from app import app_status
from app.database import create_meeting, delete_meeting, init_db, list_meetings, update_meeting_progress

try:
    from app import untranscribed
except ImportError:  # the release CI runs without the app's packages
    untranscribed = None


@unittest.skipIf(untranscribed is None, "app dependencies not installed")
class UntranscribedTest(unittest.TestCase):
    """Asked by the user: remind of the recordings whose transcription was cancelled by hand, offer to transcribe."""

    def setUp(self):
        init_db()
        for m in list_meetings():
            delete_meeting(m["id"])
        self.dir = tests.temp_dir(self)
        untranscribed._state.update(checked=0.0, noticed=0.0)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)
        app_status.take_notices()

    def _rec(self, title, status, with_file=True):
        path = self.dir / f"{title}.wav"
        if with_file:
            path.write_bytes(b"RIFF")
        m = create_meeting(title=title, filename=path.name, media_path=str(path))
        update_meeting_progress(m["id"], status=status, progress=0)
        return m["id"]

    def test_only_cancelled_recordings_with_their_file_and_not_dismissed(self):
        a = self._rec("Отменённая", "cancelled")
        self._rec("Ошибка", "failed")
        self._rec("Без файла", "cancelled", with_file=False)
        self._rec("Добавленная", "added")
        b = self._rec("Ещё одна", "cancelled")
        # cancelled mid-recognition: the phrases saved so far are there, the transcript was never finished
        from app.database import save_meeting_results

        c = self._rec("Наполовину", "cancelled")
        save_meeting_results(c, segments=[{"id": 1, "start": 0.0, "end": 2.0, "speaker": "S0", "text": "Привет"}])
        update_meeting_progress(c, status="cancelled", progress=0)
        self.assertIn(c, {x["id"] for x in untranscribed.items()})
        untranscribed.dismiss([c])
        self.assertEqual({x["id"] for x in untranscribed.items()}, {a, b})
        untranscribed.dismiss([b])
        self.assertEqual([x["id"] for x in untranscribed.items()], [a])
        with mock.patch("app.transcriber.enqueue_meeting_job", return_value=True) as enq:
            self.assertEqual(untranscribed.transcribe([a, b]), 1)  # the dismissed one is left alone
            enq.assert_called_once_with(a, manual=True)

    def test_a_notice_once_a_day_and_never_during_a_meeting(self):
        self._rec("Синк", "cancelled")
        untranscribed._state.update(checked=time.time(), noticed=0.0)  # the meeting watch of another test ticked
        with mock.patch("app.meeting_guard.busy", return_value="recording"):
            self.assertFalse(untranscribed.notice_tick(now=1_000_000.0))
        with mock.patch("app.meeting_guard.busy", return_value=""):
            self.assertTrue(untranscribed.notice_tick(now=1_000_000.0 + untranscribed.CHECK_EVERY_SEC))
            self.assertFalse(untranscribed.notice_tick(now=1_010_000.0 + untranscribed.CHECK_EVERY_SEC))  # once a day
        notice = app_status.take_notices()[-1]
        self.assertEqual(notice["target"], "dashboard")
        self.assertIn("«Синк»", notice["text"])


if __name__ == "__main__":
    unittest.main()
