import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest
from unittest import mock

from app import asr_onnx


class NoSpinningTest(unittest.TestCase):
    """ONNX Runtime's threads must not wait actively: two spinning pools froze a 4/8 laptop
    (bench-report/asr-2026-11.md)."""

    def _entries(self, so):
        return {k: so.get_session_config_entry(k) for k in asr_onnx.NO_SPINNING}

    def test_cpu_sessions_do_not_spin(self):
        with mock.patch.object(asr_onnx, "cpu_threads", return_value=3):
            so = asr_onnx._cpu_options()
        self.assertEqual(self._entries(so), {"session.intra_op.allow_spinning": "0",
                                             "session.inter_op.allow_spinning": "0"})
        self.assertEqual(so.intra_op_num_threads, 3)
        self.assertEqual(so.inter_op_num_threads, 1)

    def test_gpu_sessions_do_not_spin_either(self):
        so = asr_onnx._gpu_options()
        self.assertEqual(set(self._entries(so).values()), {"0"})


class ThreadBudgetTest(unittest.TestCase):
    """One budget for the program: live captions 2 threads, the queue what is left (bench-report/asr-2026-11.md)."""

    def _queue(self, cores, setting="auto", captions=False):
        with mock.patch("os.cpu_count", return_value=cores):
            return asr_onnx.queue_threads({"cpu_threads": setting}, captions=captions)

    def test_without_captions_the_setting_rules(self):
        self.assertEqual(self._queue(8), 4)
        self.assertEqual(self._queue(8, "all"), 8)
        self.assertEqual(self._queue(32), 8)
        self.assertEqual(self._queue(8, "6"), 6)

    def test_captions_leave_their_threads_and_two_more(self):
        self.assertEqual(self._queue(8, "all", captions=True), 4)  # 8 − 2 − 2
        self.assertEqual(self._queue(8, captions=True), 4)
        self.assertEqual(self._queue(16, "all", captions=True), 12)
        self.assertEqual(self._queue(32, captions=True), 8)  # the setting stays the cap
        self.assertEqual(self._queue(4, captions=True), 1)  # never none
        self.assertEqual(self._queue(2, captions=True), 1)

    def test_captions_take_two_threads(self):
        with mock.patch("os.cpu_count", return_value=8):
            self.assertEqual(asr_onnx.live_threads({"cpu_threads": "auto"}), 2)
            self.assertEqual(asr_onnx.live_threads({"cpu_threads": "1"}), 1)

    def test_the_window_takes_four_threads_and_phrases_two(self):
        # by the window a step on 2 threads took 1 s and the WER rose to 8-9 % (bench-report/asr-2026-11-check.md)
        with mock.patch("os.cpu_count", return_value=8), \
                mock.patch.object(asr_onnx, "live_phrases", side_effect=lambda m: m == "gigaam-v3"):
            self.assertEqual(asr_onnx.live_threads({"cpu_threads": "auto"}, "parakeet-v3"), 4)
            self.assertEqual(asr_onnx.live_threads({"cpu_threads": "auto"}, "gigaam-v3"), 2)
            self.assertEqual(asr_onnx.live_threads({"cpu_threads": "2"}, "parakeet-v3"), 2)  # the setting caps it
        with mock.patch("os.cpu_count", return_value=4), mock.patch.object(asr_onnx, "live_phrases", return_value=False):
            self.assertEqual(asr_onnx.live_threads({"cpu_threads": "auto"}, "parakeet-v3"), 2)  # auto: half of 4

    def test_the_queue_leaves_the_window_its_four_threads(self):
        from app import live

        def queue(models, cores=8, setting="auto"):
            with mock.patch("os.cpu_count", return_value=cores), \
                    mock.patch.object(live, "onnx_models_in_use", return_value=set(models)), \
                    mock.patch.object(asr_onnx, "live_phrases", side_effect=lambda m: m == "gigaam-v3"):
                return asr_onnx.queue_threads({"cpu_threads": setting}, captions=True)

        self.assertEqual(queue({"parakeet-v3"}), 2)  # 8 − 4 − 2
        self.assertEqual(queue({"gigaam-v3"}), 4)  # 8 − 2 − 2
        self.assertEqual(queue({"gigaam-v3", "parakeet-v3"}), 2)
        self.assertEqual(queue(set()), 4)  # Whisper captions in their own process
        self.assertEqual(queue({"parakeet-v3"}, 16, "all"), 10)


class CopiesTest(unittest.TestCase):
    def _fake(self):
        import sys
        import types

        fake = types.ModuleType("onnx_asr")
        fake.load_model = mock.Mock(side_effect=lambda *a, **k: mock.Mock())
        fake.load_vad = mock.Mock(return_value="vad")
        return mock.patch.dict(sys.modules, {"onnx_asr": fake}), fake

    def test_the_next_job_follows_the_budget_and_captions_keep_their_copy(self):
        mods, fake = self._fake()
        budget = [8]
        with mods, mock.patch.object(asr_onnx, "ensure_package"), mock.patch.object(asr_onnx, "fetch"), \
                mock.patch.object(asr_onnx, "queue_threads", side_effect=lambda: budget[0]), \
                mock.patch.object(asr_onnx, "live_threads", return_value=2), \
                mock.patch.dict(asr_onnx._loaded, {}, clear=True), mock.patch.dict(asr_onnx._made, {}, clear=True):
            job = asr_onnx._load("parakeet-v3")
            self.assertIs(asr_onnx._load("parakeet-v3"), job)  # the same budget: the same copy
            live = asr_onnx._load("parakeet-v3", live=True)
            self.assertIsNot(live, job)
            self.assertTrue(asr_onnx.is_loaded("parakeet-v3"))
            budget[0] = 4  # captions started: the next job's session is made with 4 threads
            job2 = asr_onnx._load("parakeet-v3")
            self.assertIsNot(job2, job)
            self.assertIs(asr_onnx._load("parakeet-v3", live=True), live)
            threads = [c.kwargs["sess_options"].intra_op_num_threads for c in fake.load_model.call_args_list]
            self.assertEqual(threads, [8, 2, 4])
            asr_onnx.release("parakeet-v3", keep_live=True)
            self.assertEqual(asr_onnx.copies(), ["parakeet-v3@live"])
            asr_onnx.release("parakeet-v3", gpu=False)
            self.assertEqual(asr_onnx.copies(), [])


if __name__ == "__main__":
    unittest.main()


class QueueBudgetCountsOllamaTest(unittest.TestCase):
    """While Ollama translates the captions on the processor, its threads leave the queue's budget."""

    def test_ollama_threads_leave_the_budget(self):
        from unittest import mock

        from app import asr_onnx, live_translate

        settings = {"cpu_threads": "all"}
        with mock.patch("os.cpu_count", return_value=16), \
                mock.patch.object(asr_onnx, "_captions_threads", return_value=4):
            with mock.patch.object(live_translate, "cpu_threads_in_use", return_value=0):
                without = asr_onnx.queue_threads(settings, captions=True)
            with mock.patch.object(live_translate, "cpu_threads_in_use", return_value=2):
                self.assertEqual(asr_onnx.queue_threads(settings, captions=True), without - 2)


class WhisperThreadsTest(unittest.TestCase):
    """Audit В22: Whisper on the processor took its own number of threads, not «Потоки процессора» and the share
    the live captions leave (the ONNX models had them)."""

    def test_whisper_on_the_processor_takes_the_budget(self):
        import sys
        import types

        from app import transcriber

        made = []
        fake = types.SimpleNamespace(WhisperModel=lambda *a, **k: made.append(k) or object())
        with mock.patch.dict(sys.modules, {"faster_whisper": fake}), \
                mock.patch.object(asr_onnx, "queue_threads", return_value=3), \
                mock.patch("app.model_manager.get_whisper_model_path", return_value="m"), \
                mock.patch.object(transcriber, "register_cuda_dlls"):
            transcriber._load_whisper_with_fallback("small", "cpu", "int8")
            transcriber._load_whisper_with_fallback("small", "cuda", "float16")
        self.assertEqual([k["cpu_threads"] for k in made], [3, 0])
