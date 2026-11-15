"""Features as tags of meetings (app/features.py): chosen by the user, given by a series rule, or
suggested by the analysis model and kept only once accepted."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest
from unittest import mock

try:
    from app import features
    from app.database import create_meeting, get_meeting, init_db, list_meetings, save_meeting_results, update_meeting_fields
except ImportError:  # app dependencies are not installed
    features = None


@unittest.skipIf(features is None, "app dependencies not installed")
class FeatureTagsTest(unittest.TestCase):
    def setUp(self):
        init_db()
        for f in features.list_features():
            features.delete_feature(f["id"])

    def _meeting(self, title="Синк по платежам"):
        m = create_meeting(title, "a.m4a", "/tmp/a.m4a")
        save_meeting_results(m["id"], speakers={"S1": {"name": "Анна"}}, segments=[
            {"id": 0, "start": 0, "end": 5, "speaker": "S1", "text": "Обсуждаем новый экран оплаты и возвраты"}])
        return m["id"]

    def test_features_are_made_once_by_name_and_tag_meetings(self):
        pay = features.create_feature("Платежи")
        self.assertEqual(features.create_feature("  платежи ")["id"], pay["id"])  # the same, any case
        search = features.create_feature("Поиск")
        self.assertNotEqual(pay["color"], search["color"])  # colours in turn
        mid = self._meeting()
        features.set_meeting_features(mid, [pay["id"], search["id"], 99999])  # an unknown id is dropped
        self.assertEqual(get_meeting(mid)["features"], [pay["id"], search["id"]])
        row = next(m for m in list_meetings() if m["id"] == mid)
        self.assertEqual(row["features"], [pay["id"], search["id"]])
        counts = {f["name"]: f["count"] for f in features.list_features()}
        self.assertEqual(counts, {"Платежи": 1, "Поиск": 1})
        features.delete_feature(search["id"])  # the tag goes with it, the meeting stays
        self.assertEqual(get_meeting(mid)["features"], [pay["id"]])
        with self.assertRaises(ValueError):
            features.update_feature(pay["id"], name="   ")

    def test_a_series_rule_tags_its_new_meetings(self):
        pay = features.create_feature("Платежи")
        from app.series import create_series

        sid = create_series("Синк платежей")
        first = self._meeting()
        update_meeting_fields(first, series_id=sid)
        features.set_meeting_features(first, [pay["id"]], for_series=True)
        second = self._meeting()
        update_meeting_fields(second, series_id=sid)
        self.assertEqual(features.apply_series_rule(second), [pay["id"]])
        self.assertEqual(get_meeting(second)["features"], [pay["id"]])
        own = self._meeting()  # a meeting with features of its own keeps them
        other = features.create_feature("Поиск")
        features.set_meeting_features(own, [other["id"]])
        update_meeting_fields(own, series_id=sid)
        self.assertEqual(features.apply_series_rule(own), [])
        self.assertEqual(get_meeting(own)["features"], [other["id"]])

    def test_the_model_only_suggests_and_a_no_is_remembered(self):
        pay, search = features.create_feature("Платежи"), features.create_feature("Поиск")
        mid = self._meeting()
        llm = mock.Mock(is_cloud=False, max_chars=100000)
        llm.chat.return_value = '["платежи", "Новая фича"]'  # a name not in the list is ignored
        with mock.patch("app.llm.target", return_value=llm):
            self.assertEqual(features.suggest(mid), [pay["id"]])
        m = get_meeting(mid)
        self.assertEqual(m["features"], [])  # nothing put on the meeting yet
        self.assertEqual(m["feature_suggestions"], [pay["id"]])
        self.assertIn("- Платежи\n- Поиск", llm.chat.call_args[0][1])
        features.decline_suggestion(mid, pay["id"])
        with mock.patch("app.llm.target", return_value=llm):
            self.assertEqual(features.suggest(mid), [])  # turned down: not suggested again
        llm.chat.return_value = '["Поиск"]'
        with mock.patch("app.llm.target", return_value=llm):
            features.suggest(mid)
        features.accept_suggestion(mid, search["id"])
        m = get_meeting(mid)
        self.assertEqual((m["features"], m["feature_suggestions"]), ([search["id"]], []))
        with mock.patch("app.llm.target", return_value=llm):
            self.assertEqual(features.suggest(mid), [])  # it has features now: no more guesses

    def test_accepting_one_suggestion_keeps_the_others(self):
        pay, search = features.create_feature("Платежи"), features.create_feature("Поиск")
        mid = self._meeting()
        llm = mock.Mock(is_cloud=False, max_chars=100000)
        llm.chat.return_value = '["Платежи", "Поиск"]'
        with mock.patch("app.llm.target", return_value=llm):
            features.suggest(mid)
        features.accept_suggestion(mid, pay["id"])
        m = get_meeting(mid)
        self.assertEqual((m["features"], m["feature_suggestions"]), ([pay["id"]], [search["id"]]))

    def test_a_deleted_meeting_leaves_no_tags_nor_deleted_tasks(self):
        from app import commitments
        from app.database import delete_meeting, get_connection

        pay = features.create_feature("Платежи")
        mid = self._meeting()
        features.set_meeting_features(mid, [pay["id"]])
        features.decline_suggestion(mid, pay["id"])
        commitments._init()
        conn = get_connection()
        conn.execute("INSERT INTO commitments_dismissed (meeting_id, who, what, quote, at, created_at) VALUES (?, '', 'тайна', '', 0, '')", (mid,))
        conn.commit()
        conn.close()
        delete_meeting(mid)
        conn = get_connection()
        left = [conn.execute(f"SELECT COUNT(*) FROM {t} WHERE meeting_id = ?", (mid,)).fetchone()[0]
                for t in ("meeting_features", "feature_declined", "commitments_dismissed")]
        conn.close()
        self.assertEqual(left, [0, 0, 0])

    def test_invisible_characters_are_dropped_from_names(self):
        f = features.create_feature("Пла\u202eтежи\u200b")
        self.assertEqual(f["name"], "Платежи")

    def test_the_meetings_title_suggests_its_feature(self):
        pay, search = features.create_feature("Платежи"), features.create_feature("Поиск")
        features.update_feature(search["id"], keywords="search,  выдача ; поиск")
        mid = self._meeting("Синк: Выдача и ранжирование")
        self.assertEqual(features.suggest_by_title(mid), [search["id"]])  # by a keyword, any case
        self.assertEqual(get_meeting(mid)["features"], [])  # only a suggestion
        other = self._meeting("Платежи: ретро")
        self.assertEqual(features.suggest_by_title(other), [pay["id"]])
        self.assertEqual(features.suggest_by_title(self._meeting("Поисковик для HR")), [])  # whole words only
        f = next(x for x in features.list_features() if x["id"] == search["id"])
        self.assertEqual(f["keywords"], "search, выдача, поиск")  # cleaned, each once

    def test_what_a_feature_is_reaches_the_models_and_recognition(self):
        pay = features.create_feature("Платежи")
        features.update_feature(pay["id"], description="Экран оплаты и возвраты", keywords="эквайринг",
                                terms="Stripe, PayGate")
        note = features.describe([pay["id"]])
        self.assertIn("Платежи: Экран оплаты и возвраты; ключевые слова: эквайринг; термины: Stripe, PayGate", note)
        from app import vocab

        vocab.invalidate()
        self.assertIn("Stripe", vocab.hotwords())  # Whisper's hint and the corrections
        self.assertIn("PayGate", vocab.glossary_note())
        from app import ollama_client

        llm = mock.Mock(is_cloud=False, max_chars=100000, label="m")
        llm.chat.return_value = "обзор"
        segs = [{"start": 0, "end": 5, "speaker": "S1", "text": "обсудили страйп"}]
        with mock.patch("app.llm.target", return_value=llm):
            ollama_client.generate_meeting_summary(segs, {}, "protocol", features_note=note)
        sent = " ".join(llm.chat.call_args[0])
        self.assertIn("Экран оплаты и возвраты", sent)
        self.assertIn("Stripe", sent)  # the glossary

    def test_the_feature_page_gathers_meetings_decisions_and_tasks(self):
        from app import commitments
        from app.database import merge_summaries

        pay = features.create_feature("Платежи")
        mid = self._meeting("Синк платежей")
        features.set_meeting_features(mid, [pay["id"]])
        merge_summaries(mid, {"tldr": "Обсудили возвраты", "protocol": "## Итоги\n- что-то\n## Решения\n- Запускаем возвраты в декабре\n- Stripe остаётся\n## Риски\n- сроки"})
        commitments.create("обновить экран оплаты", "Анна", "part", "", mid)
        page = features.overview(pay["id"])
        self.assertEqual([m["id"] for m in page["meetings"]], [mid])
        self.assertEqual(page["meetings"][0]["decisions"], ["Запускаем возвраты в декабре", "Stripe остаётся"])
        self.assertEqual([x["what"] for x in page["tasks"]], ["обновить экран оплаты"])
        self.assertIsNone(features.overview(999999))
        self.assertEqual(features.decisions_of("## Decisions\n1. Ship it\n## Next\n- x"), ["Ship it"])
        self.assertEqual(features.decisions_of("**Решения**\n- Да\n**Итог**\n- нет"), ["Да"])
        from app.ollama_client import SUMMARY_TEMPLATES

        self.assertIn("## Решения", SUMMARY_TEMPLATES["protocol"])  # the standard protocol has them to show

    def test_lists_split_on_lines_and_keep_whole_items(self):
        f = features.create_feature("Списки")
        features.update_feature(f["id"], keywords="payments\nэквайринг", terms=", ".join(f"term{i}" for i in range(80)))
        f = next(x for x in features.list_features() if x["id"] == f["id"])
        self.assertEqual(f["keywords"], "payments, эквайринг")
        self.assertTrue(all(len(t) >= 5 for t in features.split_list(f["terms"])))  # no «te» of a cut «term57»
        self.assertEqual(len(features.split_list(f["terms"])), 80)  # a hundred or so fit (40 did before)
        self.assertLessEqual(len(f["terms"]), features.TERMS_MAX)
        from app import vocab

        vocab.invalidate()
        note = vocab.glossary_note(already=features.describe([f["id"]]))
        self.assertNotIn("term7,", note)  # in the request with the meeting's feature already: not twice

    def test_answers_are_read_loosely(self):
        fs = [{"id": 1, "name": "Платежи"}, {"id": 2, "name": "Поиск"}]
        self.assertEqual(features.parse_names('Ответ: ["Поиск", "поиск", "Платежи"]', fs), [2, 1])
        self.assertEqual(features.parse_names("[]", fs), [])
        self.assertEqual(features.parse_names("не знаю", fs), [])


if __name__ == "__main__":
    unittest.main()
