"""«Обработать всё» in «Записи» (app/pending.py): recognition for the recordings without a text, the analysis
for the transcribed ones without one, in one request; nothing finished is recognized again."""

import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import shutil
import unittest
from unittest import mock

from app.database import (create_meeting, delete_meeting, init_db, list_meetings, merge_summaries,
                          save_meeting_results, update_meeting_progress)

try:
    from app import pending
except ImportError:  # the release CI runs without the app's packages
    pending = None

SEG = [{"id": 1, "start": 0.0, "end": 2.0, "speaker": "S0", "text": "Добрый день"}]


@unittest.skipIf(pending is None, "app dependencies not installed")
class ProcessPendingTest(unittest.TestCase):
    def setUp(self):
        init_db()
        for m in list_meetings():
            delete_meeting(m["id"])
        self.dir = tests.temp_dir(self)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _rec(self, title, status, with_file=True, text=False, model="", summary=None):
        path = self.dir / f"{title}.wav"
        if with_file:
            path.write_bytes(b"RIFF")
        m = create_meeting(title=title, filename=path.name, media_path=str(path))
        if text:
            save_meeting_results(m["id"], segments=SEG, transcript_model=model or None)
        if summary is not None:
            merge_summaries(m["id"], summary)
        update_meeting_progress(m["id"], status=status, progress=0)
        return m["id"]

    def _make_library(self):
        ids = {
            "added": self._rec("Добавлена", "added"),
            "failed": self._rec("Ошибка", "failed"),
            "cancelled": self._rec("Отменена", "cancelled"),
            # a cancel mid-recognition keeps the phrases so far, but no transcript was made
            "half": self._rec("Наполовину", "cancelled", text=True),
            # a recognition again of a finished recording, cancelled or failed: its transcript stays
            "again_failed": self._rec("Повтор с ошибкой", "failed", text=True, model="large-v3"),
            "cleared": self._rec("Очищена", "cleared"),
            "no_file": self._rec("Без файла", "added", with_file=False),
            "plain": self._rec("Расшифрована", "completed", text=True, model="large-v3"),
            "failed_analysis": self._rec("Анализ с ошибкой", "completed", text=True, model="large-v3",
                                         summary={"error": "timeout"}),
            "analysed": self._rec("С анализом", "completed", text=True, model="large-v3",
                                  summary={"protocol": "## Итоги"}),
            "running": self._rec("Идёт", "transcribing"),
        }
        return ids

    def test_the_plan_takes_only_what_has_no_text_or_no_analysis(self):
        ids = self._make_library()
        with mock.patch("app.llm.available", return_value=True):
            p = pending.plan()
        self.assertEqual(set(p["transcribe"]), {ids["added"], ids["failed"], ids["cancelled"], ids["half"]})
        self.assertEqual(set(p["analyse"]), {ids["plain"], ids["failed_analysis"]})
        self.assertTrue(p["analysis_ready"])

    def test_a_recording_in_the_queue_is_left_alone(self):
        ids = self._make_library()
        with mock.patch("app.llm.available", return_value=True), \
                mock.patch("app.transcriber.is_job_active", side_effect=lambda i: i in (ids["added"], ids["plain"])):
            p = pending.plan()
        self.assertNotIn(ids["added"], p["transcribe"])
        self.assertNotIn(ids["plain"], p["analyse"])

    def test_run_queues_both_and_the_analysis_is_asked_for(self):
        ids = self._make_library()
        with mock.patch("app.llm.available", return_value=True), \
                mock.patch("app.transcriber.enqueue_meeting_job", return_value=True) as enq, \
                mock.patch("app.transcriber.enqueue_analysis_job", return_value=True) as an:
            out = pending.run()
        self.assertEqual(out["transcribe"], 4)
        self.assertEqual(out["analyse"], 2)
        self.assertEqual(out["analysis_waiting"], 0)
        self.assertEqual({c.args[0] for c in enq.call_args_list}, {ids["added"], ids["failed"], ids["cancelled"], ids["half"]})
        self.assertEqual({c.args for c in an.call_args_list}, {(ids["plain"], True), (ids["failed_analysis"], True)})
        statuses = {m["id"]: m["status"] for m in list_meetings()}
        self.assertEqual(statuses[ids["added"]], "queued")
        self.assertEqual(statuses[ids["cleared"]], "cleared")
        self.assertEqual(statuses[ids["again_failed"]], "failed")

    def test_without_the_analysis_model_the_analysis_is_not_queued(self):
        self._make_library()
        with mock.patch("app.llm.available", return_value=False), \
                mock.patch("app.transcriber.enqueue_meeting_job", return_value=True), \
                mock.patch("app.transcriber.enqueue_analysis_job", return_value=True) as an:
            out = pending.run()
        an.assert_not_called()
        self.assertEqual(out["analyse"], 0)
        self.assertEqual(out["analysis_waiting"], 2)
        self.assertFalse(out["analysis_ready"])

    def test_an_asked_analysis_runs_whatever_the_automatic_setting_says(self):
        from app import transcriber

        mid = self._rec("Без авто", "completed", text=True, model="large-v3")
        with mock.patch("app.database.get_all_settings", return_value={"auto_summary": "false"}), \
                mock.patch("app.meeting_guard.busy", return_value=""), \
                mock.patch("app.llm.available", return_value=True), \
                mock.patch.object(transcriber, "_auto_analysis") as auto, \
                mock.patch.object(transcriber, "_after_transcription", return_value=[]):
            transcriber._analysis_runner(mid)
            auto.assert_not_called()
            transcriber._analysis_runner(mid, True)
            auto.assert_called_once()

    def test_only_the_recordings_asked_for(self):
        ids = self._make_library()
        with mock.patch("app.llm.available", return_value=True), \
                mock.patch("app.transcriber.enqueue_meeting_job", return_value=True) as enq, \
                mock.patch("app.transcriber.enqueue_analysis_job", return_value=True) as an:
            out = pending.run(transcribe=False, ids=[ids["plain"], ids["added"]])
        enq.assert_not_called()
        an.assert_called_once_with(ids["plain"], True)
        self.assertEqual((out["transcribe"], out["analyse"]), (0, 1))

    def test_the_route_answers_the_counts(self):
        from fastapi.testclient import TestClient

        from app import main

        with TestClient(main.app, base_url="http://127.0.0.1:8790") as c, \
                mock.patch("app.llm.available", return_value=False), \
                mock.patch("app.transcriber.enqueue_meeting_job", return_value=True) as enq:
            c.get(f"/?token={main.SESSION_TOKEN}")
            self._make_library()  # after the start: a start takes up the one «running» again
            r = c.post("/api/library/process-pending", json={"dry_run": True})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json(), {"transcribe": 4, "analyse": 2, "analysis_ready": False})
            enq.assert_not_called()
            r = c.post("/api/library/process-pending", json={})
        self.assertEqual(r.json()["transcribe"], 4)
        self.assertEqual(r.json()["analysis_waiting"], 2)


if __name__ == "__main__":
    unittest.main()
