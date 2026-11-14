"""Tasks of a meeting: an action of the meeting itself is not a task, and a task the user deleted does
not come back (app/commitments.py)."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest
from unittest import mock

try:
    from app import commitments
    from app.database import create_meeting, init_db, save_meeting_results
except ImportError:  # app dependencies are not installed (e.g. in the release CI job)
    commitments = None


@unittest.skipIf(commitments is None, "app dependencies not installed")
class InMeetingTest(unittest.TestCase):
    def test_actions_of_the_meeting_are_not_tasks(self):
        for what, quote in [("пошарить экран", "сейчас пошарю экран"), ("скинуть ссылку в чат", "скину ссылку в чат"),
                            ("включить микрофон", "секунду, включу микрофон"), ("share the screen", "let me share my screen")]:
            self.assertTrue(commitments.in_meeting_action({"what": what, "quote": quote, "due": ""}), what)
        for x in [{"what": "подготовить отчёт", "quote": "подготовлю отчёт к пятнице", "due": "к пятнице"},
                  {"what": "отправить ссылку на документ в чат", "quote": "после встречи скину в чат ссылку", "due": ""},
                  {"what": "показать демо клиенту", "quote": "покажу экран с демо клиенту", "due": "в четверг"}]:
            self.assertFalse(commitments.in_meeting_action(x), x["what"])


@unittest.skipIf(commitments is None, "app dependencies not installed")
class DismissedTest(unittest.TestCase):
    def test_a_deleted_task_stays_away_and_teaches_the_model(self):
        init_db()
        m = create_meeting("Планёрка", "q.m4a", "/tmp/q.m4a")
        save_meeting_results(m["id"], speakers={"S1": {"name": "Анна"}}, segments=[
            {"id": 0, "start": 10, "end": 14, "speaker": "S1", "text": "Сейчас пошарю экран и покажу таблицу"},
            {"id": 1, "start": 20, "end": 25, "speaker": "S1", "text": "Я обновлю бюджет до пятницы"},
            {"id": 2, "start": 30, "end": 35, "speaker": "S1", "text": "И ещё созвонюсь с подрядчиком по смете"}])
        answer = ('{"who": "Анна", "what": "пошарить экран", "due": "", "time": "00:10", "quote": "Сейчас пошарю экран"}\n'
                  '{"who": "Анна", "what": "обновить бюджет", "due": "до пятницы", "time": "00:20", "quote": "Я обновлю бюджет до пятницы"}\n'
                  '{"who": "Анна", "what": "созвониться с подрядчиком", "due": "", "time": "00:30", "quote": "созвонюсь с подрядчиком по смете"}')
        llm = mock.Mock(is_cloud=False, max_chars=100000)
        llm.chat.return_value = answer
        with mock.patch("app.llm.target", return_value=llm):
            items = commitments.extract(m["id"])
        self.assertEqual(sorted(x["what"] for x in items), ["обновить бюджет", "созвониться с подрядчиком"])
        call = next(x for x in items if x["what"] == "созвониться с подрядчиком")
        commitments.delete(call["id"])  # not a task, the user says
        with mock.patch("app.llm.target", return_value=llm):
            again = commitments.extract(m["id"])
        self.assertEqual([x["what"] for x in again], ["обновить бюджет"])
        system = llm.chat.call_args_list[-2][0][0]  # the search (the last call is the second look)
        self.assertIn("созвониться с подрядчиком", system)


if __name__ == "__main__":
    unittest.main()
