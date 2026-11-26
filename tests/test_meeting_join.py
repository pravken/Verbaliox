"""«Подключиться»: a link of the invitation opens the call; the Teams app gets only a Teams link (app/meeting_join.py)."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest
from unittest import mock

from app import meeting_join


class MeetingJoinTest(unittest.TestCase):
    def test_the_service_is_told_by_the_host(self):
        self.assertEqual(meeting_join.service("https://zoom.us/j/123456?x=teams.microsoft.com/injected"), "Zoom")
        self.assertEqual(meeting_join.service("https://TEAMS.MICROSOFT.COM/l/meetup-join/abc"), "Teams")
        self.assertEqual(meeting_join.service("https://acme.webex.com/meet/x"), "Webex")
        self.assertEqual(meeting_join.service("https://evil.example/zoom.us/j/1"), "")

    def test_only_a_teams_link_goes_to_the_teams_app(self):
        with mock.patch.object(meeting_join, "_teams_app", return_value=True):
            # found in the audit: «teams.microsoft.com» in a Zoom link's query made «msteams:/injected»
            zoom = "https://zoom.us/j/123456?x=teams.microsoft.com/injected"
            self.assertEqual(meeting_join.launch_target(zoom), zoom)
            # and the host in capitals raised (HTTP 500)
            self.assertEqual(meeting_join.launch_target("https://TEAMS.MICROSOFT.COM/l/meetup-join/abc?context=1"),
                             "msteams:/l/meetup-join/abc?context=1")
            self.assertEqual(meeting_join.launch_target("https://teams.microsoft.com/meet/123?p=x"), "msteams:/meet/123?p=x")
        with mock.patch.object(meeting_join, "_teams_app", return_value=False):
            link = "https://teams.microsoft.com/l/meetup-join/abc"
            self.assertEqual(meeting_join.launch_target(link), link)


if __name__ == "__main__":
    unittest.main()
