"""The speakers named in the analysis kept as references (app/speaker_refs.py): a rename reaches every
reading of the analysis, also after the speakers were merged or split anew; an older analysis without
references keeps working by its text."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from fastapi.testclient import TestClient

    from app import commitments, database, main, speaker_refs, transcriber
except ImportError:  # app dependencies are not installed (e.g. in the release CI job)
    speaker_refs = None

PROTOCOL = ("## Решения\n- Анна Котова предложила перенести релиз\n\n## Следующие шаги\n"
            "- **Участник 2**: подготовить смету\n- Анна Котова: созвониться с подрядчиком")


def _spk(names):
    return {f"SPEAKER_0{i}": {"id": f"SPEAKER_0{i}", "name": n, "color": "#0A84FF"} for i, n in enumerate(names)}


@unittest.skipIf(speaker_refs is None, "app dependencies not installed")
class MarkTextTest(unittest.TestCase):
    def test_names_written_in_full_become_references_and_read_back(self):
        spk = _spk(["Анна Котова", "Участник 2"])
        marked = speaker_refs.mark_text(PROTOCOL, spk)
        self.assertNotIn("Анна Котова", speaker_refs.MARK_RE.sub("", marked))
        self.assertIn("⟦spk:SPEAKER_01|Участник 2⟧", marked)
        self.assertEqual(speaker_refs.resolve_text(marked, spk), PROTOCOL)  # nothing else changes
        spk["SPEAKER_00"]["name"] = "Анна Котова-Белова"
        self.assertIn("- Анна Котова-Белова: созвониться", speaker_refs.resolve_text(marked, spk))

    def test_what_is_not_the_speakers_name_stays_text(self):
        spk = _spk(["Анна", "Я", "Олег", "Олег"])
        text = "Анна Петрова и Анна обсудили; Я ушёл; Олег остался; Аннам и Анне"
        marked = speaker_refs.mark_text(text, spk)
        self.assertIn("Анна Петрова", marked)  # another person's full name
        self.assertIn("и ⟦spk:SPEAKER_00|Анна⟧ обсудили", marked)
        self.assertIn("Я ушёл", marked)  # too short to be told from a word
        self.assertIn("Олег остался", marked)  # two speakers have the name: whose is it
        self.assertIn("Аннам и Анне", marked)  # other words, declined forms

    def test_references_there_stay_and_a_gone_speaker_shows_its_name(self):
        marked = speaker_refs.mark_text("⟦spk:SPEAKER_07|Борис⟧ и Анна", _spk(["Анна"]))
        self.assertEqual(marked, "⟦spk:SPEAKER_07|Борис⟧ и ⟦spk:SPEAKER_00|Анна⟧")
        self.assertEqual(speaker_refs.resolve_text(marked, _spk(["Мария"])), "Борис и Мария")

    def test_ids_carried_by_name_then_by_time(self):
        old_segs = [{"start": 0, "end": 10, "speaker": "SPEAKER_00"}, {"start": 10, "end": 20, "speaker": "SPEAKER_01"},
                    {"start": 20, "end": 30, "speaker": "SPEAKER_02"}]
        old_spk = _spk(["Мария", "Участник 2", "Борис"])
        new_segs = [{"start": 0, "end": 10, "speaker": "SPEAKER_01"}, {"start": 10, "end": 20, "speaker": "SPEAKER_00"},
                    {"start": 20, "end": 25, "speaker": "SPEAKER_00"}, {"start": 25, "end": 30, "speaker": "SPEAKER_02"}]
        new_spk = _spk(["Участник 1", "Мария", "Участник 3"])
        got = speaker_refs.carry_ids(old_segs, old_spk, new_segs, new_spk, named_by_time=False)
        # Мария by her name; «Участник 2» by the time it shares; Борис's name went to no voice: it stays text
        self.assertEqual(got, {"SPEAKER_00": "SPEAKER_01", "SPEAKER_01": "SPEAKER_00", "SPEAKER_02": None})
        self.assertEqual(speaker_refs.carry_ids(old_segs, old_spk, new_segs, new_spk)["SPEAKER_02"], None)  # half only


@unittest.skipIf(speaker_refs is None, "app dependencies not installed")
class StoredAnalysisTest(unittest.TestCase):
    def setUp(self):
        database.init_db()
        self.tmp = tempfile.TemporaryDirectory()
        wav = Path(self.tmp.name) / "a.wav"
        wav.write_bytes(b"RIFF")
        self.wav = wav
        self.mid = database.create_meeting("Планёрка", str(wav), str(wav))["id"]
        segs = [{"id": i, "start": i * 10.0, "end": i * 10.0 + 9, "speaker": f"SPEAKER_0{i % 3}", "text": f"реплика {i}"}
                for i in range(6)]
        database.save_meeting_results(self.mid, segments=segs, speakers=_spk(["Анна Котова", "Участник 2", "Борис Лапин"]),
                                      transcript_model="large-v3")
        database.update_meeting_fields(self.mid, audio_path=str(wav))
        database.update_meeting_progress(self.mid, status="completed", progress=100)
        self.c = TestClient(main.app, base_url="http://127.0.0.1:8790")
        self.c.cookies.set("vs_session_8790", main.SESSION_TOKEN)

    def tearDown(self):
        self.tmp.cleanup()

    def _raw(self):
        with database._db_lock:
            conn = database.get_connection()
            raw = conn.execute("SELECT summaries_json FROM meetings WHERE id = ?", (self.mid,)).fetchone()[0]
            conn.close()
        return json.loads(raw)

    def _put_raw(self, sums):
        with database._db_lock:
            conn = database.get_connection()
            conn.execute("UPDATE meetings SET summaries_json = ? WHERE id = ?", (json.dumps(sums, ensure_ascii=False), self.mid))
            conn.commit()
            conn.close()

    def _rename(self, sid, name):
        r = self.c.patch(f"/api/meetings/{self.mid}/speakers", json={"speaker_id": sid, "name": name})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_the_analysis_is_stored_with_references_and_read_with_names(self):
        sums = database.merge_summaries(self.mid, {"protocol": PROTOCOL, "error": "Анна Котова"})
        self.assertEqual(sums["protocol"], PROTOCOL)
        raw = self._raw()
        self.assertIn("⟦spk:SPEAKER_00|Анна Котова⟧ предложила", raw["protocol"])
        self.assertIn("**⟦spk:SPEAKER_01|Участник 2⟧**", raw["protocol"])
        self.assertEqual(raw["error"], "Анна Котова")  # a failure is not an analysis text
        self.assertEqual(database.get_meeting(self.mid)["summaries"]["protocol"], PROTOCOL)

    def test_a_rename_shows_in_the_page_the_exports_and_for_an_agent(self):
        database.merge_summaries(self.mid, {"protocol": PROTOCOL, "chapters": "00:00 Смета (Участник 2)"})
        m = self._rename("SPEAKER_01", "Ирина Белова")
        self.assertIn("**Ирина Белова**: подготовить смету", m["summaries"]["protocol"])  # the answer of the rename
        self.assertEqual(m["summaries"]["chapters"], "00:00 Смета (Ирина Белова)")
        m = database.get_meeting(self.mid)
        self.assertNotIn("Участник 2", json.dumps(m["summaries"], ensure_ascii=False))
        from app.export_build import build_export_bytes

        for fmt in ("md", "txt", "docx"):
            content, _t, _n = build_export_bytes(m, fmt)
            if fmt == "docx":
                import io
                import zipfile

                content = zipfile.ZipFile(io.BytesIO(content)).read("word/document.xml")
            text = content.decode("utf-8")
            self.assertIn("Ирина Белова", text, fmt)
            self.assertNotIn("⟦", text, fmt)
            self.assertNotIn("Участник 2", text, fmt)
        from app import mcp_server, obsidian

        with mock.patch.object(mcp_server, "_hidden", return_value=set()):
            agent = mcp_server.get_meeting(self.mid, ["overview", "decisions"])["text"]
        self.assertIn("Ирина Белова", agent)
        self.assertNotIn("⟦", agent)
        self.assertNotIn("⟦", obsidian.build_note(m, {"obsidian_summary": "true"}))
        r = self.c.get("/api/home/recent")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertFalse(any("⟦" in (x.get("summary") or "") for x in r.json()))

    def test_a_hand_edit_keeps_the_references(self):
        database.merge_summaries(self.mid, {"protocol": PROTOCOL})
        text = PROTOCOL.replace("перенести релиз", "перенести релиз на май")
        r = self.c.put(f"/api/meetings/{self.mid}/summaries/protocol", json={"text": text, "base": PROTOCOL})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["summaries"]["protocol"], text)
        self._rename("SPEAKER_00", "Анна Белова")
        self.assertIn("Анна Белова предложила перенести релиз на май", database.get_meeting(self.mid)["summaries"]["protocol"])

    def test_merged_speaker_references_go_to_the_one_kept(self):
        database.merge_summaries(self.mid, {"protocol": "Участник 2 и Борис Лапин договорились"})
        r = self.c.post(f"/api/meetings/{self.mid}/speakers/merge", json={"source": "SPEAKER_01", "target": "SPEAKER_02"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["summaries"]["protocol"], "Борис Лапин и Борис Лапин договорились")
        self.assertNotIn("SPEAKER_01", json.dumps(self._raw(), ensure_ascii=False))
        self._rename("SPEAKER_02", "Борис Лапиньш")
        self.assertEqual(database.get_meeting(self.mid)["summaries"]["protocol"],
                         "Борис Лапиньш и Борис Лапиньш договорились")

    def test_a_new_split_finds_the_speakers_again(self):
        database.merge_summaries(self.mid, {"protocol": "Анна Котова, Участник 2 и Борис Лапин"})
        commitments.create("Подготовить смету", "Участник 2", meeting_id=self.mid)

        def fake(wav_path, raw_segments, device, num_speakers_hint, diarization_enabled, progress_callback):
            # the voices numbered otherwise: «Участник 2» of before is SPEAKER_00 now; Борис is split in halves
            who = {0: "SPEAKER_01", 1: "SPEAKER_00", 2: "SPEAKER_02", 3: "SPEAKER_01", 4: "SPEAKER_00", 5: "SPEAKER_03"}
            segs = [{**s, "id": i, "speaker": who[i]} for i, s in enumerate(raw_segments)]
            return ({sid: {"id": sid, "name": f"Участник {int(sid[-1]) + 1}"} for sid in
                     ("SPEAKER_00", "SPEAKER_01", "SPEAKER_02", "SPEAKER_03")}, segs)

        with mock.patch("app.diarizer.diarize_and_merge_segments", fake), \
                mock.patch("app.diarizer.unload_diarizer"), \
                mock.patch.object(transcriber, "release_whisper_model"), \
                mock.patch.object(transcriber, "_release_onnx"), \
                mock.patch("app.voice_profiles.apply_to_speakers", return_value=0):
            transcriber._resplit_runner(self.mid, 0)
        m = database.get_meeting(self.mid)
        self.assertEqual(m["speakers"]["SPEAKER_01"]["name"], "Анна Котова")  # carried by the new split
        self.assertEqual(m["summaries"]["protocol"], "Анна Котова, Участник 1 и Борис Лапин")
        self.assertEqual([t["who"] for t in commitments.for_meetings([self.mid])], ["Участник 1"])
        self._rename("SPEAKER_00", "Ирина Белова")
        self._rename("SPEAKER_01", "Анна Белова")
        self.assertEqual(database.get_meeting(self.mid)["summaries"]["protocol"], "Анна Белова, Ирина Белова и Борис Лапин")

    def test_another_transcript_shown_takes_its_speakers(self):
        database.merge_summaries(self.mid, {"protocol": "Решение Бориса: Борис Лапин"})
        segs = [{"id": i, "start": i * 10.0, "end": i * 10.0 + 9, "speaker": "SPEAKER_00" if i % 3 == 2 else "SPEAKER_01",
                 "text": f"фраза {i}"} for i in range(6)]
        database.stash_transcript_for(self.mid, "small")
        database.save_meeting_results(self.mid, segments=segs, speakers=_spk(["Участник 1", "Участник 2"]),
                                      transcript_model="small")
        m = database.get_meeting(self.mid)
        self.assertEqual(m["summaries"]["protocol"], "Решение Бориса: Борис Лапин")  # its name went to no voice
        self.assertNotIn("⟦", json.dumps(self._raw(), ensure_ascii=False))

    def test_the_names_stay_the_renamed_ones_when_the_transcript_is_deleted(self):
        database.merge_summaries(self.mid, {"protocol": "Смету готовит Участник 2"})
        self._rename("SPEAKER_01", "Ирина Белова")
        self.assertTrue(database.delete_transcript_version(self.mid, "large-v3"))  # the only one: no speakers left
        self.assertEqual(database.get_meeting(self.mid)["speakers"], {})
        self.assertEqual(database.get_meeting(self.mid)["summaries"]["protocol"], "Смету готовит Ирина Белова")

    def test_an_older_analysis_keeps_working_by_its_text(self):
        old = {"protocol": "Участник 2 предложил; Анна Котова согласилась"}
        self._put_raw(old)
        self.assertEqual(database.get_meeting(self.mid)["summaries"], old)
        r = self.c.post(f"/api/meetings/{self.mid}/speakers/merge", json={"source": "SPEAKER_02", "target": "SPEAKER_00"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self._raw(), old)  # a merge does not touch it
        self._rename("SPEAKER_01", "Ирина Белова")  # the rename by text, as before; the name is a reference now
        self.assertEqual(database.get_meeting(self.mid)["summaries"]["protocol"],
                         "Ирина Белова предложил; Анна Котова согласилась")
        self.assertIn("⟦spk:SPEAKER_01|Ирина Белова⟧", self._raw()["protocol"])

    def test_a_contact_renamed_reaches_a_reference_to_its_speaker(self):
        from app import people

        people.init_table()
        self._rename("SPEAKER_02", "Олег Петрв")
        database.merge_summaries(self.mid, {"protocol": "Задача: Олег Петрв"})
        self.assertNotIn("Петрв", self._raw()["protocol"].split("|")[0])  # a reference, its name inside only
        people.add("Олег Петрв", "person")
        people.update("Олег Петрв", new_name="Олег Петров")
        people.rename_everywhere("Олег Петрв", "Олег Петров")  # as the page's rename of a contact does
        self.assertEqual(database.get_meeting(self.mid)["summaries"]["protocol"], "Задача: Олег Петров")

    def test_a_mention_put_under_someone_else_leaves_the_speaker(self):
        database.merge_summaries(self.mid, {"protocol": "Вклад: Анна Котова"})
        r = self.c.post(f"/api/meetings/{self.mid}/analysis/rename-person", json={"old": "Анна Котова", "new": "Вера Орлова"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["summaries"]["protocol"], "Вклад: Вера Орлова")
        self._rename("SPEAKER_00", "Анна Белова")
        self.assertEqual(database.get_meeting(self.mid)["summaries"]["protocol"], "Вклад: Вера Орлова")


if __name__ == "__main__":
    unittest.main()
