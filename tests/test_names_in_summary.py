"""The participants' names in the analysis (app/people.py meeting_roster, fix_name_typos): the model is
told who was there, and a name it still misspells is put right."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest
from unittest import mock

try:
    from app import database, ollama_client, people
except ImportError:  # app dependencies are not installed (e.g. in the release CI job)
    people = None


@unittest.skipIf(people is None, "app dependencies not installed")
class NamesInSummaryTest(unittest.TestCase):
    def setUp(self):
        database.init_db()
        people.init_table()
        with database._db_lock:
            conn = database.get_connection()
            conn.execute("DELETE FROM people_directory")
            conn.commit()
            conn.close()

    def test_the_roster_has_speakers_marks_and_invitees_once_with_roles(self):
        people.update("Мария Петрова", role="дизайнер")
        m = {"speakers": {"SPEAKER_00": {"name": "Мария Петрова"}, "SPEAKER_01": {"name": "Участник 2"}},
             "speaker_marks": [{"at": 3, "name": "Alexander Yatsukevich"}, {"at": 9, "name": "мария петрова"}],
             "user_notes": "Участники по календарю: Олег Сидоров <oleg@example.com>, Мария Петрова"}
        self.assertEqual(people.meeting_roster(m),
                         ["Мария Петрова — дизайнер", "Alexander Yatsukevich", "Олег Сидоров"])

    def test_misspelt_names_are_put_right_and_their_case_endings_stay(self):
        roster = ["Alexander Yatsukevich", "Мария Петрова — дизайнер", "Яцукевич Александр"]
        fix = lambda t: people.fix_name_typos(t, roster)  # noqa: E731
        self.assertEqual(fix("передать Яцкевичу задачу"), "передать Яцукевичу задачу")
        self.assertEqual(fix("Петрвой поручено"), "Петровой поручено")
        self.assertEqual(fix("Alexandr Yatsukevitch said"), "Alexander Yatsukevich said")
        self.assertEqual(fix("Алексанр сказал"), "Александр сказал")
        # right already, other words and short names are left alone
        for t in ("Яцукевичу всё", "Москва и Марс", "Марина пришла", "Петров тоже", "Петербург", "Александра отметила"):
            self.assertEqual(fix(t), t)

    def test_the_summary_is_told_who_was_there_and_its_answer_put_right(self):
        sent = []
        llm = mock.Mock(is_cloud=False, max_chars=100000, label="m")
        llm.chat = lambda system, user: (sent.append(user), "Яцкевич рассказал про сроки.")[1]
        segs = [{"start": 0, "end": 5, "speaker": "SPEAKER_00", "text": "Сегодня расскажу про сроки."}]
        with mock.patch("app.llm.target", return_value=llm):
            out = ollama_client.generate_meeting_summary(segs, {"SPEAKER_00": {"name": "Alexander Yatsukevich"}},
                                                         participants=["Яцукевич Александр"])
        self.assertIn("Яцукевич Александр", sent[0])
        self.assertIn("буква в букву", sent[0])
        self.assertEqual(out, "Яцукевич рассказал про сроки.")


if __name__ == "__main__":
    unittest.main()
