from __future__ import annotations

import http.client
import json
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from local_data_mcp.database import create_database
from local_data_mcp.phish_importer import SCHEMA
from local_data_mcp.viewer import Viewer, ViewerServer


class ViewerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.mock = self.root / "mock.sqlite"
        self.phish = self.root / "phish.sqlite"
        self.audit = self.root / "audit.jsonl"
        create_database(self.mock)
        with closing(sqlite3.connect(self.phish)) as conn:
            conn.executescript(SCHEMA)
            conn.execute("INSERT INTO phish_sync_runs(id, started_at_utc, status, api_base) VALUES (1, '2026-01-01T00:00:00Z', 'succeeded', 'https://example.test')")
            conn.execute("INSERT INTO phish_shows(id, show_date, venue_name, last_synced_run_id) VALUES (1, '1999-07-24', '<script>alert(1)</script>', 1)")
            conn.execute("INSERT INTO phish_tracks(id, show_id, title, position, last_synced_run_id) VALUES (1, 1, 'Sample', 1, 1)")
            conn.execute("INSERT INTO phish_songs(id, title, last_synced_run_id) VALUES (1, 'Song', 1)")
            conn.executemany("INSERT INTO phish_track_songs(track_id, song_id, association_order) VALUES (1, 1, ?)", [(1,), (0,)])
            conn.commit()
        self.viewer = Viewer(self.mock, self.phish, self.audit)

    def tearDown(self):
        self.temp.cleanup()

    def test_readonly_tables_filter_stable_paging_and_quoted_values(self):
        before = self.mock.read_bytes()
        status, tables = self.viewer.invoke("tables", {"source": "mock"})
        self.assertEqual(200, status)
        self.assertIn("customers", tables["data"]["tables"])
        status, page = self.viewer.invoke("rows", {"source": "mock", "table": "customers", "limit": "1", "offset": "1"})
        self.assertEqual(2, page["data"]["rows"][0]["id"])
        self.assertTrue(page["data"]["has_more"])
        _, literal = self.viewer.invoke("rows", {"source": "mock", "table": "customers", "column": "name", "query": "%"})
        self.assertEqual([], literal["data"]["rows"])
        _, injection = self.viewer.invoke("rows", {"source": "mock", "table": "customers; DROP TABLE customers"})
        self.assertFalse(injection["ok"])
        _, composite = self.viewer.invoke("rows", {"source": "phish", "table": "phish_track_songs"})
        self.assertEqual([0, 1], [row["association_order"] for row in composite["data"]["rows"]])
        self.assertEqual(before, self.mock.read_bytes())

    def test_audit_snapshot_filters_detail_and_viewer_auditing(self):
        legacy = {"schema_version": 1, "request_id": "r1", "timestamp_utc": "2026-01-01T00:00:00Z", "tool": "lookup", "outcome": "success", "result": {"nested": "[depth limited]"}}
        current = {"schema_version": 2, "request_id": "r2", "timestamp_utc": "2026-01-02T00:00:00Z", "tool": "lookup", "outcome": "error", "arguments": {"a": [1, 2]}, "result": {"message": "full"}}
        self.audit.write_text(json.dumps(legacy) + "\n" + json.dumps(current) + "\n", encoding="utf-8")
        _, first = self.viewer.invoke("audit_list", {"limit": "1", "tool": "lookup"})
        self.assertEqual("r2", first["data"]["events"][0]["request_id"])
        snap = str(first["data"]["snapshot"])
        _, next_page = self.viewer.invoke("audit_list", {"limit": "1", "offset": "1", "tool": "lookup", "snapshot": snap})
        self.assertEqual("r1", next_page["data"]["events"][0]["request_id"])
        position = str(first["data"]["events"][0]["position"])
        _, detail = self.viewer.invoke("audit_detail", {"snapshot": snap, "position": position})
        self.assertEqual(current, detail["data"]["event"])
        last = json.loads(self.audit.read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual("viewer_audit_detail", last["tool"])
        self.assertEqual(detail, last["result"])
        _, timed = self.viewer.invoke("audit_list", {"snapshot": snap, "start": "2026-01-02T00:00:00Z", "outcome": "error"})
        self.assertEqual(["r2"], [row["request_id"] for row in timed["data"]["events"]])

    def test_missing_malformed_partial_and_failed_audit(self):
        status, result = self.viewer.invoke("audit_list", {})
        self.assertEqual(404, status)
        self.assertIn("does not exist", result["error"]["message"])
        self.audit.write_text("", encoding="utf-8")
        status, result = self.viewer.invoke("audit_list", {})
        self.assertEqual(200, status)
        self.assertEqual([], result["data"]["events"])
        status, error = self.viewer.invoke("tables", {"source": "mock"})
        self.assertEqual(200, status)
        missing = Viewer(self.root / "missing.sqlite", self.phish, self.audit)
        status, result = missing.invoke("tables", {"source": "mock"})
        self.assertEqual(404, status)
        self.assertFalse((self.root / "missing.sqlite").exists())
        with patch("local_data_mcp.viewer.open_readonly", side_effect=PermissionError("denied")):
            status, result = self.viewer.invoke("tables", {"source": "mock"})
        self.assertEqual(500, status)
        self.assertEqual("source_unavailable", result["error"]["code"])
        self.audit.write_bytes(b'{"valid": true}\n{invalid}\n')
        status, result = self.viewer.invoke("audit_list", {})
        self.assertEqual(400, status)
        self.assertIn("line 2", result["error"]["message"])
        self.audit.write_bytes(b'{"unfinished":')
        status, result = self.viewer.invoke("audit_list", {})
        self.assertEqual(503, status)
        self.assertIn("incomplete", result["error"]["message"])
        self.assertEqual(b'{"unfinished":', self.audit.read_bytes())
        def fail(_event):
            raise PermissionError("denied")
        self.viewer.audit.write = fail
        status, result = self.viewer.invoke("rows", {"source": "mock", "table": "customers"})
        self.assertEqual(503, status)
        self.assertEqual("audit_failure", result["error"]["code"])
        self.assertNotIn("data", result)

    def test_large_null_and_binary_values_are_preserved(self):
        long_text = "a" * 2000
        with closing(sqlite3.connect(self.phish)) as conn:
            conn.execute("INSERT INTO phish_tracks(id, show_id, title, position, last_synced_run_id) VALUES (2, 1, ?, 2, 1)", (long_text,))
            conn.execute("INSERT INTO phish_tracks(id, show_id, title, position, last_synced_run_id) VALUES (3, 1, ?, 3, 1)", (bytes([0, 255]),))
            conn.commit()
        _, result = self.viewer.invoke("rows", {"source": "phish", "table": "phish_tracks"})
        self.assertEqual(long_text, result["data"]["rows"][1]["title"])
        self.assertIsNone(result["data"]["rows"][1]["set_name"])
        self.assertEqual({"type": "blob", "encoding": "base64", "data": "AP8="}, result["data"]["rows"][2]["title"])

    def test_http_requires_token_and_valid_host_and_origin(self):
        server = ViewerServer(self.viewer)
        self.assertEqual("127.0.0.1", server.server_address[0])
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def request(path, headers):
            with closing(http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)) as conn:
                conn.request("GET", path, headers=headers)
                response = conn.getresponse()
                return response.status, response.read(), dict(response.getheaders())
        try:
            self.assertEqual(403, request("/api/sources", {})[0])
            self.assertEqual(403, request("/api/sources", {"X-Viewer-Token": server.secret, "Origin": "http://evil.test"})[0])
            self.assertEqual(403, request("/api/sources", {"X-Viewer-Token": server.secret, "Host": "evil.test"})[0])
            status, body, headers = request("/api/sources", {"X-Viewer-Token": server.secret, "Origin": server.origin})
            self.assertEqual(200, status)
            self.assertTrue(json.loads(body)["ok"])
            auth = {"X-Viewer-Token": server.secret, "Origin": server.origin}
            status, body, _ = request("/api/rows?source=phish&table=phish_shows&column=show_date&query=1999-07-24", auth)
            self.assertEqual(200, status)
            self.assertEqual("<script>alert(1)</script>", json.loads(body)["data"]["rows"][0]["venue_name"])
            status, body, _ = request("/api/audit?tool=viewer_rows", auth)
            listing = json.loads(body)["data"]
            self.assertEqual(200, status)
            self.assertEqual("viewer_rows", listing["events"][0]["tool"])
            detail_url = f"/api/audit/detail?snapshot={listing['snapshot']}&position={listing['events'][0]['position']}"
            status, body, _ = request(detail_url, auth)
            self.assertEqual("1999-07-24", json.loads(body)["data"]["event"]["arguments"]["query"])
            status, body, headers = request("/", {})
            self.assertEqual(200, status)
            self.assertIn(b"Local Data Viewer", body)
            self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
            for path, marker in (("/app.js", b"local-viewer-token"), ("/styles.css", b".sidebar")):
                status, body, _ = request(path, {})
                self.assertEqual(200, status)
                self.assertIn(marker, body)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
