"""The log files of the data folder do not grow without end."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import applog


class SideLogsTest(unittest.TestCase):
    def test_crash_and_update_logs_keep_their_newest_part(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(applog, "LOG_DIR", Path(d)), \
                mock.patch.object(applog, "SIDE_LOG_MAX", 1000), mock.patch.object(applog, "SIDE_LOG_KEEP", 300):
            big = "".join(f"line {i:04d}\n" for i in range(500)).encode()
            (Path(d) / "update.log").write_bytes(big)
            (Path(d) / "crash.log").write_bytes(b"small\n")
            applog.trim_side_logs()
            kept = (Path(d) / "update.log").read_bytes()
            self.assertLessEqual(len(kept), 300)
            self.assertTrue(kept.startswith(b"line ") and kept.endswith(b"line 0499\n"), kept[:40])
            self.assertEqual((Path(d) / "crash.log").read_bytes(), b"small\n")
            applog.trim_side_logs()  # nothing to trim, no file missing is an error
            self.assertEqual((Path(d) / "update.log").read_bytes(), kept)


if __name__ == "__main__":
    unittest.main()
