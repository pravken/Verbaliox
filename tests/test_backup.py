import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path

from app import backup


class BackupTest(unittest.TestCase):
    def test_make_restore_apply(self):
        from app import secret_store
        from app.database import DB_PATH, _db_lock, create_meeting, get_meeting, init_db, list_meetings

        init_db()
        media = Path(tempfile.mkdtemp()) / "talk.m4a"
        media.write_bytes(b"sound")
        m = create_meeting("Встреча для копии", "talk.m4a", str(media))
        secret_store.set_secret("llm_key_openai", "sk-test")
        out = Path(tempfile.mkdtemp()) / "copy.zip"
        info = backup.make(out, with_media=True)
        self.assertGreaterEqual(info["media_files"], 1)
        with zipfile.ZipFile(out) as z:
            names = z.namelist()
            self.assertIn("meetings.db", names)
            db = Path(z.extract("meetings.db", tempfile.mkdtemp()))
        conn = sqlite3.connect(str(db))
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()
        self.assertNotIn("secrets", tables)  # API keys stay on this computer

        before = len(list_meetings())
        media.unlink()  # lost; the restore puts it back (it lived outside the app's folders: into the recordings folder)
        res = backup.restore(out)
        self.assertEqual(res["media_restored"], 1)
        self.assertFalse(media.exists())
        self.assertTrue(backup.PENDING.exists())

        create_meeting("Сделана после копии", "x.m4a", "/tmp/x.m4a")
        # What the next start does, before anything opens the database. Here the background threads of
        # the app started by earlier tests (call detection, retention, the search indexer...) still
        # read it; on Windows an open -wal cannot be deleted, so they wait on the database lock.
        with _db_lock:
            kept = backup.apply_pending()
        self.assertTrue(Path(kept).exists())
        self.assertFalse(backup.PENDING.exists())
        self.assertEqual(len(list_meetings()), before)
        self.assertEqual(get_meeting(m["id"])["title"], "Встреча для копии")
        self.assertEqual(secret_store.get_secret("llm_key_openai"), "sk-test")  # the keys of this computer stay
        moved = Path(get_meeting(m["id"])["media_path"])
        self.assertEqual(moved.parent.name, backup.RESTORED_FOLDER)
        self.assertEqual(moved.read_bytes(), b"sound")
        self.assertTrue(DB_PATH.exists())

    def test_caches_of_numbers_that_change_hands_are_dropped(self):
        from app.audio_utils import peaks_file
        from app.paths import THUMBS_DIR

        tmp = Path(tempfile.mkdtemp())

        def db(name, rows):
            p = tmp / name
            conn = sqlite3.connect(str(p))
            conn.execute("CREATE TABLE meetings (id INTEGER PRIMARY KEY, created_at TEXT, media_path TEXT)")
            conn.executemany("INSERT INTO meetings VALUES (?, ?, ?)", rows)
            conn.commit()
            conn.close()
            return p

        old = db("old.db", [(901, "2026-01-01", "a.m4a"), (902, "2026-02-01", "b.m4a"), (903, "2026-03-01", "c.m4a")])
        new = db("new.db", [(901, "2026-01-01", "a.m4a"), (902, "2026-01-15", "x.m4a")])
        THUMBS_DIR.mkdir(parents=True, exist_ok=True)
        files = {mid: (THUMBS_DIR / f"{mid}.jpg", peaks_file(mid)) for mid in (901, 902, 903)}
        for pair in files.values():
            for f in pair:
                f.write_text("[1]")
        try:
            backup._drop_stale_caches(old, new)
            self.assertTrue(all(f.exists() for f in files[901]))  # the same recording in both
            self.assertFalse(any(f.exists() for f in files[902]))  # another recording under this number
            self.assertFalse(any(f.exists() for f in files[903]))  # a number the next recording will get
        finally:
            for pair in files.values():
                for f in pair:
                    f.unlink(missing_ok=True)

    def test_only_the_newest_databases_put_aside_are_kept(self):
        from app.paths import DATA_DIR

        for p in DATA_DIR.glob("meetings.before-restore-*.db"):  # of other tests
            p.unlink()
        names = [f"meetings.before-restore-2026010{i}-120000.db" for i in range(1, 6)]
        for n in names:
            (DATA_DIR / n).write_bytes(b"x")
        try:
            backup._prune_before_restore()
            left = sorted(p.name for p in DATA_DIR.glob("meetings.before-restore-2026010*.db"))
            self.assertEqual(left, names[2:])
        finally:
            for n in names:
                (DATA_DIR / n).unlink(missing_ok=True)

    def test_restore_of_a_foreign_copy(self):
        """A copy someone sent: it may not write files where it likes nor change where data goes."""
        import json

        from app.database import create_meeting, get_all_settings, init_db, update_settings
        from app.paths import DATA_DIR

        init_db()
        update_settings({"ollama_url": "http://127.0.0.1:11434"})
        inside = DATA_DIR / "uploads" / "inside.m4a"
        m = create_meeting("Своя", "inside.m4a", str(inside))
        outside = Path(tempfile.mkdtemp()) / "Startup" / "evil.bat"
        stray = Path(tempfile.mkdtemp()) / "stray.m4a"
        out = Path(tempfile.mkdtemp()) / "copy.zip"
        backup.make(out)
        with zipfile.ZipFile(out) as z:
            db = Path(z.extract("meetings.db", tempfile.mkdtemp()))
        conn = sqlite3.connect(str(db))
        conn.execute("UPDATE settings SET value = 'http://attacker.example' WHERE key = 'ollama_url'")
        conn.execute("INSERT INTO meetings (title, filename, media_path, created_at) VALUES ('Чужая', 'evil.bat', ?, '2026-01-01')", (str(outside),))
        evil_id = conn.execute("SELECT max(id) FROM meetings").fetchone()[0]
        conn.commit()
        conn.close()
        bad = Path(tempfile.mkdtemp()) / "bad.zip"
        media = [{"id": m["id"], "path": str(inside), "name": f"media/{m['id']}_inside.m4a"},
                 {"id": evil_id, "path": str(outside), "name": f"media/{evil_id}_evil.bat"},
                 {"id": m["id"], "path": str(stray), "name": "media/stray.m4a"}]
        with zipfile.ZipFile(bad, "w") as z:
            z.writestr("manifest.json", json.dumps({"format": 1, "app": "Verbaliox", "media": media}))
            z.write(db, "meetings.db")
            for f in media:
                z.writestr(f["name"], b"x")
        res = backup.restore(bad)
        self.assertEqual(res["media_restored"], 1)  # only the file of its own recording, at its own place
        self.assertTrue(inside.exists())
        self.assertFalse(outside.exists())
        self.assertFalse(outside.parent.exists())
        self.assertFalse(stray.exists())
        conn = sqlite3.connect(str(backup.PENDING))
        url = conn.execute("SELECT value FROM settings WHERE key = 'ollama_url'").fetchone()[0]
        conn.close()
        self.assertEqual(url, get_all_settings()["ollama_url"])
        backup.PENDING.unlink()
        inside.unlink()

    def test_a_foreign_database_brings_data_only(self):
        """Its triggers, its queue of deletions and the paths in its recordings cannot reach this computer."""
        import json

        from app.database import create_meeting, get_all_settings, init_db, update_settings
        from app.paths import DATA_DIR

        init_db()
        update_settings({"ollama_url": "http://127.0.0.1:11434"})
        own = create_meeting("Своя", "own.m4a", str(DATA_DIR / "uploads" / "own.m4a"))
        victim = Path(tempfile.mkdtemp()) / "thesis.docx"
        victim.write_text("keep me")
        out = Path(tempfile.mkdtemp()) / "copy.zip"
        backup.make(out)
        with zipfile.ZipFile(out) as z:
            db = Path(z.extract("meetings.db", tempfile.mkdtemp()))
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TRIGGER evil AFTER UPDATE ON settings BEGIN "
                     "UPDATE settings SET value = 'http://attacker.example' WHERE key = 'ollama_url'; END")
        conn.execute("CREATE TRIGGER evil_insert AFTER INSERT ON settings BEGIN "
                     "UPDATE settings SET value = 'http://attacker.example' WHERE key = 'ollama_url'; END")
        conn.execute("CREATE VIEW peek AS SELECT * FROM settings")
        conn.execute("CREATE TABLE IF NOT EXISTS pending_deletes (path TEXT PRIMARY KEY, since TEXT NOT NULL)")
        conn.execute("INSERT INTO pending_deletes VALUES (?, '2026-01-01')", (str(victim),))
        tool = DATA_DIR / "bin" / "ffmpeg.exe"
        conn.execute("INSERT INTO meetings (title, filename, media_path, audio_path, exports_json, obsidian_path, "
                     "owns_media, dubs_json, created_at) VALUES ('Чужая', 'a.mp3', ?, ?, ?, ?, 1, ?, '2026-01-01')",
                     (str(tool), str(DATA_DIR / "meetings.db"), json.dumps([str(victim)]), str(victim),
                      json.dumps([{"lang": "en", "path": str(victim)}, {"lang": "de", "path": "dubs/1_de.wav"}])))
        evil_id = conn.execute("SELECT max(id) FROM meetings").fetchone()[0]
        conn.execute("UPDATE meetings SET owns_media = 1, media_path = ? WHERE id = ?", (str(victim.with_suffix(".mp4")), own["id"]))
        conn.commit()
        conn.close()
        bad = Path(tempfile.mkdtemp()) / "bad.zip"
        media = [{"id": evil_id, "path": str(tool), "name": f"media/{evil_id}_a.mp3"}]
        with zipfile.ZipFile(bad, "w") as z:
            z.writestr("manifest.json", json.dumps({"format": 1, "app": "Verbaliox", "media": media}))
            z.write(db, "meetings.db")
            z.writestr(media[0]["name"], b"MZ")
        backup.restore(bad)
        self.assertFalse(tool.exists())  # a media file of the copy never becomes a program
        conn = sqlite3.connect(str(backup.PENDING))
        try:
            self.assertEqual(conn.execute("SELECT count(*) FROM sqlite_master WHERE type IN ('trigger', 'view')").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT value FROM settings WHERE key = 'ollama_url'").fetchone()[0],
                             get_all_settings()["ollama_url"])
            self.assertEqual(conn.execute("SELECT count(*) FROM pending_deletes").fetchone()[0], 0)
            row = conn.execute("SELECT media_path, audio_path, exports_json, obsidian_path, dubs_json FROM meetings WHERE id = ?",
                               (evil_id,)).fetchone()
            self.assertEqual(Path(row[0]).parent.name, backup.RESTORED_FOLDER)  # the sound went to the recordings folder
            self.assertEqual(row[1:4], ("", "[]", ""))
            self.assertEqual([d["lang"] for d in json.loads(row[4])], ["de"])
            self.assertEqual(conn.execute("SELECT owns_media FROM meetings WHERE id = ?", (own["id"],)).fetchone()[0], 0)
        finally:
            conn.close()
        Path(row[0]).unlink(missing_ok=True)
        backup.PENDING.unlink()
        self.assertEqual(victim.read_text(), "keep me")

    def test_not_a_backup(self):
        bad = Path(tempfile.mkdtemp()) / "x.zip"
        with zipfile.ZipFile(bad, "w") as z:
            z.writestr("hello.txt", "hi")
        with self.assertRaises(ValueError):
            backup.restore(bad)


class DamagedRestoreTest(unittest.TestCase):
    def test_a_damaged_database_is_replaced_by_the_restore(self):
        """Found in the audit: a damaged database could not be checkpointed, and the restore failed at every start."""
        from unittest import mock

        d = Path(tempfile.mkdtemp())
        db, pending = d / "meetings.db", d / "meetings.restore.db"
        db.write_bytes(b"not a database" * 100)
        conn = sqlite3.connect(str(pending))
        conn.execute("CREATE TABLE meetings (id INTEGER PRIMARY KEY, title TEXT)")
        conn.execute("INSERT INTO meetings (title) VALUES ('Из копии')")
        conn.commit()
        conn.close()
        with mock.patch.object(backup, "DB_PATH", db), mock.patch.object(backup, "PENDING", pending), \
                mock.patch.object(backup, "DATA_DIR", d):
            kept = backup.apply_pending()
        self.assertTrue(Path(kept).is_file())
        self.assertEqual(Path(kept).read_bytes()[:14], b"not a database")  # the damaged one is kept aside
        conn = sqlite3.connect(str(db))
        self.assertEqual(conn.execute("SELECT title FROM meetings").fetchone()[0], "Из копии")
        conn.close()


if __name__ == "__main__":
    unittest.main()
