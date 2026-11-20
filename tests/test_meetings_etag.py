"""/api/meetings answers with an ETag and 304 when the list did not change: the page's background
poll then gets no megabytes of the same JSON to parse and draw again (found in the audit)."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest

try:
    from fastapi.testclient import TestClient

    from app import main
    from app.database import create_meeting, delete_meeting, init_db, update_meeting_fields
except ImportError:  # app dependencies are not installed
    main = None


@unittest.skipIf(main is None, "app dependencies not installed")
class MeetingsEtagTest(unittest.TestCase):
    def setUp(self):
        init_db()
        self.c = TestClient(main.app, base_url="http://127.0.0.1:8790")
        self.c.cookies.set("vs_session_8790", main.SESSION_TOKEN)
        self.mid = create_meeting("Планёрка", "a.wav", "/nowhere/a.wav")["id"]
        self.addCleanup(delete_meeting, self.mid)

    def test_unchanged_list_is_304_and_a_change_is_200(self):
        first = self.c.get("/api/meetings")
        self.assertEqual(first.status_code, 200)
        etag = first.headers.get("etag")
        self.assertTrue(etag)
        self.assertTrue(any(m["id"] == self.mid for m in first.json()))
        same = self.c.get("/api/meetings", headers={"If-None-Match": etag})
        self.assertEqual(same.status_code, 304)
        self.assertEqual(same.content, b"")
        update_meeting_fields(self.mid, title="Планёрка, итоги")
        changed = self.c.get("/api/meetings", headers={"If-None-Match": etag})
        self.assertEqual(changed.status_code, 200)
        self.assertNotEqual(changed.headers.get("etag"), etag)
        self.assertTrue(any(m["title"] == "Планёрка, итоги" for m in changed.json()))

    def test_without_a_matching_tag_it_is_the_full_list(self):
        etag = self.c.get("/api/meetings").headers["etag"]
        self.assertEqual(self.c.get("/api/meetings").status_code, 200)
        self.assertEqual(self.c.get("/api/meetings", headers={"If-None-Match": '"other"'}).status_code, 200)
        self.assertEqual(self.c.get("/api/meetings", headers={"If-None-Match": f'"x", {etag}'}).status_code, 304)


if __name__ == "__main__":
    unittest.main()
