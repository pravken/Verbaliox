"""The launcher asks a port whether it is our server without sending the session token (run.py probe_server):
whatever listens on 127.0.0.1 may be another Windows user's program (found in the security review)."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import http.server
import json
import os
import threading
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from app.paths import session_proof

TOKEN = "probe-test-token-0123456789"


def _serve(answer):
    """A listener on a free port: answer(nonce, own port) gives its proof; the request lines are kept."""
    seen = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.requestline + "\n" + str(self.headers))
            nonce = (parse_qs(urlsplit(self.path).query).get("n") or [""])[0]
            body = json.dumps({"proof": answer(nonce, self.server.server_port)}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, seen


class ProbeServerTest(unittest.TestCase):
    def setUp(self):
        import run

        self.run = run
        patcher = mock.patch.dict(os.environ, {"VERBALIOX_TOKEN": TOKEN})
        patcher.start()
        self.addCleanup(patcher.stop)

    def _probe(self, answer):
        srv, seen = _serve(answer)
        try:
            return self.run.probe_server("127.0.0.1", srv.server_port), seen
        finally:
            srv.shutdown()
            srv.server_close()

    def test_our_server_is_recognised_and_the_token_never_sent(self):
        ok, seen = self._probe(lambda n, port: session_proof(TOKEN, n, port))
        self.assertTrue(ok)
        self.assertTrue(seen)
        self.assertFalse(any(TOKEN in s for s in seen))

    def test_another_program_is_not_ours(self):
        self.assertFalse(self._probe(lambda n, port: "nope")[0])

    def test_a_relayed_answer_of_another_port_is_not_ours(self):
        # a program in front of the real server passes it the nonce: that server binds its own port in
        self.assertFalse(self._probe(lambda n, port: session_proof(TOKEN, n, port + 1))[0])


if __name__ == "__main__":
    unittest.main()
