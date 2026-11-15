import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import json
import unittest
from unittest import mock

from app import secret_store
from app.database import get_all_settings, init_db, update_settings

# The release CI runs the tests without the app's packages: what needs them is skipped there
try:
    import httpx

    from app import llm

    _RealClient = httpx.Client
except ImportError:
    httpx = llm = None
needs_deps = unittest.skipIf(llm is None, "app dependencies not installed")


class SecretStoreTest(unittest.TestCase):
    """Runs everywhere: on the Windows CI runner it checks the real DPAPI round trip."""

    def test_round_trip_and_hint(self):
        init_db()
        secret_store.set_secret("test_key", "sk-secret-value-5678")
        self.assertEqual(secret_store.get_secret("test_key"), "sk-secret-value-5678")
        self.assertEqual(secret_store.hint("test_key")["last4"], "…5678")
        # a long plain text: a short one ("abc") turns up in the base64 of the encrypted blob by chance
        plain = "sk-plain-text-must-not-show-9137"
        stored = secret_store.protect(plain)
        self.assertNotIn(plain, stored if stored.startswith("dpapi:") else "")
        self.assertEqual(secret_store.unprotect(stored), plain)
        self.assertIsNone(secret_store.unprotect("dpapi:bm90LWEtYmxvYg=="))  # foreign or broken data
        secret_store.delete_secret("test_key")
        self.assertIsNone(secret_store.get_secret("test_key"))


class _Fake:
    """Answers HTTP requests of app/llm.py without the network and records them."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def handler(self, request):
        self.requests.append(request)
        status, body = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        return httpx.Response(status, json=body)

    def client(self, **kw):
        return _RealClient(transport=httpx.MockTransport(self.handler), **kw)


def _use(provider, model="m-1", **extra):
    update_settings({"llm_provider": "cloud", "llm_cloud_consent": "true", "llm_cloud_provider": provider,
                     f"llm_model_{provider}": model, **extra})
    secret_store.set_secret(llm.key_name(provider), "sk-test-1234567890")


@needs_deps
class CloudLlmTest(unittest.TestCase):
    def setUp(self):
        init_db()

    def tearDown(self):
        update_settings({"llm_provider": "ollama"})
        for p in llm.PROVIDERS:
            secret_store.delete_secret(llm.key_name(p))

    def _chat(self, fake, system="sys", user="usr"):
        with mock.patch("app.llm.httpx.Client", side_effect=fake.client), mock.patch("app.llm.time.sleep"):
            return llm.target().chat(system, user)

    def test_anthropic_request_and_answer(self):
        _use("anthropic", "claude-sonnet-9")
        fake = _Fake((200, {"content": [{"type": "text", "text": "Ответ"}], "stop_reason": "end_turn"}))
        self.assertEqual(self._chat(fake), "Ответ")
        req = fake.requests[0]
        self.assertEqual(str(req.url), "https://api.anthropic.com/v1/messages")
        self.assertEqual(req.headers["x-api-key"], "sk-test-1234567890")
        self.assertEqual(req.headers["anthropic-version"], "2023-06-01")
        body = json.loads(req.content)
        self.assertEqual(body["system"], "sys")
        self.assertEqual(body["messages"], [{"role": "user", "content": "usr"}])
        self.assertEqual(body["model"], "claude-sonnet-9")

    def test_openai_and_compatible_services(self):
        _use("openai", "gpt-x")
        fake = _Fake((200, {"choices": [{"message": {"content": " Hi "}}]}))
        self.assertEqual(self._chat(fake), "Hi")
        self.assertEqual(fake.requests[0].headers["authorization"], "Bearer sk-test-1234567890")
        _use("openai_compat", "deepseek-chat", llm_base_url_openai_compat="https://api.deepseek.com/v1/")
        fake = _Fake((200, {"choices": [{"message": {"content": "ok"}}]}))
        self._chat(fake)
        self.assertEqual(str(fake.requests[0].url), "https://api.deepseek.com/v1/chat/completions")

    def test_gemini_request(self):
        _use("gemini", "gemini-2.5-flash")
        fake = _Fake((200, {"candidates": [{"content": {"parts": [{"text": "Привет"}]}}]}))
        self.assertEqual(self._chat(fake), "Привет")
        req = fake.requests[0]
        self.assertTrue(str(req.url).endswith("/models/gemini-2.5-flash:generateContent"))
        self.assertEqual(req.headers["x-goog-api-key"], "sk-test-1234567890")
        self.assertEqual(json.loads(req.content)["systemInstruction"]["parts"][0]["text"], "sys")

    def test_errors_are_readable_and_rate_limits_retried(self):
        _use("openai")
        with self.assertRaises(llm.LlmError) as ctx:
            self._chat(_Fake((401, {"error": {"message": "Incorrect API key provided"}})))
        self.assertIn("неверный API-ключ", str(ctx.exception))
        fake = _Fake((429, {"error": {"message": "slow down"}}), (200, {"choices": [{"message": {"content": "ok"}}]}))
        self.assertEqual(self._chat(fake), "ok")
        self.assertEqual(len(fake.requests), 2)

    def test_current_claude_models_get_no_temperature_and_room_to_reason(self):
        _use("anthropic", "claude-opus-9")
        fake = _Fake((200, {"content": [{"type": "thinking", "thinking": ""}, {"type": "text", "text": "ok"}], "stop_reason": "end_turn"}))
        self.assertEqual(self._chat(fake), "ok")
        body = json.loads(fake.requests[0].content)
        self.assertNotIn("temperature", body)  # refused by Claude Opus 5.5, Sonnet 5.5 and Haiku 5.5 (HTTP 400)
        self.assertGreaterEqual(body["max_tokens"], 16000)

    def test_a_refusal_or_a_cut_answer_is_an_error_not_an_answer(self):
        _use("anthropic", "claude-sonnet-9")
        with self.assertRaises(llm.LlmError) as ctx:
            self._chat(_Fake((200, {"content": [], "stop_reason": "refusal", "stop_details": {"category": "cyber"}})))
        self.assertIn("отказалась отвечать на этот текст (cyber)", str(ctx.exception))
        with self.assertRaises(llm.LlmError) as ctx:
            self._chat(_Fake((200, {"content": [{"type": "text", "text": "[{\"what\": \"обнов"}], "stop_reason": "max_tokens"})))
        self.assertIn("обрезан", str(ctx.exception))
        _use("openai", "gpt-x")
        with self.assertRaises(llm.LlmError):
            self._chat(_Fake((200, {"choices": [{"message": {"content": "## Обз"}, "finish_reason": "length"}]})))
        _use("gemini", "gemini-x")
        with self.assertRaises(llm.LlmError):
            self._chat(_Fake((200, {"candidates": [{"content": {"parts": [{"text": "## Обз"}]}, "finishReason": "MAX_TOKENS"}]})))

    def test_a_model_that_takes_no_temperature_is_asked_again_without_it(self):
        _use("openai", "gpt-5-mini")
        llm._NO_TEMPERATURE.clear()
        refusal = {"error": {"message": "Unsupported value: 'temperature' does not support 0.2 with this model."}}
        fake = _Fake((400, refusal), (200, {"choices": [{"message": {"content": "ok"}}]}))
        self.assertEqual(self._chat(fake), "ok")
        self.assertIn("temperature", json.loads(fake.requests[0].content))
        self.assertNotIn("temperature", json.loads(fake.requests[1].content))
        fake = _Fake((200, {"choices": [{"message": {"content": "ok"}}]}))
        self._chat(fake)  # remembered: one request
        self.assertNotIn("temperature", json.loads(fake.requests[0].content))
        llm._NO_TEMPERATURE.clear()

    def test_reasoning_of_a_compatible_service_is_dropped(self):
        _use("openai_compat", "qwen3", llm_base_url_openai_compat="http://127.0.0.1:1234/v1")
        fake = _Fake((200, {"choices": [{"message": {"content": "<think>hm</think>\nОтвет"}, "finish_reason": "stop"}]}))
        self.assertEqual(self._chat(fake), "Ответ")

    def test_a_retired_model_is_replaced_by_one_the_key_has(self):
        _use("anthropic", "claude-old-1")
        gone = {"type": "error", "error": {"type": "not_found_error", "message": "model: claude-old-1"}}
        fake = _Fake((404, gone), (200, {"data": [{"id": "claude-sonnet-9"}, {"id": "claude-haiku-9"}]}),
                     (200, {"content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn"}))
        self.assertEqual(self._chat(fake), "ok")
        self.assertEqual(json.loads(fake.requests[2].content)["model"], "claude-sonnet-9")
        self.assertEqual(llm.cloud_model("anthropic"), "claude-sonnet-9")  # kept for the next time

    def test_a_retired_model_keeps_its_family_and_the_log_names_the_model_used(self):
        from app.database import _db_lock  # noqa: F401 - the log table lives in the same database

        _use("anthropic", "claude-haiku-old")
        llm.clear_cloud_log()
        gone = {"type": "error", "error": {"type": "not_found_error", "message": "model: claude-haiku-old"}}
        fake = _Fake((404, gone), (200, {"data": [{"id": "claude-sonnet-9"}, {"id": "claude-haiku-9"}, {"id": "claude-opus-9"}]}),
                     (200, {"content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn"}))
        with mock.patch("app.llm.httpx.Client", side_effect=fake.client), mock.patch("app.llm.time.sleep"):
            tgt = llm.target()
            tgt.chat("s", "u")
        self.assertEqual(tgt.model, "claude-haiku-9")  # a cheap model stays a cheap one
        self.assertEqual([r["model"] for r in llm.cloud_log()], ["claude-haiku-9", "claude-haiku-old"])  # both sends

    def test_a_filtered_answer_is_an_error(self):
        _use("openai", "gpt-x")
        with self.assertRaises(llm.LlmError):
            self._chat(_Fake((200, {"choices": [{"message": {"content": "Часть"}, "finish_reason": "content_filter"}]})))
        _use("gemini", "gemini-x")
        with self.assertRaises(llm.LlmError) as ctx:
            self._chat(_Fake((200, {"candidates": [{"content": {"parts": [{"text": "Часть"}]}, "finishReason": "SAFETY"}]})))
        self.assertIn("SAFETY", str(ctx.exception))

    def test_an_answer_cut_off_mid_way_is_not_asked_again(self):
        _use("anthropic")
        calls = []

        def broken(request):
            calls.append(request)
            raise httpx.RemoteProtocolError("peer closed connection", request=request)

        with mock.patch("app.llm.httpx.Client", side_effect=lambda **kw: _RealClient(transport=httpx.MockTransport(broken), **kw)), \
                mock.patch("app.llm.time.sleep"):
            with self.assertRaises(llm.LlmError):
                llm.target().chat("s", "u")
        self.assertEqual(len(calls), 1)  # it may have reached the service and be paid: not sent twice

    def test_a_timeout_is_not_asked_again(self):
        _use("anthropic")
        calls = []

        def slow(request):
            calls.append(request)
            raise httpx.ReadTimeout("slow", request=request)

        with mock.patch("app.llm.httpx.Client", side_effect=lambda **kw: _RealClient(transport=httpx.MockTransport(slow), **kw)), \
                mock.patch("app.llm.time.sleep"):
            with self.assertRaises(llm.LlmError) as ctx:
                llm.target().chat("s", "u")
        self.assertEqual(len(calls), 1)  # a second wait as long, and maybe paid again, would help nobody
        self.assertIn("не ответил", str(ctx.exception))

    def test_missing_key_and_availability(self):
        update_settings({"llm_provider": "cloud", "llm_cloud_provider": "anthropic"})
        self.assertFalse(llm.available())
        with self.assertRaises(llm.LlmError):
            llm.target()
        _use("anthropic")
        self.assertTrue(llm.available())

    def test_key_never_in_settings_and_hint_only(self):
        _use("anthropic")
        self.assertNotIn("sk-test-1234567890", json.dumps(get_all_settings()))
        self.assertNotIn("sk-test-1234567890", json.dumps(llm.status()))
        self.assertEqual(llm.status()["providers"]["anthropic"]["key"]["last4"], "…7890")

    def test_long_transcript_goes_in_one_request(self):
        from app.ollama_client import generate_meeting_summary

        _use("anthropic")
        segments = [{"id": i, "start": i * 5.0, "end": i * 5 + 4, "speaker": "S", "text": "слово " * 40} for i in range(200)]
        fake = _Fake((200, {"content": [{"type": "text", "text": "## Обзор"}]}))
        with mock.patch("app.llm.httpx.Client", side_effect=fake.client):
            out = generate_meeting_summary(segments, {}, "protocol", answer_lang="ru")
        self.assertEqual(out, "## Обзор")
        self.assertEqual(len(fake.requests), 1)  # Ollama would summarise ~48k characters in parts


@needs_deps
class CloudApiTest(unittest.TestCase):
    def test_consent_and_key_endpoints(self):
        try:
            from fastapi.testclient import TestClient

            from app import main
        except ImportError:
            self.skipTest("fastapi not installed")
        init_db()
        update_settings({"llm_cloud_consent": "false", "llm_provider": "ollama"})
        # The app resumes queued recordings at start: other tests' recordings must not be processed
        with mock.patch.object(main, "enqueue_meeting_job"), TestClient(main.app, base_url="http://127.0.0.1:8792") as c:
            c.get(f"/?token={main.SESSION_TOKEN}")
            r = c.post("/api/settings", json={"settings": {"llm_provider": "cloud"}})
            self.assertEqual(r.status_code, 400)
            r = c.post("/api/settings", json={"settings": {"llm_provider": "cloud", "llm_cloud_consent": "true"}})
            self.assertEqual(r.status_code, 200)
            r = c.post("/api/llm/key", json={"provider": "gemini", "key": "AIza-secret-key-0000"})
            self.assertEqual(r.status_code, 200)
            self.assertNotIn("AIza-secret-key-0000", r.text)
            self.assertNotIn("AIza-secret-key-0000", c.get("/api/system").text)
            self.assertEqual(c.post("/api/llm/key", json={"provider": "gemini", "key": "has space"}).status_code, 400)
            c.delete("/api/llm/key/gemini")
        update_settings({"llm_provider": "ollama"})


if __name__ == "__main__":
    unittest.main()


class FormerEntropyTest(unittest.TestCase):
    """API keys saved before the program had its present name are read and saved again."""

    def _fake_dpapi(self, data, protect, entropy=secret_store._ENTROPY):
        # a stand-in for DPAPI: the entropy is bound into the blob and must match to read it back
        if protect:
            return entropy + b"|" + data
        tag, _, body = data.partition(b"|")
        if tag != entropy:
            raise OSError("DPAPI failed")
        return body

    def test_a_key_of_the_former_entropy_is_read_and_rewrapped(self):
        import base64

        with mock.patch.object(secret_store, "_dpapi", self._fake_dpapi), mock.patch.object(secret_store.sys, "platform", "win32"):
            old = "dpapi:" + base64.b64encode(secret_store._FORMER_ENTROPY + b"|sk-old-key-1234").decode()
            conn = secret_store._conn()
            conn.execute("INSERT OR REPLACE INTO secrets VALUES ('former_key', ?, '2026-10-01 00:00:00')", (old,))
            conn.commit()
            conn.close()
            self.assertEqual(secret_store.get_secret("former_key"), "sk-old-key-1234")
            self.assertEqual(secret_store.rewrap_former(), 1)
            conn = secret_store._conn()
            stored = conn.execute("SELECT value FROM secrets WHERE name = 'former_key'").fetchone()[0]
            conn.close()
            self.assertTrue(base64.b64decode(stored[6:]).startswith(secret_store._ENTROPY + b"|"))
            self.assertEqual(secret_store.get_secret("former_key"), "sk-old-key-1234")
            self.assertEqual(secret_store.rewrap_former(), 0)  # nothing left to do
