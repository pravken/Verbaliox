"""The decisions of a protocol read for «Обзор», a feature's card, the digest's cut and the MCP list_decisions
(app/features.decisions_of) and for the other tabs' context (app/meeting_context.protocol_points): read as the
analysis reads its sections (found in an audit: an older copy of the parser was left there)."""

import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest

from app.features import decisions_of
from app.meeting_context import protocol_points

TOPIC_NAMED_DECISION = ("## Краткое содержание\nОбсудили кэш.\n## Решения\nРешений не принималось\n"
                        "## Обсуждение по темам\n### Решение проблемы с кэшем\n- Предложили сбрасывать его ночью\n")
SUB_HEADED = "## Решения\n### Бюджет\n- Утвердили бюджет на квартал\n### Найм\n- Открыть две вакансии\n## Следующие шаги\n- Ольга: письмо\n"


class DecisionsReadingTest(unittest.TestCase):
    def test_a_topic_of_the_discussion_is_not_a_decision(self):
        self.assertEqual(decisions_of(TOPIC_NAMED_DECISION), [])
        self.assertEqual(protocol_points(TOPIC_NAMED_DECISION)["decisions"], [])

    def test_the_decisions_under_their_own_sub_headings(self):
        self.assertEqual(decisions_of(SUB_HEADED), ["Утвердили бюджет на квартал", "Открыть две вакансии"])
        self.assertEqual(protocol_points(SUB_HEADED), {"decisions": ["Утвердили бюджет на квартал", "Открыть две вакансии"],
                                                       "open": [], "next": ["Ольга: письмо"]})

    def test_a_bold_heading_and_english(self):
        self.assertEqual(decisions_of("**Решения**\n- Перенести релиз\n\n**Риски**\n- Сроки"), ["Перенести релиз"])
        self.assertEqual(decisions_of("## Decisions\n- Ship on Monday\n## Next steps\n- Anna: notes"), ["Ship on Monday"])


if __name__ == "__main__":
    unittest.main()
