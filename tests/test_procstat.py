"""The program's own share of the computer for the load window (app/procstat.py)."""

import os
import sys
import unittest
from unittest import mock

from app import procstat


class ProcStatTest(unittest.TestCase):
    def setUp(self):
        procstat._last_cpu.clear()

    @unittest.skipIf(sys.platform == "win32", "reads /proc")
    def test_own_process_is_measured(self):
        self.assertGreater(procstat.rss(os.getpid()) or 0, 1 << 20)
        self.assertIsNotNone(procstat.cpu_seconds(os.getpid()))
        self.assertIsNone(procstat.rss(2**30))  # no such process: nothing, not an error

    def test_cpu_share_is_of_the_whole_computer(self):
        with mock.patch.object(procstat, "cpu_seconds", side_effect=[10.0, 12.0]), \
             mock.patch("os.cpu_count", return_value=4):
            self.assertIsNone(procstat.cpu_percent(1, now=100.0))  # the first call has nothing to compare with
            self.assertEqual(procstat.cpu_percent(1, now=102.0), 25.0)  # one core of four, busy for 2 s

    def test_video_memory_by_process_or_what_ollama_reports(self):
        sizes = {1: 2 * procstat.GB, 2: procstat.GB}
        with mock.patch.object(procstat, "rss", side_effect=lambda pid: sizes.get(pid)), \
             mock.patch.object(procstat, "cpu_percent", return_value=5.0), \
             mock.patch.object(procstat, "ollama_pids", return_value=[2]), \
             mock.patch("os.getpid", return_value=1):
            exact = procstat.snapshot({}, ollama_vram_gb=4.0, gpu_by_pid={1: procstat.GB, 2: 3 * procstat.GB})
            guess = procstat.snapshot({"live": [3]}, ollama_vram_gb=4.0, gpu_by_pid=None)
        self.assertEqual((exact["ram_gb"], exact["cpu_percent"], exact["gpu_gb"], exact["gpu_exact"]), (3.0, 10.0, 4.0, True))
        self.assertEqual(exact["parts"]["ollama"]["gpu_gb"], 3.0)
        self.assertNotIn("live", guess["parts"])  # a process that is gone is left out
        self.assertEqual((guess["gpu_gb"], guess["gpu_exact"]), (4.0, False))


if __name__ == "__main__":
    unittest.main()


class CpuTrackerWindowsTest(unittest.TestCase):
    """On Windows the tracker keeps a process's handle from one look to the next: the last seconds of an own
    process that ended between two looks are read (GetProcessTimes answers while the handle is open)."""

    def test_an_ended_process_is_read_once_and_one_no_longer_own_is_let_go(self):
        import ctypes

        times = {1: (5.0, 100.0, False), 2: (3.0, 200.0, False), 3: (1.0, 300.0, False)}
        closed = []
        k32 = mock.Mock()
        k32.CloseHandle.side_effect = closed.append
        with mock.patch.object(sys, "platform", "win32"), \
                mock.patch.object(ctypes, "windll", mock.Mock(kernel32=k32), create=True), \
                mock.patch("app.procstat._open", side_effect=lambda pid: f"h{pid}"), \
                mock.patch("app.procstat._win_times", side_effect=lambda h: times[int(h[1:])]):
            t = procstat.CpuTracker()
            self.assertEqual(set(t.read([1, 2, 3])), {1, 2, 3})
            times[2] = (7.0, 200.0, True)  # ffmpeg ended since: gone from the program's processes
            got = t.read([1, 3])
            self.assertEqual(got[2], (7.0, 200.0))
            self.assertIn("h2", closed)
            got = t.read([1])  # 3 alive but no longer the program's: not counted, let go
            self.assertEqual(set(got), {1})
            self.assertIn("h3", closed)
            self.assertEqual(set(t.read([1])), {1})
