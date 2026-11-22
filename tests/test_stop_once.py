"""The end of the app finishes a screen recording once (found in review): the window's closing and the thread
that ends a hanging window both stopped the work, and the second stop killed FFmpeg while it wrote the end of
the file, then ended the process under the first."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import threading
import time
import unittest
from pathlib import Path
from unittest import mock


class _SlowFfmpeg:
    """FFmpeg asked to finish: it takes a while to write the end of the file."""

    def __init__(self):
        self.killed = False
        self.done = False
        self.closed_in = False
        self.stdin = self

    def write(self, data):
        if self.closed_in:
            raise ValueError("write to closed file")

    def close(self):
        self.closed_in = True

    def poll(self):
        return 0 if self.done or self.killed else None

    def wait(self, timeout=None):
        if not self.killed:
            time.sleep(0.3)
            self.done = True
        return 0

    def kill(self):
        if not self.done:
            self.killed = True


class StopOnceTest(unittest.TestCase):
    def test_a_second_stop_waits_for_ffmpeg_to_finish(self):
        from app.screen_capture import ScreenCapture

        cap = ScreenCapture(Path("x.mkv"), "desktop")
        cap.proc = _SlowFfmpeg()
        first = threading.Thread(target=cap.stop)
        first.start()
        time.sleep(0.05)
        cap.stop()  # the end of the app while the recording's own stop is under way
        first.join()
        self.assertTrue(cap.proc.done)
        self.assertFalse(cap.proc.killed)

    def test_the_work_is_stopped_one_call_at_a_time(self):
        import run

        running, overlap = [0], []

        def stop_all():
            running[0] += 1
            overlap.append(running[0])
            time.sleep(0.2)
            running[0] -= 1

        with mock.patch("app.shutdown.stop_all", stop_all), mock.patch.object(run, "remove_pid_file"), \
                mock.patch("app.database.update_settings"):
            threads = [threading.Thread(target=run._stop_work) for _ in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(overlap, [1, 1])

    def test_the_update_is_installed_once_on_exit(self):
        import run

        started = []

        def install_on_exit():
            time.sleep(0.05)
            started.append(1)
            return True

        run._update_launched = False
        try:
            with mock.patch("app.updater.install_on_exit", install_on_exit), \
                    mock.patch.object(run, "session_ending", side_effect=lambda: time.sleep(0.05) or False):
                barrier = threading.Barrier(4)

                def call():
                    barrier.wait()
                    run._install_update_on_exit()

                threads = [threading.Thread(target=call) for _ in range(4)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()
        finally:
            run._update_launched = False
        self.assertEqual(started, [1])


if __name__ == "__main__":
    unittest.main()
