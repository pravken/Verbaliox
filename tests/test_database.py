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


class SchemaOnceTest(unittest.TestCase):
    """Audit В20: the tables of the features, the series and the minutes worked were made (CREATE TABLE, PRAGMA,
    commit) before every reading; the recordings had no index for what is looked up among them; a connection
    stayed open when a recording's row failed to read."""

    def _sql(self, module, fn):
        from unittest import mock

        from app import database

        seen = []
        real = database.get_connection

        def watched():
            c = real()
            c.set_trace_callback(seen.append)
            return c
        with mock.patch.object(module, "get_connection", side_effect=watched):
            fn()
        return seen

    def test_tables_are_made_once_per_database(self):
        from datetime import date

        from app import database, features, series, worktime

        database.init_db()
        for module, fn in ((features, features.feature_map), (series, series.list_series),
                           (database, lambda: worktime.days(date(2026, 11, 1), date(2026, 11, 3)))):
            fn()
            again = [s for s in self._sql(module, fn) if "CREATE" in s.upper() or "PRAGMA TABLE_INFO" in s.upper()]
            self.assertEqual(again, [], module.__name__)
        database.init_db()  # a database opened again (a restored backup): made again
        self.assertTrue([s for s in self._sql(features, features.feature_map) if "CREATE" in s.upper()])

    def test_the_lookups_of_the_recordings_use_an_index(self):
        from app import database

        database.init_db()
        conn = database.get_connection()
        try:
            for sql in ("SELECT 1 FROM meetings WHERE status = 'downloading' LIMIT 1", "SELECT id FROM meetings WHERE folder_id = 1",
                        "SELECT id FROM meetings WHERE series_id = 1", "SELECT 1 FROM meetings WHERE media_path = 'a.wav'",
                        "SELECT meeting_id FROM meeting_features WHERE feature_id = 1"):
                plan = " ".join(str(r[-1]) for r in conn.execute("EXPLAIN QUERY PLAN " + sql))
                self.assertIn("SEARCH", plan.upper(), f"{sql}: {plan}")
        finally:
            conn.close()

    def test_a_row_that_fails_to_read_closes_its_connection(self):
        from unittest import mock

        from app import database

        database.init_db()
        m = database.create_meeting(title="Сбой", filename="x.wav", media_path="x.wav")
        opened = []
        real = database.get_connection
        with mock.patch.object(database, "get_connection", side_effect=lambda: opened.append(real()) or opened[-1]), \
                mock.patch.object(database, "_deserialize_meeting", side_effect=ValueError("damaged")):
            with self.assertRaises(ValueError):
                database.get_meeting(m["id"])
        import sqlite3
        with self.assertRaises(sqlite3.ProgrammingError):  # closed
            opened[0].execute("SELECT 1")
