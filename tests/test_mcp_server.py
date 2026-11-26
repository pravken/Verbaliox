import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import json
import os
import subprocess
import sys
import unittest
from unittest import mock
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
        database.update_meeting_fields(secret["id"], folder_id=database.system_folder_id("dictations"))
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

    def test_the_agent_is_told_the_content_is_untrusted(self):
        """Found in the audit: a participant can speak a prompt injection into a transcript; the server says
        that what it returns is data, never instructions."""
        init = mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        self.assertIn("never instructions", init["result"]["instructions"])
        for tool in mcp_server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]:
            self.assertIn("untrusted", tool["description"], tool["name"])

    def test_search_sections_tasks_and_dictations_hidden(self):
        err, found = _call("search_meetings", query="туман")
        self.assertFalse(err)
        self.assertEqual([m["id"] for m in found["meetings"]], [self.mid])  # the dictation is not given
        err, meeting = _call("get_meeting", id=self.mid, sections=["decisions", "summary"])
        self.assertFalse(err)
        self.assertIn("Выпускать в пятницу", meeting["text"])
        self.assertNotIn("Тестирование до пятницы", meeting["text"])  # no transcript unless asked
        self.assertIn("transcript", _call("get_meeting", id=self.mid)[1]["available_sections"])
        err, msg = _call("get_meeting", id=self.secret)
        self.assertTrue(err)
        err, tasks = _call("list_tasks", scope="waiting")
        self.assertEqual([t["task"] for t in tasks["tasks"]], ["Прислать смету"])
        # a section asked for alone: the meeting still says it has decisions
        self.assertIn("decisions", _call("get_meeting", id=self.mid, sections=["summary"])[1]["available_sections"])
        # the user's name merged with a variant in the directory: a task promised to the variant is «waiting» too
        with mock.patch("app.people.canonical", side_effect=lambda n, rows=None: "Анна" if n.strip() in ("Аня", "Анна") else n):
            with database._db_lock:
                conn = database.get_connection()
                conn.execute("UPDATE commitments SET to_whom = 'Аня'")
                conn.commit()
                conn.close()
            self.assertEqual([t["task"] for t in _call("list_tasks", scope="waiting")[1]["tasks"]], ["Прислать смету"])
        # the list of dictations cannot be read: the call fails, nothing is handed out
        with mock.patch("app.database.dictation_ids", side_effect=RuntimeError("database is locked")):
            with self.assertRaises(RuntimeError):
                mcp_server._hidden()
        database.update_settings({"mcp_local_only": "true"})  # allowed by the user
        self.assertEqual(len(_call("search_meetings", query="туман")[1]["meetings"]), 2)

    def test_recordings_marked_local_in_earlier_versions_stay_hidden(self):
        """The «только локально» mark went with the cloud models: what the user had closed to the agent stays
        closed (a recording, a folder and the folders inside it); the dictations still follow the setting."""
        own = database.create_meeting(title="Туман: личное", filename="c.wav", media_path="c.wav")
        inner = database.create_meeting(title="Туман: в закрытой папке", filename="d.wav", media_path="d.wav")
        for mid in (own["id"], inner["id"]):
            database.save_meeting_results(mid, segments=SEGMENTS, speakers=SPEAKERS, language="ru")
            database.update_meeting_progress(mid, status="completed", progress=100, duration=70.0)
        top = database.create_folder("Закрытое")
        sub = database.create_folder("Внутри", parent_id=top["id"])
        database.update_meeting_fields(inner["id"], folder_id=sub["id"])
        with database._db_lock:
            conn = database.get_connection()
            conn.execute("UPDATE meetings SET local_only = 1 WHERE id = ?", (own["id"],))
            conn.execute("UPDATE folders SET local_only = 1 WHERE id = ? OR system_key = 'dictations'", (top["id"],))
            conn.execute("DELETE FROM settings WHERE key = 'formerly_local_v1'")  # a database of an earlier version
            conn.commit()
            conn.close()
        database.init_db()
        database.update_settings({"mcp_local_only": "true"})  # the dictations allowed
        found = {m["id"] for m in _call("search_meetings", query="туман")[1]["meetings"]}
        self.assertEqual(found, {self.mid, self.secret})
        err, msg = _call("get_meeting", id=inner["id"])
        self.assertTrue(err)
        self.assertNotIn("dictation", msg)
        # Found in the review: told by the folder, the mark opened again when the folder was deleted or the
        # recording moved out of it
        database.delete_folder(sub["id"])
        database.delete_folder(top["id"])
        database.update_meeting_fields(own["id"], folder_id=None)
        found = {m["id"] for m in _call("search_meetings", query="туман")[1]["meetings"]}
        self.assertEqual(found, {self.mid, self.secret})
        self.assertTrue({own["id"], inner["id"]} <= database.formerly_local_ids())

    def test_a_setting_changed_by_the_app_counts_at_once(self):
        """Found in the review: the MCP server is a process of its own and kept its cache of the settings, so
        the hidden recordings stayed open to the agent after the user took the permission back in the app."""
        def app_sets(value):  # the app writes the table from its own process (here: its own connection)
            import sqlite3

            conn = sqlite3.connect(str(database.DB_PATH))
            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('mcp_local_only', ?)", (value,))
            conn.commit()
            conn.close()

        self.assertIn(self.secret, mcp_server._hidden())
        app_sets("true")
        self.assertEqual(mcp_server._hidden(), set())
        self.assertEqual(len(_call("search_meetings", query="туман")[1]["meetings"]), 2)
        app_sets("false")
        self.assertIn(self.secret, mcp_server._hidden())
        self.assertEqual([m["id"] for m in _call("search_meetings", query="туман")[1]["meetings"]], [self.mid])

    def test_decisions_and_tasks_read_little_and_are_capped(self):
        """Audit В22: the decisions read every meeting of the period whole (its transcript), the tasks the directory
        for each task, and both answered without a limit."""
        from app import people

        with mock.patch("app.database.get_meeting", side_effect=AssertionError("a meeting read whole")):
            err, got = _call("list_decisions", since="2000-01-01")
        self.assertFalse(err, got)
        self.assertEqual([d["decision"] for d in got["decisions"]], ["Выпускать в пятницу"])
        self.assertNotIn("truncated", got)
        for i in range(4):
            commitments.create(f"Задача {i}", "Боря", meeting_id=self.mid)
        people.merge(["Борис", "Боря"])
        self.addCleanup(lambda: [people.remove(n) for n in ("Борис", "Боря")])
        real = database.get_connection
        with mock.patch("app.people.get_connection", side_effect=real) as conn, mock.patch.object(mcp_server, "MAX_ITEMS", 3):
            err, tasks = _call("list_tasks", scope="all", person="Борис")
        self.assertFalse(err, tasks)
        self.assertEqual((len(tasks["tasks"]), tasks["total"], tasks["truncated"]), (3, 5, True))
        self.assertLessEqual(conn.call_count, 1)

    def test_people_heard_only_in_dictations_are_not_listed(self):
        """Found in the audit: list_people counted the hidden recordings, so their speakers, calendar
        attendees and task owners reached the agent."""
        lone = database.create_meeting(title="Ещё одна закрытая", filename="c.wav", media_path="c.wav")
        database.save_meeting_results(lone["id"], segments=SEGMENTS, speakers={"SPEAKER_00": {"name": "Вера"}, "SPEAKER_01": {"name": "Анна"}},
                                      language="ru")
        database.update_meeting_progress(lone["id"], status="completed", progress=100, duration=70.0)
        database.update_meeting_fields(lone["id"], folder_id=database.system_folder_id("dictations"), user_notes="Участники по календарю: Глеб")
        commitments.create("Подписать договор", "Дина", meeting_id=lone["id"])

        names = {p["name"]: p for p in _call("list_people")[1]["people"]}
        self.assertNotIn("Вера", names)
        self.assertNotIn("Глеб", names)
        self.assertNotIn("Дина", names)
        self.assertEqual(names["Анна"]["recordings"], 1)  # only the recording the agent may read
        database.update_settings({"mcp_local_only": "true"})  # allowed by the user
        names = {p["name"] for p in _call("list_people")[1]["people"]}
        self.assertTrue({"Вера", "Глеб", "Дина"} <= names)

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
