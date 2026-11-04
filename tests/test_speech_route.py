import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest

from app import speech_route as sr


class SpeechRouteTest(unittest.TestCase):
    """The Russian model for Russian speech, the main one for the rest (app/speech_route.py)."""

    ROUTED = {"whisper_model": "large-v3-turbo", "speech_model_ru": "gigaam-v3"}

    def test_off_without_a_model_of_its_own(self):
        for s in ({"whisper_model": "parakeet-v3"}, {"whisper_model": "gigaam-v3", "speech_model_ru": "gigaam-v3"}):
            self.assertFalse(sr.routing_on(s))
            self.assertEqual(sr.default_choice(s), s["whisper_model"])
            self.assertEqual(sr.resolve(s, "auto", lambda: "ru"), (s["whisper_model"], None))

    def test_language_of_the_recording_decides(self):
        never = lambda: self.fail("no detection when the language is known")  # noqa: E731
        self.assertEqual(sr.default_choice(self.ROUTED), "auto")
        self.assertEqual(sr.resolve(self.ROUTED, "ru", never), ("gigaam-v3", "ru"))
        self.assertEqual(sr.resolve(self.ROUTED, "en", never), ("large-v3-turbo", None))
        self.assertEqual(sr.resolve(self.ROUTED, "mixed", never), ("large-v3-turbo", None))

    def test_auto_listens_first(self):
        self.assertEqual(sr.resolve(self.ROUTED, "auto", lambda: "ru"), ("gigaam-v3", "ru"))
        self.assertEqual(sr.resolve(self.ROUTED, "auto", lambda: "other"), ("large-v3-turbo", None))
        self.assertEqual(sr.resolve(self.ROUTED, None, lambda: None), ("large-v3-turbo", None))

        def broken():
            raise RuntimeError("no audio")
        self.assertEqual(sr.resolve(self.ROUTED, "auto", broken), ("large-v3-turbo", None))

    def test_letters_tell_the_language(self):
        self.assertEqual(sr.lang_of_text("Давайте начнём с того, что успели сделать за эту неделю"), "ru")
        self.assertEqual(sr.lang_of_text("Let us start with what we finished this week, then the plans"), "other")
        self.assertEqual(sr.lang_of_text("Давайте почнемо з того, що встигли зробити за цей тиждень, її"), "other")
        self.assertIsNone(sr.lang_of_text("Да"))
        self.assertEqual(sr.lang_of_text("Добар дан, хајде да почнемо са оним што смо урадили ове недеље"), "other")  # Serbian
        self.assertEqual(sr.lang_of_text("Сәлеметсіз бе, осы аптада не істегенімізден бастайық"), "other")  # Kazakh


if __name__ == "__main__":
    unittest.main()
