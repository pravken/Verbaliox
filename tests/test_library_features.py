import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import shutil
import sqlite3
import tempfile
import re
import unittest
from pathlib import Path
from unittest import mock

from app import database, sysinfo
from app.database import (
    create_folder,
    create_meeting,
    delete_folder,
    delete_meeting,
    get_meeting,
    init_db,
    list_folders,
    meeting_ids_in_folder,
    save_meeting_results,
    set_meeting_folder,
    system_folder_id,
    update_folder,
    update_meeting_progress,
    update_settings,
)

# The release CI runs the tests without the app's packages: what needs them is skipped there
try:
    from app import idle_unload, obsidian, pending_exports
    from app.ollama_client import clean_title, is_generic_title
except ImportError:  # httpx, python-docx … are not installed
    idle_unload = obsidian = pending_exports = None
needs_deps = unittest.skipIf(obsidian is None, "app dependencies not installed")

SEGMENTS = [
    {"id": 1, "start": 0.0, "end": 4.0, "speaker": "SPEAKER_00", "text": "Обсудим релиз на следующей неделе."},
    {"id": 2, "start": 65.0, "end": 70.0, "speaker": "SPEAKER_01", "text": "Тестирование до пятницы."},
]
SPEAKERS = {"SPEAKER_00": {"name": "Анна"}, "SPEAKER_01": {"name": "Борис"}}


def _done_meeting(title="Планёрка", **kw):
    m = create_meeting(title=title, filename="a.wav", media_path="a.wav", **kw)
    save_meeting_results(m["id"], segments=SEGMENTS, speakers=SPEAKERS, summaries={"tldr": "- Коротко"}, language="ru")
    update_meeting_progress(m["id"], status="completed", progress=100, duration=70.0)
    return get_meeting(m["id"])


class FolderTest(unittest.TestCase):
    def setUp(self):
        init_db()

    def test_system_folders_and_default_placement(self):
        keys = {f["system_key"] for f in list_folders() if f["system_key"]}
        self.assertEqual(keys, {"recordings", "imports", "dictations"})
        rec = create_meeting(title="r", filename="r.webm", media_path="r.webm", source="recording")
        imp = create_meeting(title="i", filename="i.mp4", media_path="i.mp4")
        self.assertEqual(rec["folder_id"], system_folder_id("recordings"))
        self.assertEqual(imp["folder_id"], system_folder_id("imports"))
        self.assertTrue(imp["is_video"])
        self.assertFalse(rec["is_video"])  # a recording made in the app is audio, even in .webm

    def test_nesting_moving_and_deleting(self):
        a = create_folder("A")
        b = create_folder("B", a["id"])
        c = create_folder("C", b["id"])
        with self.assertRaises(ValueError):
            update_folder(a["id"], parent_id=c["id"])  # into its own subfolder
        with self.assertRaises(ValueError):
            update_folder(system_folder_id("imports"), parent_id=a["id"])
        m = create_meeting(title="x", filename="x.wav", media_path="x.wav")
        set_meeting_folder(m["id"], c["id"])
        self.assertIn(m["id"], meeting_ids_in_folder(a["id"]))
        delete_folder(b["id"])  # C and its recordings move up into A
        folders = {f["id"]: f for f in list_folders()}
        self.assertNotIn(b["id"], folders)
        self.assertEqual(folders[c["id"]]["parent_id"], a["id"])
        with self.assertRaises(ValueError):
            delete_folder(system_folder_id("recordings"))

    def test_old_library_is_sorted_once(self):
        root = tests.temp_dir(self)
        try:
            conn = sqlite3.connect(root / "old.db")
            conn.execute("CREATE TABLE meetings (id INTEGER PRIMARY KEY, media_path TEXT, filename TEXT, created_at TEXT, "
                         "folder_id INTEGER, source TEXT, owns_media INTEGER, recorded_at TEXT)")
            conn.execute("CREATE TABLE folders (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, parent_id INTEGER, system_key TEXT, created_at TEXT)")
            up = database.UPLOADS_DIR
            rows = [
                (1, str(up / "1a2b3c4d_Созвон.m4a"), "1a2b3c4d_Созвон.m4a"),       # the app's own mix
                (2, str(up / "1a2b3c4d_Запись 10-15.webm"), "Запись 10-15.webm"),  # microphone recording
                (3, str(up / "1a2b3c4d_lecture.mp4"), "lecture.mp4"),              # imported copy
                (4, "D:\\Video\\talk.mkv", "talk.mkv"),                             # used in place
            ]
            for r in rows:
                conn.execute("INSERT INTO meetings (id, media_path, filename, created_at) VALUES (?, ?, ?, '2024-01-01 10:00:00')", r)
            cur = conn.cursor()
            database._ensure_system_folders(cur)
            database._sort_existing_meetings(cur)
            got = {r[0]: r[1:] for r in cur.execute("SELECT id, source, owns_media FROM meetings")}
            conn.close()
            self.assertEqual(got[1], ("recording", 1))
            self.assertEqual(got[2], ("recording", 1))
            self.assertEqual(got[3], ("import", 1))
            self.assertEqual(got[4], ("local", 0))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_delete_removes_own_recordings_only(self):
        outside = tests.temp_dir(self)
        try:
            own = outside / "rec.m4a"
            theirs = outside / "theirs.mp4"
            own.write_bytes(b"x")
            theirs.write_bytes(b"x")
            a = create_meeting(title="a", filename="rec.m4a", media_path=str(own), source="recording", owns_media=True)
            b = create_meeting(title="b", filename="theirs.mp4", media_path=str(theirs), source="local")
            delete_meeting(a["id"])
            delete_meeting(b["id"])
            self.assertFalse(own.exists())
            self.assertTrue(theirs.exists())  # a file added by its path is the user's
        finally:
            shutil.rmtree(outside, ignore_errors=True)


@needs_deps
class TitleTest(unittest.TestCase):
    def test_generic_titles(self):
        for title in ("Запись 14-05", "zoom_0", "VID_20240512_130245", "Recording (3)", "Голосовая заметка", "audio", "123"):
            self.assertTrue(is_generic_title(title), title)
        for title in ("Планёрка 12.05", "Интервью с Петровым", "Q3 roadmap"):
            self.assertFalse(is_generic_title(title), title)

    def test_clean_title(self):
        self.assertEqual(clean_title('Название: «Планирование релиза».\nВторое'), "Планирование релиза")


@needs_deps
class ObsidianTest(unittest.TestCase):
    def setUp(self):
        init_db()
        self.vault = tests.temp_dir(self)
        update_settings({"obsidian_vault": str(self.vault), "obsidian_subfolder": "Meetings/2024",
                         "obsidian_filename": "{date} {title}", "obsidian_generate": "false"})

    def tearDown(self):
        update_settings({"obsidian_vault": "", "obsidian_feature_folders": "true", "obsidian_filename": "{date} {title}", "date_folders": "off"})
        shutil.rmtree(self.vault, ignore_errors=True)

    def test_note_is_written_renamed_and_never_overwrites_others(self):
        m = _done_meeting(title="Релиз: план/итоги", recorded_at="2024-05-12 10:30:00")
        path = obsidian.export_meeting(m["id"])
        self.assertEqual(path, self.vault / "Meetings" / "2024" / "2024-05-12 Релиз план итоги.md")
        text = path.read_text(encoding="utf-8")
        self.assertIn("date: 2024-05-12", text)
        self.assertIn(f"verbaliox_id: {m['id']}", text)
        self.assertIn('  - "Анна"', text)
        self.assertIn("**Борис** `01:05` Тестирование до пятницы.", text)
        self.assertIn("## Резюме", text)

        database.update_meeting_fields(m["id"], title="Итоги релиза")
        new_path = obsidian.export_meeting(m["id"])
        self.assertFalse(path.exists())  # renamed, not copied
        self.assertTrue(new_path.name.endswith("Итоги релиза.md"))

        foreign = new_path.with_name("2024-05-12 Чужая заметка.md")
        foreign.write_text("моя заметка", encoding="utf-8")
        other = _done_meeting(title="Чужая заметка", recorded_at="2024-05-12 09:00:00")
        written = obsidian.export_meeting(other["id"])
        self.assertNotEqual(written, foreign)
        self.assertEqual(foreign.read_text(encoding="utf-8"), "моя заметка")

    def test_notes_follow_the_date_folders_and_come_back(self):
        """Asked by the user: «Папки по дате» turned on, the notes made before go into their date's folders;
        turned off, they come back and the date folders left empty go."""
        m = _done_meeting(title="Планёрка", recorded_at="2024-05-13 10:30:00")
        flat = obsidian.export_meeting(m["id"])
        base = self.vault / "Meetings" / "2024"
        self.assertEqual(flat.parent, base)
        update_settings({"date_folders": "year_month"})
        obsidian.relayout(wait=True)
        moved = base / "2024" / "2024-05" / flat.name
        self.assertTrue(moved.is_file())
        self.assertFalse(flat.exists())
        self.assertEqual(database.get_meeting(m["id"])["obsidian_path"], str(moved))
        self.assertEqual(obsidian.export_meeting(m["id"]), moved)  # a new note goes there too
        update_settings({"date_folders": "off"})
        obsidian.relayout(wait=True)
        self.assertTrue(flat.is_file())
        self.assertFalse((base / "2024" / "2024-05").exists())
        self.assertFalse(obsidian.relayout_status()["active"])

    def test_a_note_follows_its_recordings_feature_and_title(self):
        """Asked by the user: a feature given to a recording whose note was made before takes the note to the
        feature's folder by itself; a new title renames it; no feature any more, it comes back."""
        from app import features

        m = _done_meeting(title="Синк", recorded_at="2024-05-15 10:30:00")
        first = obsidian.export_meeting(m["id"])
        base = self.vault / "Meetings" / "2024"
        f = features.create_feature("Конвой", "#4C7FD9")
        features.set_meeting_features(m["id"], [f["id"]])
        moved = obsidian.follow_now(m["id"])
        self.assertEqual(moved, base / "Конвой" / first.name)
        self.assertFalse(first.exists())
        database.update_meeting_fields(m["id"], title="Синк по конвою")
        renamed = obsidian.follow_now(m["id"])
        self.assertEqual(renamed.name, "2024-05-15 Синк по конвою.md")
        self.assertEqual(database.get_meeting(m["id"])["obsidian_path"], str(renamed))
        features.set_meeting_features(m["id"], [])
        back = obsidian.follow_now(m["id"])
        self.assertEqual(back.parent, base)
        self.assertFalse((base / "Конвой").exists())  # the feature's folder left empty goes

    def test_user_notes_and_edits_survive_updates(self):
        m = _done_meeting(title="Планёрка", recorded_at="2024-05-13 10:30:00")
        path = obsidian.export_meeting(m["id"])
        text = path.read_text(encoding="utf-8")
        self.assertIn(obsidian.NOTES_MARKER, text)
        # The user writes in their section: kept by every update
        path.write_text(text + "- [x] позвонить Анне\n", encoding="utf-8")
        database.update_meeting_fields(m["id"], title="Планёрка команды")
        path = obsidian.export_meeting(m["id"], explicit=False)
        self.assertIn("- [x] позвонить Анне", path.read_text(encoding="utf-8"))
        # An edit above the section: an automatic update leaves the note alone
        edited = path.read_text(encoding="utf-8").replace("## Резюме", "## Резюме (моё)")
        path.write_text(edited, encoding="utf-8")
        obsidian.export_meeting(m["id"], explicit=False)
        self.assertEqual(path.read_text(encoding="utf-8"), edited)

    def test_a_note_edited_in_obsidian_keeps_its_link_when_moved(self):
        """Found in an audit: an automatic update after a rename moved the note edited in Obsidian, then left it
        (the edit is kept) before the recording learnt the new place: the next export wrote a second note."""
        m = _done_meeting(title="Планёрка", recorded_at="2024-05-13 10:30:00")
        path = obsidian.export_meeting(m["id"])
        edited = path.read_text(encoding="utf-8").replace("## Резюме", "## Резюме (моё)")
        path.write_text(edited, encoding="utf-8")
        database.update_meeting_fields(m["id"], title="Планёрка отдела")
        moved = obsidian.export_meeting(m["id"], explicit=False)
        self.assertFalse(path.exists())
        self.assertEqual(moved.read_text(encoding="utf-8"), edited)  # the edit is not undone
        self.assertEqual(database.get_meeting(m["id"])["obsidian_path"], str(moved))
        self.assertEqual(obsidian.export_meeting(m["id"]), moved)  # no second note
        self.assertEqual(sorted(p.name for p in moved.parent.glob("*.md")), [moved.name])

    def test_a_failed_write_keeps_the_note_and_the_users_section(self):
        m = _done_meeting(title="Планёрка", recorded_at="2024-05-13 10:30:00")
        path = obsidian.export_meeting(m["id"])
        mine = path.read_text(encoding="utf-8") + "- [x] позвонить Анне\n"
        path.write_text(mine, encoding="utf-8")
        with mock.patch("os.replace", side_effect=OSError("файл занят")):
            with self.assertRaises(OSError):
                obsidian.export_meeting(m["id"])
        self.assertEqual(path.read_text(encoding="utf-8"), mine)
        self.assertEqual([p.name for p in path.parent.iterdir()], [path.name])  # no temporary file left

    def test_a_move_onto_an_existing_note_carries_the_users_section(self):
        m = _done_meeting(title="Планёрка", recorded_at="2024-05-13 10:30:00")
        old = obsidian.export_meeting(m["id"])
        old.write_text(old.read_text(encoding="utf-8") + "- [x] позвонить Анне\n", encoding="utf-8")
        database.update_meeting_fields(m["id"], title="Планёрка команды")
        # a note of this recording is already at the new name (left by an earlier export)
        target = old.with_name("2024-05-13 Планёрка команды.md")
        shutil.copy(old, target)
        target.write_text(obsidian.split_user_notes(target.read_text(encoding="utf-8"))[0] + "\n" + obsidian.NOTES_MARKER
                          + "\n## Мои заметки\n\nсвоё в новой\n", encoding="utf-8")
        path = obsidian.export_meeting(m["id"])
        self.assertEqual(path, target)
        text = path.read_text(encoding="utf-8")
        self.assertIn("своё в новой", text)
        self.assertIn("- [x] позвонить Анне", text)
        self.assertFalse(old.exists())  # not left behind

    def test_notes_of_a_feature_go_into_its_folder_and_name(self):
        from app import features

        f = features.create_feature("Туманы на картах", "#FF9F0A")
        m = _done_meeting(title="Синк", recorded_at="2024-05-14 10:30:00")
        features.set_meeting_features(m["id"], [f["id"]])
        update_settings({"obsidian_filename": "{date} {feature} — {title}"})
        path = obsidian.export_meeting(m["id"])
        self.assertEqual(path, self.vault / "Meetings" / "2024" / "Туманы на картах" / "2024-05-14 Туманы на картах — Синк.md")
        text = path.read_text(encoding="utf-8")
        self.assertIn('features:\n  - "Туманы на картах"', text)
        self.assertIn('  - "Туманы-на-картах"', text)  # a tag cannot hold spaces
        # without a feature: the common folder, and no dash left at the start of the name
        other = _done_meeting(title="Планёрка", recorded_at="2024-05-14 11:00:00")
        self.assertEqual(obsidian.export_meeting(other["id"]), self.vault / "Meetings" / "2024" / "2024-05-14 Планёрка.md")
        # the folders switched off: the note moves back into the common folder
        update_settings({"obsidian_feature_folders": "false"})
        moved = obsidian.export_meeting(m["id"])
        self.assertEqual(moved.parent, self.vault / "Meetings" / "2024")
        self.assertFalse(path.exists())

    def test_the_note_has_everything_with_contents_links_and_marks(self):
        m = _done_meeting(title="Синк", recorded_at="2024-05-15 10:00:00")
        database.save_summary_templates([{"id": "risks", "name": "Риски", "prompt": "Какие риски?"}])
        database.merge_summaries(m["id"], {"chapters": "- [00:00] Начало\n- [01:05] Тесты", "decisions": "- Выпускать в пятницу",
                                           "tpl:risks": "- Срыв сроков", "notes": "- Конспект", "custom": "Ответ на вопрос", "error": "старая ошибка"})
        text = obsidian.export_meeting(m["id"]).read_text(encoding="utf-8")
        for heading in ("## Решения", "## Риски", "## Ответ на вопрос", "## Участники", "## Расшифровка"):
            self.assertIn(heading, text)
        self.assertNotIn("старая ошибка", text)
        self.assertIn("[[#Решения]]", text)  # the contents at the top
        self.assertRegex(text, r"\[\[#\^t(\d+)\|01:05\]\] Тесты")  # a chapter links to its line of the transcript
        anchor = re.search(r"\[\[#\^(t\d+)\|01:05\]\]", text).group(1)
        self.assertRegex(text, r"`01:05` Тестирование до пятницы\. \^" + anchor)
        self.assertIn("| Борис |", text)  # who spoke how long
        # the analysis and the transcript between their marks (each mark once), the transcript last of the two
        for mark in (obsidian.ANALYSIS_START, obsidian.ANALYSIS_END, obsidian.TRANSCRIPT_START, obsidian.TRANSCRIPT_END):
            self.assertEqual(text.count(mark), 1)
        a0, a1 = text.index(obsidian.ANALYSIS_START), text.index(obsidian.ANALYSIS_END)
        t0, t1 = text.index(obsidian.TRANSCRIPT_START), text.index(obsidian.TRANSCRIPT_END)
        self.assertTrue(a0 < text.index("## Решения") < a1 < t0 < text.index("## Расшифровка") < t1)
        # every section between its own marks, named in the properties («read only the tasks»)
        props = text.split("\n---\n", 1)[0]
        self.assertIn('section_mark: "each section is between the HTML comments verbaliox:<id>:start', props)
        for sid, title in (("decisions", "Решения"), ("template_risks", "Риски"), ("answer", "Ответ на вопрос"),
                           ("participants", "Участники"), ("synopsis", "Конспект"), ("chapters", "Главы"), ("transcript", "Расшифровка")):
            self.assertIn(f'  - "{sid}: {title}"', props)
            part = text.split(f"<!-- verbaliox:{sid}:start -->", 1)[1].split(f"<!-- verbaliox:{sid}:end -->", 1)[0]
            self.assertTrue(part.strip().startswith(f"## {title}"), sid)
        self.assertNotIn("<!--", props)
        database.save_summary_templates([])

    def test_reexport_completes_what_the_analysis_lacks(self):
        """Asked by the user: re-export with «complete»: a transcript without an overview goes to the queue."""
        with_all = _done_meeting(title="Полная", recorded_at="2024-05-17 10:00:00")
        database.merge_summaries(with_all["id"], {"protocol": "- Обзор", "tasks": "- Задача"})
        bare = _done_meeting(title="Без обзора", recorded_at="2024-05-17 11:00:00")
        self.assertEqual(obsidian.missing_parts(get_meeting(with_all["id"])), [])
        self.assertIn("protocol", obsidian.missing_parts(get_meeting(bare["id"])))
        import time

        with mock.patch("app.transcriber.enqueue_complete_job", return_value=True) as job:
            obsidian.export_all(missing_only=False, complete=True)
            for _ in range(50):
                if not obsidian.export_all_status()["active"]:
                    break
                time.sleep(0.05)
        queued = {c.args[0] for c in job.call_args_list}
        self.assertIn(bare["id"], queued)
        self.assertNotIn(with_all["id"], queued)  # complete already: written at once
        self.assertTrue(get_meeting(with_all["id"]).get("obsidian_path"))
        self.assertGreaterEqual(obsidian.export_all_status()["queued"], 1)

    def test_auto_export_writes_new_and_earlier_notes(self):
        m = _done_meeting(title="Ранняя", recorded_at="2024-05-16 10:00:00")
        update_settings({"obsidian_auto": "true"})
        try:
            obsidian.refresh_if_exported(m["id"])  # a section made for a recording without a note yet
            import time

            for _ in range(50):
                if (database.get_meeting(m["id"]) or {}).get("obsidian_path"):
                    break
                time.sleep(0.05)
            self.assertTrue(Path(database.get_meeting(m["id"])["obsidian_path"]).is_file())
            other = _done_meeting(title="Ещё одна", recorded_at="2024-05-16 11:00:00")
            st = obsidian.export_all(missing_only=True)
            for _ in range(100):
                if not obsidian.export_all_status()["active"]:
                    break
                time.sleep(0.05)
            self.assertGreaterEqual(st["total"], 1)
            self.assertTrue(Path(database.get_meeting(other["id"])["obsidian_path"]).is_file())
        finally:
            update_settings({"obsidian_auto": "false"})

    def test_tasks_become_checklist(self):
        self.assertEqual(obsidian._tasks_as_checklist("- сделать\n- [x] готово"), "- [ ] сделать\n- [x] готово")


@needs_deps
class FormerNameNoteTest(unittest.TestCase):
    """Notes written while the program was called VerbaScribe stay recognised as its own."""

    def test_old_id_and_notes_marker(self):
        from app import obsidian

        with tempfile.TemporaryDirectory() as tmp:
            note = Path(tmp) / "n.md"
            note.write_text("---\nverbascribe_id: 5\n---\n# T\n", encoding="utf-8")
            self.assertTrue(obsidian._is_ours(note, 5))
            self.assertFalse(obsidian._is_ours(note, 6))
        ours, user = obsidian.split_user_notes("# T\nbody\n<!-- verbascribe:notes -->\n## Мои заметки\n- [x] done\n")
        self.assertEqual(ours, "# T\nbody\n")
        self.assertTrue(user.startswith(obsidian.NOTES_MARKER + "\n## Мои заметки"))


class PendingExportTest(unittest.TestCase):
    def setUp(self):
        init_db()
        self.out = tests.temp_dir(self)
        update_settings({"export_dir": str(self.out)})

    def tearDown(self):
        update_settings({"export_dir": ""})
        shutil.rmtree(self.out, ignore_errors=True)

    def test_ready_queued_and_saved_after_the_job(self):
        m = _done_meeting()
        self.assertEqual(pending_exports.request(m["id"], {"kind": "doc", "fmt": "txt"})["status"], "ready")
        with mock.patch("app.transcriber.enqueue_translate_job", return_value=True) as enq:
            res = pending_exports.request(m["id"], {"kind": "doc", "fmt": "srt", "lang": "en"})
        self.assertEqual(res["status"], "queued")
        enq.assert_called_once()
        self.assertEqual(len(database.get_pending_exports(m["id"])), 1)
        # The translation job finished: the file is written into the export folder
        from app.translation import source_fingerprint

        database.save_meeting_translation(m["id"], "en", {"model": "test", "items": {
            "1": {"text": "Let us discuss the release.", "src": source_fingerprint(SEGMENTS[0]["text"]), "start": 0.0},
        }})
        pending_exports.process(m["id"])
        files = list(self.out.iterdir())
        self.assertEqual(len(files), 1)
        self.assertIn("Let us discuss the release.", files[0].read_text(encoding="utf-8"))
        self.assertEqual(database.get_pending_exports(m["id"]), [])

    def test_a_later_export_keeps_the_menu_options_and_the_date_folder(self):
        m = _done_meeting()
        update_settings({"date_folders": "day"})
        try:
            database.set_pending_exports(m["id"], [{"kind": "doc", "fmt": "txt", "opts": {"times": False, "names": False}}])
            pending_exports.process(m["id"])
        finally:
            update_settings({"date_folders": "off"})
        files = [f for f in self.out.rglob("*") if f.is_file()]
        self.assertEqual(len(files), 1)
        self.assertNotEqual(files[0].parent, self.out)  # in the recording's date folder
        self.assertNotIn("[00:00]", files[0].read_text(encoding="utf-8"))
        self.assertIn(str(files[0]), database.get_meeting(m["id"]).get("exports") or [])

    def test_failed_job_drops_the_export(self):
        m = _done_meeting()
        database.set_pending_exports(m["id"], [{"kind": "doc", "fmt": "txt", "lang": "de", "variant": "translated", "tries": 1}])
        pending_exports.process(m["id"])  # the translation was already tried once
        self.assertEqual(database.get_pending_exports(m["id"]), [])
        self.assertEqual(list(self.out.iterdir()), [])

    def test_an_export_asked_while_others_are_written_is_kept(self):
        """Found in an audit: process() wrote the list it read before writing the files back over one asked meanwhile."""
        m = _done_meeting()
        database.set_pending_exports(m["id"], [{"kind": "doc", "fmt": "txt"}])
        asked = {"kind": "doc", "fmt": "srt", "lang": "en", "variant": "translated", "opts": {}, "tries": 1}
        real = pending_exports.perform

        def slow_perform(meeting, item):
            database.set_pending_exports(m["id"], database.get_pending_exports(m["id"]) + [asked])  # the page asks now
            return real(meeting, item)

        with mock.patch.object(pending_exports, "perform", slow_perform):
            pending_exports.process(m["id"])
        self.assertEqual(len(list(self.out.iterdir())), 1)
        self.assertEqual(database.get_pending_exports(m["id"]), [asked])

    def test_a_bilingual_text_export_is_refused_before_the_translation(self):
        with self.assertRaises(ValueError):
            pending_exports.normalize({"kind": "doc", "fmt": "md", "lang": "en", "variant": "bilingual"})
        self.assertEqual(pending_exports.normalize({"kind": "doc", "fmt": "srt", "lang": "en", "variant": "bilingual"})["fmt"], "srt")

    def test_dub_needs_the_dub_window(self):
        m = _done_meeting()
        self.assertEqual(pending_exports.request(m["id"], {"kind": "dub_media", "lang": "en"})["status"], "needs_dub")


@needs_deps
class LibraryScopeTest(unittest.TestCase):
    def setUp(self):
        init_db()

    def test_scoped_question_reads_small_folders_in_full(self):
        from app import library_qa

        folder = create_folder("Scope")
        m = _done_meeting()
        set_meeting_folder(m["id"], folder["id"])
        with mock.patch("app.ollama_client.ensure_ollama_running"), \
                mock.patch("app.ollama_client.get_ollama_status", return_value={"running": True, "models": ["qwen2.5:7b"]}), \
                mock.patch("app.ollama_client._ollama_chat", return_value="О релизе [1].") as chat:
            res = library_qa.ask_library("о чём это?", meeting_ids=meeting_ids_in_folder(folder["id"]))
        self.assertEqual(res["mode"], "full")
        self.assertTrue(res["found"])
        self.assertIn("Тестирование до пятницы.", chat.call_args[0][3])
        with self.assertRaises(ValueError):
            library_qa.ask_library("вопрос", meeting_ids=[])

    def _ask(self, question, reply):
        from app import library_qa

        folder = create_folder("Scope")
        m = _done_meeting()
        set_meeting_folder(m["id"], folder["id"])
        with mock.patch("app.ollama_client.ensure_ollama_running"), \
                mock.patch("app.ollama_client.get_ollama_status", return_value={"running": True, "models": ["qwen2.5:7b"]}), \
                mock.patch("app.ollama_client._ollama_chat", return_value=reply) as chat:
            return library_qa.ask_library(question, meeting_ids=meeting_ids_in_folder(folder["id"])), chat

    def test_a_greeting_gets_a_reply_without_a_search(self):
        res, chat = self._ask("Привет!", "Здравствуйте! Задайте вопрос по записям.")
        self.assertEqual(res["mode"], "chat")
        self.assertTrue(res["found"])
        self.assertEqual(res["sources"], [])
        self.assertNotIn("Тестирование до пятницы.", chat.call_args[0][3])

    def test_only_cited_fragments_are_sources(self):
        res, _ = self._ask("о чём это?", "Во фрагментах нет ответа.")
        self.assertEqual(res["sources"], [])
        res, _ = self._ask("о чём это?", "О релизе [1].")
        self.assertEqual([s["n"] for s in res["sources"]], [1])

    def test_every_citation_form_counts(self):
        from app.library_qa import cited_numbers

        self.assertEqual(cited_numbers("А [1][3], Б [2, 4]; В [5; 6]"), {1, 2, 3, 4, 5, 6})
        self.assertEqual(cited_numbers("Решили [7-9] и [11–12], ещё [2, 4-5]"), {2, 4, 5, 7, 8, 9, 11, 12})
        self.assertEqual(cited_numbers("Нет ответа. Версия [v2], ссылка [x]"), set())

    def test_a_general_question_is_answered_with_reasoning_and_without_sources(self):
        from app import library_qa

        folder = create_folder("Scope")
        m = _done_meeting()
        set_meeting_folder(m["id"], folder["id"])
        with mock.patch("app.ollama_client.ensure_ollama_running"), \
                mock.patch("app.ollama_client.get_ollama_status", return_value={"running": True, "models": ["qwen2.5:7b"]}), \
                mock.patch("app.ollama_client._ollama_chat", side_effect=["нет", "Это метод оценки проектов."]) as chat:
            res = library_qa.ask_library("Объясни, что такое RICE", meeting_ids=meeting_ids_in_folder(folder["id"]))
        self.assertEqual(res["mode"], "general")
        self.assertEqual(res["sources"], [])
        self.assertTrue(chat.call_args.kwargs.get("think"))
        self.assertNotIn("Тестирование до пятницы.", chat.call_args[0][3])

    def test_a_question_about_meetings_skips_the_check(self):
        from app.library_qa import about_recordings

        llm = mock.Mock()
        self.assertTrue(about_recordings("что решили на встрече?", llm, False))
        llm.chat.assert_not_called()
        llm.chat.return_value = "Нет."
        self.assertFalse(about_recordings("сколько будет 2+2", llm, False))
        llm.chat.return_value = "**Нет**"
        self.assertFalse(about_recordings("сколько будет 2+2", llm, False))
        llm.chat.reset_mock()
        # a retelling of the chosen recordings is about them, whatever the model says
        for q in ("Перескажи кратко", "Сделай резюме", "Подведи итоги", "Give me a recap"):
            self.assertTrue(about_recordings(q, llm, True), q)
        llm.chat.assert_not_called()
        llm.chat.side_effect = RuntimeError("down")
        self.assertTrue(about_recordings("сколько будет 2+2", llm, False))

    def test_a_follow_up_searches_its_own_words_first(self):
        from app import library_qa

        long_q = ("Какие сроки релиза мобильного приложения назвали аналитики маркетинга разработчики "
                  "дизайнеры тестировщики менеджеры")
        history = [{"question": long_q, "answer": "Пятница."}]
        with mock.patch("app.ollama_client.ensure_ollama_running"), \
                mock.patch("app.ollama_client.get_ollama_status", return_value={"running": True, "models": ["qwen2.5:7b"]}), \
                mock.patch("app.ollama_client._ollama_chat", return_value="да"), \
                mock.patch.object(library_qa, "retrieve", return_value=[]) as found:
            library_qa.ask_library("а бюджет?", history=history)
        self.assertIn("бюдж", library_qa._terms(found.call_args[0][0]))

    def test_the_conversation_takes_its_room_from_the_fragments(self):
        from app import library_qa

        folder = create_folder("Scope")
        m = _done_meeting()
        set_meeting_folder(m["id"], folder["id"])
        many = [{"meeting_id": m["id"], "title": "Т", "date": "2026-01-01", "start": float(i), "speaker": "А",
                 "text": "x", "context": "слово " * 180} for i in range(40)]
        history = [{"question": "вопрос " * 150, "answer": "ответ " * 300}] * 3
        with mock.patch("app.ollama_client.ensure_ollama_running"), \
                mock.patch("app.ollama_client.get_ollama_status", return_value={"running": True, "models": ["qwen2.5:7b"]}), \
                mock.patch.object(library_qa, "full_fragments", return_value=many), \
                mock.patch("app.ollama_client._ollama_chat", side_effect=["да", "Ответ [1]."]) as chat:
            res = library_qa.ask_library("а подробнее?", meeting_ids=meeting_ids_in_folder(folder["id"]), history=history)
        self.assertEqual(res["mode"], "full")
        self.assertLessEqual(len(chat.call_args[0][3]), library_qa.FULL_MODE_MAX_CHARS + 4000 + 200)

    def test_a_follow_up_gets_the_conversation(self):
        from app import library_qa

        folder = create_folder("Scope")
        m = _done_meeting()
        set_meeting_folder(m["id"], folder["id"])
        history = [{"question": "Что решили по релизу?", "answer": "Тестирование до пятницы."}] * 5
        with mock.patch("app.ollama_client.ensure_ollama_running"), \
                mock.patch("app.ollama_client.get_ollama_status", return_value={"running": True, "models": ["qwen2.5:7b"]}), \
                mock.patch("app.ollama_client._ollama_chat", side_effect=["да", "Подробности в обсуждении [1]."]) as chat:
            res = library_qa.ask_library("а подробнее?", meeting_ids=meeting_ids_in_folder(folder["id"]), history=history)
        self.assertEqual(res["mode"], "full")
        self.assertIn("Предыдущий разговор", chat.call_args_list[0][0][3])  # the check sees the conversation
        user = chat.call_args[0][3]
        self.assertIn("Что решили по релизу?", user)
        self.assertEqual(user.count("Что решили по релизу?"), library_qa.HISTORY_TURNS)
        self.assertTrue(user.rstrip().endswith("Вопрос: а подробнее?"))

    def test_overviews_are_whole_recordings_and_their_export_names_no_moment(self):
        """Reported by the user: a brief's marks all read «▶ 00:00»: a whole recording is cited, not a moment."""
        from app import library_qa
        from app.assistant_chats import answer_text

        frags = library_qa.summary_fragments([{"id": 1, "title": "Т", "summaries": {"tldr": "Обзор."}, "created_at": "2026-11-12"}])
        self.assertTrue(frags[0]["whole"])
        text = answer_text("q", "a [1]", [{"n": 1, "title": "Т", "date": "2026-11-12", "start": 0.0, "whole": True},
                                         {"n": 2, "title": "Т", "date": "2026-11-12", "start": 75.0, "text": "фраза"}], "Источники")
        self.assertIn("[1] Т · 2026-11-12\n", text + "\n")
        self.assertIn("00:01:15", text)
        self.assertNotIn("00:00:00", text)

    def test_small_talk_is_told_from_questions(self):
        from app.library_qa import is_small_talk

        for q in ("привет", "Спасибо большое!", "кто ты?", "hello", "thanks"):
            self.assertTrue(is_small_talk(q), q)
        for q in ("о чём была встреча?", "привет, что решили по релизу?", "задачи на неделю"):
            self.assertFalse(is_small_talk(q), q)


class SystemTest(unittest.TestCase):
    def test_memory_and_cpu(self):
        mem = sysinfo.memory()
        if mem is not None:
            self.assertGreater(mem["total_gb"], 0)
        sysinfo.cpu_percent()
        cpu = sysinfo.cpu_percent()
        self.assertTrue(cpu is None or 0 <= cpu <= 100)

    @needs_deps
    def test_idle_keep_alive_follows_the_setting(self):
        init_db()
        update_settings({"idle_unload_minutes": "15"})
        self.assertEqual(idle_unload.ollama_keep_alive(), "15m")
        update_settings({"idle_unload_minutes": "0"})
        self.assertIsNone(idle_unload.ollama_keep_alive())
        update_settings({"idle_unload_minutes": "10"})


if __name__ == "__main__":
    unittest.main()
