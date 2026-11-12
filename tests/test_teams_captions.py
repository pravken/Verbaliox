"""Who speaks, read from the Teams captions (app/teams_captions.py): the text of the panel as pairs."""

import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import time
import unittest

from app import teams_captions as tc


class TeamsCaptionsTest(unittest.TestCase):
    PANEL = ["Natalia Rudavina", "Да, но это опять же какимто куском?",
             "Natalia Rudavina", "Не так что это прям вот весь большой фронт.",
             "Vladislav Lisnevskiy", "А так окей.",
             "Vladislav Lisnevskiy", "Мы можем сейчас контур сделать? Да вот вот примерный контур вот."]

    def test_names_and_lines_as_the_window_shows_them(self):
        got = tc.pairs(self.PANEL)
        self.assertEqual([n for n, _ in got], ["Natalia Rudavina"] * 2 + ["Vladislav Lisnevskiy"] * 2)
        self.assertEqual(got[2][1], "А так окей.")

    def test_a_short_line_is_not_taken_for_a_name(self):
        self.assertFalse(tc.looks_like_name("А так окей."))
        self.assertFalse(tc.looks_like_name("Да, конечно"))
        self.assertTrue(tc.looks_like_name("Борис Мелехин"))
        self.assertTrue(tc.looks_like_name("борис", known={"борис"}))  # a calendar name, whatever its case

    def test_each_line_gives_one_mark_even_while_it_grows(self):
        r = tc.Reader()
        r.started_at = time.time() - 100
        r._take(tc.pairs(["Natalia Rudavina", "Да, но это опять"]))
        r._take(tc.pairs(["Natalia Rudavina", "Да, но это опять же какимто куском?"]))  # the same line, longer
        r._take(tc.pairs(self.PANEL))
        snap = r.snapshot()
        self.assertEqual(snap["lines"], 4)
        self.assertEqual(snap["names"], ["Natalia Rudavina", "Vladislav Lisnevskiy"])
        self.assertTrue(all(97 <= m["at"] <= 99 for m in snap["marks"]))  # the caption lag taken off


if __name__ == "__main__":
    unittest.main()


class TeamsVersionTest(unittest.TestCase):
    def test_the_captions_become_a_version_of_their_own(self):
        marks = [{"at": 10.0, "name": "Natalia Rudavina", "text": "Да, но это опять же каким-то куском?"},
                 {"at": 14.0, "name": "Vladislav Lisnevskiy", "text": "А так окей."},
                 {"at": 3.0, "name": "Борис"}]  # a mark clicked by hand: no text, not a line
        v = tc.as_transcript(marks)
        self.assertEqual([s["text"] for s in v["segments"]], ["Да, но это опять же каким-то куском?", "А так окей."])
        self.assertEqual([v["speakers"][s["speaker"]]["name"] for s in v["segments"]], ["Natalia Rudavina", "Vladislav Lisnevskiy"])
        first = v["segments"][0]
        self.assertLessEqual(first["end"], 14.0)  # it ends where the next line starts
        self.assertEqual(len(first["words"]), 7)
        self.assertIsNone(tc.as_transcript([{"at": 1, "name": "Борис"}]))

    def test_a_clear_keeps_the_captions(self):
        from app.database import (all_transcripts, clear_results, create_meeting, init_db,
                                  save_meeting_results, save_transcript_version)

        init_db()
        m = create_meeting(title="Teams", filename="a.wav", media_path="a.wav")
        save_meeting_results(m["id"], segments=[{"id": 0, "start": 0, "end": 1, "speaker": "SPEAKER_00", "text": "раз"}],
                             speakers={"SPEAKER_00": {"name": "Участник 1"}}, transcript_model="gigaam-v3")
        save_transcript_version(m["id"], tc.TEAMS, tc.as_transcript([{"at": 0, "name": "Анна", "text": "раз два три"}]))
        clear_results(m["id"])
        self.assertEqual(list(all_transcripts(m["id"])), [tc.TEAMS])  # the model's text went, the captions stayed
