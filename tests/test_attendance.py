import asyncio
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from local_data_mcp.audit import AuditWriter
from local_data_mcp.service import LookupService


class AttendanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.catalog = self.root / "catalog.sqlite"
        self.attendance = self.root / "attendance.sqlite"
        self.audit_path = self.root / "audit.jsonl"
        with closing(sqlite3.connect(self.catalog)) as c, c:
            c.execute("CREATE TABLE phish_shows (id INTEGER PRIMARY KEY, show_date TEXT, venue_name TEXT, city TEXT, state TEXT, country TEXT)")
            c.executemany("INSERT INTO phish_shows VALUES(?,?,?,?,?,?)", [
                (1, "1999-07-24", "Alpine", "East Troy", "WI", "USA"),
                (2, "2000-09-24", "Target", "Minneapolis", "MN", "USA"),
                (3, "2000-09-24", "Other", "Minneapolis", "MN", "USA")])
        self.service = LookupService(self.root / "mock.sqlite", AuditWriter(self.audit_path), self.catalog,
                                     require_question_id=True, attendance_database_path=self.attendance)
        self.qid = self.service.invoke("audit_record_question", {"question": "Mark show attended"})["_audit"]["request_id"]

    def call(self, tool, **args):
        return self.service.invoke(tool, {"question_id": self.qid, **args})

    def test_add_list_and_idempotency(self):
        self.assertEqual(0, self.call("phish_list_attended_shows")["data"]["total"])
        self.assertFalse(self.attendance.exists())
        first = self.call("phish_add_attended_show", show_date="1999-07-24")
        self.assertTrue(first["data"]["added"])
        repeat = self.call("phish_add_attended_show", show_date="1999-07-24")
        self.assertFalse(repeat["data"]["added"])
        self.assertEqual(first["data"]["attendance"], repeat["data"]["attendance"])
        self.assertTrue(self.call("phish_add_attended_show", show_date="2000-09-24", show_id=2)["data"]["added"])
        page = self.call("phish_list_attended_shows", limit=1)["data"]
        self.assertEqual(2, page["total"])
        self.assertTrue(page["has_more"])
        self.assertEqual("Alpine", page["shows"][0]["venue_name"])
        self.assertEqual(2, self.call("phish_list_attended_shows", year=2000)["data"]["shows"][0]["show_id"])
        self.assertEqual("2000-09-24", self.call("phish_list_attended_shows", limit=1, offset=1)["data"]["shows"][0]["show_date"])
        events = [json.loads(line) for line in self.audit_path.read_text().splitlines()]
        start = next(x for x in events if x["tool"] == "phish_add_attended_show_started")
        finish = next(x for x in events if x["tool"] == "phish_add_attended_show" and x["outcome"] == "success")
        self.assertEqual(start["arguments"]["mutation_id"], finish["result"]["data"]["mutation_id"])
        self.assertEqual(self.qid, start["arguments"]["question_id"])

    def test_reject_unknown_ambiguous_invalid_and_collision(self):
        self.assertEqual("not_found", self.call("phish_add_attended_show", show_date="1998-01-01")["error"]["code"])
        self.assertEqual("ambiguous_show", self.call("phish_add_attended_show", show_date="2000-09-24")["error"]["code"])
        self.assertEqual("invalid_input", self.call("phish_add_attended_show", show_date="bad")["error"]["code"])
        self.assertEqual("invalid_input", self.call("phish_list_attended_shows", year=True)["error"]["code"])
        self.assertEqual("invalid_input", self.service.invoke("phish_list_attended_shows", {})["error"]["code"])
        self.service.attendance_database_path = self.catalog
        self.assertEqual("invalid_input", self.call("phish_add_attended_show", show_date="1999-07-24")["error"]["code"])

    def test_start_failure_prevents_save(self):
        self.service.audit.write = lambda event: (_ for _ in ()).throw(PermissionError("denied"))
        self.assertEqual("audit_failure", self.call("phish_add_attended_show", show_date="1999-07-24")["error"]["code"])
        self.assertFalse(self.attendance.exists())

    def test_completion_failure_reports_possible_save_and_retry(self):
        original = self.service.audit.write
        calls = []
        def fail_completion(event):
            calls.append(event)
            if len(calls) == 2:
                raise PermissionError("denied")
            original(event)
        self.service.audit.write = fail_completion
        result = self.call("phish_add_attended_show", show_date="1999-07-24")
        self.assertEqual("audit_failure", result["error"]["code"])
        self.assertIn("may have been saved", result["error"]["message"])
        self.service.audit.write = original
        self.assertFalse(self.call("phish_add_attended_show", show_date="1999-07-24")["data"]["added"])
        self.assertEqual(1, self.call("phish_list_attended_shows")["data"]["total"])

    def test_mcp_round_trip(self):
        from mcp.shared.memory import create_connected_server_and_client_session
        from local_data_mcp.server import create_server
        async def run():
            server = create_server(self.root / "mock", self.audit_path, self.catalog, self.attendance)
            async with create_connected_server_and_client_session(server) as session:
                def payload(result): return result.structuredContent or json.loads(result.content[0].text)
                names = {x.name for x in (await session.list_tools()).tools}
                self.assertTrue({"phish_add_attended_show", "phish_list_attended_shows"} <= names)
                q = payload(await session.call_tool("audit_record_question", {"question":"I attended 1999-07-24"}))
                qid = q["_audit"]["request_id"]
                result = payload(await session.call_tool("phish_add_attended_show", {"show_date":"1999-07-24", "question_id":qid}))
                self.assertTrue(result["data"]["added"])
                listing = payload(await session.call_tool("phish_list_attended_shows", {"question_id":qid}))
                self.assertEqual(1, listing["data"]["total"])
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()