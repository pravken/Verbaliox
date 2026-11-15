"""The first start (run.py, setup.bat): what a user's first-start log showed, checked from the text (no Windows
here): the database before the tray, the server after the window's WebView2, the Python uv downloaded."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class FirstStartTest(unittest.TestCase):
    def setUp(self):
        self.run = (ROOT / "run.py").read_text(encoding="utf-8")
        self.main = self.run.split("\ndef main() -> None:", 1)[1]

    def test_the_database_is_made_before_the_tray_and_autostart_read_the_settings(self):
        # «[tray] not available: no such table: settings» on the first start
        db = self.main.index("init_db()")
        self.assertLess(db, self.main.index("autostart.sync()"))
        self.assertLess(db, self.main.index("TrayController(window)"))

    def test_the_server_starts_once_the_windows_webview2_is_ready(self):
        # an access violation inside WebView2 while the server loaded its libraries on the first start
        ready = self.main.split("def _on_gui_ready() -> None:", 1)[1].split("webview.start(", 1)[0]
        self.assertIn("window.events.loaded.wait(SERVER_AFTER_WINDOW_SEC)", ready)
        self.assertLess(ready.index("loaded.wait"), ready.index("_start_server()"))
        # the server is started only by _start_server, not before the window (the headless mode aside)
        windowed = self.main.split("server_thread = None", 1)[1].split("def _start_server", 1)[0]
        self.assertNotIn("start_server_in_thread(", windowed)

    def test_setup_uses_the_python_uv_downloaded_when_its_link_is_refused(self):
        bat = (ROOT / "setup.bat").read_bytes().decode("ascii")
        self.assertIn("call :managed_venv", bat)
        managed = bat.split(":managed_venv", 2)[2].split("goto :eof", 2)
        self.assertIn(r'python\cpython-3.11.*-windows-x86_64-none', managed[0])
        self.assertIn('"!MANAGED_PY!" -m venv .venv', managed[0] + managed[1])
        # tried before another Python of the system is taken
        uv = bat.index("--python-preference only-managed")
        self.assertLess(uv, bat.index("call :managed_venv"))
        self.assertLess(bat.index("call :managed_venv"), bat.index('"!UV!" venv .venv --python 3.11\r\n'))


if __name__ == "__main__":
    unittest.main()
