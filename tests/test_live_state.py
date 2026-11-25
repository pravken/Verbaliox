"""The answer to each piece of audio of the live captions (about every 0.25 s) carries only what changed since the
version the page has: the new lines and those whose translation or target language arrived, not the translations
of the last 60 lines and up to 200 lines waiting for one each time."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest
from unittest import mock

from app.database import init_db

try:
    from app import live
except ImportError:  # the release CI runs without the app's packages
    live = None


def _line(i, translation=None):
    return {"id": i, "text": f"Строка {i}", "lang": "ru", "start": float(i), "end": i + 0.5, "translation": translation}


@unittest.skipIf(live is None, "app dependencies not installed")
class StateVersionTest(unittest.TestCase):
    def setUp(self):
        init_db()
        with mock.patch.object(live, "caption_onnx_model", return_value=None):
            self.s = live.LiveSession("ru", None)
        self.s.translator = mock.Mock(draft_target="", draft_translation="", ready=True, error="", _model=None)

    def test_only_what_changed_since_the_pages_version(self):
        s = self.s
        s._add_lines([_line(i) for i in range(1, 101)])
        first = s.state(version=0)
        self.assertEqual(len(first["lines"]), 100)
        v = first["version"]
        quiet = s.state(version=v)
        self.assertEqual((quiet["lines"], quiet["translations"], quiet["targets"]), ([], {}, {}))
        self.assertEqual(quiet["version"], v)
        s.lines[49]["translation"], s.lines[49]["target"] = "Line 50", "en"
        s._add_lines([_line(101)])
        got = s.state(version=v)
        self.assertEqual([ln["id"] for ln in got["lines"]], [50, 101])
        self.assertEqual(got["translations"], {50: "Line 50"})
        self.assertEqual(got["targets"], {50: "en"})
        self.assertGreater(got["version"], v)
        # the answer was lost (a failed request): the same version again gives the same changes
        self.assertEqual([ln["id"] for ln in s.state(version=v)["lines"]], [50, 101])
        self.assertEqual(s.state(version=got["version"])["lines"], [])

    def test_without_a_version_the_answer_is_as_before(self):
        s = self.s
        s._add_lines([_line(1, "One"), _line(2)])
        st = s.state(1)
        self.assertEqual([ln["id"] for ln in st["lines"]], [2])  # new, and the one waiting for its translation
        self.assertEqual(st["translations"], {1: "One"})
        self.assertIn("version", st)

    def test_the_lines_kept_are_bounded(self):
        s = self.s
        for k in range(0, live.LINES_KEPT + 1000, 100):
            s._add_lines([_line(i) for i in range(k + 1, k + 101)])
        self.assertLessEqual(len(s.lines), live.LINES_KEPT + 500)
        self.assertEqual(s.lines[-1]["id"], live.LINES_KEPT + 1000)

    def test_the_route_answers_with_a_ready_json_response(self):
        try:
            from fastapi.testclient import TestClient

            from app import main
        except ImportError:
            self.skipTest("fastapi not installed")
        s = self.s
        s._add_lines([_line(1), _line(2)])
        with live._sessions_lock:
            live._sessions[s.id] = s
        self.addCleanup(live.stop_session, s.id)
        with mock.patch.object(main, "enqueue_meeting_job"), mock.patch.object(s, "step"), \
                mock.patch("fastapi.routing.jsonable_encoder", side_effect=AssertionError("encoded on the loop")), \
                TestClient(main.app, base_url="http://127.0.0.1:8795") as c:
            c.get(f"/?token={main.SESSION_TOKEN}")
            r = c.post(f"/api/live/{s.id}/audio?since=0&v=0", content=b"\x00\x00" * 4000)
            self.assertEqual(r.status_code, 200, r.text)
            v = r.json()["version"]
            self.assertEqual([ln["id"] for ln in r.json()["lines"]], [1, 2])
            r = c.post(f"/api/live/{s.id}/audio?since=2&v={v}", content=b"\x00\x00" * 4000)
            self.assertEqual(r.json()["lines"], [])


if __name__ == "__main__":
    unittest.main()
