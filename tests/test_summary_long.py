"""A long recording's overview covers it from the beginning (app/ollama_client.generate_meeting_summary)."""

import re
import unittest
from unittest import mock

from app import ollama_client


class LongSummaryTest(unittest.TestCase):
    def test_notes_of_all_parts_fit_the_last_request(self):
        # 1.5 hours of speech: the map step makes ~8 parts, each answered with long notes
        segs = [{"start": t, "end": t + 9, "speaker": "S1",
                 "text": "обсуждаем настройку рендера и документацию по шейдерам " * 3}
                for t in range(0, 5400, 10)]
        prompts = []

        def chat(system, user):
            prompts.append(user)
            if user.startswith("Это фрагмент"):
                first = re.search(r"\[(\d[\d:]*)\]", user).group(1)
                return f"- [{first}] начало части\n" + "- [x] пункт конспекта\n" * 400  # ~9000 chars
            if user.startswith("Ниже последовательные конспекты"):
                stamps = re.findall(r"\[(\d[\d:]*)\] начало части", user)
                return "\n".join(f"- [{s}] начало части" for s in stamps) + "\n- сжатый конспект"
            return "обзор"

        llm = mock.Mock(is_cloud=False, max_chars=100000)
        llm.chat.side_effect = chat
        with mock.patch("app.llm.target", return_value=llm):
            self.assertEqual(ollama_client.generate_meeting_summary(segs, {}, "protocol"), "обзор")
        final = prompts[-1]
        self.assertLessEqual(len(final), ollama_client.SINGLE_PASS_MAX_CHARS + 3000)
        self.assertIn("[00:00] начало части", final)  # the beginning of the meeting is there
        self.assertIn("от начала до конца", final)

    def test_the_users_notes_leave_room_in_one_request(self):
        """A recording just under the one-request limit, with 6000 characters of notes: read in parts,
        so the request still fits the model's window."""
        text = "обсуждаем настройку рендера и документацию " * 10
        n = (ollama_client.SINGLE_PASS_MAX_CHARS - 2000) // (len(text) + 12)
        segs = [{"start": i * 10, "end": i * 10 + 9, "speaker": "S1", "text": text} for i in range(n)]
        asked = []
        llm = mock.Mock(is_cloud=False, max_chars=100000, label="m")
        llm.chat.side_effect = lambda system, user: asked.append(user) or "- [00:00] конспект"
        with mock.patch("app.llm.target", return_value=llm):
            ollama_client.generate_meeting_summary(segs, {}, "protocol", user_notes="заметка " * 750)
        self.assertTrue(any(a.startswith("Это фрагмент") for a in asked))
        self.assertLessEqual(len(asked[-1]), ollama_client.SINGLE_PASS_MAX_CHARS + 6000 + 3000)

    def test_the_parts_are_read_once_for_the_overview_and_the_chapters(self):
        segs = [{"start": t, "end": t + 9, "speaker": "S1", "text": "обсуждаем настройку рендера " * 6}
                for t in range(0, 5400, 10)]
        asked = []

        def chat(system, user):
            asked.append(user[:20])
            return "- [00:00] конспект" if user.startswith("Это фрагмент") else "ответ"

        llm = mock.Mock(is_cloud=False, max_chars=100000, label="qwen3:8b")
        llm.chat.side_effect = chat
        notes = {}
        with mock.patch("app.llm.target", return_value=llm):
            ollama_client.generate_meeting_summary(segs, {}, "protocol", part_notes=notes)
            parts = sum(a.startswith("Это фрагмент") for a in asked)
            ollama_client.generate_meeting_summary(segs, {}, "chapters", part_notes=notes)
        self.assertGreater(parts, 1)
        self.assertEqual(sum(a.startswith("Это фрагмент") for a in asked), parts)  # none asked again


if __name__ == "__main__":
    unittest.main()


class LongHighlightsTest(unittest.TestCase):
    def test_moments_come_from_the_whole_recording(self):
        from app import media_cut

        segs = [{"start": t, "end": t + 9, "speaker": "S1", "text": "говорим о планах на квартал и бюджете " * 3}
                for t in range(0, 5400, 10)]

        def chat(system, user):
            first = re.search(r"\[(\d[\d:]*)\]", user).group(1)
            h, mm, ss = ([0] + [int(x) for x in first.split(":")])[-3:]
            a = h * 3600 + mm * 60 + ss + 30
            return f"{a // 3600}:{a % 3600 // 60:02d}:{a % 60:02d}-{a // 3600}:{(a + 30) % 3600 // 60:02d}:{(a + 30) % 60:02d} | момент"

        llm = mock.Mock(is_cloud=False, max_chars=20000)
        llm.chat.side_effect = chat
        with mock.patch("app.llm.target", return_value=llm), mock.patch("app.database.is_local_only", return_value=False):
            moments = media_cut.pick_highlights({"segments": segs, "speakers": {}, "duration": 5400})
        self.assertGreater(llm.chat.call_count, 1)
        self.assertGreater(moments[-1]["start"], 3600)  # the last hour is not lost
        self.assertEqual(moments, sorted(moments, key=lambda x: x["start"]))
