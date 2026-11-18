import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import json
import unittest
from datetime import datetime, timedelta
from unittest import mock

from app.database import create_meeting, get_meeting, init_db, update_meeting_fields, update_settings

try:
    from app import calendar_ics, calendar_match
except ImportError:  # the release CI runs without the app's packages
    calendar_ics = calendar_match = None

EVENT = {"title": "Синк по релизу", "attendees": ["Анна Смирнова", "boris.petrov@example.com", "Я Сам"],
         "online": True, "all_day": False}


@unittest.skipIf(calendar_match is None, "app dependencies not installed")
class CalendarMatchTest(unittest.TestCase):
    """Reported by the user: a person called them directly during a meeting in the calendar, and the
    recording got the meeting's name. The people heard and the title must agree with the event."""

    def setUp(self):
        init_db()
        update_settings({"my_name": "Я Сам"})

    def tearDown(self):
        update_settings({"my_name": ""})

    def test_the_verdict(self):
        v = calendar_match.verdict
        self.assertEqual(v(EVENT, names=["Борис Петров"]), "yes")  # an invitee heard (Latin e-mail, Cyrillic name)
        self.assertEqual(v(EVENT, names=["Smirnova Anna"]), "yes")
        self.assertEqual(v(EVENT, names=["Олег Кузнецов", "Я Сам"]), "no")  # someone else called
        self.assertEqual(v(EVENT, title="Синк по релизу"), "yes")  # the Teams meeting window
        self.assertEqual(v(EVENT, title="Олег Кузнецов"), "no")  # a call window of another person
        self.assertEqual(v(EVENT, call_app="telegram"), "no")  # a meeting with a link is not a Telegram call
        self.assertEqual(v(EVENT, title="Запись"), "unknown")  # nothing to tell by yet
        self.assertEqual(calendar_match.call_title(["Олег Кузнецов", "Я Сам", "Участник 2"]), "Звонок: Олег Кузнецов")

    def _recording(self):
        return create_meeting(title="Запись", filename="a.wav", media_path="", title_is_default=True)["id"]

    def test_a_call_meanwhile_keeps_out_of_the_meeting(self):
        mid = self._recording()
        with mock.patch.object(calendar_ics, "_source", return_value="x"), \
                mock.patch.object(calendar_ics, "current_meeting", return_value=EVENT):
            calendar_ics.apply_to_recording(mid, datetime.now(), title="Запись", names=["Олег Кузнецов"], call_app="telegram")
        m = get_meeting(mid)
        self.assertEqual(m["title"], "Звонок: Олег Кузнецов")
        self.assertNotIn("Участники по календарю", m.get("user_notes") or "")

    def test_unknown_at_first_then_the_voices_decide(self):
        for names, kept in ((["Анна Смирнова"], True), (["Олег Кузнецов"], False)):
            mid = self._recording()
            with mock.patch.object(calendar_ics, "_source", return_value="x"), \
                    mock.patch.object(calendar_ics, "current_meeting", return_value=EVENT):
                calendar_ics.apply_to_recording(mid, datetime.now(), title="Запись")
            m = get_meeting(mid)
            self.assertEqual(m["title"], "Синк по релизу")  # for now
            self.assertIn("Участники по календарю", m["user_notes"])
            calendar_match.recheck(mid, {"S0": {"name": names[0]}, "S1": {"name": "Участник 2"}})
            m = get_meeting(mid)
            self.assertEqual(m["title"] == "Синк по релизу", kept)
            self.assertEqual("Участники по календарю" in (m.get("user_notes") or ""), kept)
            self.assertTrue(json.loads(m["calendar_json"])["sure"])
            if not kept:
                self.assertEqual(m["title"], "Звонок: Олег Кузнецов")


if __name__ == "__main__":
    unittest.main()
