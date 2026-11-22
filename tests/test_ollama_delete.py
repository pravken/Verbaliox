"""The trash of an Ollama model (Settings → ИИ-анализ). Reported by the user: a model that was no longer in
the list showed «Ollama не запущена — запустите её, чтобы удалить модель». The program stops Ollama when it
is idle and then lists the models from its folder, so the trash is pressed with Ollama stopped: it is
started for the deletion, and a model Ollama does not have counts as deleted."""

import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest
from unittest import mock

try:
    from app import ollama_client
except ImportError:
    ollama_client = None


class _Resp:
    def __init__(self, status: int, data=None):
        self.status_code = status
        self._data = data or {}
        self.text = ""

    def json(self):
        return self._data

    def read(self):
        return b""


class _Client:
    """httpx.Client for /api/tags and /api/delete; records what was deleted."""

    def __init__(self, listed, delete_status=200):
        self.listed, self.delete_status, self.deleted = listed, delete_status, []

    def __call__(self, *a, **k):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, **k):
        return _Resp(200, {"models": [{"name": n} for n in self.listed]})

    def request(self, method, url, json=None, **k):
        self.deleted.append(json["model"])
        return _Resp(self.delete_status, {"error": "model not found"})


@unittest.skipIf(ollama_client is None, "app dependencies not installed")
class DeleteOllamaModelTest(unittest.TestCase):
    def setUp(self):
        from app.database import init_db

        init_db()

    def _delete(self, name, client, running=True, on_disk=()):
        with mock.patch.object(ollama_client, "ensure_ollama_running", return_value=running) as start, \
                mock.patch.object(ollama_client, "models_on_disk", return_value=list(on_disk)), \
                mock.patch.object(ollama_client.httpx, "Client", client):
            ollama_client.delete_ollama_model(name)
        return start

    def test_a_stopped_ollama_is_started_to_delete(self):
        client = _Client(["gemma4:e2b"])
        start = self._delete("gemma4:e2b", client)
        start.assert_called_once()
        self.assertEqual(client.deleted, ["gemma4:e2b"])

    def test_the_installed_variant_of_the_tag_is_deleted(self):
        client = _Client(["gemma4:e4b-it-q4_K_M"])
        self._delete("gemma4:e4b", client)
        self.assertEqual(client.deleted, ["gemma4:e4b-it-q4_K_M"])

    def test_with_several_variants_only_the_one_named_is_deleted(self):
        """Found in the review: the first variant listed was deleted, whichever the page named."""
        client = _Client(["gemma4:e4b-it-q4_K_M", "gemma4:e4b-it-q8_0"])
        self._delete("gemma4:e4b-it-q8_0", client)
        self.assertEqual(client.deleted, ["gemma4:e4b-it-q8_0"])
        client = _Client(["gemma4:e4b-it-q4_K_M", "gemma4:e4b-it-q8_0"])
        with self.assertRaises(RuntimeError):
            self._delete("gemma4:e4b", client)  # which one is not known: none
        self.assertEqual(client.deleted, [])

    def test_a_name_without_a_tag_is_only_its_latest(self):
        self.assertEqual(ollama_client.installed_name("qwen3", ["qwen3:8b"]), None)
        self.assertEqual(ollama_client.installed_name("qwen3", ["qwen3:8b", "qwen3:latest"]), "qwen3:latest")
        client = _Client(["qwen3:8b"])
        self._delete("qwen3", client)
        self.assertEqual(client.deleted, [])

    def test_a_model_ollama_does_not_have_is_deleted_already(self):
        client = _Client(["qwen3:8b"])
        self._delete("gemma4:e4b", client)  # no error
        self.assertEqual(client.deleted, [])

    def test_not_found_counts_as_deleted(self):
        client = _Client(["gemma4:e2b"], delete_status=404)
        self._delete("gemma4:e2b", client)  # no error
        self.assertEqual(client.deleted, ["gemma4:e2b"])

    def test_ollama_that_cannot_start(self):
        client = _Client([])
        self._delete("gemma4:e2b", client, running=False)  # nothing of it on the disk: nothing to delete
        self.assertEqual(client.deleted, [])
        with self.assertRaisesRegex(RuntimeError, "Не удалось запустить Ollama"):
            self._delete("gemma4:e2b", client, running=False, on_disk=["gemma4:e2b"])

    def test_the_catalog_names_what_the_trash_deletes(self):
        with mock.patch.object(ollama_client, "_is_ollama_port_open", return_value=False), \
                mock.patch.object(ollama_client, "find_ollama_executable", return_value=None), \
                mock.patch.object(ollama_client, "models_on_disk", return_value=["gemma4:e4b-it-q4_K_M"]):
            catalog = {m["id"]: m for m in ollama_client.get_ollama_status()["catalog"]}
        self.assertTrue(catalog["gemma4:e4b"]["installed"])
        self.assertEqual(catalog["gemma4:e4b"]["installed_as"], "gemma4:e4b-it-q4_K_M")
        self.assertFalse(catalog["gemma4:e2b"]["installed"])
        self.assertEqual(catalog["gemma4:e2b"]["installed_as"], "")


if __name__ == "__main__":
    unittest.main()
