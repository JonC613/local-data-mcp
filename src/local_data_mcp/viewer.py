"""Loopback-only, audited browser viewer for the configured local data."""

from __future__ import annotations

import argparse
import base64
import hmac
import json
import os
import secrets
import sqlite3
import webbrowser
from collections import deque
from contextlib import closing
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .audit import AuditWriter
from .database import open_readonly


TABLES = {
    "mock": ("customers", "products", "orders", "order_items"),
    "phish": ("phish_shows", "phish_tracks", "phish_songs", "phish_track_songs", "phish_sync_runs", "phish_sync_pages"),
}
STATIC = Path(__file__).with_name("viewer_static")
MAX_FILTER = 200


class ViewerError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _number(value: Any, label: str, minimum: int, maximum: int) -> int:
    if not isinstance(value, str) or not value.isascii() or not value.isdecimal() or len(value) > 12:
        raise ViewerError(f"{label} must be an integer from {minimum} to {maximum}.")
    number = int(value)
    if not minimum <= number <= maximum:
        raise ViewerError(f"{label} must be an integer from {minimum} to {maximum}.")
    return number


def _text(value: str, label: str, maximum: int = MAX_FILTER) -> str:
    if len(value) > maximum or any(ord(c) < 32 for c in value):
        raise ViewerError(f"{label} must contain at most {maximum} printable characters.")
    return value


def _date_time(value: str, label: str) -> datetime | None:
    if not value:
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError
        return result.astimezone(timezone.utc)
    except (ValueError, OverflowError) as exc:
        raise ViewerError(f"{label} must be an ISO timestamp with a timezone.") from exc


def _json_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"type": "blob", "encoding": "base64", "data": base64.b64encode(value).decode("ascii")}
    return value


class Viewer:
    def __init__(self, mock: Path, phish: Path, audit: Path):
        self.sources = {"mock": mock.expanduser().resolve(), "phish": phish.expanduser().resolve()}
        self.audit = AuditWriter(audit)

    def _source(self, source: str) -> Path:
        if source not in self.sources:
            raise ViewerError("Unknown database.")
        return self.sources[source]

    def sources_info(self, args: dict[str, str]) -> dict[str, Any]:
        return {"sources": [{"id": key, "label": "Mock database" if key == "mock" else "Phish database"}
                            for key in self.sources]}

    def tables(self, args: dict[str, str]) -> dict[str, Any]:
        source = args.get("source", "")
        path = self._source(source)
        with closing(open_readonly(path)) as connection:
            found = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        return {"source": source, "tables": [table for table in TABLES[source] if table in found]}

    def rows(self, args: dict[str, str]) -> dict[str, Any]:
        source = args.get("source", "")
        path = self._source(source)
        table = args.get("table", "")
        if table not in TABLES[source]:
            raise ViewerError("Table is not available.")
        limit = _number(args.get("limit", "50"), "limit", 1, 100)
        offset = _number(args.get("offset", "0"), "offset", 0, 1000000)
        column = _text(args.get("column", ""), "column")
        query = _text(args.get("query", ""), "query")
        if bool(column) != bool(query):
            raise ViewerError("Choose a column and enter a filter value together.")
        with closing(open_readonly(path)) as connection:
            connection.execute("BEGIN")
            exists = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
            if not exists:
                raise ViewerError("Table is unavailable in this database.", 404)
            columns = connection.execute(f"PRAGMA table_info({_quote(table)})").fetchall()
            names = [row["name"] for row in columns]
            if column and column not in names:
                raise ViewerError("Filter column is not available.")
            keys = [row["name"] for row in sorted((r for r in columns if r["pk"]), key=lambda r: r["pk"])]
            if not keys:
                # SQLite tables without a primary key can still use their unshadowed rowid.
                rowid = next((x for x in ("_rowid_", "rowid", "oid") if x not in {n.casefold() for n in names}), None)
                if rowid is None:
                    raise ViewerError("This table has no usable stable pagination key.")
                try:
                    connection.execute(f"SELECT {rowid} FROM {_quote(table)} LIMIT 0")
                except sqlite3.Error as exc:
                    raise ViewerError("This table has no usable stable pagination key.") from exc
                keys = [rowid]
            where = ""
            params: list[Any] = []
            if query:
                escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                where = f" WHERE CAST({_quote(column)} AS TEXT) LIKE ? ESCAPE '\\'"
                params.append(f"%{escaped}%")
            order = ", ".join(_quote(key) for key in keys)
            records = connection.execute(
                f"SELECT * FROM {_quote(table)}{where} ORDER BY {order} LIMIT ? OFFSET ?",
                (*params, limit + 1, offset),
            ).fetchall()
        return {"source": source, "table": table, "columns": names,
                "rows": [{key: _json_value(row[key]) for key in names} for row in records[:limit]],
                "offset": offset, "limit": limit, "has_more": len(records) > limit, "order_by": keys}

    def _audit_snapshot(self, args: dict[str, str]):
        try:
            stream = self.audit.path.open("rb")
        except FileNotFoundError as exc:
            raise ViewerError("Audit log does not exist yet.", 404) from exc
        size = os.fstat(stream.fileno()).st_size
        try:
            boundary = _number(args["snapshot"], "snapshot", 0, 2**53 - 1) if "snapshot" in args else size
            if boundary > size:
                raise ViewerError("Audit log changed; refresh the audit view.")
        except Exception:
            stream.close()
            raise
        return stream, boundary

    def audit_list(self, args: dict[str, str]) -> dict[str, Any]:
        limit = _number(args.get("limit", "50"), "limit", 1, 100)
        offset = _number(args.get("offset", "0"), "offset", 0, 10000)
        filters = {key: _text(args.get(key, ""), key) for key in ("tool", "outcome", "request_id", "start", "end")}
        start, end = _date_time(filters["start"], "start"), _date_time(filters["end"], "end")
        if start and end and start > end:
            raise ViewerError("Start time must not be after end time.")
        stream, boundary = self._audit_snapshot(args)
        matches: deque[dict[str, Any]] = deque(maxlen=offset + limit + 1)
        with stream:
            line_number = 0
            while stream.tell() < boundary:
                position = stream.tell()
                raw = stream.readline(boundary - position)
                line_number += 1
                if not raw.endswith(b"\n"):
                    raise ViewerError(f"Audit log has an incomplete line at line {line_number} (byte {position}).")
                try:
                    event = json.loads(raw)
                    if not isinstance(event, dict):
                        raise ValueError
                except (ValueError, UnicodeDecodeError, RecursionError) as exc:
                    raise ViewerError(f"Audit log has invalid JSON at line {line_number} (byte {position}).") from exc
                if any(filters[k] and event.get(k) != filters[k] for k in ("tool", "outcome", "request_id")):
                    continue
                if start or end:
                    try:
                        when = _date_time(str(event.get("timestamp_utc", "")), "event timestamp")
                    except ViewerError as exc:
                        raise ViewerError(f"Invalid timestamp at line {line_number} (byte {position}).") from exc
                    if when is None or (start and when < start) or (end and when > end):
                        continue
                matches.append({**{k: event.get(k) for k in ("timestamp_utc", "tool", "outcome", "request_id", "schema_version")},
                                "position": position})
        ordered = list(reversed(matches))
        return {"events": ordered[offset:offset + limit], "snapshot": boundary, "offset": offset,
                "limit": limit, "has_more": len(ordered) > offset + limit}

    def audit_detail(self, args: dict[str, str]) -> dict[str, Any]:
        if "snapshot" not in args:
            raise ViewerError("The audit snapshot is required.")
        stream, boundary = self._audit_snapshot(args)
        try:
            position = _number(args.get("position", ""), "position", 0, max(0, boundary - 1))
            if position >= boundary:
                raise ViewerError("Audit event is outside the snapshot.")
            if position:
                stream.seek(position - 1)
                if stream.read(1) != b"\n":
                    raise ViewerError("Audit position is not a record boundary.")
            stream.seek(position)
            raw = stream.readline(boundary - position)
            if not raw.endswith(b"\n"):
                raise ViewerError(f"Audit log has an incomplete line at byte {position}.")
            try:
                event = json.loads(raw)
                if not isinstance(event, dict):
                    raise ValueError
            except (ValueError, UnicodeDecodeError, RecursionError) as exc:
                raise ViewerError(f"Audit log has invalid JSON at byte {position}.") from exc
        finally:
            stream.close()
        return {"event": event, "snapshot": boundary, "position": position}

    def invoke(self, operation: str, args: dict[str, str]) -> tuple[int, dict[str, Any]]:
        operations = {"sources": self.sources_info, "tables": self.tables, "rows": self.rows,
                      "audit_list": self.audit_list, "audit_detail": self.audit_detail}
        try:
            data = operations[operation](args)
            status, outcome, error = 200, "success", None
            response: dict[str, Any] = {"ok": True, "data": data}
        except ViewerError as exc:
            status, outcome = exc.status, "error"
            error = {"code": "invalid_request", "message": str(exc)}
            response = {"ok": False, "error": error}
        except FileNotFoundError:
            status, outcome = 404, "error"
            error = {"code": "source_missing", "message": "The configured database was not found."}
            response = {"ok": False, "error": error}
        except (OSError, sqlite3.Error) as exc:
            status, outcome = 500, "error"
            error = {"code": "source_unavailable", "message": "The local source could not be read."}
            response = {"ok": False, "error": error}
        except Exception:
            status, outcome = 500, "error"
            error = {"code": "viewer_error", "message": "The viewer could not complete the request."}
            response = {"ok": False, "error": error}
        event = self.audit.make_event(tool=f"viewer_{operation}", arguments=args, outcome=outcome,
                                      result=response, error=error)
        response["_audit"] = {"request_id": event["request_id"]}
        try:
            self.audit.write(event)
        except (OSError, TypeError, ValueError, OverflowError, RecursionError):
            message = "Data withheld: the audit record could not be written."
            if error and error.get("message", "").startswith("Audit log has an incomplete line"):
                message = error["message"] + " The incomplete log was not modified; its audit event could not be written."
            return 503, {"ok": False, "error": {"code": "audit_failure", "message": message}}
        return status, response


class ViewerServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, viewer: Viewer, port: int = 0):
        self.viewer = viewer
        self.secret = secrets.token_urlsafe(32)
        super().__init__(("127.0.0.1", port), ViewerHandler)

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.server_port}"


class ViewerHandler(BaseHTTPRequestHandler):
    server: ViewerServer

    def log_message(self, format, *args):
        pass

    def _send(self, status: int, data: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}":
            self._send(403, b"Forbidden", "text/plain; charset=utf-8")
            return
        origin = self.headers.get("Origin")
        if origin and origin != self.server.origin:
            self._send(403, b"Forbidden", "text/plain; charset=utf-8")
            return
        parsed = urlsplit(self.path)
        static = {"/": ("index.html", "text/html; charset=utf-8"),
                  "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                  "/styles.css": ("styles.css", "text/css; charset=utf-8")}
        if parsed.path in static:
            name, content_type = static[parsed.path]
            self._send(200, (STATIC / name).read_bytes(), content_type)
            return
        operations = {"/api/sources": "sources", "/api/tables": "tables", "/api/rows": "rows",
                      "/api/audit": "audit_list", "/api/audit/detail": "audit_detail"}
        if parsed.path not in operations:
            self._send(404, b"Not found", "text/plain; charset=utf-8")
            return
        token = self.headers.get("X-Viewer-Token", "")
        if not token.isascii() or not hmac.compare_digest(token, self.server.secret):
            self._send(403, b"Forbidden", "text/plain; charset=utf-8")
            return
        try:
            values = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=16)
            if any(len(v) != 1 for v in values.values()):
                raise ValueError
            args = {key: value[0] for key, value in values.items()}
        except ValueError:
            self._send(400, b"Invalid query", "text/plain; charset=utf-8")
            return
        status, result = self.server.viewer.invoke(operations[parsed.path], args)
        self._send(status, json.dumps(result, ensure_ascii=True, allow_nan=False).encode("utf-8"), "application/json; charset=utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="View configured local SQLite databases and audit events.")
    parser.add_argument("--mock-db", type=Path, default=Path(os.environ.get("LOCAL_DATA_MCP_DB_PATH", "data/mock.sqlite")))
    parser.add_argument("--phish-db", type=Path, default=Path(os.environ.get("LOCAL_DATA_MCP_PHISH_DB_PATH", "data/phish.sqlite")))
    parser.add_argument("--audit-log", type=Path, default=Path(os.environ.get("LOCAL_DATA_MCP_AUDIT_PATH", "data/audit.jsonl")))
    parser.add_argument("--port", type=int, default=0, help="Loopback port (0 chooses an available port).")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535")
    server = ViewerServer(Viewer(args.mock_db, args.phish_db, args.audit_log), args.port)
    url = f"{server.origin}/#{server.secret}"
    print(f"Local viewer: {url}\nPress Ctrl+C to stop.", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
