"""Windows shutting down (found in the audit: the app vetoed it and did not finish its recordings)."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import sys
import unittest
from pathlib import Path
from unittest import mock


class SessionEndTest(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32", "the tray window is Windows only")
    def test_shutdown_is_never_vetoed_and_the_work_is_finished(self):
        from app import tray

        ended = []
        t = tray.Tray(Path("x.ico"), lambda: [], lambda c: None, lambda: None, on_session_end=lambda: ended.append(1))
        self.assertEqual(t._proc(1, tray.WM_QUERYENDSESSION, 0, 0), 1)  # yes, Windows may end the session
        self.assertEqual(ended, [])
        self.assertEqual(t._proc(1, tray.WM_ENDSESSION, 0, 0), 0)  # the end called off: nothing done
        self.assertEqual(ended, [])
        self.assertEqual(t._proc(1, tray.WM_ENDSESSION, 1, 0), 0)
        self.assertEqual(ended, [1])

    def test_the_window_closes_while_windows_shuts_down(self):
        import run

        app = run.TrayController.__new__(run.TrayController)
        app.quitting, app._status, app._told_tray = False, {"state": "recording"}, False
        with mock.patch.object(run, "session_ending", return_value=True):
            self.assertTrue(app.on_closing())
        self.assertTrue(app.quitting)


class WebView2Test(unittest.TestCase):
    """Found in the audit: without the WebView2 Runtime the window stayed on «Запуск…» (the old IE engine)."""

    def _fake_winreg(self, pv):
        import types

        reg = types.SimpleNamespace(HKEY_LOCAL_MACHINE=1, HKEY_CURRENT_USER=2)

        class Key:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def open_key(root, path):
            if pv is None:
                raise OSError("no key")
            return Key()

        reg.OpenKey = open_key
        reg.QueryValueEx = lambda k, name: (pv, 1)
        return reg

    def test_the_runtime_is_found_by_its_version(self):
        import run

        for pv, want in (("131.0.2903.70", True), ("0.0.0.0", False), (None, False)):
            with mock.patch.object(run.sys, "platform", "win32"), mock.patch.dict(sys.modules, {"winreg": self._fake_winreg(pv)}):
                self.assertEqual(run.webview2_installed(), want, pv)


if __name__ == "__main__":
    unittest.main()
