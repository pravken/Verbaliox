import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

try:
    from app import commitments, database, mcp_server
except ImportError:  # the release CI runs without the app's packages
    mcp_server = None

SEGMENTS = [
    {"id": 1, "start": 0.0, "end": 4.0, "speaker": "SPEAKER_00", "text": "Обсудим релиз тумана на картах."},
    {"id": 2, "start": 65.0, "end": 70.0, "speaker": "SPEAKER_01", "text": "Тестирование до пятницы."},
]
SPEAKERS = {"SPEAKER_00": {"name": "Анна"}, "SPEAKER_01": {"name": "Борис"}}


def _call(name, **args):
    answer = mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}})
    result = answer["result"]
    return result["isError"], (json.loads(result["content"][0]["text"]) if not result["isError"] else result["content"][0]["text"])


@unittest.skipIf(mcp_server is None, "app dependencies not installed")
class McpServerTest(unittest.TestCase):
    """Asked by the user: an agent reads the library itself (Model Context Protocol), not exported files."""

    def setUp(self):
        database.init_db()
        with database._db_lock:
            conn = database.get_connection()
            conn.execute("DELETE FROM meetings")
            conn.commit()
            conn.close()
        commitments._init()
        with database._db_lock:
            conn = database.get_connection()
            conn.execute("DELETE FROM commitments")
            conn.commit()
            conn.close()
        database.update_settings({"my_name": "Анна", "mcp_local_only": "false"})
        m = database.create_meeting(title="Синк по туману", filename="a.wav", media_path="a.wav")
        database.save_meeting_results(m["id"], segments=SEGMENTS, speakers=SPEAKERS, language="ru",
                                      summaries={"tldr": "- Коротко", "protocol": "## Обзор\n- Про туман\n## Решения\n- Выпускать в пятницу\n"})
        database.update_meeting_progress(m["id"], status="completed", progress=100, duration=70.0)
        self.mid = m["id"]
        t = commitments.create("Прислать смету", "Борис", meeting_id=self.mid)
        with database._db_lock:
            conn = database.get_connection()
            conn.execute("UPDATE commitments SET to_whom = 'Анна' WHERE id = ?", (t["id"],))
            conn.commit()
            conn.close()
        secret = database.create_meeting(title="Секретная туманная встреча", filename="b.wav", media_path="b.wav")
        database.save_meeting_results(secret["id"], segments=SEGMENTS, speakers=SPEAKERS, language="ru")
        database.update_meeting_progress(secret["id"], status="completed", progress=100, duration=70.0)
        database.update_meeting_fields(secret["id"], local_only=1)
        self.secret = secret["id"]

    def tearDown(self):
        database.update_settings({"my_name": "", "mcp_local_only": "false"})

    def test_the_protocol(self):
        init = mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
        self.assertEqual(init["result"]["serverInfo"]["name"], "verbaliox")
        self.assertIn("tools", init["result"]["capabilities"])
        self.assertIsNone(mcp_server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        names = {t["name"] for t in mcp_server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]}
        self.assertEqual(names, {"search_meetings", "get_meeting", "list_decisions", "list_tasks", "list_people", "list_features"})
        self.assertEqual(mcp_server.handle({"jsonrpc": "2.0", "id": 3, "method": "nope"})["error"]["code"], -32601)

    def test_search_sections_tasks_and_local_only_hidden(self):
        err, found = _call("search_meetings", query="туман")
        self.assertFalse(err)
        self.assertEqual([m["id"] for m in found["meetings"]], [self.mid])  # the local-only one is not given
        err, meeting = _call("get_meeting", id=self.mid, sections=["decisions", "summary"])
        self.assertFalse(err)
        self.assertIn("Выпускать в пятницу", meeting["text"])
        self.assertNotIn("Тестирование до пятницы", meeting["text"])  # no transcript unless asked
        self.assertIn("transcript", _call("get_meeting", id=self.mid)[1]["available_sections"])
        err, msg = _call("get_meeting", id=self.secret)
        self.assertTrue(err)
        err, tasks = _call("list_tasks", scope="waiting")
        self.assertEqual([t["task"] for t in tasks["tasks"]], ["Прислать смету"])
        database.update_settings({"mcp_local_only": "true"})  # allowed by the user
        self.assertEqual(len(_call("search_meetings", query="туман")[1]["meetings"]), 2)

    def test_it_runs_on_stdio_as_a_script(self):
        """In UTF-8 both ways whatever the console's code page: on Windows a pipe is cp1251 and the agent got
        the Cyrillic as U+FFFD (found by the user)."""
        script = Path(mcp_server.__file__)
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(p for p in (env.get("PYTHONPATH", ""), str(Path("tests/stubs").resolve())) if p)
        env["PYTHONIOENCODING"] = "cp1251"  # the Windows pipe
        env.pop("PYTHONUTF8", None)
        lines = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                 {"jsonrpc": "2.0", "method": "notifications/initialized"},
                 {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "list_features", "arguments": {}}},
                 {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "search_meetings", "arguments": {"query": "туман"}}},
                 {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "get_meeting", "arguments": {"id": self.mid, "sections": ["decisions"]}}}]
        data = ("\n".join(json.dumps(x, ensure_ascii=False) for x in lines) + "\n").encode("utf-8")
        out = subprocess.run([sys.executable, str(script)], input=data, capture_output=True, timeout=60, env=env)
        answers = [json.loads(x) for x in out.stdout.decode("utf-8").splitlines() if x.strip()]
        self.assertEqual([a["id"] for a in answers], [1, 2, 3, 4], out.stderr.decode("utf-8", "replace")[-2000:])
        self.assertFalse(answers[1]["result"]["isError"])
        found = json.loads(answers[2]["result"]["content"][0]["text"])
        self.assertEqual([m["title"] for m in found["meetings"]], ["Синк по туману"])  # the query came whole
        meeting = json.loads(answers[3]["result"]["content"][0]["text"])
        self.assertIn("Выпускать в пятницу", meeting["text"])
        self.assertNotIn("\ufffd", out.stdout.decode("utf-8"))

if __name__ == "__main__":
    unittest.main()
