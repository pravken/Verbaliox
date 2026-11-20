import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest
from datetime import date

try:
    import holidays  # noqa: F401
    from app import holidays_cal
    from app.database import init_db, update_settings
except ImportError:  # the release CI runs without the app's packages
    holidays_cal = None


@unittest.skipIf(holidays_cal is None, "holidays not installed")
class HolidaysTest(unittest.TestCase):
    """Asked by the user: the public holidays of a country chosen in the settings (the app is used in several
    countries: Serbia, Lithuania, Poland, Cyprus and others) are days off (app/holidays_cal.py)."""

    def setUp(self):
        init_db()

    def tearDown(self):
        update_settings({"holiday_country": "", "holiday_subdiv": ""})

    def test_the_countries_asked_for_are_there_with_their_regions(self):
        by = {c["code"]: c for c in holidays_cal.countries()}
        for code in ("RS", "LT", "PL", "CY", "DE", "US"):
            self.assertIn(code, by)
        self.assertTrue(by["DE"]["subdivs"])
        self.assertIn({"code": "BY", "name": "Bayern"}, by["DE"]["subdivs"])
        self.assertEqual(by["US"]["name"], "United States")

    def test_none_until_a_country_is_chosen_then_its_days(self):
        span = (date(2026, 1, 1), date(2026, 1, 10))
        self.assertEqual(holidays_cal.between(*span), {})
        update_settings({"holiday_country": "RS"})
        days = holidays_cal.between(*span, lang="en")
        self.assertIn("2026-01-01", days)
        self.assertIn("2026-01-07", days)  # Orthodox Christmas
        self.assertNotIn("2026-01-10", holidays_cal.between(*span))  # the end is not included
        self.assertTrue(holidays_cal.is_holiday(date(2026, 1, 7)))
        self.assertEqual(holidays_cal.is_holiday(date(2026, 1, 8)), "")

    def test_a_region_adds_its_own_days(self):
        span = (date(2026, 1, 1), date(2026, 12, 31))
        whole = holidays_cal.between(*span, country="DE", subdiv="")
        bavaria = holidays_cal.between(*span, country="DE", subdiv="BY")
        self.assertNotIn("2026-01-06", whole)
        self.assertIn("2026-01-06", bavaria)  # Epiphany in Bavaria only

    def test_the_settings_take_only_codes(self):
        from app.settings_schema import clean

        self.assertEqual(clean("holiday_country", "lt"), "LT")
        self.assertEqual(clean("holiday_country", ""), "")
        self.assertEqual(clean("holiday_subdiv", "BY"), "BY")
        for key, bad in (("holiday_country", "Serbia"), ("holiday_subdiv", "../x")):
            with self.assertRaises(ValueError):
                clean(key, bad)


if __name__ == "__main__":
    unittest.main()
