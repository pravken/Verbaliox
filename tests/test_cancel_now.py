"""A cancel stops a job at once: the request to the analysis model and FFmpeg are broken off
(app/cancel_scope.py, app/audio_utils._run_ffmpeg)."""

import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import http.server
import sys
import threading
import time
import unittest

from app import cancel_scope
from app.audio_utils import _run_ffmpeg


class _Slow(http.server.BaseHTTPRequestHandler):
    def do_POST(self):  # an answer that takes long, like a small model writing an overview
        time.sleep(5)
        self.send_response(200)
        self.end_headers()

    def log_message(self, *a):
        pass


class CancelNowTest(unittest.TestCase):
    def test_a_request_is_broken_off(self):
        import httpx

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Slow)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        url = f"http://127.0.0.1:{srv.server_address[1]}/"
        result = {}

        def job():
            result["tid"] = threading.get_ident()
            cancel_scope.reset(result["tid"])
            t0 = time.time()

            def request():
                with httpx.Client(timeout=30) as c:
                    return c.post(url, json={})

            try:
                cancel_scope.call(request, on_abort=lambda: result.setdefault("cleanup", True))
                result["err"] = None
            except Exception as e:
                result["err"] = e
            result["sec"] = time.time() - t0

        th = threading.Thread(target=job)
        th.start()
        time.sleep(0.5)
        cancel_scope.abort(result["tid"])
        th.join(10)
        self.assertIsInstance(result.get("err"), cancel_scope.Aborted)
        self.assertLess(result["sec"], 2.0)
        time.sleep(0.2)
        self.assertTrue(result.get("cleanup"))  # the work behind the request is told to stop

    def test_ffmpeg_is_killed(self):
        state = {"t0": time.time()}

        def check():
            if time.time() - state["t0"] > 0.5:
                raise KeyboardInterrupt("cancelled")

        t0 = time.time()
        with self.assertRaises(KeyboardInterrupt):
            _run_ffmpeg([sys.executable, "-c", "import time; time.sleep(20)"], 0, check)
        self.assertLess(time.time() - t0, 5.0)


if __name__ == "__main__":
    unittest.main()
