"""«Разделить заново»: the participants split by voices again on the text there is (app/transcriber.py)."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from app import database, transcriber
    from app.diarizer import _split_segments_by_word_pauses
except ImportError:  # app dependencies are not installed (e.g. in the release CI job)
    transcriber = None


def _words(text, start, step=0.4, gap_after=None):
    out, t = [], start
    for i, w in enumerate(text.split()):
        out.append({"start": round(t, 2), "end": round(t + step - 0.05, 2), "word": " " + w})
        t += step + (1.0 if gap_after is not None and i == gap_after else 0.0)
    return out


@unittest.skipIf(transcriber is None, "app dependencies not installed")
class ResplitInputTest(unittest.TestCase):
    def test_a_line_typed_over_stays_whole_and_keeps_its_text(self):
        said = {"start": 0.0, "end": 5.0, "text": "раз два три четыре пять шесть", "words": _words("раз два три четыре пять шесть", 0, gap_after=2)}
        typed = {**said, "text": "Раз, два, три — исправлено"}
        out = transcriber.resplit_input([said, typed])
        self.assertNotIn("keep_whole", out[0])
        self.assertTrue(out[1]["keep_whole"])
        pieces = _split_segments_by_word_pauses(out)
        self.assertGreater(len([p for p in pieces if not p.get("keep_whole")]), 1)  # the line said: cut at its pause
        self.assertEqual([p["text"] for p in pieces if p.get("keep_whole")], ["Раз, два, три — исправлено"])

    def test_pieces_keep_the_language_of_their_line(self):
        seg = {"start": 0.0, "end": 5.0, "text": "one two three four five six", "lang": "en",
               "words": _words("one two three four five six", 0, gap_after=2)}
        pieces = _split_segments_by_word_pauses([seg])
        self.assertGreater(len(pieces), 1)
        self.assertTrue(all(p.get("lang") == "en" for p in pieces))


@unittest.skipIf(transcriber is None, "app dependencies not installed")
class CarryNamesTest(unittest.TestCase):
    def test_names_given_go_to_the_voice_sharing_their_time(self):
        old_segs = [{"start": 0, "end": 10, "speaker": "SPEAKER_00"}, {"start": 10, "end": 20, "speaker": "SPEAKER_01"}]
        old_spk = {"SPEAKER_00": {"name": "Мария", "color": "#FF0000", "is_me": True}, "SPEAKER_01": {"name": "Участник 2"}}
        new_segs = [{"start": 0, "end": 9, "speaker": "SPEAKER_00"}, {"start": 9, "end": 15, "speaker": "SPEAKER_01"},
                    {"start": 15, "end": 20, "speaker": "SPEAKER_02"}]
        new_spk = {f"SPEAKER_0{i}": {"name": f"Участник {i + 1}"} for i in range(3)}
        self.assertEqual(transcriber.carry_names(old_segs, old_spk, new_segs, new_spk), 1)
        self.assertEqual(new_spk["SPEAKER_00"]["name"], "Мария")
        self.assertEqual(new_spk["SPEAKER_00"]["color"], "#FF0000")
        self.assertTrue(new_spk["SPEAKER_00"]["is_me"])
        self.assertEqual(new_spk["SPEAKER_01"]["name"], "Участник 2")  # a default name is not carried

    def test_a_name_already_found_by_voice_is_not_given_twice(self):
        old_segs = [{"start": 0, "end": 10, "speaker": "SPEAKER_00"}]
        old_spk = {"SPEAKER_00": {"name": "Мария"}}
        new_segs = [{"start": 0, "end": 5, "speaker": "SPEAKER_00"}, {"start": 5, "end": 10, "speaker": "SPEAKER_01"}]
        new_spk = {"SPEAKER_00": {"name": "Участник 1"}, "SPEAKER_01": {"name": "Мария"}}  # a voice profile named it
        transcriber.carry_names(old_segs, old_spk, new_segs, new_spk)
        self.assertEqual(new_spk["SPEAKER_00"]["name"], "Участник 1")


@unittest.skipIf(transcriber is None, "app dependencies not installed")
class ResplitJobTest(unittest.TestCase):
    def setUp(self):
        database.init_db()
        self.tmp = tempfile.TemporaryDirectory()
        wav = Path(self.tmp.name) / "a.wav"
        wav.write_bytes(b"RIFF")
        m = database.create_meeting("Встреча", str(wav), str(wav))
        self.mid = m["id"]
        segs = [{"id": 1, "start": 0.0, "end": 6.0, "speaker": "SPEAKER_00", "text": "Это я правил руками",
                 "words": _words("раз два три", 0)},
                {"id": 2, "start": 6.0, "end": 12.0, "speaker": "SPEAKER_01", "text": "четыре пять шесть",
                 "words": _words("четыре пять шесть", 6)}]
        database.save_meeting_results(self.mid, segments=segs,
                                      speakers={"SPEAKER_00": {"id": "SPEAKER_00", "name": "Мария", "color": "#0A84FF"},
                                                "SPEAKER_01": {"id": "SPEAKER_01", "name": "Участник 2"}},
                                      transcript_model="large-v3")
        database.update_meeting_fields(self.mid, audio_path=str(wav))
        database.update_meeting_progress(self.mid, status="completed", progress=100)

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_new_split_is_saved_with_the_text_and_names_kept(self):
        seen = {}

        def fake(wav_path, raw_segments, device, num_speakers_hint, diarization_enabled, progress_callback):
            seen.update(raw=raw_segments, hint=num_speakers_hint)
            segs = [{**raw_segments[0], "speaker": "SPEAKER_00", "id": 1}, {**raw_segments[1], "speaker": "SPEAKER_01", "id": 2}]
            return ({"SPEAKER_00": {"id": "SPEAKER_00", "name": "Участник 1"},
                     "SPEAKER_01": {"id": "SPEAKER_01", "name": "Участник 2"}}, segs)

        with mock.patch("app.diarizer.diarize_and_merge_segments", fake), \
                mock.patch("app.diarizer.unload_diarizer"), \
                mock.patch.object(transcriber, "release_whisper_model"), \
                mock.patch.object(transcriber, "_release_onnx"), \
                mock.patch("app.voice_profiles.apply_to_speakers", return_value=0):
            text = transcriber._resplit_runner(self.mid, 3)
        self.assertIn("2", text)
        self.assertEqual(seen["hint"], 3)
        self.assertTrue(seen["raw"][0]["keep_whole"])  # typed over: not cut
        m = database.get_meeting(self.mid)
        self.assertEqual([s["speaker"] for s in m["segments"]], ["SPEAKER_00", "SPEAKER_01"])
        self.assertEqual(m["segments"][0]["text"], "Это я правил руками")
        self.assertNotIn("keep_whole", m["segments"][0])
        self.assertEqual(m["speakers"]["SPEAKER_00"]["name"], "Мария")  # shared most of its time
        self.assertEqual(m["speakers"]["SPEAKER_01"]["name"], "Участник 2")
        self.assertEqual(m["transcript_model"], "large-v3")  # the same transcript, split anew

    def test_one_named_person_split_in_two_keeps_the_name_on_the_larger_part(self):
        old_segs = [{"start": 0, "end": 20, "speaker": "SPEAKER_00"}]
        new_segs = [{"start": 0, "end": 5, "speaker": "SPEAKER_00"}, {"start": 5, "end": 20, "speaker": "SPEAKER_01"}]
        new_spk = {"SPEAKER_00": {"name": "Участник 1"}, "SPEAKER_01": {"name": "Участник 2"}}
        transcriber.carry_names(old_segs, {"SPEAKER_00": {"name": "Мария"}}, new_segs, new_spk)
        self.assertEqual((new_spk["SPEAKER_00"]["name"], new_spk["SPEAKER_01"]["name"]), ("Участник 1", "Мария"))


@unittest.skipIf(transcriber is None, "app dependencies not installed")
class EditsWhileSplittingTest(unittest.TestCase):
    def test_edits_wait_for_a_new_split(self):
        """Its result replaces the transcript: an edit made meanwhile would be lost under it."""
        from fastapi import HTTPException

        from app.main import _ensure_not_transcribing

        with transcriber._jobs_lock:
            transcriber._queue_add(987654, "resplit")
        try:
            self.assertTrue(transcriber.is_transcribing(987654))
            with self.assertRaises(HTTPException) as err:
                _ensure_not_transcribing(987654)
            self.assertEqual(err.exception.status_code, 409)
        finally:
            with transcriber._jobs_lock:
                transcriber._queue[:] = [q for q in transcriber._queue if q["id"] != 987654]


if __name__ == "__main__":
    unittest.main()
