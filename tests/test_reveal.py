"""«Показать в папке»: Explorer is given the file in a form it understands, spaces included."""

import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest
from pathlib import Path
from unittest import mock

from app.paths import explorer_command, reveal_in_explorer


class RevealTest(unittest.TestCase):
    def test_a_path_with_spaces_is_quoted_after_select(self):
        p = Path(r"C:\Users\me\Documents\Verbaliox\recordings\2026-11-12 Supervisors Sync.m4a")
        # one quoted argument «"/select,C:\...\..."» made Explorer open Documents
        self.assertEqual(explorer_command(p), f'explorer.exe /select,"{p}"')

    def test_a_folder_is_opened_not_selected(self):
        with mock.patch("subprocess.Popen") as popen:
            reveal_in_explorer(Path(__file__).parent)
        cmd = popen.call_args[0][0]
        self.assertIsInstance(cmd, str)
        self.assertNotIn("/select", cmd)


if __name__ == "__main__":
    unittest.main()
