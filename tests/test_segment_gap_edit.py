"""An edit of a line after a gap in the stored places of a transcript (found in an audit): a transcript moved from
an older version's JSON skipped its empty entries, so its rows were at places 0, 1, 3…; the edit of the third line
updated the row at place 2, which did not exist, and was lost without a word."""

import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import json
import unittest

from app.database import _db_lock, create_meeting, edit_meeting, get_connection, get_meeting, init_db


class SegmentGapEditTest(unittest.TestCase):
    def test_the_edit_after_the_gap_is_kept(self):
        init_db()
        mid = create_meeting("Старая расшифровка", "a.m4a", "/nonexistent/a.m4a")["id"]
        lines = [{"id": i, "start": i * 2.0, "end": i * 2.0 + 1, "speaker": "S1", "text": f"Фраза {i}"} for i in range(4)]
        with _db_lock:
            conn = get_connection()
            for pos, seg in zip((0, 1, 3, 4), lines):  # the place 2 was a null entry of the old JSON
                conn.execute("INSERT INTO segments (meeting_id, pos, data) VALUES (?, ?, ?)",
                             (mid, pos, json.dumps(seg, ensure_ascii=False)))
            conn.execute("UPDATE meetings SET has_transcript = 1 WHERE id = ?", (mid,))
            conn.commit()
            conn.close()

        def fix(m):
            m["segments"][2]["text"] = "Исправленная фраза"
            return ["segments"]

        edit_meeting(mid, fix)
        self.assertEqual([s["text"] for s in get_meeting(mid)["segments"]], ["Фраза 0", "Фраза 1", "Исправленная фраза", "Фраза 3"])

        def fix_last(m):
            m["segments"][3]["text"] = "Последняя"
            return ["segments"]

        edit_meeting(mid, fix_last)  # the places are in order now: one row written
        self.assertEqual(get_meeting(mid)["segments"][3]["text"], "Последняя")


if __name__ == "__main__":
    unittest.main()
