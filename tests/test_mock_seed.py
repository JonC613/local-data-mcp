from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from local_data_mcp.audit import AuditWriter
from local_data_mcp.cli import seed_mock_100
from local_data_mcp.database import SeedConflict, create_database, expand_mock_database


class MockSeedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / "mock.sqlite"
        self.audit = self.root / "audit.jsonl"
        create_database(self.db)

    def tearDown(self):
        self.temp.cleanup()

    def test_expansion_is_reproducible_linked_and_preserves_examples(self):
        other = self.root / "other.sqlite"
        create_database(other)
        with closing(sqlite3.connect(self.db)) as conn:
            original = {name: conn.execute(f"SELECT * FROM {name} ORDER BY id").fetchall()
                        for name in ("customers", "products", "orders", "order_items")}
        first = expand_mock_database(self.db)
        second = expand_mock_database(other)
        self.assertEqual(first["sha256"], second["sha256"])
        self.assertEqual({"customers": 100, "products": 100, "orders": 100, "order_items": 100}, first["counts"])
        self.assertEqual({"customers": 96, "products": 97, "orders": 96, "order_items": 95}, first["inserted"])
        with closing(sqlite3.connect(self.db)) as conn, closing(sqlite3.connect(other)) as copy:
            self.assertEqual([], conn.execute("PRAGMA foreign_key_check").fetchall())
            for name, rows in original.items():
                current = conn.execute(f"SELECT * FROM {name} ORDER BY id").fetchall()
                self.assertEqual(rows, current[:len(rows)])
                self.assertEqual(current, copy.execute(f"SELECT * FROM {name} ORDER BY id").fetchall())
            self.assertEqual(1, conn.execute("SELECT count(*) FROM customers c WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.customer_id=c.id)").fetchone()[0])
            self.assertEqual(1, conn.execute("SELECT count(*) FROM orders o WHERE NOT EXISTS (SELECT 1 FROM order_items i WHERE i.order_id=o.id)").fetchone()[0])
            self.assertEqual(2, conn.execute("SELECT count(*) FROM products p WHERE NOT EXISTS (SELECT 1 FROM order_items i WHERE i.product_id=p.id)").fetchone()[0])
        repeated = expand_mock_database(self.db)
        self.assertEqual(first["sha256"], repeated["sha256"])
        self.assertEqual({name: 0 for name in first["counts"]}, repeated["inserted"])

    def test_conflicting_data_aborts_without_partial_insert(self):
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute("UPDATE products SET name='Custom product' WHERE id=10")
            conn.commit()
        with self.assertRaises(SeedConflict):
            expand_mock_database(self.db)
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(4, conn.execute("SELECT count(*) FROM customers").fetchone()[0])
            self.assertEqual("Custom product", conn.execute("SELECT name FROM products WHERE id=10").fetchone()[0])
            self.assertEqual(4, conn.execute("SELECT count(*) FROM orders").fetchone()[0])

    def test_seed_writes_correlated_start_and_success_events(self):
        result = seed_mock_100(self.db, self.audit)
        events = [json.loads(line) for line in self.audit.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(["started", "success"], [event["outcome"] for event in events])
        self.assertEqual(result["seed_run_id"], events[0]["arguments"]["seed_run_id"])
        self.assertEqual(result["seed_run_id"], events[1]["arguments"]["seed_run_id"])
        self.assertEqual(result, events[1]["result"])

    def test_audit_start_failure_prevents_database_changes(self):
        with patch("local_data_mcp.cli.AuditWriter.write", side_effect=PermissionError("denied")):
            with self.assertRaisesRegex(RuntimeError, "No rows were added"):
                seed_mock_100(self.db, self.audit)
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(4, conn.execute("SELECT count(*) FROM customers").fetchone()[0])

    def test_completion_audit_failure_reports_committed_database(self):
        class FailCompletion:
            def __init__(self, path):
                self.writer = AuditWriter(path)
                self.calls = 0

            def make_event(self, **kwargs):
                return self.writer.make_event(**kwargs)

            def write(self, event):
                self.calls += 1
                if self.calls == 2:
                    raise PermissionError("denied")
                self.writer.write(event)

        with patch("local_data_mcp.cli.AuditWriter", FailCompletion):
            with self.assertRaisesRegex(RuntimeError, "database was updated"):
                seed_mock_100(self.db, self.audit)
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(100, conn.execute("SELECT count(*) FROM customers").fetchone()[0])
        self.assertEqual("started", json.loads(self.audit.read_text(encoding="utf-8").splitlines()[0])["outcome"])


if __name__ == "__main__":
    unittest.main()
