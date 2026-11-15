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
        self.assertIn("update.bat", cmd)

    def test_not_a_git_clone_or_not_windows_says_so(self):
        with mock.patch.object(updater.sys, "platform", "linux"):
            with self.assertRaises(RuntimeError):
                updater.launch_git_update()
        with mock.patch.object(updater.sys, "platform", "win32"), mock.patch.object(updater, "is_git_checkout", return_value=False):
            with self.assertRaises(RuntimeError):
                updater.launch_git_update()


if __name__ == "__main__":
    unittest.main()
