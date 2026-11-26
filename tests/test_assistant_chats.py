"""The assistant's conversations (app/assistant_chats.py, app/api/assistant.py)."""
import tests  # noqa: F401
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import assistant_chats as ac


class AssistantChatsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.file = Path(self.tmp.name) / "assistant_chats.json"
        self.patch = mock.patch.object(ac, "CHATS_FILE", self.file)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_saved_and_loaded_newest_first(self):
        ac.save_chats([
            {"id": "a", "title": "Старый", "updated": "2026-10-01T10:00", "items": []},
            {"id": "b", "title": "Новый", "updated": "2026-10-20T10:00", "items": [{"id": 1, "question": "Что решили?", "status": "done"}]},
        ])
        chats = ac.load_chats()
        self.assertEqual([c["id"] for c in chats], ["b", "a"])
        self.assertEqual(chats[0]["items"][0]["question"], "Что решили?")

    def test_merged_as_the_window_closes(self):
        """Found in the audit: what changed in the last half-second was lost with the window. As it closes the page
        sends only the changed conversations and the removed ids (a keepalive request: 64 KB at most); the others
        stay as stored."""
        done = [{"id": 1, "question": "Что решили?", "status": "done"}]
        ac.save_chats([{"id": "a", "title": "Первый", "updated": "2026-10-01", "items": done},
                       {"id": "b", "title": "Второй", "updated": "2026-10-02", "items": done},
                       {"id": "c", "title": "Третий", "updated": "2026-10-03", "items": done}])
        ac.merge_chats([{"id": "b", "title": "Второй, переименован", "updated": "2026-10-05", "items": done},
                        {"id": "d", "title": "Новый", "updated": "2026-10-04", "items": done}], deleted=["c"])
        self.assertEqual([(c["id"], c["title"]) for c in ac.load_chats()],
                         [("b", "Второй, переименован"), ("d", "Новый"), ("a", "Первый")])
        with self.assertRaises(ValueError):
            ac.merge_chats([{"title": "no id"}])

    def test_the_merge_route(self):
        from fastapi.testclient import TestClient

        from app import main

        c = TestClient(main.app, base_url="http://127.0.0.1:8790")
        c.cookies.set("vs_session_8790", main.SESSION_TOKEN)
        ac.save_chats([{"id": "a", "updated": "2026-10-01", "items": [{"id": 1, "question": "?", "status": "done"}]}])
        r = c.post("/api/assistant/chats/merge", json={"chats": [], "deleted": ["a"]})
        self.assertEqual((r.status_code, r.json()), (200, {"count": 0}))
        self.assertEqual(c.post("/api/assistant/chats/merge", json={"chats": [{"items": []}]}).status_code, 400)

    def test_a_running_answer_is_stored_as_stopped(self):
        ac.save_chats([{"id": "a", "items": [{"id": 1, "question": "?", "status": "pending"}]}])
        self.assertEqual(ac.load_chats()[0]["items"][0]["status"], "stopped")

    def test_unknown_fields_and_bad_lists(self):
        ac.save_chats([{"id": "a", "secret": "x", "items": [{"id": 1, "question": "q", "status": "done", "html": "<b>"}]}])
        chat = ac.load_chats()[0]
        self.assertNotIn("secret", chat)
        self.assertNotIn("html", chat["items"][0])
        with self.assertRaises(ValueError):
            ac.save_chats({"id": "a"})
        with self.assertRaises(ValueError):
            ac.save_chats([{"title": "no id"}])

    def test_ids_and_periods_are_what_the_page_can_put_in_its_markup(self):
        """The file is read back into the page's markup: an id that is not a number drops that question,
        a period that is not dates loses those dates."""
        ac.save_chats([{"id": "a", "items": [
            {"id": "1, alert(1)", "question": "плохой", "status": "done"},
            {"id": 7, "question": "хороший", "status": "done",
             "scope": {"type": "period", "from": "2026-10-01\"><b>", "to": "2026-10-24"}},
        ]}])
        items = ac.load_chats()[0]["items"]
        self.assertEqual([x["id"] for x in items], [7])
        self.assertEqual(items[0]["scope"], {"type": "period", "to": "2026-10-24"})

    def test_limits(self):
        many = [{"id": str(i), "updated": f"2026-10-{i % 28 + 1:02d}", "items": [{"id": n, "question": "q", "status": "done"} for n in range(150)]}
                for i in range(250)]
        chats = ac.save_chats(many)
        self.assertEqual(len(chats), ac.MAX_CHATS)
        self.assertTrue(all(len(c["items"]) == ac.MAX_ITEMS for c in chats))
        self.assertLessEqual(self.file.stat().st_size, ac.MAX_BYTES)

    def test_a_broken_file_gives_no_conversations(self):
        self.file.write_text("{not json", encoding="utf-8")
        self.assertEqual(ac.load_chats(), [])
        self.file.write_text(json.dumps({"x": 1}), encoding="utf-8")
        self.assertEqual(ac.load_chats(), [])

    def test_answer_documents(self):
        src = [{"n": 1, "title": "Встреча", "date": "22.10", "start": 3725, "speaker": "Анна", "text": "Сделаем к среде"}]
        text = ac.answer_text("Что решили?", "- Пункт **один** [1]", src, "Источники")
        self.assertIn("# Что решили?", text)
        self.assertIn("[1] Встреча · 22.10 · 01:02:05 — Анна: Сделаем к среде", text)
        doc = ac.answer_docx("Что решили?", "## Итог\n- Пункт **один** [1]", src, "Источники")
        self.assertTrue(doc.startswith(b"PK"))


class AssistantApiTest(unittest.TestCase):
    def test_export_formats(self):
        from fastapi.testclient import TestClient
        from app.main import app

        from app import main

        client = TestClient(app, base_url="http://127.0.0.1:8790")
        client.get(f"/?token={main.SESSION_TOKEN}")
        body = {"question": "Что/решили?", "answer": "Ответ", "sources": [], "lang": "ru"}
        r = client.post("/api/assistant/export", json={**body, "fmt": "md"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("filename*=UTF-8''", r.headers["content-disposition"])
        self.assertNotIn("/", r.headers["content-disposition"].split("''", 1)[1].replace("%2F", ""))
        r = client.post("/api/assistant/export", json={**body, "fmt": "exe"})
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
