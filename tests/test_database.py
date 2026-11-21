"""The list of recordings: what its flags say."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest
class FailedAnalysisTest(unittest.TestCase):
    """Found by the user: an analysis that failed (Ollama not started) kept only its error, and the strip said
    «Итоги готовы» with «Открыть итоги» over an empty analysis."""

    def test_an_error_alone_is_no_results(self):
        from app import database

        database.init_db()
        m = database.create_meeting(title="Сбой анализа", filename="x.wav", media_path="x.wav")
        database.merge_summaries(m["id"], {"error": "Ollama не запущена"})
        row = next(x for x in database.list_meetings() if x["id"] == m["id"])
        self.assertFalse(row["has_summary"])
        database.merge_summaries(m["id"], {"tldr": "- Коротко"})
        row = next(x for x in database.list_meetings() if x["id"] == m["id"])
        self.assertTrue(row["has_summary"])
