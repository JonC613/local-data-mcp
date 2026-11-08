import asyncio
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from local_data_mcp.audit import AuditWriter
from local_data_mcp.phishnet import SourceError, fetch_json
from local_data_mcp.service import LookupService

DATE = "2000-09-24"


def fake_fetch(endpoint, show_date, key):
    rows = {
        "reviews": [{"showdate": DATE, "artist_name": "Phish", "reviewid": 2, "username": "fan",
                     "review_text": "Great show", "posted_at": "2001-01-01", "score": 4, "permalink": "https://phish.net/review/2"}],
        "shows": [{"showdate": DATE, "artist_name": "Phish", "showid": 9, "setlist_notes": "A note"}],
        "jamcharts": [{"showdate": DATE, "artist_name": "Phish", "uniqueid": 12, "song": "Cities",
                       "position": 1, "jamchart_description": "A long jam"}],
    }
    return rows[endpoint], endpoint + "-hash"


class PhishNetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.audit = self.root / "audit.jsonl"
        self.service = LookupService(self.root / "mock.sqlite", AuditWriter(self.audit), require_question_id=True)
        self.qid = self.service.invoke("audit_record_question", {"question": "Show reviews"})["_audit"]["request_id"]

    def call(self, name, **kw):
        return self.service.invoke(name, {"question_id": self.qid, "show_date": DATE, **kw})

    @patch.dict(os.environ, {"PHISHNET_API_KEY": "test-secret"})
    @patch("local_data_mcp.phishnet.fetch_json", side_effect=fake_fetch)
    def test_refresh_reads_audit_and_expiry(self, fetch):
        self.assertEqual("snapshot_unavailable", self.call("phish_get_show_reviews")["error"]["code"])
        result = self.call("phishnet_refresh_show")
        self.assertTrue(result["ok"])
        data = result["data"]
        reviews = self.call("phish_get_show_reviews")["data"]
        self.assertEqual("Great show", reviews["reviews"][0]["review_text"])
        self.assertEqual(data["snapshot_id"], reviews["snapshot_id"])
        self.assertEqual("Cities", self.call("phish_get_show_highlights")["data"]["jamcharts"][0]["song"])
        self.assertEqual(data["snapshot_id"], self.call("phish_get_external_source_status")["data"]["snapshot_id"])
        self.assertEqual(3, fetch.call_count)
        events = [json.loads(line) for line in self.audit.read_text().splitlines()]
        self.assertTrue(any(e["tool"] == "phishnet_refresh_started" for e in events))
        self.assertTrue(any(e["tool"] == "phishnet_refresh_show" and e["result"]["data"]["reviews"] for e in events))
        self.assertNotIn("test-secret", self.audit.read_text())
        self.service.phishnet.snapshots[DATE]["retrieved_at_utc"] = (datetime.now(timezone.utc)-timedelta(hours=25)).isoformat()
        self.assertEqual("snapshot_expired", self.call("phish_get_show_reviews")["error"]["code"])

    @patch.dict(os.environ, {"PHISHNET_API_KEY": "test-secret"})
    @patch("local_data_mcp.phishnet.fetch_json", side_effect=fake_fetch)
    def test_failed_refresh_preserves_snapshot(self, fetch):
        self.call("phishnet_refresh_show")
        old = self.call("phish_get_external_source_status")["data"]["snapshot_id"]
        fetch.side_effect = SourceError("external_unavailable", "failure")
        self.assertEqual("external_unavailable", self.call("phishnet_refresh_show")["error"]["code"])
        self.assertEqual(old, self.call("phish_get_external_source_status")["data"]["snapshot_id"])
        self.assertEqual("invalid_input", self.service.invoke("phish_get_show_reviews", {"show_date": DATE})["error"]["code"])
        self.assertEqual("invalid_input", self.call("phish_get_show_reviews", limit=51)["error"]["code"])

    @patch.dict(os.environ, {"PHISHNET_API_KEY": "test-secret"})
    @patch("local_data_mcp.phishnet.fetch_json", side_effect=fake_fetch)
    def test_audit_failure_prevents_network(self, fetch):
        self.service.audit.write = lambda event: (_ for _ in ()).throw(PermissionError("denied"))
        self.assertEqual("audit_failure", self.call("phishnet_refresh_show")["error"]["code"])
        fetch.assert_not_called()

    def test_missing_key(self):
        with patch.dict(os.environ, {"PHISHNET_API_KEY": "", "PHISHNET_API_KEY_FILE": str(self.root / "missing")}):
            self.assertEqual("external_not_configured", self.call("phishnet_refresh_show")["error"]["code"])

    def test_fetch_headers_and_malformed_responses(self):
        class Response:
            status = 200
            def __init__(self, body): self.body = body
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, limit): return self.body

        class Opener:
            def __init__(self, body): self.body = body
            def open(self, request, timeout):
                self.request = request
                self.timeout = timeout
                return Response(self.body)

        opener = Opener(b'{"error":false,"data":[]}')
        with patch("local_data_mcp.phishnet.build_opener", return_value=opener):
            rows, digest = fetch_json("reviews", DATE, "secret")
        self.assertEqual([], rows)
        self.assertEqual(64, len(digest))
        self.assertEqual("secret", opener.request.get_header("X-api-key"))
        self.assertNotIn("secret", opener.request.full_url)
        self.assertTrue(opener.request.full_url.startswith("https://api.phish.net/v5/reviews/showdate/"))
        for body in (b'bad', b'{"error": 2, "data": []}', b'{"error": false, "data": [1]}'):
            with patch("local_data_mcp.phishnet.build_opener", return_value=Opener(body)):
                with self.assertRaises(SourceError):
                    fetch_json("reviews", DATE, "secret")

    def test_mcp_tool_discovery(self):
        from local_data_mcp.server import create_server
        from mcp.shared.memory import create_connected_server_and_client_session
        async def run():
            async with create_connected_server_and_client_session(create_server(self.root / "mock", self.audit)) as session:
                names = {x.name for x in (await session.list_tools()).tools}
                self.assertTrue({"phishnet_refresh_show", "phish_get_show_reviews", "phish_get_show_highlights",
                                 "phish_get_external_source_status"} <= names)
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
