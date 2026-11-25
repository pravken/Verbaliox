"""A cut cancelled while FFmpeg writes (found in an audit): on Windows the process just killed still holds the
unfinished file, and the error of its delete took the place of the cancel. The file goes once FFmpeg has ended."""

import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import io
import unittest

from app import media_cut


class _Cancelled(Exception):
    pass


class _Proc:
    def __init__(self):
        self.stdout = io.StringIO("out_time_us=1000000\n")
        self.stderr = io.StringIO("")
        self.ended = False
        self.returncode = None

    def kill(self):
        pass  # the process ends a moment later

    def wait(self, timeout=None):
        self.ended = True
        self.returncode = -9
        return self.returncode


class _HeldFile:
    """The unfinished file: held by FFmpeg until it has ended."""

    def __init__(self, proc):
        self.proc, self.name, self.removed = proc, "cut.part.mp4", False

    def unlink(self, missing_ok=False):
        if not self.proc.ended:
            raise PermissionError("[WinError 32] used by another process")
        self.removed = True


class CutCancelTest(unittest.TestCase):
    def test_the_cancel_reaches_the_job_and_the_file_goes(self):
        proc = _Proc()
        part = _HeldFile(proc)

        def cancel():
            raise _Cancelled()

        with self.assertRaises(_Cancelled):
            media_cut._follow(proc, 10.0, part, lambda r: None, cancel)
        self.assertTrue(part.removed)


if __name__ == "__main__":
    unittest.main()
