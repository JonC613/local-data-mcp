"""Bounded Phish.net v5 requests and process-local, expiring show snapshots."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

MAX_BYTES = 2 * 1024 * 1024
MAX_AGE = timedelta(hours=24)
BASE = "https://api.phish.net"


class SourceError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_json(endpoint, show_date, key):
    params = urlencode({"limit": 100, "order_by": "showdate", "direction": "ASC"})
    url = f"{BASE}/v5/{endpoint}/showdate/{show_date}.json?{params}"
    request = Request(url, headers={"X-API-KEY": key, "User-Agent": "local-data-mcp/0.1", "Accept": "application/json"})
    try:
        with build_opener(_NoRedirect).open(request, timeout=15) as response:
            raw = response.read(MAX_BYTES + 1)
            status = response.status
    except (HTTPError, URLError, OSError, ValueError):
        raise SourceError("external_unavailable", "Phish.net could not be reached or rejected the request.") from None
    if status != 200 or len(raw) > MAX_BYTES:
        raise SourceError("external_unavailable", "Phish.net returned an invalid or oversized response.")
    try:
        data = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise SourceError("external_invalid_response", "Phish.net returned invalid JSON.") from None
    if not isinstance(data, dict) or data.get("error") not in (False, 0) or not isinstance(data.get("data"), list):
        raise SourceError("external_invalid_response", "Phish.net returned an API error or invalid response.")
    if any(not isinstance(row, dict) for row in data["data"]):
        raise SourceError("external_invalid_response", "Phish.net returned invalid rows.")
    return data["data"], hashlib.sha256(raw).hexdigest()


def _key():
    key = os.environ.get("PHISHNET_API_KEY", "").strip()
    if not key:
        key_file = Path(os.environ.get("PHISHNET_API_KEY_FILE", Path(__file__).resolve().parents[2] / ".env.phishnet"))
        try:
            for line in key_file.read_text(encoding="utf-8").splitlines():
                name, sep, value = line.partition("=")
                if sep and name.strip() == "PHISHNET_API_KEY":
                    key = value.strip().strip('"').strip("'")
                    break
        except (OSError, UnicodeError):
            pass
    if not key:
        raise SourceError("external_not_configured", "Configure PHISHNET_API_KEY in the server environment or local key file.")
    return key


def _field(row, name):
    value = row.get(name)
    return value if isinstance(value, (str, int, float, bool)) or value is None else None


class PhishNet:
    def __init__(self):
        self.snapshots = {}

    def refresh(self, show_date):
        key = _key()
        responses, hashes = {}, {}
        for endpoint in ("reviews", "shows", "jamcharts"):
            rows, digest = fetch_json(endpoint, show_date, key)
            # Date-scoped endpoints may include artists other than Phish.
            responses[endpoint] = [r for r in rows if str(r.get("showdate", "")) == show_date
                                   and str(r.get("artist_name", "Phish")).casefold() == "phish"]
            hashes[endpoint] = digest
            if len(rows) >= 100:
                hashes[endpoint + "_truncated"] = True
        reviews = [{name: _field(r, name) for name in
                    ("reviewid", "username", "review_text", "posted_at", "score", "permalink")}
                   for r in responses["reviews"]]
        reviews.sort(key=lambda r: (str(r["posted_at"] or ""), str(r["reviewid"] or "")), reverse=True)
        shows = [{name: _field(r, name) for name in ("showid", "venue", "city", "state", "country", "setlist_notes", "permalink")}
                 for r in responses["shows"]]
        shows.sort(key=lambda r: str(r["showid"] or ""))
        jams = [{name: _field(r, name) for name in ("uniqueid", "song", "set", "position", "jamchart_description", "permalink")}
                for r in responses["jamcharts"]]
        jams.sort(key=lambda r: (str(r["set"] or ""), str(r["position"] or ""), str(r["uniqueid"] or "")))
        captured = datetime.now(timezone.utc)
        snapshot_id = hashlib.sha256(json.dumps({"date": show_date, "hashes": hashes}, sort_keys=True).encode()).hexdigest()
        snapshot = {"source": "Phish.net", "source_url": "https://phish.net",
                    "show_date": show_date, "snapshot_id": snapshot_id,
                    "retrieved_at_utc": captured.isoformat(), "response_sha256": hashes,
                    "reviews": reviews, "shows": shows, "jamcharts": jams,
                    "upstream_limit_per_endpoint": 100,
                    "possibly_truncated_endpoints": [name for name in responses if hashes.get(name + "_truncated")]}
        snapshot["response_sha256"] = {name: hashes[name] for name in responses}
        if len(self.snapshots) >= 25 and show_date not in self.snapshots:
            del self.snapshots[next(iter(self.snapshots))]
        self.snapshots[show_date] = snapshot
        return snapshot

    def get(self, show_date):
        snapshot = self.snapshots.get(show_date)
        if snapshot is None:
            raise SourceError("snapshot_unavailable", "No snapshot for this show; refresh it first.")
        retrieved = datetime.fromisoformat(snapshot["retrieved_at_utc"])
        if datetime.now(timezone.utc) - retrieved >= MAX_AGE:
            del self.snapshots[show_date]
            raise SourceError("snapshot_expired", "The source snapshot expired; refresh it before use.")
        return snapshot
