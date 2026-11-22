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


class QuitFromPageTest(unittest.TestCase):
    """Asked by the user: «Выйти» in the window closes the whole program, past the tray, and only the app's
    own page may ask for it."""

    def setUp(self):
        import run

        self.run = run

    def tearDown(self):
        self.run.QUIT_REQUESTED.clear()

    def test_quit_closes_past_the_tray(self):
        app = self.run.TrayController.__new__(self.run.TrayController)
        app.quitting, app._status, app._told_tray = False, {"state": "busy"}, False
        self.run.QUIT_REQUESTED.set()
        with mock.patch.object(self.run, "session_ending", return_value=False):
            self.assertTrue(app.on_closing())
        self.assertTrue(app.quitting)

    def test_only_the_own_page_quits(self):
        import sys
        import types

        api = self.run.WindowApi("127.0.0.1", 8765)
        win = mock.Mock()
        fake = types.SimpleNamespace(windows=[win])
        with mock.patch.dict(sys.modules, {"webview": fake}):
            win.get_current_url.return_value = "https://example.com/"
            self.assertFalse(api.quit_app())
            self.assertFalse(self.run.QUIT_REQUESTED.is_set())
            win.get_current_url.return_value = "http://127.0.0.1:8765/"
            with mock.patch.object(self.run.threading, "Timer") as timer:
                self.assertTrue(api.quit_app())
            self.assertTrue(self.run.QUIT_REQUESTED.is_set())
            timer.return_value.start.assert_called_once()


class NoTrayIconTest(unittest.TestCase):
    """Found in the review: TRAY_READY was set when the icon did not show (no icon file, Shell_NotifyIcon failed),
    so «Свернуть в трей» and closing during a recording hid the window with nothing to bring it back."""

    def setUp(self):
        import run

        self.run = run
        run.TRAY_READY.clear()

    def tearDown(self):
        self.run.TRAY_READY.clear()

    def _app(self, shows):
        app = self.run.TrayController.__new__(self.run.TrayController)
        app.quitting, app._status, app._told_tray = False, {"state": "recording"}, False
        app.tray = mock.Mock(hwnd=None)
        app.tray.start.return_value = shows
        app.window = mock.Mock()
        app._apply_hotkey = lambda: None
        return app

    def test_start_tells_whether_the_icon_shows(self):
        with mock.patch.object(self.run, "ICO_PATH", mock.Mock(exists=lambda: True)):
            self.assertFalse(self._app(False).start())
            with mock.patch.object(self.run.threading, "Thread"):
                self.assertTrue(self._app(True).start())
        with mock.patch.object(self.run, "ICO_PATH", mock.Mock(exists=lambda: False)):
            self.assertFalse(self._app(True).start())

    def test_the_icon_coming_later_lets_the_window_hide(self):
        app = self._app(False)
        with mock.patch.object(self.run, "ICO_PATH", mock.Mock(exists=lambda: True)):
            app.start()
        self.assertFalse(self.run.TRAY_READY.is_set())
        app.tray.on_shown()  # Explorer started after the app and took the icon
        self.assertTrue(self.run.TRAY_READY.is_set())

    def test_without_the_icon_a_recording_window_is_minimized_not_hidden(self):
        app = self._app(False)
        with mock.patch.object(self.run, "session_ending", return_value=False), \
             mock.patch.object(self.run.threading, "Timer") as timer, \
             mock.patch("app.database.get_all_settings", return_value={"close_to_tray": "true"}):
            self.assertFalse(app.on_closing())
            self.assertIs(timer.call_args[0][1], app.window.minimize)
            app._status = {"state": "idle"}
            self.assertTrue(app.on_closing())  # idle: closes, not hidden away

    def test_hide_to_tray_minimizes_without_the_icon(self):
        import types

        api = self.run.WindowApi("127.0.0.1", 8765)
        win = mock.Mock()
        win.get_current_url.return_value = "http://127.0.0.1:8765/"
        with mock.patch.dict(sys.modules, {"webview": types.SimpleNamespace(windows=[win])}), \
             mock.patch.object(self.run.threading, "Timer") as timer:
            self.assertTrue(api.hide_to_tray())
            self.assertIs(timer.call_args[0][1], win.minimize)


class BackgroundNoticeTest(unittest.TestCase):
    """Found in the review: «работает в фоне» became once for good, so a user closing the window during a
    recording later could think it stopped. Told at every close while recording; the idle note stays once."""

    def setUp(self):
        import run

        self.run = run
        run.TRAY_READY.set()

    def tearDown(self):
        self.run.TRAY_READY.clear()

    def test_told_at_every_close_while_recording_once_when_idle(self):
        app = self.run.TrayController.__new__(self.run.TrayController)
        app.quitting, app._told_tray = False, False
        app._status = {"state": "recording", "recording": True}
        app.window = mock.Mock()
        told = []
        app._notify = lambda title, text, **kw: told.append(title)
        settings = {"close_to_tray": "true", "tray_told": "1"}
        with mock.patch.object(self.run, "session_ending", return_value=False), \
             mock.patch.object(self.run.threading, "Timer"), \
             mock.patch("app.database.get_all_settings", return_value=settings), \
             mock.patch("app.database.update_settings"):
            self.assertFalse(app.on_closing())
            self.assertFalse(app.on_closing())
            self.assertEqual(told, ["Verbaliox работает в фоне"] * 2)
            app._status = {"state": "idle", "recording": False}
            self.assertFalse(app.on_closing())  # told once already (tray_told)
            self.assertEqual(len(told), 2)


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
