"""Ollama when the app closes (app/ollama_client.py, app/shutdown.py): the `ollama serve` the app started ends
with it; an Ollama the user started stays, without the models the app loaded."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest
from unittest import mock

try:
    from app import ollama_client, shutdown
    from app.database import init_db
except ImportError:  # app dependencies are not installed
    ollama_client = None


@unittest.skipIf(ollama_client is None, "app dependencies not installed")
class OllamaOnExitTest(unittest.TestCase):
    def setUp(self):
        init_db()
        self.addCleanup(setattr, ollama_client, "_started_serve", None)

    def test_the_serve_the_app_started_ends_with_it(self):
        proc = mock.Mock()
        opened = iter([False, True])
        with mock.patch.object(ollama_client, "_is_ollama_port_open", side_effect=lambda *a: next(opened)), \
                mock.patch.object(ollama_client, "find_ollama_executable", return_value="ollama.exe"), \
                mock.patch.object(ollama_client.subprocess, "Popen", return_value=proc), \
                mock.patch.object(ollama_client.time, "sleep"), \
                mock.patch.object(shutdown, "_bind_to_app"):
            self.assertTrue(ollama_client.ensure_ollama_running())
        self.assertIn(proc, list(shutdown._procs))  # ended by stop_all with its runners
        proc.poll.return_value = None
        with mock.patch.object(ollama_client.httpx, "Client") as client:
            self.assertEqual(ollama_client.release_on_exit(), [])  # ours: nothing to ask, it ends
        client.assert_not_called()
        shutdown._procs.discard(proc)

    def test_the_users_ollama_stays_but_lets_go_of_the_models(self):
        sent = []

        class Client:
            def __init__(self, *a, **k):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def get(self, url):
                return mock.Mock(json=lambda: {"models": [{"name": "gemma4:e4b"}]})

            def post(self, url, json=None):
                sent.append(json)

        with mock.patch.object(ollama_client, "_is_ollama_port_open", return_value=True), \
                mock.patch.object(ollama_client.httpx, "Client", Client):
            self.assertEqual(ollama_client.release_on_exit(), ["gemma4:e4b"])
        self.assertEqual(sent, [{"model": "gemma4:e4b", "keep_alive": 0}])


if __name__ == "__main__":
    unittest.main()
