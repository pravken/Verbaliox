"""«Выгрузить всё» stops an overview or an answer asked on the page (app/ollama_client.py): it is a
plain request, not a queued job, and the model came back for its next part."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import threading
import time
import unittest
from unittest import mock

try:
    from app import cancel_scope, ollama_client
except ImportError:  # app dependencies are not installed (e.g. in the release CI job)
    ollama_client = None


class _SlowClient:
    """httpx.Client whose answer takes `delay` seconds."""
    delay = 3.0

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, *a, **k):
        time.sleep(self.delay)
        return mock.Mock(status_code=200, json=lambda: {"message": {"content": "ответ"}})


@unittest.skipIf(ollama_client is None, "app dependencies not installed")
class AnalysisStopTest(unittest.TestCase):
    def setUp(self):
        from app.database import init_db

        init_db()  # the request reads the settings (how long the model stays)
        with ollama_client._analysis_lock:  # nothing left from another test's requests
            ollama_client._analysis.clear()
            ollama_client._analysis_ended.clear()

    def _chat(self, box):
        try:
            box["value"] = ollama_client._ollama_chat("http://127.0.0.1:1", "qwen3:8b", "s", "u")
        except Exception as e:
            box["error"] = e

    def test_an_answer_being_written_is_known_and_stopped(self):
        box = {}
        with mock.patch.object(ollama_client.httpx, "Client", _SlowClient), \
                mock.patch.object(ollama_client, "raise_for_ollama"), \
                mock.patch("app.vram.ollama_release_others", return_value=[]), \
                mock.patch("app.vram.release_idle_speech_models", return_value=[]), \
                mock.patch("app.vram.ollama_unload", return_value=[]) as unload:
            th = threading.Thread(target=self._chat, args=(box,))
            th.start()
            time.sleep(0.5)
            self.assertEqual(ollama_client.analysis_running(), ["qwen3:8b"])
            started = time.time()
            self.assertEqual(ollama_client.stop_analysis(), 1)
            th.join(5)
            self.assertLess(time.time() - started, 1.5)  # not after the answer
            self.assertIsInstance(box.get("error"), cancel_scope.Aborted)
            time.sleep(0.3)
            unload.assert_called()  # Ollama stops writing it
        self.assertEqual(ollama_client.analysis_running(), [])

    def test_a_next_part_right_after_a_stop_ends_too_but_a_later_request_does_not(self):
        _SlowClient.delay = 0.05
        try:
            with mock.patch.object(ollama_client.httpx, "Client", _SlowClient), \
                    mock.patch.object(ollama_client, "raise_for_ollama"), \
                    mock.patch("app.vram.ollama_release_others", return_value=[]), \
                    mock.patch("app.vram.release_idle_speech_models", return_value=[]), \
                    mock.patch("app.vram.ollama_unload", return_value=[]), \
                    mock.patch.object(ollama_client, "ANALYSIS_LINGER_SEC", 0.5):
                box = {}

                def overview():
                    self._chat(box)  # one part done
                    ollama_client.stop_analysis()  # «Выгрузить всё» between two parts
                    self._chat(box)  # the next part
                    box["second"] = box.pop("error", None)
                    time.sleep(0.7)
                    box.pop("value", None)
                    self._chat(box)  # a new request on the same pooled thread, later

                th = threading.Thread(target=overview)
                th.start()
                th.join(5)
                self.assertIsInstance(box["second"], cancel_scope.Aborted)
                self.assertEqual(box.get("value"), "ответ")
                self.assertNotIn("error", box)
        finally:
            _SlowClient.delay = 3.0


if __name__ == "__main__":
    unittest.main()
