"""The tasks' exports and the series' prompts (found in an audit): a task added or given a date by hand keeps its
date; the Todoist CSV cells are written as text (a task said in a meeting starting with «=» ran as a formula in
Excel); a task past the first hour of a recording is checked at its moment, not at its minutes modulo 100."""

import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import csv
import io
import unittest
from unittest import mock

from app import commitments

MANUAL = {"who": "Ольга", "to_whom": "", "what": "подготовить отчёт", "due": "", "due_date": "2026-12-01",
          "status": "open", "meeting_title": "Планёрка", "meeting_date": "2026-11-20"}
SAID = {"who": "=HYPERLINK(\"http://example.invalid\")", "to_whom": "", "what": "=1+1", "due": "к пятнице",
        "due_date": "", "status": "open", "meeting_title": "+Встреча", "meeting_date": "2026-11-20"}


class TasksExportTest(unittest.TestCase):
    def test_a_date_set_by_hand_is_exported(self):
        self.assertIn("📅 2026-12-01", commitments.export_text([MANUAL], "md"))
        self.assertIn("(2026-12-01)", commitments.as_text([MANUAL]))
        rows = list(csv.reader(io.StringIO(commitments.export_text([MANUAL], "csv"))))
        self.assertEqual(rows[1][3], "2026-12-01")
        rows = list(csv.reader(io.StringIO(commitments.export_text([MANUAL], "todoist"))))
        self.assertEqual(rows[1][7], "2026-12-01")
        self.assertIn("(к пятнице)", commitments.as_text([SAID]))  # the words, when there is no date

    def test_todoist_cells_are_text(self):
        rows = list(csv.reader(io.StringIO(commitments.export_text([SAID], "todoist"))))
        self.assertTrue(rows[1][1].startswith("'="))
        self.assertTrue(rows[1][2].startswith("'+"))

    def test_a_task_past_the_first_hour_is_checked_at_its_moment(self):
        seen = []

        def ground(md, segments, speakers):
            seen.append(md)
            return md

        with mock.patch("app.grounding.ground_summary", side_effect=ground):
            commitments.supported({"who": "Ольга", "what": "отчёт", "at": 6330.0}, {"segments": [{"text": "x"}]})
        self.assertIn("[1:45:30]", seen[0])


if __name__ == "__main__":
    unittest.main()
