"""Search by meaning: Ollama not answering for a moment (restarted, a timeout) is no fault of a recording (found
in an audit): every recording of the library was put aside for the rest of the run and never indexed."""

import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest
from unittest import mock

import httpx

from app import semantic


class _Stop(BaseException):
    pass


class _Wake:
    def __init__(self):
        self.calls = 0

    def wait(self, _timeout=None):
        self.calls += 1
        if self.calls > 1:
            raise _Stop()
        return True

    def clear(self):
        pass


class OllamaDownTest(unittest.TestCase):
    def _round(self, error):
        with mock.patch.object(semantic, "_wake", _Wake()), mock.patch.object(semantic, "_skip", set()) as skip, \
                mock.patch.object(semantic, "enabled", return_value=True), \
                mock.patch.object(semantic, "_ollama_up", return_value=True), \
                mock.patch.object(semantic, "_gpu_busy", return_value=False), \
                mock.patch.object(semantic, "get_all_settings", return_value={}), \
                mock.patch.object(semantic, "pending_ids", return_value=[7, 8]), \
                mock.patch.object(semantic, "index_meeting", side_effect=error) as index, \
                mock.patch.dict(semantic._state, {"error": ""}), mock.patch("traceback.print_exc"):
            with self.assertRaises(_Stop):
                semantic._run()
            return set(skip), index.call_count, semantic._state["error"]

    def test_a_timeout_puts_no_recording_aside(self):
        skipped, tried, error = self._round(httpx.ReadTimeout("timed out"))
        self.assertEqual(skipped, set())
        self.assertEqual(tried, 1)  # the round stops: the others are not asked of a service that is down
        self.assertIn("timed out", error)

    def test_a_refused_connection_puts_no_recording_aside(self):
        self.assertEqual(self._round(httpx.ConnectError("refused"))[0], set())

    def test_a_recording_that_fails_by_itself_is_put_aside(self):
        skipped, tried, _ = self._round(ValueError("bad text"))
        self.assertEqual(skipped, {7, 8})
        self.assertEqual(tried, 2)


if __name__ == "__main__":
    unittest.main()
