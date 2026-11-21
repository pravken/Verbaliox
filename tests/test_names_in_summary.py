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
             "speaker_marks": [{"at": 3, "name": "Alexander Matsulevich"}, {"at": 9, "name": "мария петрова"}],
             "user_notes": "Участники по календарю: Олег Сидоров <oleg@example.com>, Мария Петрова"}
        self.assertEqual(people.meeting_roster(m),
                         ["Мария Петрова — дизайнер", "Alexander Matsulevich", "Олег Сидоров"])

    def test_misspelt_names_are_put_right_and_their_case_endings_stay(self):
        roster = ["Alexander Matsulevich", "Мария Петрова — дизайнер", "Мацулевич Александр"]
        fix = lambda t: people.fix_name_typos(t, roster)  # noqa: E731
        self.assertEqual(fix("передать Мацлевичу задачу"), "передать Мацулевичу задачу")
        self.assertEqual(fix("Петрвой поручено"), "Петровой поручено")
        self.assertEqual(fix("Alexandr Matsulevitch said"), "Alexander Matsulevich said")
        self.assertEqual(fix("Алексанр сказал"), "Александр сказал")
        # right already, other words and short names are left alone
        for t in ("Мацулевичу всё", "Москва и Марс", "Марина пришла", "Петров тоже", "Петербург", "Александра отметила"):
            self.assertEqual(fix(t), t)

    def test_the_summary_is_told_who_was_there_and_its_answer_put_right(self):
        sent = []
        llm = mock.Mock(max_chars=100000, label="m")
        llm.chat = lambda system, user: (sent.append(user), "Мацлевич рассказал про сроки.")[1]
        segs = [{"start": 0, "end": 5, "speaker": "SPEAKER_00", "text": "Сегодня расскажу про сроки."}]
        with mock.patch("app.llm.target", return_value=llm):
            out = ollama_client.generate_meeting_summary(segs, {"SPEAKER_00": {"name": "Alexander Matsulevich"}},
                                                         participants=["Мацулевич Александр"])
        self.assertIn("Мацулевич Александр", sent[0])
        self.assertIn("буква в букву", sent[0])
        self.assertEqual(out, "Мацулевич рассказал про сроки.")


    def test_the_summary_is_told_of_the_contacts_named_in_the_talk(self):
        # asked by the user: a contact named in the talk, not a participant, is written as in the contacts
        people.add("Дмитрий Кравченко")
        people.update("Дмитрий Кравченко", role="тимлид")
        people.add("Ксения Белкина")
        sent = []
        llm = mock.Mock(max_chars=100000, label="m")
        llm.chat = lambda system, user: (sent.append(user), "Дмитрий Кравчено проверит.")[1]
        segs = [{"start": 0, "end": 5, "speaker": "SPEAKER_00", "text": "Это проверит Дмитрий Кравченко."}]
        with mock.patch("app.llm.target", return_value=llm):
            out = ollama_client.generate_meeting_summary(segs, {"SPEAKER_00": {"name": "Мария"}}, participants=["Мария"])
        self.assertIn("Дмитрий Кравченко — тимлид", sent[0])
        self.assertIn("Ксения Белкина", sent[0])  # the other contacts follow (a misheard name can still match)
        self.assertEqual(out, "Дмитрий Кравченко проверит.")


    def test_a_contacts_short_name_is_written_out_in_full(self):
        # asked by the user: «Дима» merged into «Дмитрий Орлов» is written as the full name in the analysis
        people.merge(["Дмитрий Орлов", "Дима"])
        text = "Дима проверит сроки, Дима Орлов согласен. Диме прислать смету. Димитрий не придёт."
        self.assertEqual(people.expand_names(text),
                         "Дмитрий Орлов проверит сроки, Дмитрий Орлов согласен. Диме прислать смету. Димитрий не придёт.")
        sent = []
        llm = mock.Mock(max_chars=100000, label="m")
        llm.chat = lambda system, user: (sent.append(user), "Дима проверит сроки.")[1]
        segs = [{"start": 0, "end": 5, "speaker": "SPEAKER_00", "text": "Дима проверит сроки."}]
        with mock.patch("app.llm.target", return_value=llm):
            out = ollama_client.generate_meeting_summary(segs, {"SPEAKER_00": {"name": "Мария"}}, participants=["Мария"])
        self.assertIn("не «Дима» или «Саня», а полное имя и фамилия", sent[0])
        self.assertEqual(out, "Дмитрий Орлов проверит сроки.")


if __name__ == "__main__":
    unittest.main()
