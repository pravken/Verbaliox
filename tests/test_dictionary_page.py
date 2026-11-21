"""The section «Словарь» (app/dictionary_page.py): how many recordings hold a word, and the words a hand
edit suggests until they are learned or hidden."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest

try:
    from fastapi.testclient import TestClient

    from app import dictionary_page, main
    from app.database import clear_dictionary, create_meeting, init_db, merge_summaries, save_meeting_results
except ImportError:  # app dependencies are not installed
    dictionary_page = None


@unittest.skipIf(dictionary_page is None, "app dependencies not installed")
class DictionaryPageTest(unittest.TestCase):
    def setUp(self):
        init_db()
        clear_dictionary()
        self.client = TestClient(main.app, base_url="http://127.0.0.1:8790")
        self.client.cookies.set("vs_session_8790", main.SESSION_TOKEN)

    def tearDown(self):
        clear_dictionary()

    def _recording(self, title, lines):
        m = create_meeting(title, "a.wav", "a.wav", language="ru")
        segs = [{"id": i + 1, "start": i * 5.0, "end": i * 5.0 + 4, "speaker": "SPEAKER_00", "text": x} for i, x in enumerate(lines)]
        save_meeting_results(m["id"], speakers={}, segments=segs, summaries={}, language="ru", transcript_model="test")
        return m["id"]

    def test_usage_counts_recordings_not_lines(self):
        self._recording("Синк по релизу", ["Обновили Kubernetes вчера", "Kubernetes снова упал"])
        self._recording("Планёрка", ["Про Kubernetes кластер"])
        term = self.client.post("/api/dictionary", json={"term": "Kubernetes", "category": "Термины"}).json()["last"]
        other = self.client.post("/api/dictionary", json={"term": "Пиксель-Рендер"}).json()["last"]
        usage = self.client.get("/api/dictionary/usage").json()
        self.assertGreaterEqual(usage[str(term["id"])], 2)
        self.assertEqual(usage[str(other["id"])], 0)

    def test_a_hand_edit_suggests_until_learned_or_hidden(self):
        mid = self._recording("Созвон с подрядчиком", ["Текст"])
        merge_summaries(mid, {"protocol": "Решили перенести сервис в кубернетис, проверит жиру."})
        r = self.client.put(f"/api/meetings/{mid}/summaries/protocol",
                            json={"text": "Решили перенести сервис в Kubernetes, проверит Jira."})
        self.assertEqual(r.status_code, 200)
        offers = self.client.get("/api/dictionary/offers").json()
        pairs = {(o["wrong"], o["right"]) for o in offers}
        self.assertIn(("кубернетис", "Kubernetes"), pairs)
        self.assertTrue(all(o["title"] == "Созвон с подрядчиком" for o in offers))
        self.client.post("/api/dictionary/learn", json={"pairs": [{"wrong": "кубернетис", "right": "Kubernetes"}]})
        self.client.post("/api/dictionary/offers/hide", json={"wrong": "жиру", "right": "Jira"})
        self.assertEqual(self.client.get("/api/dictionary/offers").json(), [])


if __name__ == "__main__":
    unittest.main()
