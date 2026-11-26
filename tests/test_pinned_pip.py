"""pip itself is installed pinned with its hashes, as every other package (requirements-pip.txt)."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class PinnedPipTest(unittest.TestCase):
    def test_pip_is_never_upgraded_to_whatever_is_newest(self):
        req = (ROOT / "requirements-pip.txt").read_text(encoding="utf-8")
        self.assertRegex(req, r"(?m)^pip==\d+(\.\d+)+ \\$")
        self.assertGreaterEqual(len(re.findall(r"--hash=sha256:[0-9a-f]{64}", req)), 1)
        for f in ("setup.bat", "app/dub_setup.py"):
            text = (ROOT / f).read_text(encoding="utf-8")
            self.assertNotIn("--upgrade pip", text, f)
            self.assertNotIn('"--upgrade", "pip"', text, f)
            self.assertIn("requirements-pip.txt", text, f)


if __name__ == "__main__":
    unittest.main()
