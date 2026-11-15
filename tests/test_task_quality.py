"""Tasks of a meeting: an action of the meeting itself is not a task, and a task the user deleted does
not come back (app/commitments.py)."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest
from unittest import mock

try:
    from app import commitments
    from app.database import create_meeting, init_db, save_meeting_results
except ImportError:  # app dependencies are not installed (e.g. in the release CI job)
    commitments = None


@unittest.skipIf(commitments is None, "app dependencies not installed")
class InMeetingTest(unittest.TestCase):
    def test_actions_of_the_meeting_are_not_tasks(self):
        for what, quote in [("пошарить экран", "сейчас пошарю экран"), ("скинуть ссылку в чат", "скину ссылку в чат"),
                            ("включить микрофон", "секунду, включу микрофон"), ("share the screen", "let me share my screen")]:
            self.assertTrue(commitments.in_meeting_action({"what": what, "quote": quote, "due": ""}), what)
        for x in [{"what": "подготовить отчёт", "quote": "подготовлю отчёт к пятнице", "due": "к пятнице"},
                  {"what": "отправить ссылку на документ в чат", "quote": "после встречи скину в чат ссылку", "due": ""},
                  {"what": "показать демо клиенту", "quote": "покажу экран с демо клиенту", "due": "в четверг"}]:
            self.assertFalse(commitments.in_meeting_action(x), x["what"])


    def test_product_tasks_with_meeting_words_stay(self):
        """All three audits: single words («экран», «демонстрация», «звук», «в чат») dropped real tasks."""
        for what, quote in [("переделать экран оплаты", "надо переделать экран оплаты"),
                            ("подготовить демонстрацию для клиента", "Олег подготовит демонстрацию для клиента"),
                            ("разослать запись встречи", "разошлю всем запись встречи"),
                            ("купить камеру в переговорку", "купим новую камеру в переговорку"),
                            ("написать в чат поддержки", "напиши в чат поддержки про сбой"),
                            ("починить звук в приложении", "звук в приложении пропадает, починим"),
                            ("fix the mute button bug", "we need to fix the mute button bug"),
                            ("обновить экран логина", "экран логина надо обновить")]:
            self.assertFalse(commitments.in_meeting_action({"what": what, "quote": quote, "due": ""}), what)
        for what, quote in [("открыть таблицу", "секунду, сейчас открою таблицу"), ("показать слайд", "дайте я покажу слайд")]:
            self.assertTrue(commitments.in_meeting_action({"what": what, "quote": quote, "due": ""}), what)


@unittest.skipIf(commitments is None, "app dependencies not installed")
class DismissedTest(unittest.TestCase):
    def test_a_deleted_task_stays_away_and_teaches_the_model(self):
        init_db()
        m = create_meeting("Планёрка", "q.m4a", "/tmp/q.m4a")
        save_meeting_results(m["id"], speakers={"S1": {"name": "Анна"}}, segments=[
            {"id": 0, "start": 10, "end": 14, "speaker": "S1", "text": "Сейчас пошарю экран и покажу таблицу"},
            {"id": 1, "start": 20, "end": 25, "speaker": "S1", "text": "Я обновлю бюджет до пятницы"},
            {"id": 2, "start": 30, "end": 35, "speaker": "S1", "text": "И ещё созвонюсь с подрядчиком по смете"}])
        answer = ('{"who": "Анна", "what": "пошарить экран", "due": "", "time": "00:10", "quote": "Сейчас пошарю экран"}\n'
                  '{"who": "Анна", "what": "обновить бюджет", "due": "до пятницы", "time": "00:20", "quote": "Я обновлю бюджет до пятницы"}\n'
                  '{"who": "Анна", "what": "созвониться с подрядчиком", "due": "", "time": "00:30", "quote": "созвонюсь с подрядчиком по смете"}')
        llm = mock.Mock(is_cloud=False, max_chars=100000)
        llm.chat.return_value = answer
        with mock.patch("app.llm.target", return_value=llm):
            items = commitments.extract(m["id"])
        self.assertEqual(sorted(x["what"] for x in items), ["обновить бюджет", "созвониться с подрядчиком"])
        call = next(x for x in items if x["what"] == "созвониться с подрядчиком")
        commitments.delete(call["id"])  # not a task, the user says
        with mock.patch("app.llm.target", return_value=llm):
            again = commitments.extract(m["id"])
        self.assertEqual([x["what"] for x in again], ["обновить бюджет"])
        system = llm.chat.call_args_list[-2][0][0]  # the search (the last call is the second look)
        self.assertIn("созвониться с подрядчиком", system)


@unittest.skipIf(commitments is None, "app dependencies not installed")
class MfuTest(unittest.TestCase):
    """The organizer's meeting follow-up (MFU) pasted into a recording: its tasks are taken as written,
    the ones heard only in the talk stay, marked by their source."""

    def _llm(self):
        talk = ('{"who": "Анна", "what": "обновить бюджет", "due": "до пятницы", "time": "00:20", "quote": "Я обновлю бюджет до пятницы"}\n'
                '{"who": "Анна", "what": "созвониться с подрядчиком", "due": "", "time": "00:30", "quote": "созвонюсь с подрядчиком по смете"}')
        mfu = ('{"who": "Анна", "kind": "part", "what": "обновить бюджет проекта", "due": "до пятницы", "quote": "Анна — обновить бюджет"}\n'
               '{"who": "Пётр", "kind": "ext", "what": "подготовить договор", "due": "к 20 ноября", "quote": "Пётр — договор к 20 ноября"}')

        def chat(system, user):
            if system == commitments._SYSTEM_MFU:
                self.mfu_seen = user
                return mfu
            if system == commitments._CHECK:
                return "\n".join(f"{i}: да" for i in range(1, 10))
            return talk

        llm = mock.Mock(is_cloud=False, max_chars=100000)
        llm.chat.side_effect = chat
        return llm

    def test_the_mfu_tasks_come_first_and_the_talk_adds_the_rest(self):
        init_db()
        m = create_meeting("Планёрка", "q.m4a", "/tmp/q.m4a")
        save_meeting_results(m["id"], speakers={"S1": {"name": "Анна"}}, segments=[
            {"id": 0, "start": 20, "end": 25, "speaker": "S1", "text": "Я обновлю бюджет до пятницы"},
            {"id": 1, "start": 30, "end": 35, "speaker": "S1", "text": "И ещё созвонюсь с подрядчиком по смете"}])
        from app.database import update_meeting_fields

        update_meeting_fields(m["id"], mfu="Итоги:\n1. Анна — обновить бюджет до пятницы\n2. Пётр — договор к 20 ноября")
        llm = self._llm()
        with mock.patch("app.llm.target", return_value=llm):
            items = commitments.extract(m["id"])
        got = {x["what"]: x for x in items}
        self.assertEqual(set(got), {"обновить бюджет проекта", "подготовить договор", "созвониться с подрядчиком"})
        self.assertEqual(got["подготовить договор"]["source"], "mfu")  # not said in the talk: kept, as agreed
        self.assertEqual(got["обновить бюджет проекта"]["source"], "mfu")  # said in both: once, the MFU's words
        self.assertEqual(got["обновить бюджет проекта"]["at"], 20)  # with the moment it was said
        self.assertEqual(got["созвониться с подрядчиком"]["source"], "ai")  # heard only in the talk
        self.assertIn("Пётр — договор", self.mfu_seen)

    def test_two_reports_are_two_tasks(self):
        same = commitments._same_as_mfu
        self.assertFalse(same({"who": "Анна", "what": "отчёт по продажам"}, {"who": "Анна", "what": "отчёт по закупкам"}))
        self.assertTrue(same({"who": "Анна", "what": "подготовить отчёт"}, {"who": "Анна Петрова", "what": "подготовить отчёт по продажам"}))

    def test_without_an_mfu_nothing_changes(self):
        init_db()
        m = create_meeting("Планёрка 2", "q.m4a", "/tmp/q.m4a")
        save_meeting_results(m["id"], speakers={"S1": {"name": "Анна"}}, segments=[
            {"id": 0, "start": 20, "end": 25, "speaker": "S1", "text": "Я обновлю бюджет до пятницы"}])
        llm = self._llm()
        with mock.patch("app.llm.target", return_value=llm):
            items = commitments.extract(m["id"])
        self.assertTrue(items and all(x["source"] == "ai" for x in items))
        self.assertFalse(any(c[0][0] == commitments._SYSTEM_MFU for c in llm.chat.call_args_list))

    def test_every_summary_is_told_the_mfu(self):
        from app import ollama_client

        llm = mock.Mock(is_cloud=False, max_chars=100000, label="m")
        llm.chat.return_value = "обзор"
        segs = [{"start": 0, "end": 5, "speaker": "S1", "text": "обсудили бюджет"}]
        with mock.patch("app.llm.target", return_value=llm):
            ollama_client.generate_meeting_summary(segs, {}, "protocol", mfu="1. Анна — обновить бюджет")
        system, user = llm.chat.call_args[0]
        self.assertIn("Анна — обновить бюджет", system + user)
        self.assertIn("MFU", system + user)


@unittest.skipIf(commitments is None, "app dependencies not installed")
class PersonNamesTest(unittest.TestCase):
    """«Макс будет делать» is the task of «Maksim Pravko» of the Teams captions (the owner's case)."""

    def test_short_latin_and_misspelt_names_find_the_participant(self):
        from app.people import resolve_person

        roster = ["Maksim Pravko", "Анна Петрова — дизайнер", "Aleksandr Ivanov", "Александра Смирнова", "Дмитрий Яцукевич"]
        for said, who in [("Макс", "Maksim Pravko"), ("Максим", "Maksim Pravko"), ("Правко", "Maksim Pravko"),
                          ("Max", "Maksim Pravko"), ("Аня", "Анна Петрова"), ("Петрова", "Анна Петрова"),
                          ("Дима", "Дмитрий Яцукевич"), ("Яцкевич", "Дмитрий Яцукевич"), ("Иванов", "Aleksandr Ivanov")]:
            self.assertEqual(resolve_person(said, roster), who, said)
        for said in ("Саша", "Олег", "маркетинг"):  # two fit, or nobody: as said
            self.assertEqual(resolve_person(said, roster), said)


if __name__ == "__main__":
    unittest.main()
