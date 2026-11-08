from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from local_data_mcp.audit import AuditWriter
from local_data_mcp.database import DatabaseAlreadyExists, create_database
from local_data_mcp.service import LookupService


class LocalDataMcpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / "mock.sqlite"
        self.audit_path = self.root / "audit.jsonl"
        create_database(self.db)
        self.writer = AuditWriter(self.audit_path)
        self.service = LookupService(self.db, self.writer)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_seed_is_reproducible_and_requires_explicit_reset(self) -> None:
        other = self.root / "other.sqlite"
        create_database(other)
        with closing(sqlite3.connect(self.db)) as first, closing(sqlite3.connect(other)) as second:
            for table in ("customers", "products", "orders", "order_items"):
                self.assertEqual(first.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall(),
                                 second.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall())
        with self.assertRaises(DatabaseAlreadyExists):
            create_database(self.db)

    def test_copilot_configuration_is_valid_and_uses_local_server(self) -> None:
        config_path = Path(__file__).resolve().parents[1] / ".mcp.example.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        server = config["mcpServers"]["local-data-lookups"]
        self.assertEqual(["-m", "local_data_mcp.server"], server["args"])
        self.assertIn("<PROJECT_ROOT>", server["command"])
        self.assertIn("LOCAL_DATA_MCP_DB_PATH", server["env"])
        self.assertIn("<PROJECT_ROOT>", server["env"]["LOCAL_DATA_MCP_DB_PATH"])

    def test_customer_search_duplicate_names_empty_and_wildcards(self) -> None:
        result = self.service.invoke("find_customers", {"query": "Jordan Lee"})
        self.assertTrue(result["ok"])
        self.assertEqual([2, 3], [row["id"] for row in result["data"]["customers"]])
        self.assertEqual([], self.service.invoke("find_customers", {"query": "missing"})["data"]["customers"])
        self.assertEqual([], self.service.invoke("find_customers", {"query": "%"})["data"]["customers"])

    def test_orders_and_details_cross_table_and_total(self) -> None:
        orders = self.service.invoke("list_customer_orders", {"customer_id": 1})
        self.assertEqual([1001, 1002], [row["id"] for row in orders["data"]["orders"]])
        self.assertEqual([], self.service.invoke("list_customer_orders", {"customer_id": 999})["data"]["orders"])
        detail = self.service.invoke("get_order_details", {"order_id": 1001})
        self.assertEqual("Acme Analytics", detail["data"]["order"]["customer_name"])
        self.assertEqual(["Field Notebook", "USB-C Hub"], [item["product_name"] for item in detail["data"]["items"]])
        self.assertEqual(3899, detail["data"]["total_cents"])
        self.assertEqual("not_found", self.service.invoke("get_order_details", {"order_id": 999})["error"]["code"])

    def test_same_inputs_return_same_lookup_data_and_database_is_read_only(self) -> None:
        first = self.service.invoke("get_order_details", {"order_id": 1001})
        second = self.service.invoke("get_order_details", {"order_id": 1001})
        self.assertEqual(first["data"], second["data"])
        self.assertNotEqual(first["_audit"]["request_id"], second["_audit"]["request_id"])
        with self.assertRaises(sqlite3.OperationalError):
            with closing(sqlite3.connect(f"file:{self.db.as_posix()}?mode=ro", uri=True)) as connection:
                connection.execute("DELETE FROM orders")
        with closing(sqlite3.connect(self.db)) as connection:
            self.assertEqual(4, connection.execute("SELECT count(*) FROM orders").fetchone()[0])

    def test_invalid_arguments_and_unknown_tool_are_rejected_and_audited(self) -> None:
        self.assertEqual("invalid_input", self.service.invoke("find_customers", {"query": "  "})["error"]["code"])
        self.assertEqual("invalid_input", self.service.invoke("list_customer_orders", {"customer_id": True})["error"]["code"])
        self.assertEqual("invalid_input", self.service.invoke("list_customer_orders", {"customer_id": 1, "limit": 51})["error"]["code"])
        self.assertEqual("invalid_input", self.service.invoke("drop_table", {})["error"]["code"])
        events = [json.loads(line) for line in self.audit_path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(4, len(events))
        self.assertTrue(all(event["outcome"] == "invalid_input" for event in events))
        self.assertEqual(4, len({event["request_id"] for event in events}))

    def test_audit_failure_withholds_data(self) -> None:
        def fail(_event):
            raise PermissionError("audit path denied")

        self.writer.write = fail
        result = self.service.invoke("find_customers", {"query": "Acme"})
        self.assertEqual("audit_failure", result["error"]["code"])
        self.assertNotIn("data", result)

    def test_success_and_not_found_events_have_result_or_error(self) -> None:
        success_response = self.service.invoke("find_customers", {"query": "Acme"})
        not_found_response = self.service.invoke("get_order_details", {"order_id": 999})
        events = [json.loads(line) for line in self.audit_path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(["success", "not_found"], [event["outcome"] for event in events])
        self.assertIsNotNone(events[0]["result"])
        self.assertIsNotNone(events[1]["error"])
        self.assertEqual(events[0]["request_id"], success_response["_audit"]["request_id"])
        self.assertEqual(events[1]["request_id"], not_found_response["_audit"]["request_id"])

    def test_malformed_unicode_is_logged_as_valid_json(self) -> None:
        response = self.service.invoke("find_customers", {"query": "\ud800"})
        self.assertEqual("lookup_failed", response["error"]["code"])
        event = json.loads(self.audit_path.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual("error", event["outcome"])

    def test_audit_search_detail_and_self_audit(self) -> None:
        original = self.service.invoke("find_customers", {"query": "Acme"})
        request_id = original["_audit"]["request_id"]
        summaries = self.service.invoke("audit_find_events", {"tool": "find_customers", "limit": 1})
        self.assertEqual(request_id, summaries["data"]["events"][0]["request_id"])
        detail = self.service.invoke("audit_get_event", {"request_id": request_id})
        self.assertEqual("Acme", detail["data"]["event"]["arguments"]["query"])
        events = [json.loads(line) for line in self.audit_path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(detail, events[-1]["result"])
        self.assertEqual(detail["_audit"]["request_id"], events[-1]["request_id"])
        self.assertEqual("invalid_input", self.service.invoke("audit_get_event", {"request_id": "bad"})["error"]["code"])
        self.assertEqual("not_found", self.service.invoke("audit_get_event", {"request_id": "00000000-0000-0000-0000-000000000000"})["error"]["code"])

    def test_audit_preserves_complete_nested_arguments_and_responses(self) -> None:
        long_text = "x" * 1200
        arguments = {"show_date": "1999-07-24", "context": {"nested": {"values": [long_text] * 70}}}
        show = {"shows": [{"show": {"venue_name": long_text}, "tracks": [{"songs": [{"title": long_text}]}] * 70}]}
        self.service._phish_get_show = lambda args: show
        response = self.service.invoke("phish_get_show", arguments)
        event = json.loads(self.audit_path.read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(2, event["schema_version"])
        self.assertEqual(arguments, event["arguments"])
        self.assertEqual(response, event["result"])
        self.assertEqual(70, len(event["result"]["data"]["shows"][0]["tracks"]))
        failure = self.service.invoke("find_customers", {"query": long_text})
        event = json.loads(self.audit_path.read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(long_text, event["arguments"]["query"])
        self.assertEqual(failure, event["result"])

    def test_unserializable_audit_values_fail_closed(self) -> None:
        result = self.service.invoke("find_customers", {"query": object()})
        self.assertEqual("audit_failure", result["error"]["code"])
        self.assertFalse(self.audit_path.exists())

    def test_audit_lookup_fails_closed_on_bad_log_and_write_failure(self) -> None:
        self.audit_path.write_text('{bad json}\n', encoding="utf-8")
        result = self.service.invoke("audit_find_events", {})
        self.assertEqual("lookup_failed", result["error"]["code"])
        self.audit_path.write_text('', encoding="utf-8")
        def fail(_event):
            raise PermissionError("audit path denied")
        self.writer.write = fail
        result = self.service.invoke("audit_find_events", {})
        self.assertEqual("audit_failure", result["error"]["code"])
        self.assertNotIn("data", result)

    def test_phish_sync_pages_are_bounded_and_pageable(self) -> None:
        db = self.root / "phish.sqlite"
        with closing(sqlite3.connect(db)) as connection:
            connection.execute("CREATE TABLE phish_sync_pages (sync_run_id INTEGER, endpoint TEXT, request_path TEXT, page INTEGER, http_status INTEGER, attempts_json TEXT, item_count INTEGER, fetched_at_utc TEXT, response_sha256 TEXT, error_summary TEXT)")
            connection.executemany("INSERT INTO phish_sync_pages VALUES (1, 'tracks', '/tracks', ?, 200, '[]', 1, 'time', 'hash', NULL)", [(1,), (2,), (3,)])
            connection.commit()
        self.service.phish_database_path = db
        result = self.service.invoke("audit_phish_sync_pages", {"run_id": 1, "limit": 1, "offset": 1})
        self.assertEqual(2, result["data"]["pages"][0]["page"])
        self.assertEqual("invalid_input", self.service.invoke("audit_phish_sync_pages", {"run_id": 1, "offset": -1})["error"]["code"])

    def test_mcp_discovers_and_invokes_all_tools(self) -> None:
        try:
            from mcp.shared.memory import create_connected_server_and_client_session
            from local_data_mcp.server import create_server
        except ImportError as exc:
            self.skipTest(f"MCP SDK unavailable: {exc}")

        async def exercise() -> None:
            server = create_server(self.db, self.audit_path)
            async with create_connected_server_and_client_session(server) as session:
                def payload(result):
                    if result.structuredContent is not None:
                        return result.structuredContent
                    return json.loads(result.content[0].text)

                tools = await session.list_tools()
                names = {tool.name for tool in tools.tools}
                self.assertTrue({"find_customers", "list_customer_orders", "get_order_details", "phish_get_show", "audit_find_events", "audit_get_event", "audit_phish_sync_runs", "audit_phish_sync_pages"}.issubset(names))
                search = await session.call_tool("find_customers", {"query": "Acme"})
                self.assertFalse(search.isError)
                self.assertEqual("Acme Analytics", payload(search)["data"]["customers"][0]["name"])
                orders = await session.call_tool("list_customer_orders", {"customer_id": 1})
                self.assertFalse(orders.isError)
                self.assertEqual(1001, payload(orders)["data"]["orders"][0]["id"])
                result = await session.call_tool("get_order_details", {"order_id": 1001})
                self.assertFalse(result.isError)
                self.assertEqual(3899, payload(result)["data"]["total_cents"])

        asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()
