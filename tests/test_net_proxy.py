"""Requests to this computer (Ollama) never go through a proxy of the system settings (app/net_proxy.py)."""
import http.server
import os
import threading
import unittest
from unittest import mock

import app  # noqa: F401 - installs the loopback exemption
from app import net_proxy

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None


class LoopbackExemptTest(unittest.TestCase):
    def test_registry_proxy_gets_loopback_exceptions(self):
        # what getproxies_registry() returns on Windows: the proxy, no list of exceptions
        get = net_proxy.with_loopback_exempt(lambda: {"http": "http://proxy.corp:8080", "https": "http://proxy.corp:8080"})
        no = get()["no"].split(",")
        for host in ("localhost", "127.0.0.1", "::1"):
            self.assertIn(host, no)

    def test_own_exceptions_kept_and_no_proxy_untouched(self):
        get = net_proxy.with_loopback_exempt(lambda: {"https": "http://p:1", "no": "corp.local"})
        self.assertTrue(get()["no"].startswith("corp.local,"))
        self.assertEqual(net_proxy.with_loopback_exempt(lambda: {})(), {})

    @unittest.skipIf(httpx is None, "httpx not installed")
    def test_httpx_reads_the_exempting_function(self):
        import httpx._utils as hu

        self.assertIsNotNone(getattr(hu.getproxies, "__wrapped__", None))
        with mock.patch.dict(os.environ, {"HTTP_PROXY": "http://127.0.0.1:9", "http_proxy": "http://127.0.0.1:9",
                                          "NO_PROXY": "", "no_proxy": ""}):
            mounts = hu.get_environment_proxies()
        self.assertIn("all://127.0.0.1", mounts)
        self.assertIsNone(mounts["all://127.0.0.1"])

    @unittest.skipIf(httpx is None, "httpx not installed")
    def test_request_to_this_computer_bypasses_a_dead_proxy(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, *a):
                pass

        srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            with mock.patch.dict(os.environ, {"HTTP_PROXY": "http://127.0.0.1:9", "http_proxy": "http://127.0.0.1:9",
                                              "NO_PROXY": "", "no_proxy": ""}):
                r = httpx.get(f"http://127.0.0.1:{srv.server_port}/", timeout=5)
            self.assertEqual(r.text, "ok")
        finally:
            srv.shutdown()
            srv.server_close()


if __name__ == "__main__":
    unittest.main()
