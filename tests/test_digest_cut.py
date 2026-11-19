import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest

try:
    from app import commitments, database
    from app.media_cut import analysis_moments
except ImportError:  # the release CI runs without the app's packages
    analysis_moments = None


@unittest.skipIf(analysis_moments is None, "app dependencies not installed")
class DigestTest(unittest.TestCase):
    """Asked by the user: a digest of about five minutes for whoever missed the meeting, made of what the
    analysis found (no new request to a model)."""

    def test_decisions_tasks_and_chapters_within_the_budget(self):
        database.init_db()
        commitments._init()
        m = database.create_meeting(title="Синк", filename="a.wav", media_path="a.wav")
        segs = [{"id": i, "start": i * 30.0, "end": i * 30.0 + 25, "speaker": "S0", "text": "слово"} for i in range(80)]
        database.save_meeting_results(m["id"], segments=segs, speakers={"S0": {"name": "Анна"}}, language="ru", summaries={
            "protocol": "## Решения\n- Выпускать в пятницу [12:30]\n- Без времени\n",
            "chapters": "- [00:00] Начало\n- [20:00] Тесты\n"})
        database.update_meeting_progress(m["id"], status="completed", progress=100, duration=2400.0)
        commitments.create("Прислать смету", "Борис", meeting_id=m["id"], at=900.0)
        got = analysis_moments(database.get_meeting(m["id"]))
        self.assertEqual([x["kind"] for x in got], ["chapter", "decision", "task", "chapter"])  # in the order of the recording
        self.assertEqual(got[1]["start"], 742.0)  # a little before the moment the decision was said
        self.assertIn("Выпускать в пятницу", got[1]["title"])
        small = analysis_moments(database.get_meeting(m["id"]), budget=40)
        self.assertEqual([x["kind"] for x in small], ["decision"])  # the decisions first when the time is short
