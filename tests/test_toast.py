"""The Windows toast of a meeting's start with «Подключиться» (app/toast.py)."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import base64
import sys
import unittest
from unittest import mock
from xml.dom import minidom

from app import toast


class ToastTest(unittest.TestCase):
    LINK = "msteams:/l/meetup-join/19%3ameeting_x%40thread.v2/0?context=%7b%22Tid%22%3a%22a%26b%22%7d"

    def test_the_toast_has_the_button_and_stays_and_its_text_is_escaped(self):
        xml = toast.toast_xml("Начинается — «Синк & <команда>»", "Нажмите — подключиться в Teams",
                              [("Подключиться", self.LINK)], launch=self.LINK, stay=True)
        doc = minidom.parseString(xml)  # well formed whatever the title holds
        root = doc.documentElement
        self.assertEqual(root.getAttribute("scenario"), "reminder")
        self.assertEqual(root.getAttribute("launch"), self.LINK)
        acts = doc.getElementsByTagName("action")
        self.assertEqual([a.getAttribute("content") for a in acts], ["Подключиться", "Закрыть"])
        self.assertEqual(acts[0].getAttribute("arguments"), self.LINK)
        self.assertEqual(acts[0].getAttribute("activationType"), "protocol")
        self.assertIn("Синк & <команда>", doc.getElementsByTagName("text")[0].firstChild.data)

    def test_the_script_keeps_quotes_and_the_balloon_is_used_off_windows(self):
        s = toast.script(toast.toast_xml("It's", "x", [("Go", "https://zoom.us/j/1")]))
        self.assertIn("It''s", s)  # a single quote doubled inside the PowerShell string
        self.assertIn(toast.APP_ID, s)
        if sys.platform != "win32":
            self.assertFalse(toast.show("a", "b", [("Go", "https://zoom.us/j/1")]))
        with mock.patch.object(toast.sys, "platform", "win32"), mock.patch.object(toast, "_register"), \
                mock.patch("subprocess.run") as run:
            run.return_value.returncode = 0
            self.assertTrue(toast.show("a", "b", [("Go", "https://zoom.us/j/1")]))
            args = run.call_args[0][0]
            self.assertIn("-EncodedCommand", args)
            self.assertIn("zoom.us", base64.b64decode(args[-1]).decode("utf-16-le"))


if __name__ == "__main__":
    unittest.main()
