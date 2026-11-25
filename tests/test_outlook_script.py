"""The PowerShell that reads classic Outlook's calendar (app/calendar_outlook._SCRIPT), checked as text: the run
itself needs Outlook on Windows (docs/pc-session-audit.md)."""

import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest

from app import calendar_outlook


class OutlookScriptTest(unittest.TestCase):
    def test_sorted_before_the_recurrences_are_included(self):
        # Outlook's documentation: Sort('[Start]') first, then IncludeRecurrences (found in an audit)
        s = calendar_outlook._SCRIPT
        self.assertLess(s.index("$items.Sort('[Start]')"), s.index("$items.IncludeRecurrences = $true"))
        self.assertLess(s.index("$items.IncludeRecurrences = $true"), s.index("$items.Restrict("))

    def test_one_appointment_that_cannot_be_read_is_left_out(self):
        s = calendar_outlook._SCRIPT
        loop = s[s.index("foreach ($a in $found) {"):s.index("ConvertTo-Json")]
        self.assertLess(loop.index("try {"), loop.index("$a.AllDayEvent"))
        self.assertIn("} catch { continue }", loop)


if __name__ == "__main__":
    unittest.main()
