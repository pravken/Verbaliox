"""The MFU saved while its recording is being processed (reported by the user: «Сохранить и обновить задачи»
during recognition ran the analysis model beside the speech models for 13 minutes and the computer hung)."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest
from unittest import mock

try:
    from fastapi.testclient import TestClient

    from app import database, main, transcriber
except ImportError:  # app dependencies are not installed (e.g. in the release CI job)
    transcriber = None


@unittest.skipIf(transcriber is None, "app dependencies not installed")
class MfuDuringJobTest(unittest.TestCase):
    def setUp(self):
        database.init_db()
        self.mid = database.create_meeting("Планёрка", "p.wav", "p.wav")["id"]
        self.addCleanup(database.delete_meeting, self.mid)
        database.save_meeting_results(self.mid, speakers={"SPEAKER_00": {"name": "Участник 1"}},
                                      segments=[{"id": 0, "start": 0.0, "end": 2.0, "speaker": "SPEAKER_00",
                                                 "text": "Отчёт пришлю в пятницу"}],
                                      language="ru", transcript_model="large-v3-turbo")
        self.client = TestClient(main.app, base_url="http://127.0.0.1:8790")
        self.client.get(f"/?token={main.SESSION_TOKEN}")

    def test_the_tasks_wait_for_the_end_of_the_job_and_the_mfu_is_saved(self):
        with transcriber._jobs_lock:
            transcriber._active_jobs.add(self.mid)
        try:
            r = self.client.put(f"/api/meetings/{self.mid}/mfu", json={"text": "1. Отчёт — Участник 1, пятница"})
            self.assertEqual(r.status_code, 200, r.text)
            with mock.patch("app.commitments.extract") as extract:
                r = self.client.post(f"/api/meetings/{self.mid}/commitments", json={})
            self.assertEqual(r.status_code, 409, r.text)
            extract.assert_not_called()  # no analysis model beside the recognition
        finally:
            with transcriber._jobs_lock:
                transcriber._active_jobs.discard(self.mid)
        self.assertEqual(database.get_meeting(self.mid)["mfu"], "1. Отчёт — Участник 1, пятница")
        with mock.patch("app.commitments.extract", return_value=[]) as extract, \
                mock.patch("app.analysis_chain.sync_next_steps"), mock.patch("app.obsidian.refresh_if_exported"):
            r = self.client.post(f"/api/meetings/{self.mid}/commitments", json={})
        self.assertEqual(r.status_code, 200, r.text)
        extract.assert_called_once()


if __name__ == "__main__":
    unittest.main()
