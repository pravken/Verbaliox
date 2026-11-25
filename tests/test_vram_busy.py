"""/api/vram «busy» names the job the queue runs: the loop over the Ollama models wrote its own flag over it, and a
running transcription read as no work (found in an audit)."""

import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest
from unittest import mock

from app import transcriber, vram


class VramBusyTest(unittest.TestCase):
    def test_the_job_is_named_with_an_ollama_model_loaded(self):
        from app.database import init_db

        init_db()
        with mock.patch.object(transcriber, "running_job_kind", return_value="transcribe"), \
                mock.patch.object(vram, "job_stage", return_value="transcribing"), \
                mock.patch.object(vram, "ollama_loaded", return_value=[{"name": "qwen3:8b", "size_vram_gb": 5.0}]), \
                mock.patch.object(vram, "ollama_installed", return_value=["qwen3:8b"]), \
                mock.patch.object(vram, "remember_blobs"), \
                mock.patch.object(vram, "gpu_memory", return_value=None), \
                mock.patch("app.ollama_client.analysis_running", return_value=[]):
            snap = vram.vram_snapshot()
        self.assertEqual(snap["busy"], "transcribe")
        chip = next(c for c in snap["chips"] if c["kind"] == "ollama")
        self.assertTrue(chip["can_unload"])
        self.assertFalse(chip["in_use"])


if __name__ == "__main__":
    unittest.main()
