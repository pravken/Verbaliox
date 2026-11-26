"""The unload after idle time sees a dictation and a model comparison (found in an audit): neither goes through the
queue, and the models they use were unloaded under them."""

import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest
from unittest import mock

from app import bench, dictation, idle_unload, live, transcriber


class IdleUnloadSeesTheWorkTest(unittest.TestCase):
    def _busy(self, dictation_state=None, bench_state=None):
        with mock.patch.object(transcriber, "running_job_kind", return_value=None), \
                mock.patch("app.ollama_client.analysis_running", return_value=[]), \
                mock.patch.object(live, "has_sessions", return_value=False), \
                mock.patch.dict(dictation._state, dictation_state or {"active": False, "busy": False}), \
                mock.patch.dict(bench._state, bench_state or {"running": False}):
            return idle_unload._busy()

    def test_nothing_running(self):
        self.assertFalse(self._busy())

    def test_a_dictation_spoken_or_recognized(self):
        self.assertTrue(self._busy({"active": True, "busy": False}))
        self.assertTrue(self._busy({"active": False, "busy": True}))

    def test_a_model_comparison(self):
        self.assertTrue(self._busy(bench_state={"running": True}))


if __name__ == "__main__":
    unittest.main()
