"""Which Teams meeting is open (app/meeting_watch.py): a new meeting means a new recording."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest
from unittest import mock

from app import meeting_watch as mw


class MeetingTitleTest(unittest.TestCase):
    def test_the_meeting_and_not_the_sections_of_the_main_window(self):
        self.assertEqual(mw.meeting_title(["Чат | Анна Петрова | Microsoft Teams", "Планёрка дизайна | Microsoft Teams"]),
                         "Планёрка дизайна")
        self.assertEqual(mw.meeting_title(["Meeting with Anna | Microsoft Teams (work or school)"]), "Meeting with Anna")
        for none in (["Календарь | Microsoft Teams"], ["Microsoft Teams"], ["Activity | Microsoft Teams"], [], [""]):
            self.assertEqual(mw.meeting_title(none), "")

    def test_a_window_without_the_leave_button_is_not_a_meeting(self):
        # the main window with a channel open has a title like a meeting's: the leave button decides
        wins = [(1, "Общий | Дизайн | Microsoft Teams"), (2, "Планёрка | Microsoft Teams")]
        mw._HAS_LEAVE.clear()
        with mock.patch.object(mw, "teams_windows", return_value=wins), \
                mock.patch.object(mw, "_has_leave_button", side_effect=lambda h: h == 2):
            self.assertEqual(mw.current()["title"], "Планёрка")
        mw._HAS_LEAVE.clear()
        with mock.patch.object(mw, "teams_windows", return_value=wins[:1]), \
                mock.patch.object(mw, "_has_leave_button", return_value=False):
            self.assertEqual(mw.current()["title"], "")
        mw._HAS_LEAVE.clear()
        with mock.patch.object(mw, "teams_windows", return_value=wins[1:]), \
                mock.patch.object(mw, "_has_leave_button", return_value=None):  # no UI Automation: the title decides
            self.assertEqual(mw.current()["title"], "Планёрка")


if __name__ == "__main__":
    unittest.main()
