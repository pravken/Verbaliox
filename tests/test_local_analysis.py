"""Analysis runs on the local Ollama only: what the cloud models of earlier versions left in the database
(the API keys, the log of requests, their settings) is deleted, and a stored cloud choice is not followed."""

import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest
from unittest import mock

from app import database as db

try:
    from app import llm
except ImportError:
    llm = None
needs_deps = unittest.skipIf(llm is None, "app dependencies not installed")

OLD_SETTINGS = {"llm_provider": "cloud", "llm_cloud_consent": "true", "llm_cloud_provider": "anthropic",
                "llm_model_anthropic": "some-model", "llm_base_url_openai_compat": "https://example.org/v1",
                "dictation_translate_cloud": "true"}


def _tables() -> set:
    with db._db_lock:
        conn = db.get_connection()
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        conn.close()
    return names


def _leave_cloud_data() -> None:
    """A database of an earlier version: an encrypted API key, the log of cloud requests, the cloud settings."""
    with db._db_lock:
        conn = db.get_connection()
        conn.execute("CREATE TABLE IF NOT EXISTS secrets (name TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)")
        conn.execute("INSERT OR REPLACE INTO secrets VALUES ('llm_key_anthropic', 'plain:sk-test', '2026-01-01 10:00:00')")
        conn.execute("CREATE TABLE IF NOT EXISTS cloud_log (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, "
                     "provider TEXT NOT NULL, model TEXT NOT NULL, chars INTEGER NOT NULL, tokens INTEGER NOT NULL, purpose TEXT NOT NULL)")
        conn.execute("INSERT INTO cloud_log (at, provider, model, chars, tokens, purpose) VALUES ('2026-01-01', 'anthropic', 'm', 1, 1, 'x')")
        conn.executemany("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", OLD_SETTINGS.items())
        conn.commit()
        conn.close()
    db.forget_settings()


class CloudLeftoversTest(unittest.TestCase):
    def test_keys_log_and_settings_are_deleted_at_start(self):
        db.init_db()
        _leave_cloud_data()
        self.assertIn("secrets", _tables())
        db.init_db()  # the next start
        self.assertNotIn("secrets", _tables())
        self.assertNotIn("cloud_log", _tables())
        settings = db.get_all_settings()
        for key in OLD_SETTINGS:
            self.assertNotIn(key, settings)
        self.assertEqual([k for k in settings if k.startswith("llm_")], [])

    def test_a_recording_marked_local_only_by_an_earlier_version_reads_as_usual(self):
        db.init_db()
        mid = db.create_meeting("Встреча", "a.wav", "/tmp/a.wav")["id"]
        self.addCleanup(db.delete_meeting, mid)
        with db._db_lock:
            conn = db.get_connection()
            conn.execute("UPDATE meetings SET local_only = 1 WHERE id = ?", (mid,))
            conn.commit()
            conn.close()
        self.assertNotIn("local_only", db.get_meeting(mid))
        self.assertEqual(db.get_meeting(mid)["title"], "Встреча")


@needs_deps
class OllamaOnlyTest(unittest.TestCase):
    def test_analysis_uses_ollama_whatever_was_stored(self):
        db.init_db()
        _leave_cloud_data()  # read before the next start cleans it: still Ollama
        status = {"running": True, "models": ["qwen3:8b"], "chat_models": ["qwen3:8b"]}
        with mock.patch("app.ollama_client.ensure_ollama_running"), \
                mock.patch("app.ollama_client.get_ollama_status", return_value=status), \
                mock.patch("app.ollama_client._ollama_chat", return_value="ok") as chat:
            for asked in (None, "cloud"):
                tgt = llm.target(asked)
                self.assertEqual(tgt.provider, "ollama")
                self.assertEqual(tgt.model, "qwen3:8b")
                self.assertEqual(tgt.chat("s", "u"), "ok")
        self.assertEqual(chat.call_count, 2)
        db.init_db()

    def test_the_settings_endpoint_does_not_store_cloud_settings(self):
        try:
            from app.api.system import SettingsUpdatePayload, api_update_settings
        except ImportError:
            self.skipTest("app dependencies not installed")
        db.init_db()
        api_update_settings(SettingsUpdatePayload(settings={**OLD_SETTINGS, "llm_key_openai": "sk-x", "auto_title": "true"}))
        settings = db.get_all_settings()
        self.assertEqual(settings.get("auto_title"), "true")
        for key in (*OLD_SETTINGS, "llm_key_openai"):
            self.assertNotIn(key, settings)

    def test_the_cloud_routes_are_gone(self):
        try:
            from app import main  # noqa: F401 - the routers are made with the app
            from app.api import analysis, assistant, export, home, library, media, recording, system, tasks
        except ImportError:
            self.skipTest("app dependencies not installed")
        paths = {getattr(r, "path", "") for part in (analysis, assistant, export, home, library, media, recording, system, tasks)
                 for r in part.router.routes}
        self.assertIn("/api/open-url", paths)
        for gone in ("/api/llm/status", "/api/llm/key", "/api/llm/test/{provider}", "/api/privacy/cloud-log",
                     "/api/meetings/{meeting_id}/local-only", "/api/meetings/{meeting_id}/llm-estimate"):
            self.assertNotIn(gone, paths)


if __name__ == "__main__":
    unittest.main()
