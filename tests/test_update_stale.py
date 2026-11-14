"""An update downloaded before a newer release came out is downloaded again, not installed as the newer."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest
from unittest import mock

from app import updater


class StaleDownloadTest(unittest.TestCase):
    def setUp(self):
        self.saved = (dict(updater._state["download"]), updater._state["latest"])

    def tearDown(self):
        updater._state["download"], updater._state["latest"] = self.saved

    def test_an_older_archive_is_downloaded_again(self):
        updater._state["download"] = {"active": False, "done": True, "path": "x.zip", "version": "0.8.7", "progress": 100, "error": ""}
        updater._state["latest"] = {"version": "0.8.8"}
        self.assertFalse(updater.ready_to_install())
        with mock.patch.object(updater, "start_download") as start:
            updater._auto_download({"can_install": True, "auto": True, "latest": {"version": "0.8.8"},
                                    "download": dict(updater._state["download"])})
        start.assert_called_once()
        with self.assertRaises(RuntimeError):
            with mock.patch("pathlib.Path.is_file", return_value=True):
                updater.launch_installer()

    def test_the_archive_of_the_latest_release_installs(self):
        updater._state["download"] = {"active": False, "done": True, "path": "x.zip", "version": "0.8.8", "progress": 100, "error": ""}
        updater._state["latest"] = {"version": "0.8.8"}
        with mock.patch.object(updater, "auto_enabled", return_value=True), \
                mock.patch.object(updater, "is_git_checkout", return_value=False):
            self.assertTrue(updater.ready_to_install())


if __name__ == "__main__":
    unittest.main()
