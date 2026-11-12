"""«Unload» as a switch (app/vram.py): a model the running job does not use goes at once; one in use
goes once the work is stopped."""

import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest
from unittest import mock

try:
    from app import transcriber, vram
except ImportError:  # app dependencies are not installed
    vram = None


@unittest.skipIf(vram is None, "app dependencies not installed")
class UnloadSwitchTest(unittest.TestCase):
    def _stage(self, stage):
        return mock.patch.object(vram, "job_stage", return_value=stage)

    def test_whisper_goes_while_the_overview_is_written(self):
        with self._stage("summarizing"), mock.patch.object(transcriber, "release_whisper_model") as rel, \
                mock.patch.object(vram, "vram_snapshot", return_value={}):
            vram.unload("whisper")
        rel.assert_called_once()

    def test_whisper_in_use_is_refused_without_stop(self):
        with self._stage("transcribing"), mock.patch.object(transcriber, "release_whisper_model") as rel:
            with self.assertRaises(RuntimeError):
                vram.unload("whisper")
        rel.assert_not_called()

    def test_stop_cancels_the_work_then_unloads(self):
        # stop_work ends the job: the stage is gone when unload looks
        with self._stage(None), mock.patch.object(vram, "stop_work") as stop, \
                mock.patch.object(transcriber, "release_whisper_model") as rel, \
                mock.patch.object(vram, "vram_snapshot", return_value={}):
            vram.unload("whisper", stop=True)
        stop.assert_called_once()
        rel.assert_called_once()

    def test_stop_all_jobs_cancels_queued_and_running(self):
        with transcriber._jobs_lock:
            transcriber._active_jobs.update({901, 902})
        try:
            self.assertEqual(transcriber.stop_all_jobs(), 2)
            self.assertTrue(transcriber._cancel_wanted(901) and transcriber._cancel_wanted(902))
        finally:
            with transcriber._jobs_lock:
                transcriber._active_jobs.difference_update({901, 902})
                transcriber._cancel_requested.difference_update({901, 902})


if __name__ == "__main__":
    unittest.main()
