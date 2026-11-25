"""«Показать в папке»: Explorer is given the file in a form it understands, spaces included."""

import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest
from pathlib import Path
from unittest import mock

from app.paths import explorer_command, is_network_path, reveal_in_explorer


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

    def test_a_network_path_in_any_spelling_is_refused(self):
        """«/\\host\\share» passed a check for «\\\\» and «//»: Windows makes it \\\\host\\share all the same
        and connects to that server, sending the user's Windows login."""
        for p in ("\\\\host\\share", "//host/share", "/\\host\\share", "\\/host/share", ' "\\\\host\\x"'):
            self.assertTrue(is_network_path(p), p)
        for p in ("C:\\Users\\me\\a.m4a", "/home/me/a.m4a", "", "relative\\x"):
            self.assertFalse(is_network_path(p), p)
        from fastapi.testclient import TestClient

        from app import main

        with TestClient(main.app, base_url="http://127.0.0.1:8790") as c, mock.patch("app.paths.reveal_in_explorer") as rev:
            c.get(f"/?token={main.SESSION_TOKEN}")
            r = c.post("/api/reveal", json={"path": "/\\attacker\\share\\x"})
        self.assertEqual(r.status_code, 400)
        rev.assert_not_called()

    def test_a_backup_never_resolves_a_network_path(self):
        from app import backup

        with mock.patch.object(Path, "resolve", side_effect=AssertionError("resolved")):
            self.assertFalse(backup._inside(Path("/\\attacker\\share\\a.mp3"), [Path("/tmp")]))


if __name__ == "__main__":
    unittest.main()
