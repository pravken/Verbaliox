import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest

try:
    from app.live_translate import _degenerate, _first_line, collapse_repeats, serbian_to_cyrillic, serbian_to_latin
except ImportError:  # httpx/app dependencies are not installed (e.g. in the release CI job)
    collapse_repeats = None


@unittest.skipIf(collapse_repeats is None, "app dependencies not installed")
class LiveTranslateTextTest(unittest.TestCase):
    def test_looping_runs_are_collapsed(self):
        self.assertEqual(collapse_repeats("что мы здесь будем что мы здесь будем испытать"), "что мы здесь будем испытать")

    def test_single_word_repeats_stay(self):
        self.assertEqual(collapse_repeats("да, да, хорошо"), "да, да, хорошо")

    def test_degenerate_answers_are_detected(self):
        self.assertTrue(_degenerate("that we're going to experience here.",
                                    "что мы здесь будем что мы здесь будем то, что мы здесь будем испытывать"))
        self.assertTrue(_degenerate("Hello", ""))
        self.assertFalse(_degenerate("that we're going to experience here.", "что мы будем испытывать здесь."))

    def test_only_the_first_line_without_quotes(self):
        self.assertEqual(_first_line('"Hallo"\n\nThis is the translation.'), "Hallo")
        self.assertEqual(_first_line("мы будем“”"), "мы будем")

    def test_serbian_scripts(self):
        self.assertEqual(serbian_to_cyrillic("што ćemo ovde, Ljubljana, džem"), "што ћемо овде, Љубљана, џем")
        self.assertEqual(serbian_to_latin("Љубљана, џем, ћемо"), "Ljubljana, džem, ćemo")


class PhraseLanguageTest(unittest.TestCase):
    def test_plain_russian_and_english(self):
        from app.live_translate import phrase_language

        self.assertEqual(phrase_language("Давайте перенесём встречу на пятницу"), "ru")
        self.assertEqual(phrase_language("Let's move the meeting to Friday"), "en")
        self.assertIsNone(phrase_language("Привіт, як справи? Їдемо завтра"))  # Ukrainian
        self.assertIsNone(phrase_language("Wir verschieben das Treffen auf Freitag"))  # German: no English words
        self.assertIsNone(phrase_language("Ок"))  # too short to tell


if __name__ == "__main__":
    unittest.main()


@unittest.skipIf(collapse_repeats is None, "app dependencies not installed")
class FastModelTest(unittest.TestCase):
    def test_the_fast_model_is_a_measured_one_free_for_commercial_use(self):
        """bench-report/translation.md: gemma4:e2b; qwen2.5:3b, llama3.2 and gemma2 are not free for commercial use."""
        from unittest import mock

        from app import live_translate

        for bad in ("qwen2.5:3b", "llama3.2:3b", "gemma2:2b"):
            self.assertNotIn(bad, live_translate.FAST_MODEL_HINTS)
        with mock.patch.object(live_translate, "installed_models", return_value=["gemma4:e4b", "gemma4:e2b", "qwen2.5:1.5b"]), \
                mock.patch("app.database.get_all_settings", return_value={"ollama_model": "gemma4:e4b"}):
            self.assertEqual(live_translate.model_choices(), {"quality": "gemma4:e4b", "fast": "gemma4:e2b",
                                                              "auto": {"quality": "gemma4:e4b", "fast": "gemma4:e2b"},
                                                              "installed": ["gemma4:e4b", "gemma4:e2b", "qwen2.5:1.5b"]})


class DraftIntervalTest(unittest.TestCase):
    """The draft is translated as often as the model allows: a fast translator keeps up with the speech."""

    def _tr(self, cost):
        from app.live_translate import LiveTranslator

        tr = LiveTranslator.__new__(LiveTranslator)  # no worker thread, no Ollama
        tr._draft_cost = cost
        return tr

    def test_before_the_first_draft_the_slow_interval(self):
        from app.live_translate import DRAFT_INTERVAL_SEC

        self.assertEqual(self._tr(None).draft_interval(), DRAFT_INTERVAL_SEC)

    def test_a_fast_model_every_half_second(self):
        from app.live_translate import DRAFT_MIN_INTERVAL_SEC

        self.assertEqual(self._tr(0.12).draft_interval(), DRAFT_MIN_INTERVAL_SEC)

    def test_a_slow_model_is_busy_a_third_of_the_time_at_most(self):
        """Hy-MT on a laptop processor takes 0.8-1.5 s a phrase: a draft every 1.2 s kept it busy 67-100 %."""
        self.assertAlmostEqual(self._tr(0.3).draft_interval(), 0.9)
        for cost in (0.6, 0.8, 1.5):
            self.assertAlmostEqual(self._tr(cost).draft_interval(), 3 * cost)
            self.assertLessEqual(cost / self._tr(cost).draft_interval(), 1 / 3 + 1e-9)

    def test_on_the_processor_a_slow_draft_is_not_translated(self):
        tr = self._tr(1.6)
        tr.on_cpu = True
        tr._draft_text, tr._draft_done_for, tr._last_draft_at = "we will move the", "", 0.0
        self.assertTrue(tr.drafts_off())
        self.assertFalse(tr._draft_due())
        tr.on_cpu = False  # in the video card: still translated, three times as seldom
        self.assertFalse(tr.drafts_off())
        self.assertTrue(tr._draft_due())
        tr.on_cpu, tr._draft_cost = True, 1.2  # a processor fast enough
        self.assertTrue(tr._draft_due())


class ShortReplyTest(unittest.TestCase):
    """A line of one short word is translated without the model: a translator answered «No.» with «No.», and the
    page hid the translation as the same text."""

    def test_one_word_replies(self):
        from app.live_translate import short_reply

        self.assertEqual(short_reply("No.", "ru"), "Нет.")
        self.assertEqual(short_reply("No?", "ru"), "Нет?")
        self.assertEqual(short_reply("Да?", "en"), "Yes?")
        self.assertEqual(short_reply("NO!", "ru"), "НЕТ!")

    def test_fillers_and_phrases_are_not_short_replies(self):
        from app.live_translate import short_reply

        self.assertIsNone(short_reply("Um...", "ru"))
        self.assertIsNone(short_reply("No way.", "ru"))
        self.assertIsNone(short_reply("No.", "de"))  # no list for that language: the model translates

    def test_the_translator_is_not_asked(self):
        from app.live_translate import LiveTranslator

        tr = LiveTranslator.__new__(LiveTranslator)
        tr.target, tr.pair = "ru", ["ru", "en"]
        tr._source_lang = lambda: "en"
        tr._chat = lambda *a, **k: self.fail("the model was asked")
        self.assertEqual(tr._translate_clean("No.", "en", target="ru"), "Нет.")


def _translator(**kw):
    """A LiveTranslator without its worker thread (the test calls _run itself)."""
    from unittest import mock

    from app import live_translate

    with mock.patch.object(live_translate.threading, "Thread"):
        tr = live_translate.LiveTranslator(lambda: "en", "ru", **kw)
    return tr


def _no_db(test):
    """Ollama's address without the settings table."""
    from unittest import mock

    from app import live_translate

    p = mock.patch.object(live_translate, "_base_url", return_value="http://127.0.0.1:11434")
    p.start()
    test.addCleanup(p.stop)


@unittest.skipIf(collapse_repeats is None, "app dependencies not installed")
class StopWhileLoadingTest(unittest.TestCase):
    """A caption session closed while its translator was getting ready loads nothing into Ollama afterwards."""

    def setUp(self):
        _no_db(self)

    def test_closed_while_ollama_starts_no_model_is_loaded(self):
        from unittest import mock

        from app import live_translate

        tr = _translator()
        calls = []

        def choices():
            calls.append(1)
            tr.stop()  # the session closes while the list of models is not read yet
            return {"quality": None, "fast": None, "installed": []}

        tr._chat = lambda *a, **k: self.fail("the model was loaded")
        with mock.patch("app.ollama_client.ensure_ollama_running"), \
                mock.patch.object(live_translate, "model_choices", choices), \
                mock.patch.object(live_translate.time, "sleep"):
            tr._run()  # returns instead of waiting 30 s and loading
        self.assertEqual(len(calls), 1)
        self.assertFalse(tr.ready)

    def test_closed_during_the_warm_up_the_model_is_released(self):
        from unittest import mock

        tr = _translator()
        tr.model_override = "hy-mt3-1.8b"

        def warm_up(*a, **k):
            tr.stop()
            return "ок"

        tr._chat = warm_up
        with mock.patch("app.ollama_client.ensure_ollama_running"), \
                mock.patch("app.idle_unload.translator_switched", return_value=True) as switched:
            tr._run()
        switched.assert_called_once_with("hy-mt3-1.8b", None)
        self.assertFalse(tr.ready)

    def test_a_session_that_stays_keeps_its_model(self):
        from unittest import mock

        tr = _translator()
        tr.model_override = "hy-mt3-1.8b"
        tr._chat = lambda *a, **k: "ок"
        with mock.patch("app.ollama_client.ensure_ollama_running"), \
                mock.patch("app.idle_unload.translator_switched") as switched:
            tr._ensure_ready()
        self.assertTrue(tr.ready)
        switched.assert_not_called()


class _Ps:
    """httpx.Client answering /api/ps."""

    def __init__(self, models):
        self.models = models

    def __call__(self, *a, **k):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, **k):
        from unittest import mock

        return mock.Mock(json=lambda: {"models": self.models})


@unittest.skipIf(collapse_repeats is None, "app dependencies not installed")
class ProcessorThreadsTest(unittest.TestCase):
    """A translator Ollama runs without a video card gets two threads (options.num_thread), counted for speech
    recognition's thread budget (cpu_threads_in_use)."""

    def setUp(self):
        from app import live_translate

        _no_db(self)
        live_translate._ON_CPU.clear()
        live_translate._CPU_TRANSLATORS.clear()
        self.addCleanup(live_translate._ON_CPU.clear)
        self.addCleanup(live_translate._CPU_TRANSLATORS.clear)

    def test_model_on_cpu_reads_size_vram(self):
        from unittest import mock

        from app import live_translate

        ps = [{"name": "hy-mt3-1.8b:latest", "size": 1500, "size_vram": 0},
              {"name": "gemma4:e2b", "size": 7000, "size_vram": 7000}]
        with mock.patch.object(live_translate.httpx, "Client", _Ps(ps)):
            self.assertTrue(live_translate.model_on_cpu("hy-mt3-1.8b"))
            self.assertFalse(live_translate.model_on_cpu("gemma4:e2b"))
            self.assertIsNone(live_translate.model_on_cpu("gemma4:e4b"))  # not loaded
        with mock.patch.object(live_translate.httpx, "Client", _Ps([{"name": "gemma4:e2b"}])):
            self.assertIsNone(live_translate.model_on_cpu("gemma4:e2b"))  # an Ollama that does not say

    def test_a_model_partly_in_the_video_card_counts_as_the_processor(self):
        from unittest import mock

        from app import live_translate

        ps = [{"name": "hy-mt3-7b:latest", "size": 5300, "size_vram": 3000}]
        with mock.patch.object(live_translate.httpx, "Client", _Ps(ps)):
            self.assertTrue(live_translate.model_on_cpu("hy-mt3-7b"))

    def _ready(self, on_cpu):
        from unittest import mock

        from app import live_translate

        tr = _translator()
        tr.model_override = "hy-mt3-1.8b"
        sent = []
        tr._chat = lambda *a, **k: sent.append(tr._live_options()) or "ок"
        with mock.patch("app.ollama_client.ensure_ollama_running"), \
                mock.patch.object(live_translate, "model_on_cpu", return_value=on_cpu):
            tr._ensure_ready()
        return tr, sent

    def test_on_the_processor_two_threads_from_the_warm_up_on(self):
        from app import live_translate

        tr, sent = self._ready(True)
        # loaded once as Ollama chose, then again with its threads before the first line
        self.assertEqual(sent, [{}, {"num_thread": 2}])
        self.assertEqual(live_translate.cpu_threads_in_use(), 2)
        tr2, sent2 = self._ready(True)  # the next session knows it: one load, with its threads
        self.assertEqual(sent2, [{"num_thread": 2}])
        tr.stop()
        tr._run()
        self.assertEqual(live_translate.cpu_threads_in_use(), 2)  # the other session still translates
        tr2.stop()
        tr2._run()
        self.assertEqual(live_translate.cpu_threads_in_use(), 0)

    def test_in_the_video_card_nothing_changes(self):
        from app import live_translate

        tr, sent = self._ready(False)
        self.assertEqual(sent, [{}])
        self.assertEqual(live_translate.cpu_threads_in_use(), 0)

    def test_the_threads_go_in_the_request(self):
        from unittest import mock

        from app import live_translate

        body = live_translate.translator_payload("hy-mt3-1.8b", "Hello", "en", "ru", extra_options={"num_thread": 2})
        self.assertEqual(body["options"]["num_thread"], 2)
        self.assertNotIn("num_thread", live_translate.translator_payload("hy-mt3-1.8b", "Hello", "en", "ru")["options"])
        tr = _translator()
        tr._model, tr.on_cpu = "hy-mt3-1.8b", True
        with mock.patch.object(live_translate, "translator_chat", return_value="Привет") as chat:
            tr._chat("Hello", src_lang="en", target="ru")
        self.assertEqual(chat.call_args.kwargs["extra_options"], {"num_thread": 2})
