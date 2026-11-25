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


if __name__ == "__main__":
    unittest.main()
