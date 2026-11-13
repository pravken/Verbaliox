"""Imported files stay where they are unless Settings say to copy them (app/api/library.py)."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from app import main  # noqa: F401 - the routers are made with the app
    from app.api import library
    from app.database import get_meeting, init_db, update_settings
except ImportError:  # app dependencies are not installed (e.g. in the release CI job)
    library = None


@unittest.skipIf(library is None, "fastapi and app dependencies not installed")
class ImportInPlaceTest(unittest.TestCase):
    def setUp(self):
        init_db()
        self.tmp = tempfile.TemporaryDirectory()
        self.src = Path(self.tmp.name) / "Встреча.mp4"
        self.src.write_bytes(b"0" * 2048)

    def tearDown(self):
        update_settings({"import_copy": "false"})
        self.tmp.cleanup()

    def _add(self):
        with mock.patch.object(library, "enqueue_meeting_job"):
            out = library.api_add_local_path(library.LocalPathPayload(path=str(self.src)))
        return get_meeting(out["created"][0]["id"])

    def test_by_default_the_file_stays_where_it_is(self):
        update_settings({"import_copy": "false"})
        m = self._add()
        self.assertEqual(Path(m["media_path"]), self.src.resolve())
        self.assertFalse(m["owns_media"])

    def test_with_the_setting_the_program_keeps_a_copy(self):
        update_settings({"import_copy": "true"})
        m = self._add()
        copy = Path(m["media_path"])
        self.assertNotEqual(copy, self.src.resolve())
        self.assertEqual(copy.parent, library.UPLOADS_DIR)
        self.assertEqual(copy.read_bytes(), self.src.read_bytes())
        self.assertTrue(m["owns_media"])
        self.assertTrue(self.src.exists())  # the original is left alone
        copy.unlink()


if __name__ == "__main__":
    unittest.main()
