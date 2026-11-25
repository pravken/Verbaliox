import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import json
import unittest
from unittest import mock

from app import backup


class DubPathsTest(unittest.TestCase):
    """A dub's files are the only ones deleting the dub deletes: a restored database naming the database
    itself or bin/ffmpeg.exe as a dub's file leaves them alone."""

    def test_a_backup_keeps_only_the_files_of_dubs(self):
        raw = json.dumps([{"lang": "a", "path": "meetings.db"}, {"lang": "b", "srt_path": "bin/ffmpeg.exe"},
                          {"lang": "c", "path": "dubs"}, {"lang": "d", "path": "dubs/x.de.mp4", "srt_path": "dubs\\x.de.srt"}])
        self.assertEqual([d["lang"] for d in json.loads(backup._clean_dubs(raw))], ["d"])
        self.assertIsNone(backup._clean_dubs(json.dumps([{"lang": "d", "path": "dubs/x.mp4"}])))

    def test_deleting_a_dub_deletes_only_its_own_files(self):
        from app import database as db

        db.init_db()
        tool = db.DATA_DIR / "bin" / "tool.exe"
        dub = db.DATA_DIR / "dubs" / "t.de.mp4"
        for p in (tool, dub):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"x")
        m = db.create_meeting("Dub", "a.mp3", "")
        conn = db.get_connection()
        conn.execute("UPDATE meetings SET dubs_json = ? WHERE id = ?",
                     (json.dumps([{"lang": "de", "path": "dubs/t.de.mp4", "srt_path": "bin/tool.exe"}]), m["id"]))
        conn.commit()
        conn.close()
        with mock.patch.object(db.events, "publish"):
            self.assertTrue(db.delete_meeting_dub(m["id"], "de"))
        self.assertTrue(tool.exists())
        self.assertFalse(dub.exists())
        tool.unlink()


if __name__ == "__main__":
    unittest.main()
