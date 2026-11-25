import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest
from unittest import mock

from app import cpu_priority


class _FakeKernel:
    def __init__(self, prio=0):
        self.prio = prio
        self.cls = None
        self.calls = []

    def GetCurrentProcess(self):
        return -1

    def GetCurrentThread(self):
        return -2

    def SetPriorityClass(self, h, cls):
        self.cls = cls
        return 1

    def GetThreadPriority(self, h):
        return self.prio

    def SetThreadPriority(self, h, prio):
        self.calls.append(prio)
        self.prio = prio
        return 1


class CpuPriorityTest(unittest.TestCase):
    def test_a_worker_process_runs_below_normal_on_windows(self):
        k = _FakeKernel()
        with mock.patch.object(cpu_priority, "_WINDOWS", True), mock.patch.object(cpu_priority, "_kernel32", return_value=k):
            self.assertTrue(cpu_priority.lower_process())
        self.assertEqual(k.cls, cpu_priority.BELOW_NORMAL_PRIORITY_CLASS)

    def test_elsewhere_nice(self):
        with mock.patch.object(cpu_priority, "_WINDOWS", False), mock.patch("os.nice", create=True) as nice:
            self.assertTrue(cpu_priority.lower_process())
        nice.assert_called_once_with(cpu_priority.NICE)

    def test_the_thread_gets_its_priority_back(self):
        k = _FakeKernel(prio=0)
        with mock.patch.object(cpu_priority, "_WINDOWS", True), mock.patch.object(cpu_priority, "_kernel32", return_value=k):
            with cpu_priority.below_normal_thread():
                self.assertEqual(k.prio, cpu_priority.THREAD_PRIORITY_BELOW_NORMAL)
            self.assertEqual(k.prio, 0)
            with self.assertRaises(ValueError):  # an error in the work gives it back too
                with cpu_priority.below_normal_thread():
                    raise ValueError
            self.assertEqual(k.prio, 0)

    def test_a_thread_already_lower_is_left_alone(self):
        k = _FakeKernel(prio=-2)
        with mock.patch.object(cpu_priority, "_WINDOWS", True), mock.patch.object(cpu_priority, "_kernel32", return_value=k):
            with cpu_priority.below_normal_thread():
                pass
        self.assertEqual(k.calls, [])

    def test_nothing_happens_to_a_thread_outside_windows(self):
        with mock.patch.object(cpu_priority, "_WINDOWS", False), mock.patch.object(cpu_priority, "_kernel32") as k:
            with cpu_priority.below_normal_thread():
                pass
        k.assert_not_called()

    def test_transcription_on_the_processor_runs_below_normal_and_on_the_card_not(self):
        from app import asr_onnx

        seen = []
        with mock.patch.object(asr_onnx, "_load"), \
                mock.patch.object(asr_onnx, "_transcribe_with", side_effect=lambda *a: seen.append(k.prio) or []), \
                mock.patch.object(cpu_priority, "_WINDOWS", True), \
                mock.patch.object(cpu_priority, "_kernel32", return_value=_FakeKernel()) as kk:
            k = kk.return_value
            asr_onnx.transcribe("gigaam-v3", None, 1.0, lambda _r: None, lambda: None)
            asr_onnx.transcribe("gigaam-v3", None, 1.0, lambda _r: None, lambda: None, gpu=True)
        self.assertEqual(seen, [cpu_priority.THREAD_PRIORITY_BELOW_NORMAL, 0])


if __name__ == "__main__":
    unittest.main()
