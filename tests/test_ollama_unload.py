"""Unloading an Ollama model with the video card busy (app/vram.py ollama_unload)."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest
from unittest import mock

try:
    from app import vram
except ImportError:  # app dependencies are not installed (e.g. in the release CI job)
    vram = None


@unittest.skipIf(vram is None, "app dependencies not installed")
class OllamaUnloadTest(unittest.TestCase):
    def setUp(self):
        from app.database import init_db

        init_db()

    def test_no_answer_from_a_busy_ollama_is_not_taken_for_gone(self):
        # /api/ps does not answer (None) and then says the model is still there: it is not reported unloaded
        import itertools

        answers = itertools.chain([None, None], itertools.repeat([{"name": "qwen3:8b"}]))
        with mock.patch.object(vram, "_ollama_ps", side_effect=lambda timeout=0.8: next(answers)), \
                mock.patch.object(vram.httpx, "Client"), mock.patch("time.sleep"), \
                mock.patch.object(vram, "OLLAMA_UNLOAD_WAIT_SEC", 0.01), mock.patch.object(vram, "OLLAMA_AFTER_STOP_SEC", 0.01), \
                mock.patch.object(vram, "_stop_ollama_runners") as stop, mock.patch.object(vram, "_retry_unload_later") as retry, \
                mock.patch("app.ollama_client._ollama_address", return_value=("127.0.0.1", 11434)):
            left = vram.ollama_unload(["qwen3:8b"])
        self.assertEqual(left, ["qwen3:8b"])
        stop.assert_called_once()           # its runner was stopped
        retry.assert_called_once_with(["qwen3:8b"])  # and it is tried again once the card is free

    def test_the_weight_files_learnt_before_are_used_under_load(self):
        vram._BLOBS["qwen3:8b"] = ["sha256-abc123abc123"]
        try:
            with mock.patch.object(vram.httpx, "Client") as client:
                self.assertEqual(vram._model_blobs(["qwen3:8b"]), ["sha256-abc123abc123"])
                client.return_value.__enter__.return_value.post.assert_not_called()  # Ollama not asked
        finally:
            vram._BLOBS.pop("qwen3:8b", None)

    def test_a_model_left_loaded_is_unloaded_by_the_retry_later(self):
        """«Выгрузить всё» with Ollama busy: the retry in the background stops the runner of a model still
        there (a NameError there kept a 6 GB model on the card while Whisper loaded)."""
        threads = []
        with mock.patch("threading.Thread", side_effect=lambda target, **kw: threads.append(target) or mock.Mock()), \
                mock.patch("time.sleep"), mock.patch.object(vram, "RETRY_FOR_SEC", 60.0), \
                mock.patch("app.ollama_client.analysis_running", return_value=[]), \
                mock.patch.object(vram, "ollama_unload", side_effect=[["gemma4:e4b"], []]) as unload, \
                mock.patch.object(vram, "_stop_ollama_runners") as stop, \
                mock.patch("app.ollama_client._ollama_address", return_value=("127.0.0.1", 11434)), \
                mock.patch("traceback.print_exc") as tb:
            vram._retrying.pop("gemma4:e4b", None)
            vram._retry_unload_later(["gemma4:e4b"])
            self.assertEqual(len(threads), 1)
            threads[0]()  # the thread's body, here
        tb.assert_not_called()  # no error in the loop
        self.assertEqual(unload.call_count, 2)
        stop.assert_called_once_with(["gemma4:e4b"])


if __name__ == "__main__":
    unittest.main()
