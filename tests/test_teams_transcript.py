"""The transcript Teams saves after a meeting (.vtt) imported into a recording (app/teams_transcript.py)."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest

try:
    from app import database, teams_transcript
except ImportError:  # app dependencies are not installed (e.g. in the release CI job)
    teams_transcript = None

VTT = """WEBVTT

a1b2/12-0
00:00:01.000 --> 00:00:04.000
<v Анна Петрова>Добрый день, начнём с бюджета.</v>

a1b2/13-0
00:00:05.000 --> 00:00:08.500
<v Иван Сидоров>Бюджет готов, осталось согласовать.</v>

00:01:02.250 --> 00:01:03.000
Анна Петрова: Отлично.
"""


@unittest.skipIf(teams_transcript is None, "app dependencies not installed")
class TeamsVttTest(unittest.TestCase):
    def test_parse(self):
        cues = teams_transcript.parse_vtt(VTT)
        self.assertEqual([(c["start"], c["name"]) for c in cues], [(1.0, "Анна Петрова"), (5.0, "Иван Сидоров"), (62.25, "Анна Петрова")])
        self.assertEqual(cues[2]["text"], "Отлично.")

    def test_import_names_the_voices_but_keeps_a_name_given(self):
        database.init_db()
        m = database.create_meeting("Бюджет", "a.wav", "a.wav")
        database.save_meeting_results(m["id"], segments=[
            {"id": 1, "start": 0.8, "end": 4.2, "speaker": "SPEAKER_00", "text": "добрый день начнём с бюджета"},
            {"id": 2, "start": 4.9, "end": 8.6, "speaker": "SPEAKER_01", "text": "бюджет готов осталось согласовать"}],
            speakers={"SPEAKER_00": {"id": "SPEAKER_00", "name": "Участник 1"}, "SPEAKER_01": {"id": "SPEAKER_01", "name": "Ваня"}})
        lines, named = teams_transcript.import_into(m["id"], VTT)
        self.assertEqual((lines, named), (3, 1))
        got = database.get_meeting(m["id"])
        self.assertEqual(got["speakers"]["SPEAKER_00"]["name"], "Анна Петрова")
        self.assertEqual(got["speakers"]["SPEAKER_01"]["name"], "Ваня")  # given by the user: stays
        self.assertIn("teams", database.all_transcripts(m["id"]))

    def test_not_a_transcript(self):
        database.init_db()
        m = database.create_meeting("X", "b.wav", "b.wav")
        with self.assertRaises(ValueError):
            teams_transcript.import_into(m["id"], "hello")


if __name__ == "__main__":
    unittest.main()
