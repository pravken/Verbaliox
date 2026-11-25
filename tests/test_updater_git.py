"""A git clone updates through update.bat from the app (app/updater.launch_git_update)."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest
from unittest import mock

from app import updater


class GitUpdateTest(unittest.TestCase):
    def test_update_bat_runs_in_its_own_window_after_the_app_is_gone(self):
        with mock.patch.object(updater.sys, "platform", "win32"), mock.patch.object(updater, "is_git_checkout", return_value=True), \
                mock.patch("pathlib.Path.is_file", return_value=True), mock.patch.object(updater.subprocess, "Popen") as popen:
            updater.launch_git_update()
        cmd = popen.call_args[0][0]
        self.assertIn("timeout /t 3", cmd)  # update.bat waits for a key while the app still runs
        # the path through the environment: a "%" of a folder's name would be expanded in the command line
        self.assertIn("%VERBALIOX_UPDATE_BAT%", cmd)
        self.assertTrue(popen.call_args.kwargs["env"]["VERBALIOX_UPDATE_BAT"].endswith("update.bat"))

    def test_scripts_do_not_run_a_path_or_a_branch_name_as_commands(self):
        """A folder or a branch named with & | % (git allows them) is not run as a command by cmd, and the
        removal of the installed copy deletes only a folder of the program's name."""
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        bat = (root / "update.bat").read_text(encoding="utf-8")
        check = bat.index("BAD_BRANCH=1")
        self.assertLess(check, bat.index("git fetch origin %BRANCH%"))
        self.assertNotIn('if "%BRANCH%"', bat)
        setup = (root / "setup.bat").read_text(encoding="utf-8")
        self.assertNotIn("echo %%p | find", setup)  # a pipe reads the path as a command line again
        ps = (root / "uninstall.ps1").read_text(encoding="utf-8-sig")
        self.assertNotIn('rd /s /q `"$path`"', ps)
        self.assertIn("%VERBALIOX_RD_PATH%", ps)
        iss = (root / "installer" / "verbaliox.iss").read_text(encoding="utf-8-sig")
        guarded = iss.split("SameText(ExtractFileName(RemoveBackslashUnlessRoot(ExpandConstant('{app}'))), 'Verbaliox')", 1)
        self.assertEqual(len(guarded), 2)
        self.assertIn("DelTree(ExpandConstant('{app}')", guarded[1])
        self.assertNotIn("DelTree(ExpandConstant('{app}')", guarded[0])

    def test_not_a_git_clone_or_not_windows_says_so(self):
        with mock.patch.object(updater.sys, "platform", "linux"):
            with self.assertRaises(RuntimeError):
                updater.launch_git_update()
        with mock.patch.object(updater.sys, "platform", "win32"), mock.patch.object(updater, "is_git_checkout", return_value=False):
            with self.assertRaises(RuntimeError):
                updater.launch_git_update()


if __name__ == "__main__":
    unittest.main()
