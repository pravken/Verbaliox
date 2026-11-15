"""The analysis in steps (app/analysis_chain.py): the protocol's result sections are the lists of the
decisions and the tasks word for word, and a task found later is added to its «Следующие шаги»."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest
from unittest import mock

try:
    from app import analysis_chain, commitments
    from app.database import create_meeting, get_meeting, init_db, merge_summaries, save_meeting_results
    from app.meeting_context import protocol_points
except ImportError:  # app dependencies are not installed
    analysis_chain = None

PROTOCOL = ("## Краткое содержание\nОбсудили рекламу.\n\n## Решения\n- Провести обход [01:00]\n\n"
            "## Открытые вопросы\nОткрытых вопросов нет\n\n## Следующие шаги\n- Ольга: позвонить в агентство\n\n"
            "## Обсуждение по темам\n### Реклама\n- говорили о баннерах [02:00]")


@unittest.skipIf(analysis_chain is None, "app dependencies not installed")
class ReplaceSectionTest(unittest.TestCase):
    def test_a_section_gets_exactly_these_points_and_the_rest_stays(self):
        md = analysis_chain.replace_section(PROTOCOL, "next", ["Ольга: позвонить в агентство", "Игорь: заказать баннеры"])
        self.assertEqual(protocol_points(md)["next"], ["Ольга: позвонить в агентство", "Игорь: заказать баннеры"])
        self.assertIn("### Реклама\n- говорили о баннерах [02:00]", md)
        self.assertEqual(protocol_points(md)["decisions"], ["Провести обход [01:00]"])
        md = analysis_chain.replace_section(md, "open", ["Кто платит"])
        self.assertEqual(protocol_points(md)["open"], ["Кто платит"])
        self.assertNotIn("Открытых вопросов нет", md)

    def test_nothing_found_says_so_and_a_missing_section_is_added_before_the_topics(self):
        md = analysis_chain.replace_section(PROTOCOL, "decisions", [])
        self.assertIn("## Решения\nРешений не принималось\n", md)
        md = analysis_chain.replace_section("## Краткое содержание\nТекст\n\n## Обсуждение по темам\n- x", "next", ["Ольга: позвонить"])
        self.assertLess(md.index("## Следующие шаги"), md.index("## Обсуждение по темам"))


@unittest.skipIf(analysis_chain is None, "app dependencies not installed")
class ChainTest(unittest.TestCase):
    def setUp(self):
        init_db()
        m = create_meeting("Совещание", "a.m4a", "/tmp/a.m4a")
        save_meeting_results(m["id"], speakers={"S1": {"name": "Ольга"}}, segments=[
            {"id": 0, "start": 0, "end": 5, "speaker": "S1", "text": "Решили провести обход, я позвоню в агентство"}])
        self.mid = m["id"]

    def test_the_task_found_later_joins_the_next_steps(self):
        merge_summaries(self.mid, {"protocol": PROTOCOL})
        commitments.create("позвонить в агентство", "Ольга", "part", "", self.mid)
        self.assertEqual(analysis_chain.sync_next_steps(self.mid), 0)  # already there
        commitments.create("заказать баннеры", "Игорь", "part", "2026-12-01", self.mid)
        self.assertEqual(analysis_chain.sync_next_steps(self.mid), 1)
        steps = protocol_points(get_meeting(self.mid)["summaries"]["protocol"])["next"]
        self.assertEqual(steps, ["Ольга: позвонить в агентство", "Игорь: заказать баннеры (срок: 2026-12-01)"])

    def test_the_steps_run_in_order_and_the_protocol_holds_their_lists(self):
        calls = []
        decisions = "## Решения\n- Провести обход [00:01]\n\n## Открытые вопросы\n- Кто платит за баннеры"

        def fake_summary(template_key, context_note="", **_):
            calls.append(template_key)
            if template_key == "decisions":
                return decisions
            self.assertIn("Провести обход", context_note)
            self.assertIn("Ольга: позвонить в агентство", context_note)
            # the model wrote its own lists: the program puts the found ones in their place
            return ("## Краткое содержание\nОбход.\n\n## Решения\n- Что-то другое\n\n## Открытые вопросы\n- Иное\n\n"
                    "## Следующие шаги\n- Выдуманный шаг\n\n## Обсуждение по темам\n- обход [00:01]")

        def fake_extract(meeting_id, model_name=None, hints=None):
            calls.append("tasks")
            self.assertIn("Провести обход", hints)
            commitments.create("позвонить в агентство", "Ольга", "part", "", meeting_id)
            return []

        with mock.patch("app.ollama_client.generate_meeting_summary", side_effect=fake_summary), \
                mock.patch("app.commitments.extract", side_effect=fake_extract):
            md = analysis_chain.run(self.mid)
        self.assertEqual(calls, ["decisions", "tasks", "protocol"])
        p = protocol_points(md)
        self.assertEqual(p["decisions"], ["Провести обход [00:01]"])
        self.assertEqual(p["open"], ["Кто платит за баннеры"])
        self.assertEqual(p["next"], ["Ольга: позвонить в агентство"])
        self.assertIn("## Обсуждение по темам\n- обход [00:01]", md)

    def test_off_by_default(self):
        self.assertFalse(analysis_chain.enabled({}))
        self.assertTrue(analysis_chain.enabled({"analysis_chain": "true"}))


if __name__ == "__main__":
    unittest.main()
