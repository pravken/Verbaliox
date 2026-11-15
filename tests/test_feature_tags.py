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
        self.assertIn("Платежи; Поиск", llm.chat.call_args[0][1])
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

    def test_answers_are_read_loosely(self):
        fs = [{"id": 1, "name": "Платежи"}, {"id": 2, "name": "Поиск"}]
        self.assertEqual(features.parse_names('Ответ: ["Поиск", "поиск", "Платежи"]', fs), [2, 1])
        self.assertEqual(features.parse_names("[]", fs), [])
        self.assertEqual(features.parse_names("не знаю", fs), [])


if __name__ == "__main__":
    unittest.main()
