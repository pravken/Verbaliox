"""The dictionary applied to recognized text (app/vocab.py), for every speech model."""

import unittest

from app import vocab

TERMS = [{"term": "Claude"}, {"term": "Kubernetes"}, {"term": "Verbaliox", "variants": "вербал"},
         {"term": "Максим"}, {"term": "OpenAI"}, {"term": "Jira"}, {"term": "ИИ", "variants": "и и"}]


class VocabFixTest(unittest.TestCase):
    def setUp(self):
        self.rules = vocab.Rules(TERMS)

    def fix(self, text):
        return vocab.fix_text(text, self.rules)

    def test_heard_wrong_in_either_script(self):
        self.assertEqual(self.fix("Попроси klot сделать это."), "Попроси Claude сделать это.")
        self.assertEqual(self.fix("спроси у клода"), "спроси у Claude")
        self.assertEqual(self.fix("в кубернетисе всё упало"), "в Kubernetes всё упало")
        self.assertEqual(self.fix("задача в джире"), "задача в Jira")

    def test_variants_and_split_words(self):
        self.assertEqual(self.fix("Вербал работает"), "Verbaliox работает")
        self.assertEqual(self.fix("Open AI выпустила"), "OpenAI выпустила")
        self.assertEqual(self.fix("про и и поговорим"), "про ИИ поговорим")

    def test_ordinary_words_stay(self):
        for text in ("клад нашли", "дай Максима и Максиму", "кот сыре сила", "Claude уже тут"):
            self.assertEqual(self.fix(text), text)

    def test_a_phrase_does_not_run_over_punctuation(self):
        self.assertEqual(self.fix("Open. AI"), "Open. AI")

    def test_without_similar_sound_only_variants(self):
        rules = vocab.Rules(TERMS, fuzzy=False)
        self.assertEqual(vocab.fix_text("klot и вербал", rules), "klot и Verbaliox")

    def test_word_timings_become_one_word(self):
        words = [{"start": 0.0, "end": 1.0, "word": " Open", "prob": 0.9},
                 {"start": 1.0, "end": 2.0, "word": " AI,", "prob": 0.5}, {"start": 2.0, "end": 3.0, "word": " ok"}]
        self.assertEqual(vocab.fix_words(words, self.rules),
                         [{"start": 0.0, "end": 2.0, "word": " OpenAI,", "prob": 0.5}, {"start": 2.0, "end": 3.0, "word": " ok"}])

    def test_segments(self):
        segs = [{"start": 0, "end": 1, "text": "Это klot.", "words": [{"start": 0, "end": 0.5, "word": " Это"},
                                                                        {"start": 0.5, "end": 1, "word": " klot."}]}]
        vocab.fix_segments(segs, self.rules)
        self.assertEqual(segs[0]["text"], "Это Claude.")
        self.assertEqual(segs[0]["words"][1]["word"], " Claude.")


class VocabStoreTest(unittest.TestCase):
    def setUp(self):
        from app import database

        self.db = database
        database.init_db()
        self._clear()

    def _clear(self):
        for it in self.db.list_dictionary():
            if it["term"] == "Claude":
                self.db.delete_dictionary_term(it["id"])
        vocab.invalidate()

    def tearDown(self):
        self._clear()

    def test_variants_saved_and_used(self):
        item = self.db.add_dictionary_term("Claude", "Термин", "клод, Claude, klot, клод")
        self.assertEqual(item["variants"], "клод, klot")
        # Adding the word again without variants keeps them
        self.assertEqual(self.db.add_dictionary_term("Claude")["variants"], "клод, klot")
        self.db.set_dictionary_variants(item["id"], "клоуд")
        vocab.invalidate()
        self.assertIn("Claude", vocab.hotwords().split(", "))
        self.assertEqual(vocab.fix_text("клоуд", vocab.current()), "Claude")


if __name__ == "__main__":
    unittest.main()
