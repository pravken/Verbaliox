"""One context for every analysis of a recording (app/meeting_context.py): the tasks and the protocol's
result reach the other tabs, and the protocol's decisions reach the search for tasks."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest
from unittest import mock

try:
    from app import commitments, meeting_context
    from app.database import create_meeting, get_meeting, init_db, merge_summaries, save_meeting_results
except ImportError:  # app dependencies are not installed
    meeting_context = None

PROTOCOL = ("## Краткое содержание\nОбсудили рекламу.\n## Решения\n- В четверг провести обход этажа [33:01]\n"
            "## Открытые вопросы\n- Кто платит за баннеры\n## Следующие шаги\n- Ольга: позвонить в агентство\n"
            "## Обсуждение по темам\n### Реклама\n- говорили о баннерах")


@unittest.skipIf(meeting_context is None, "app dependencies not installed")
class MeetingContextTest(unittest.TestCase):
    def setUp(self):
        init_db()
        m = create_meeting("Совещание", "a.m4a", "/tmp/a.m4a")
        save_meeting_results(m["id"], speakers={"S1": {"name": "Ольга"}}, segments=[
            {"id": 0, "start": 0, "end": 5, "speaker": "S1", "text": "В четверг проведём обход этажа"}])
        self.mid = m["id"]

    def test_the_protocol_result_is_read_by_section(self):
        p = meeting_context.protocol_points(PROTOCOL)
        self.assertEqual(p["decisions"], ["В четверг провести обход этажа [33:01]"])
        self.assertEqual(p["open"], ["Кто платит за баннеры"])
        self.assertEqual(p["next"], ["Ольга: позвонить в агентство"])

    def test_other_tabs_get_the_tasks_and_the_protocol(self):
        merge_summaries(self.mid, {"protocol": PROTOCOL})
        commitments.create("подготовить баннеры", "Ольга", "part", "2026-12-01", self.mid)
        m = get_meeting(self.mid)
        note = meeting_context.note_for_summary(m, "tldr")
        self.assertIn("Ольга: подготовить баннеры (срок: 2026-12-01)", note)
        self.assertIn("В четверг провести обход этажа", note)
        proto = meeting_context.note_for_summary(m, "protocol")
        self.assertIn("подготовить баннеры", proto)
        self.assertNotIn("Протокол этой встречи", proto)  # the protocol is not told itself
        self.assertEqual(meeting_context.note_for_summary(m, "chapters"), "")

    def test_the_search_for_tasks_reads_the_transcript_alone(self):
        # the protocol's points as hints narrowed the search or brought in points that are not tasks
        merge_summaries(self.mid, {"protocol": PROTOCOL})
        llm = mock.Mock(is_cloud=False, max_chars=100000)
        llm.chat.return_value = '{"who": "Ольга", "what": "провести обход этажа", "due": "в четверг", "time": "00:00", "quote": "В четверг проведём обход этажа"}'
        with mock.patch("app.llm.target", return_value=llm):
            commitments.extract(self.mid)
        sent = llm.chat.call_args_list[0][0][1]
        self.assertNotIn("В четверг провести обход этажа", sent)
        self.assertIn("В четверг проведём обход этажа", sent)  # the transcript itself

if __name__ == "__main__":
    unittest.main()
