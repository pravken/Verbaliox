"""A recording deleted while it was transcribed or analysed (found in an audit): the transcript, the tasks and the
feature suggestions the work finds after the delete are not written (they stayed in the search and in «Задачи»)."""

import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest
from unittest import mock

from app import commitments, features
from app.database import _db_lock, create_meeting, delete_meeting, get_connection, init_db, save_meeting_results

SEGMENTS = [{"id": 0, "start": 0, "end": 5, "speaker": "S1", "text": "В четверг проведём обход этажа"}]


def _count(sql, mid):
    with _db_lock:
        conn = get_connection()
        try:
            return conn.execute(sql, (mid,)).fetchone()[0]
        finally:
            conn.close()


class DeletedWhileAnalysedTest(unittest.TestCase):
    def setUp(self):
        init_db()
        self.mid = create_meeting("Удаляемая встреча", "a.m4a", "/nonexistent/a.m4a")["id"]

    def test_the_transcript(self):
        delete_meeting(self.mid)
        save_meeting_results(self.mid, speakers={"S1": {"name": "Ольга"}}, segments=SEGMENTS)
        self.assertEqual(_count("SELECT COUNT(*) FROM segments WHERE meeting_id = ?", self.mid), 0)
        self.assertEqual(_count("SELECT COUNT(*) FROM segments_fts_rows WHERE meeting_id = ?", self.mid), 0)

    def test_the_tasks(self):
        save_meeting_results(self.mid, speakers={"S1": {"name": "Ольга"}}, segments=SEGMENTS)
        llm = mock.Mock(max_chars=100000)

        def answer(*_a, **_k):
            delete_meeting(self.mid)  # deleted while the model answers
            return ('{"who": "Ольга", "what": "провести обход этажа", "due": "в четверг", "time": "00:00", '
                    '"quote": "В четверг проведём обход этажа"}')

        llm.chat.side_effect = answer
        with mock.patch("app.llm.target", return_value=llm), \
                mock.patch.object(commitments, "verify", side_effect=lambda items, m, llm: items):
            self.assertEqual(commitments.extract(self.mid), [])
        self.assertEqual(_count("SELECT COUNT(*) FROM commitments WHERE meeting_id = ?", self.mid), 0)

    def test_the_feature_suggestions(self):
        f = features.create_feature("Обход", "#4C7FD9")
        delete_meeting(self.mid)
        self.assertEqual(features._keep_suggestions(self.mid, [f["id"]]), [])
        self.assertEqual(_count("SELECT COUNT(*) FROM feature_suggestions WHERE meeting_id = ?", self.mid), 0)


if __name__ == "__main__":
    unittest.main()
