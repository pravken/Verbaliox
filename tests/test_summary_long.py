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


if __name__ == "__main__":
    unittest.main()
