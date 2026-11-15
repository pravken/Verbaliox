"""uninstall.ps1 / uninstall.bat: the full removal (no PowerShell here, so what can be checked from the text)."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class UninstallScriptTest(unittest.TestCase):
    def setUp(self):
        self.raw = (ROOT / "uninstall.ps1").read_bytes()
        self.ps = self.raw.decode("utf-8-sig")
        self.bat = (ROOT / "uninstall.bat").read_bytes()

    def test_windows_powershell_reads_the_russian_text(self):
        # Windows PowerShell 5.1 takes a file without a BOM for the ANSI code page: the messages would be garbage
        self.assertTrue(self.raw.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\n", self.raw.replace(b"\r\n", b""))  # CRLF only
        self.assertNotIn(b"\n", self.bat.replace(b"\r\n", b""))  # cmd finds nothing wrong in CRLF
        self.assertIn(b"uninstall.ps1", self.bat)

    def test_it_deletes_only_a_verbaliox_folder_and_never_a_profile_or_a_drive(self):
        self.assertIn('Join-Path $AppDir "run.py"', self.ps)
        self.assertIn("app\\paths.py", self.ps)
        self.assertIn("function Is-Protected", self.ps)
        for guarded in ("$env:USERPROFILE", "$env:LOCALAPPDATA", "$env:SystemRoot", '"Desktop"', '"MyDocuments"'):
            self.assertIn(guarded, self.ps)
        # every removal goes through Remove-Folder, which asks Is-Protected
        body = self.ps.split("function Remove-Folder", 1)[1]
        self.assertIn("Is-Protected $path", body.split("\n}", 1)[0])

    def test_it_runs_from_a_copy_so_the_program_folder_can_go(self):
        self.assertIn('Join-Path $env:TEMP "verbaliox-uninstall.ps1"', self.ps)
        self.assertIn("-FromTemp", self.ps)

    def test_what_it_removes(self):
        for item in ("Verbaliox", "VerbaScribe", "Verbaliox.migrating", "Verbaliox.before-rename-*",
                     r"CurrentVersion\Run", "{6F2C1B8E-4E7A-4C3B-9A51-7D0E2B5C9F14}_is1",
                     "OLLAMA_MODELS", "VERBALIOX_DATA_DIR", "VERBALIOX_MODELS_DIR", "Verbaliox.lnk"):
            self.assertIn(item, self.ps)
        # the installer's id is the one the uninstall entry has
        iss = (ROOT / "installer" / "verbaliox.iss").read_text(encoding="utf-8-sig")
        self.assertIn("6F2C1B8E-4E7A-4C3B-9A51-7D0E2B5C9F14", iss)

    def test_shared_tools_are_only_removed_when_asked(self):
        for flag in ("WithOllama", "WithUv", "WithPython"):
            self.assertRegex(self.ps, r"\$remove\w+ = \$" + flag + r" -or")
        # with -Yes nothing shared is asked, so nothing shared goes
        self.assertEqual(len(re.findall(r"-not \$Yes -and", self.ps)), 3)


if __name__ == "__main__":
    unittest.main()
