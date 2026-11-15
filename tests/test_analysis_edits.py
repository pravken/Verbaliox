"""Hand corrections of the analysis (app/analysis_edits.py): a word put right in every section, the words
a hand edit replaced, and the dictionary learning them."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import json
import unittest

try:
    from fastapi.testclient import TestClient

    from app import analysis_edits, main
    from app.database import (clear_dictionary, create_meeting, get_meeting, init_db, list_dictionary,
                              merge_summaries)
except ImportError:  # app dependencies are not installed
    analysis_edits = None

PROTOCOL = "## Решения\n- Перенести сервис в кубернетис\n- **Кубернетис** — до пятницы\n\n## Следующие шаги\n- Ирина: доклад"


@unittest.skipIf(analysis_edits is None, "app dependencies not installed")
class ReplaceTest(unittest.TestCase):
    def test_whole_words_only_and_the_sentence_start_keeps_its_capital(self):
        text, n = analysis_edits.replace_word("кубер и Кубер, но не кубернетис", "кубер", "куб")
        self.assertEqual(n, 2)
        self.assertEqual(text, "куб и Куб, но не кубернетис")

    def test_markdown_lines_stay(self):
        text, n = analysis_edits.replace_word(PROTOCOL, "кубернетис", "Kubernetes")
        self.assertEqual(n, 2)
        self.assertIn("- Перенести сервис в Kubernetes\n- **Kubernetes** — до пятницы", text)

    def test_a_phrase_with_other_spaces(self):
        text, n = analysis_edits.replace_word("про клод  код говорили", "клод код", "Claude Code")
        self.assertEqual((text, n), ("про Claude Code говорили", 1))

    def test_the_chapters_json_changes_its_texts_not_its_keys(self):
        chapters = json.dumps([{"start": 0, "title": "Про кубер", "desc": "кубер"}], ensure_ascii=False)
        changed, n = analysis_edits.replace_in_summaries({"chapters": chapters, "error": "кубер"}, "кубер", "Kubernetes")
        self.assertEqual(n, 2)
        self.assertEqual(json.loads(changed["chapters"])[0], {"start": 0, "title": "Про Kubernetes", "desc": "Kubernetes"})
        self.assertNotIn("error", changed)


@unittest.skipIf(analysis_edits is None, "app dependencies not installed")
class WordChangesTest(unittest.TestCase):
    def test_typos_and_terms_are_offered(self):
        old = "Решили перенести сервис в кубернетис, Ирина проверит жиру до пятницы."
        new = "Решили перенести сервис в Kubernetes, Ирина проверит Jira до пятницы."
        self.assertEqual(analysis_edits.word_changes(old, new),
                         [{"wrong": "кубернетис", "right": "Kubernetes", "sure": True},
                          {"wrong": "жиру", "right": "Jira", "sure": True}])

    def test_grammar_is_offered_unticked_and_speaker_labels_never(self):
        self.assertEqual(analysis_edits.word_changes("Иван принял решение", "Иван приняли решение"),
                         [{"wrong": "принял", "right": "приняли", "sure": False}])
        self.assertEqual(analysis_edits.word_changes("Участник 2 предложил", "Ольга предложил"), [])
        self.assertFalse(analysis_edits.learnable("Участник 2"))
        self.assertFalse(analysis_edits.learnable("Ромашка, Москва"))
        self.assertTrue(analysis_edits.learnable("кубернетис"))

    def test_a_reworded_thought_and_case_alone_are_not(self):
        self.assertEqual(analysis_edits.word_changes("Обсудили бюджет", "Согласовали бюджет"), [])
        self.assertEqual(analysis_edits.word_changes("ирина", "Ирина"), [])
        old = "Короткая встреча о планах."
        new = "Совсем другой и довольно длинный текст вместо прежнего, переписанный целиком."
        self.assertEqual(analysis_edits.word_changes(old, new), [])


@unittest.skipIf(analysis_edits is None, "app dependencies not installed")
class LearnTest(unittest.TestCase):
    def setUp(self):
        init_db()
        clear_dictionary()

    def tearDown(self):
        clear_dictionary()

    def test_the_wrong_spelling_becomes_a_variant_of_the_term(self):
        self.assertEqual(analysis_edits.learn([{"wrong": "кубернетис", "right": "Kubernetes"}]), ["Kubernetes"])
        analysis_edits.learn([{"wrong": "кубер", "right": "kubernetes"}])  # the same term, another variant
        terms = list_dictionary()
        self.assertEqual(len(terms), 1)
        self.assertEqual(terms[0]["term"], "Kubernetes")
        self.assertEqual(terms[0]["variants"], "кубернетис, кубер")

    def test_the_analysis_answer_goes_through_the_variants_line_by_line(self):
        analysis_edits.learn([{"wrong": "кубернетис", "right": "Kubernetes"}])
        fixed = analysis_edits.fix_with_dictionary("## Решения\n  - Перенести в кубернетис.\n- Другое")
        self.assertEqual(fixed, "## Решения\n  - Перенести в Kubernetes.\n- Другое")


@unittest.skipIf(analysis_edits is None, "app dependencies not installed")
class ApiTest(unittest.TestCase):
    def setUp(self):
        init_db()
        clear_dictionary()
        self.mid = create_meeting("Планёрка", "a.m4a", "/tmp/a.m4a")["id"]
        merge_summaries(self.mid, {"protocol": PROTOCOL, "tldr": "Сервис переезжает в кубернетис."})
        self.c = TestClient(main.app, base_url="http://127.0.0.1:8790")
        self.c.cookies.set("vs_session_8790", main.SESSION_TOKEN)

    def tearDown(self):
        clear_dictionary()

    def test_fix_puts_it_right_in_every_section_and_learns(self):
        r = self.c.post(f"/api/meetings/{self.mid}/summaries/fix", json={"wrong": "кубернетис", "right": "Kubernetes"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["replaced"], 3)
        self.assertEqual(r.json()["learned"], ["Kubernetes"])
        sums = get_meeting(self.mid)["summaries"]
        self.assertNotIn("кубернетис", sums["protocol"].lower())
        self.assertEqual(sums["tldr"], "Сервис переезжает в Kubernetes.")

    def test_fix_one_section_without_the_dictionary(self):
        r = self.c.post(f"/api/meetings/{self.mid}/summaries/fix",
                        json={"wrong": "кубернетис", "right": "Kubernetes", "key": "tldr", "learn": False})
        self.assertEqual(r.json()["replaced"], 1)
        self.assertIn("кубернетис", get_meeting(self.mid)["summaries"]["protocol"])
        self.assertEqual(list_dictionary(), [])

    def test_a_hand_edit_is_saved_and_its_words_offered(self):
        r = self.c.put(f"/api/meetings/{self.mid}/summaries/tldr", json={"text": "Сервис переезжает в Kubernetes."})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["suggest"], [{"wrong": "кубернетис", "right": "Kubernetes", "sure": True}])
        self.assertEqual(get_meeting(self.mid)["summaries"]["tldr"], "Сервис переезжает в Kubernetes.")
        r = self.c.post("/api/dictionary/learn", json={"pairs": r.json()["suggest"]})
        self.assertEqual(r.json()["learned"], ["Kubernetes"])

    def test_an_edit_of_a_section_changed_meanwhile_is_refused(self):
        r = self.c.put(f"/api/meetings/{self.mid}/summaries/tldr",
                       json={"text": "Моя правка.", "base": "Текст, который был раньше."})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(get_meeting(self.mid)["summaries"]["tldr"], "Сервис переезжает в кубернетис.")
        r = self.c.put(f"/api/meetings/{self.mid}/summaries/tldr",
                       json={"text": "Моя правка.", "base": "Сервис переезжает в кубернетис."})
        self.assertEqual(r.status_code, 200)

    def test_an_empty_or_missing_section_is_refused(self):
        self.assertEqual(self.c.put(f"/api/meetings/{self.mid}/summaries/tldr", json={"text": "  "}).status_code, 400)
        self.assertEqual(self.c.put(f"/api/meetings/{self.mid}/summaries/followup", json={"text": "x"}).status_code, 404)
        self.assertEqual(self.c.put(f"/api/meetings/{self.mid}/summaries/error", json={"text": "x"}).status_code, 400)


@unittest.skipIf(analysis_edits is None, "app dependencies not installed")
class SuspectsTest(unittest.TestCase):
    MEETING = {
        "summaries": {"protocol": "## Решения\n- Перенести сервис в кубер\n- Обсудили бюджет", "error": "x"},
        "segments": [{"id": 0, "start": 0, "end": 5, "text": "переносим в кубер и бюджет", "words": [
            {"word": " переносим", "start": 0, "end": 1, "prob": 0.95},
            {"word": " в", "start": 1, "end": 1.2, "prob": 0.99},
            {"word": " кубер", "start": 1.2, "end": 2, "prob": 1.0,
             "alts": [{"text": "кубер", "models": ["gigaam"]}, {"text": "Kubernetes", "models": ["whisper"]}]},
            {"word": " и", "start": 2, "end": 2.1, "prob": 0.99},
            {"word": " бюджет", "start": 2.1, "end": 3, "prob": 0.3},
            {"word": " переносим", "start": 3, "end": 4, "prob": 0.2}]}],
    }

    def test_disputed_and_unsure_words_found_in_the_analysis(self):
        found = analysis_edits.suspects(self.MEETING)
        self.assertEqual([(x["word"], x["options"], x["source"]) for x in found],
                         [("кубер", ["Kubernetes"], "dispute"), ("бюджет", [], "unsure")])
        self.assertEqual(found[0]["start"], 1.2)  # «переносим» is unsure too but the analysis does not have it

    def test_the_model_answer_keeps_only_words_of_the_text(self):
        answer = ('Вот: [{"wrong": "кубер", "right": "Kubernetes", "reason": "продукт"}, '
                  '{"wrong": "Жира", "right": "Jira"}, {"wrong": "бюджет", "right": "Бюджет"}, "x"]')
        self.assertEqual(analysis_edits._parse_check(answer, "Перенести в кубер, обсудили бюджет"),
                         [{"wrong": "кубер", "right": "Kubernetes", "reason": "продукт"}])
        self.assertEqual(analysis_edits._parse_check("не знаю", "текст"), [])

    def test_the_check_asks_the_fast_local_model(self):
        from unittest import mock

        seen = {}

        class Fake:
            def chat(self, system, user, short=False):
                seen.update(user=user, short=short)
                return '[{"wrong": "кубер", "right": "Kubernetes"}]'

        with mock.patch("app.llm.uses_cloud", return_value=False), \
                mock.patch("app.live_translate.model_choices", return_value={"fast": "gemma4:e2b"}), \
                mock.patch("app.llm.target", return_value=Fake()) as tgt:
            out = analysis_edits.check_with_model(self.MEETING)
        self.assertEqual(tgt.call_args[0][0], "gemma4:e2b")
        self.assertTrue(seen["short"])
        self.assertIn("Перенести сервис в кубер", seen["user"])
        self.assertEqual(out, [{"wrong": "кубер", "right": "Kubernetes", "reason": ""}])


if __name__ == "__main__":
    unittest.main()
