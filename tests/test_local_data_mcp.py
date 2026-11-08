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

    def test_customer_prefix_search_is_literal_ordered_and_pageable(self) -> None:
        with closing(sqlite3.connect(self.db)) as conn:
            conn.executemany("INSERT INTO customers VALUES (?, ?, ?)", [
                (5, "alpha", "alpha@example.test"),
                (6, "Alpha Labs", "alpha-labs@example.test"),
                (7, "% Sample", "percent@example.test"),
                (8, "A_ Example", "underscore@example.test"),
            ])
            conn.commit()
        first = self.service.invoke("find_customers_by_prefix", {"prefix": "ALPHA", "limit": 1})
        self.assertEqual(["alpha"], [row["name"] for row in first["data"]["customers"]])
        self.assertTrue(first["data"]["has_more"])
        second = self.service.invoke("find_customers_by_prefix", {"prefix": "ALPHA", "limit": 1, "offset": 1})
        self.assertEqual(["Alpha Labs"], [row["name"] for row in second["data"]["customers"]])
        self.assertFalse(second["data"]["has_more"])
        literal = self.service.invoke("find_customers_by_prefix", {"prefix": "%"})
        self.assertEqual(["% Sample"], [row["name"] for row in literal["data"]["customers"]])
        underscore = self.service.invoke("find_customers_by_prefix", {"prefix": "A_"})
        self.assertEqual(["A_ Example"], [row["name"] for row in underscore["data"]["customers"]])
        self.assertEqual("invalid_input", self.service.invoke("find_customers_by_prefix", {"prefix": "A", "offset": -1})["error"]["code"])

    def test_question_and_customer_count_are_correlated_and_audited(self) -> None:
        question = "How many customers?\nPlease include all records."
        recorded = self.service.invoke("audit_record_question", {"question": question, "retrospective": False})
        question_id = recorded["_audit"]["request_id"]
        result = self.service.invoke("count_customers", {"question_id": question_id})
        self.assertEqual(4, result["data"]["customer_count"])
        events = [json.loads(line) for line in self.audit_path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(question, events[0]["arguments"]["question"])
        self.assertEqual(question_id, events[1]["arguments"]["question_id"])
        self.assertEqual(result, events[1]["result"])
        bad = self.service.invoke("count_customers", {"question_id": "00000000-0000-0000-0000-000000000000"})
        self.assertEqual("invalid_input", bad["error"]["code"])
        non_question_id = result["_audit"]["request_id"]
        bad = self.service.invoke("count_customers", {"question_id": non_question_id})
        self.assertEqual("invalid_input", bad["error"]["code"])
        bad = self.service.invoke("audit_record_question", {"question": "   "})
        self.assertEqual("invalid_input", bad["error"]["code"])
        retrospective = self.service.invoke("audit_record_question", {"question": question, "retrospective": True})
        event = json.loads(self.audit_path.read_text(encoding="utf-8").splitlines()[-1])
        self.assertTrue(event["arguments"]["retrospective"])
        self.assertEqual(retrospective["_audit"]["request_id"], event["request_id"])

    def test_customer_count_and_question_withhold_results_if_audit_fails(self) -> None:
        def fail(_event):
            raise PermissionError("audit path denied")
        self.writer.write = fail
        for tool, arguments in (("audit_record_question", {"question": "How many customers?"}), ("count_customers", {})):
            result = self.service.invoke(tool, arguments)
            self.assertEqual("audit_failure", result["error"]["code"])
            self.assertNotIn("data", result)

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

    def test_phish_state_year_count_is_exact_and_audited(self) -> None:
        db = self.root / "phish.sqlite"
        with closing(sqlite3.connect(db)) as connection:
            connection.execute("CREATE TABLE phish_shows (id INTEGER PRIMARY KEY, show_date TEXT, venue_name TEXT, city TEXT, state TEXT, country TEXT)")
            connection.executemany("INSERT INTO phish_shows VALUES (?, ?, ?, ?, ?, ?)", [
                (1, "1999-07-24", "Alpine Valley", "East Troy", "WI", "USA"),
                (2, "1999-07-25", "Alpine Valley", "East Troy", "wi", "USA"),
                (3, "1999-07-26", "Other", "Elsewhere", "WI", "Canada"),
                (4, "2000-07-24", "Alpine Valley", "East Troy", "WI", "USA"),
                (5, "1999-12-02", "Winter Tour", "Elsewhere", "MI", "USA"),
            ])
            connection.executemany("INSERT INTO phish_shows VALUES (?, '1999-08-01', 'Venue', 'East Troy', 'WI', 'USA')", [(i,) for i in range(10, 61)])
            connection.commit()
        self.service.phish_database_path = db
        q = self.service.invoke("audit_record_question", {"question": "How many?", "retrospective": False})
        result = self.service.invoke("phish_count_shows_by_state", {"state": "wi", "year": 1999, "country": "usa", "question_id": q["_audit"]["request_id"]})
        self.assertEqual(53, result["data"]["count"])
        self.assertEqual(50, len(result["data"]["shows"]))
        self.assertTrue(result["data"]["has_more"])
        self.assertEqual([1, 2], [row["id"] for row in result["data"]["shows"][:2]])
        event = json.loads(self.audit_path.read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(q["_audit"]["request_id"], event["arguments"]["question_id"])
        self.assertEqual(result, event["result"])
        injected = self.service.invoke("phish_count_shows_by_state", {"state": "WI", "year": 1999, "country": "USA' OR 1=1 --"})
        self.assertEqual(0, injected["data"]["count"])
        self.assertEqual("invalid_input", self.service.invoke("phish_count_shows_by_state", {"state": "W%", "year": 1999})["error"]["code"])
        self.assertEqual("invalid_input", self.service.invoke("phish_count_shows_by_state", {"state": "WI", "year": True})["error"]["code"])

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
                self.assertTrue({"audit_record_question", "count_customers", "find_customers", "find_customers_by_prefix", "list_customer_orders", "get_order_details", "phish_get_show", "phish_count_shows_by_state", "audit_find_events", "audit_get_event", "audit_phish_sync_runs", "audit_phish_sync_pages"}.issubset(names))
                question = payload(await session.call_tool("audit_record_question", {"question": "How many customers?"}))
                question_id = question["_audit"]["request_id"]
                missing = payload(await session.call_tool("count_customers", {}))
                self.assertEqual("invalid_input", missing["error"]["code"])
                missing_audit = payload(await session.call_tool("audit_get_event", {"request_id": missing["_audit"]["request_id"], "question_id": question_id}))
                self.assertEqual("invalid_input", missing_audit["data"]["event"]["outcome"])
                count = payload(await session.call_tool("count_customers", {"question_id": question_id}))
                self.assertEqual(4, count["data"]["customer_count"])
                prefix = payload(await session.call_tool("find_customers_by_prefix", {"prefix": "A", "question_id": question_id}))
                self.assertEqual(["Acme Analytics"], [row["name"] for row in prefix["data"]["customers"]])
                self.assertFalse(prefix["data"]["has_more"])
                audit = payload(await session.call_tool("audit_get_event", {"request_id": count["_audit"]["request_id"], "question_id": question_id}))
                self.assertEqual(question_id, audit["data"]["event"]["arguments"]["question_id"])
                search = await session.call_tool("find_customers", {"query": "Acme", "question_id": question_id})
                self.assertFalse(search.isError)
                self.assertEqual("Acme Analytics", payload(search)["data"]["customers"][0]["name"])
                orders = await session.call_tool("list_customer_orders", {"customer_id": 1, "question_id": question_id})
                self.assertFalse(orders.isError)
                self.assertEqual(1001, payload(orders)["data"]["orders"][0]["id"])
                result = await session.call_tool("get_order_details", {"order_id": 1001, "question_id": question_id})
                self.assertFalse(result.isError)
                self.assertEqual(3899, payload(result)["data"]["total_cents"])

        asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()
