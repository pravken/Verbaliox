"""Wrong input gets a 4xx answer that says what is wrong, not «Internal Server Error»."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest

try:
    from fastapi.testclient import TestClient

    from app import database, main
except ImportError:  # app dependencies are not installed (e.g. in the release CI job)
    main = None


@unittest.skipIf(main is None, "app dependencies not installed")
class BadInputTest(unittest.TestCase):
    def setUp(self):
        database.init_db()
        self.c = TestClient(main.app, base_url="http://127.0.0.1:8790")
        self.c.get(f"/?token={main.SESSION_TOKEN}")

    def test_answers(self):
        f = database.create_folder("Папка")
        self.assertEqual(self.c.patch(f"/api/folders/{f['id']}", json={"parent_id": "abc"}).status_code, 400)
        self.assertEqual(self.c.post("/api/settings", json={"settings": {"num_speakers": "inf"}}).status_code, 400)
        self.assertEqual(self.c.post("/api/settings", json={"settings": {"idle_unload_minutes": "1e999"}}).status_code, 400)
        self.assertEqual(self.c.patch("/api/meetings/999999/title", json={"title": "x"}).status_code, 404)


if __name__ == "__main__":
    unittest.main()
