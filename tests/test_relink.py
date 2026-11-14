"""«Указать файл…»: a recording whose file moved is pointed at its new place (app/api/library.py)."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from app import main  # noqa: F401 - the routers are made with the app
    from app.api import library
    from app.database import create_meeting, get_meeting, init_db, update_meeting_progress
except ImportError:  # app dependencies are not installed (e.g. in the release CI job)
    library = None


@unittest.skipIf(library is None, "app dependencies not installed")
class RelinkTest(unittest.TestCase):
    def setUp(self):
        init_db()
        self.tmp = tempfile.TemporaryDirectory()
        self.new = Path(self.tmp.name) / "Встреча.mp4"
        self.new.write_bytes(b"0" * 100)
        m = create_meeting("Встреча", "Встреча.mp4", str(Path(self.tmp.name) / "old" / "Встреча.mp4"), source="local")
        self.mid = m["id"]
        from app.database import _db_lock, get_connection

        with _db_lock:
            conn = get_connection()
            conn.execute("UPDATE meetings SET duration = 600 WHERE id = ?", (self.mid,))
            conn.commit()
            conn.close()
        update_meeting_progress(self.mid, status="failed", error_message="Файл не найден")

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_then_found(self):
        self.assertTrue(main.api_get_meeting(self.mid)["media_missing"])
        with mock.patch("app.audio_utils.get_media_duration", return_value=601.0), \
                mock.patch.object(library, "enqueue_meeting_job") as enq:
            out = library.api_relink_media(self.mid, library.RelinkPayload(path=str(self.new)))
        self.assertFalse(out["media_missing"])
        self.assertEqual(Path(get_meeting(self.mid)["media_path"]), self.new.resolve())
        enq.assert_called_once_with(self.mid)  # no transcript yet: it is made now

    def test_another_length_is_asked_about(self):
        with mock.patch("app.audio_utils.get_media_duration", return_value=60.0):
            res = library.api_relink_media(self.mid, library.RelinkPayload(path=str(self.new)))
        self.assertEqual(res.status_code, 409)
        self.assertNotEqual(Path(get_meeting(self.mid)["media_path"]), self.new.resolve())
        with mock.patch("app.audio_utils.get_media_duration", return_value=60.0), \
                mock.patch.object(library, "enqueue_meeting_job"):
            library.api_relink_media(self.mid, library.RelinkPayload(path=str(self.new), force=True))
        self.assertEqual(Path(get_meeting(self.mid)["media_path"]), self.new.resolve())


if __name__ == "__main__":
    unittest.main()
