"""The sound a backup's restore puts back (found in an audit): the retention setting does not delete it at the
next start; a copy made before owns_media existed restores; a second restore of the same copy points the
recording to the file the first one put into the recordings folder."""

import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import sqlite3
import unittest
import zipfile
from pathlib import Path

from app import backup


def _pending_row(mid):
    conn = sqlite3.connect(str(backup.PENDING))
    conn.row_factory = sqlite3.Row
    try:
        return dict(conn.execute("SELECT * FROM meetings WHERE id = ?", (mid,)).fetchone())
    finally:
        conn.close()


class RestoredMediaTest(unittest.TestCase):
    def setUp(self):
        from app.database import init_db

        init_db()
        backup.PENDING.unlink(missing_ok=True)
        self.addCleanup(backup.PENDING.unlink, missing_ok=True)

    def _copy_of_an_old_recording(self, name):
        from app.database import _db_lock, create_meeting, get_connection

        media = tests.temp_dir(self) / name
        media.write_bytes(b"sound" * 100)
        m = create_meeting("Встреча двухлетней давности", name, str(media))
        with _db_lock:
            conn = get_connection()
            conn.execute("UPDATE meetings SET status = 'completed', owns_media = 1, recorded_at = '2024-01-10 10:00:00', "
                         "created_at = '2024-01-10 10:00:00' WHERE id = ?", (m["id"],))
            conn.commit()
            conn.close()
        out = tests.temp_dir(self) / "copy.zip"
        backup.make(out, with_media=True)
        media.unlink()  # lost; the restore puts it into the recordings folder
        return m["id"], out

    def test_the_retention_counts_from_the_restore(self):
        from app.database import _db_lock, expired_media_ids, get_connection

        mid, out = self._copy_of_an_old_recording("old-talk.m4a")
        backup.restore(out)
        row = _pending_row(mid)
        self.assertTrue(row["media_restored_at"])
        self.assertTrue(Path(row["media_path"]).is_file())
        # the restored database in use (as after the restart): its old recording keeps its sound for N days
        with _db_lock:
            conn = get_connection()
            conn.execute("UPDATE meetings SET media_path = ?, media_restored_at = ? WHERE id = ?",
                         (row["media_path"], row["media_restored_at"], mid))
            conn.commit()
            conn.close()
        self.assertNotIn(mid, expired_media_ids(30))
        with _db_lock:
            conn = get_connection()
            conn.execute("UPDATE meetings SET media_restored_at = '' WHERE id = ?", (mid,))
            conn.commit()
            conn.close()
        self.assertIn(mid, expired_media_ids(30))  # the setting itself still works
        Path(row["media_path"]).unlink(missing_ok=True)

    def test_a_copy_without_owns_media_restores(self):
        mid, out = self._copy_of_an_old_recording("older-version.m4a")
        work = tests.temp_dir(self)
        with zipfile.ZipFile(out) as z:
            db = Path(z.extract("meetings.db", str(work)))
            manifest = z.read("manifest.json")
            media = [(n, z.read(n)) for n in z.namelist() if n.startswith("media/")]
        conn = sqlite3.connect(str(db))
        cols = {r[1] for r in conn.execute("PRAGMA table_info(meetings)")}
        for col in {"owns_media", "media_restored_at"} & cols:
            conn.execute(f"ALTER TABLE meetings DROP COLUMN {col}")
        conn.commit()
        conn.close()
        old = work / "old.zip"
        with zipfile.ZipFile(old, "w") as z:
            z.writestr("manifest.json", manifest)
            z.write(db, "meetings.db")
            for n, data in media:
                z.writestr(n, data)
        res = backup.restore(old)
        self.assertGreaterEqual(res["media_restored"], 1)
        row = _pending_row(mid)
        self.assertTrue(Path(row["media_path"]).is_file())
        self.assertTrue(row.get("media_restored_at"))
        Path(row["media_path"]).unlink(missing_ok=True)

    def test_a_second_restore_of_the_same_copy(self):
        mid, out = self._copy_of_an_old_recording("twice.m4a")
        backup.restore(out)
        first = Path(_pending_row(mid)["media_path"])
        self.assertTrue(first.is_file())
        res = backup.restore(out)
        self.assertGreaterEqual(res["media_kept"], 1)  # (the library of the other tests may hold more)
        self.assertEqual(Path(_pending_row(mid)["media_path"]), first)  # not the place on the other computer
        first.unlink()


if __name__ == "__main__":
    unittest.main()
