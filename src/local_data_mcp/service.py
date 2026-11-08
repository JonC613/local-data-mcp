"""Validated deterministic lookups and audit orchestration."""

from __future__ import annotations

from datetime import date
from collections import deque
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Callable
from uuid import UUID

from .audit import AuditWriter
from .database import open_readonly


MAX_LIMIT = 50
DEFAULT_LIMIT = 20


class InputError(ValueError):
    pass


def _positive_id(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InputError(f"{label} must be a positive integer.")
    return value


def _limit(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_LIMIT:
        raise InputError(f"limit must be an integer from 1 to {MAX_LIMIT}.")
    return value


def _search_query(value: Any, label: str = "query") -> str:
    if not isinstance(value, str):
        raise InputError(f"{label} must be a string.")
    cleaned = value.strip()
    if not cleaned or len(cleaned) > 100 or any(ord(char) < 32 for char in cleaned):
        raise InputError(f"{label} must contain 1 to 100 printable characters.")
    return cleaned


def _iso_date(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise InputError(f"{label} must be an ISO date (YYYY-MM-DD).")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise InputError(f"{label} must be an ISO date (YYYY-MM-DD).") from exc
    if parsed.isoformat() != value:
        raise InputError(f"{label} must be an ISO date (YYYY-MM-DD).")
    return value


class LookupService:
    """Small allowlisted interface over a read-only SQLite connection."""

    def __init__(self, database_path: Path, audit: AuditWriter, phish_database_path: Path | None = None):
        self.database_path = database_path
        self.audit = audit
        self.phish_database_path = phish_database_path

    def _find_customers(self, args: dict[str, Any]) -> dict[str, Any]:
        query = args.get("query")
        if not isinstance(query, str):
            raise InputError("query must be a string.")
        query = query.strip()
        if not query or len(query) > 100 or any(ord(char) < 32 for char in query):
            raise InputError("query must contain 1 to 100 printable characters.")
        limit = _limit(args.get("limit", DEFAULT_LIMIT))
        escaped = query.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        with closing(open_readonly(self.database_path)) as connection:
            rows = connection.execute(
                """SELECT id, name, email FROM customers
                   WHERE lower(name) LIKE lower(?) ESCAPE '\\'
                   ORDER BY lower(name), id LIMIT ?""",
                (f"%{escaped}%", limit),
            ).fetchall()
        return {"customers": [dict(row) for row in rows]}

    def _list_customer_orders(self, args: dict[str, Any]) -> dict[str, Any]:
        customer_id = _positive_id(args.get("customer_id"), "customer_id")
        limit = _limit(args.get("limit", DEFAULT_LIMIT))
        with closing(open_readonly(self.database_path)) as connection:
            rows = connection.execute(
                """SELECT id, customer_id, ordered_at, status FROM orders
                   WHERE customer_id = ? ORDER BY ordered_at, id LIMIT ?""",
                (customer_id, limit),
            ).fetchall()
        return {"customer_id": customer_id, "orders": [dict(row) for row in rows]}

    def _get_order_details(self, args: dict[str, Any]) -> dict[str, Any]:
        order_id = _positive_id(args.get("order_id"), "order_id")
        with closing(open_readonly(self.database_path)) as connection:
            order = connection.execute(
                """SELECT o.id, o.customer_id, c.name AS customer_name, o.ordered_at, o.status
                   FROM orders o JOIN customers c ON c.id = o.customer_id WHERE o.id = ?""",
                (order_id,),
            ).fetchone()
            if order is None:
                return {"error": {"code": "not_found", "message": f"Order {order_id} was not found."}}
            items = connection.execute(
                """SELECT i.id, i.product_id, p.name AS product_name, i.quantity,
                          i.unit_price_cents, i.quantity * i.unit_price_cents AS line_total_cents
                   FROM order_items i JOIN products p ON p.id = i.product_id
                   WHERE i.order_id = ? ORDER BY i.id""",
                (order_id,),
            ).fetchall()
        item_dicts = [dict(row) for row in items]
        return {
            "order": dict(order),
            "items": item_dicts,
            "total_cents": sum(item["line_total_cents"] for item in item_dicts),
        }

    def _phish_connection(self) -> sqlite3.Connection:
        if self.phish_database_path is None:
            raise InputError("The local Phish catalog is not configured.")
        return open_readonly(self.phish_database_path)

    def _phish_find_shows(self, args: dict[str, Any]) -> dict[str, Any]:
        query = args.get("query")
        year = args.get("year")
        start_date = args.get("start_date")
        end_date = args.get("end_date")
        if query is None and year is None and start_date is None and end_date is None:
            raise InputError("Provide at least one of query, year, start_date, or end_date.")
        clauses: list[str] = []
        parameters: list[Any] = []
        if query is not None:
            term = _search_query(query)
            escaped = term.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            clauses.append("(lower(coalesce(venue_name,'')) LIKE lower(?) ESCAPE '\\' OR lower(coalesce(city,'')) LIKE lower(?) ESCAPE '\\' OR lower(coalesce(state,'')) LIKE lower(?) ESCAPE '\\' OR lower(coalesce(country,'')) LIKE lower(?) ESCAPE '\\' OR lower(coalesce(tour_name,'')) LIKE lower(?) ESCAPE '\\')")
            parameters.extend([f"%{escaped}%"] * 5)
        if year is not None:
            if isinstance(year, bool) or not isinstance(year, int) or not 1900 <= year <= 2200:
                raise InputError("year must be an integer from 1900 to 2200.")
            clauses.append("show_date >= ? AND show_date < ?")
            parameters.extend([f"{year:04d}-01-01", f"{year + 1:04d}-01-01"])
        if start_date is not None:
            start_date = _iso_date(start_date, "start_date")
            clauses.append("show_date >= ?")
            parameters.append(start_date)
        if end_date is not None:
            end_date = _iso_date(end_date, "end_date")
            clauses.append("show_date <= ?")
            parameters.append(end_date)
        if start_date and end_date and start_date > end_date:
            raise InputError("start_date must not be later than end_date.")
        limit = _limit(args.get("limit", DEFAULT_LIMIT))
        with closing(self._phish_connection()) as connection:
            rows = connection.execute(
                """SELECT id, show_date, venue_name, city, state, country, tour_name,
                          audio_status, duration_ms
                   FROM phish_shows WHERE """ + " AND ".join(clauses) +
                " ORDER BY show_date, id LIMIT ?",
                (*parameters, limit),
            ).fetchall()
        return {"shows": [dict(row) for row in rows]}

    def _phish_get_show(self, args: dict[str, Any]) -> dict[str, Any]:
        show_date = _iso_date(args.get("show_date"), "show_date")
        with closing(self._phish_connection()) as connection:
            show_rows = connection.execute(
                """SELECT id, show_date, venue_id, venue_slug, venue_name, city, state,
                          country, tour_name, audio_status, duration_ms, source_updated_at
                   FROM phish_shows WHERE show_date=? ORDER BY id""",
                (show_date,),
            ).fetchall()
            shows = []
            for show in show_rows:
                track_rows = connection.execute(
                    """SELECT id, slug, title, set_name, position, duration_ms,
                              jam_starts_at_second, audio_status, source_updated_at
                       FROM phish_tracks WHERE show_id=? ORDER BY position, id""",
                    (show["id"],),
                ).fetchall()
                tracks = []
                for track in track_rows:
                    songs = connection.execute(
                        """SELECT s.id, s.slug, s.title FROM phish_track_songs ts
                           JOIN phish_songs s ON s.id=ts.song_id
                           WHERE ts.track_id=? ORDER BY ts.association_order""",
                        (track["id"],),
                    ).fetchall()
                    tracks.append({**dict(track), "songs": [dict(song) for song in songs]})
                shows.append({"show": dict(show), "tracks": tracks})
        if not shows:
            return {"error": {"code": "not_found", "message": f"No show was found for {show_date}."}}
        return {"shows": shows}

    def _phish_find_song_performances(self, args: dict[str, Any]) -> dict[str, Any]:
        term = _search_query(args.get("query"))
        limit = _limit(args.get("limit", DEFAULT_LIMIT))
        escaped = term.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        with closing(self._phish_connection()) as connection:
            rows = connection.execute(
                """SELECT s.id AS song_id, s.title AS song_title,
                          sh.id AS show_id, sh.show_date, sh.venue_name, sh.city, sh.state,
                          t.id AS track_id, t.title AS track_title, t.set_name, t.position
                   FROM phish_songs s
                   JOIN phish_track_songs ts ON ts.song_id=s.id
                   JOIN phish_tracks t ON t.id=ts.track_id
                   JOIN phish_shows sh ON sh.id=t.show_id
                   WHERE lower(s.title) LIKE lower(?) ESCAPE '\\'
                   ORDER BY sh.show_date, sh.id, t.position, t.id, s.id LIMIT ?""",
                (f"%{escaped}%", limit),
            ).fetchall()
        return {"performances": [dict(row) for row in rows]}

    def _audit_events(self):
        """Read complete events from the configured local JSONL audit log."""
        try:
            stream = self.audit.path.open("r", encoding="utf-8")
        except FileNotFoundError:
            return
        with stream:
            for line in stream:
                if not line.endswith("\n"):
                    raise ValueError("Audit log contains an incomplete line.")
                event = json.loads(line)
                if not isinstance(event, dict):
                    raise ValueError("Audit log contains a non-object event.")
                yield event

    def _audit_find_events(self, args: dict[str, Any]) -> dict[str, Any]:
        tool = args.get("tool")
        if tool is not None:
            tool = _search_query(tool, "tool")
        limit = _limit(args.get("limit", DEFAULT_LIMIT))
        matches = deque(maxlen=limit)
        for event in self._audit_events():
            if tool is None or event.get("tool") == tool:
                matches.append({key: event.get(key) for key in
                                ("request_id", "timestamp_utc", "tool", "outcome")})
        return {"events": list(reversed(matches))}

    def _audit_get_event(self, args: dict[str, Any]) -> dict[str, Any]:
        request_id = args.get("request_id")
        try:
            if not isinstance(request_id, str) or str(UUID(request_id)) != request_id:
                raise ValueError
        except ValueError as exc:
            raise InputError("request_id must be a canonical lowercase UUID.") from exc
        for event in self._audit_events():
            if event.get("request_id") == request_id:
                return {"event": event}
        return {"error": {"code": "not_found", "message": "Audit event was not found."}}

    def _audit_phish_sync_runs(self, args: dict[str, Any]) -> dict[str, Any]:
        limit = _limit(args.get("limit", DEFAULT_LIMIT))
        with closing(self._phish_connection()) as connection:
            rows = connection.execute(
                """SELECT id, started_at_utc, finished_at_utc, status, api_base,
                          shows_pages, tracks_pages, show_count, track_count, song_count, error_summary
                   FROM phish_sync_runs ORDER BY id DESC LIMIT ?""", (limit,)
            ).fetchall()
        return {"runs": [dict(row) for row in rows]}

    def _audit_phish_sync_pages(self, args: dict[str, Any]) -> dict[str, Any]:
        run_id = _positive_id(args.get("run_id"), "run_id")
        limit = _limit(args.get("limit", DEFAULT_LIMIT))
        offset = args.get("offset", 0)
        if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= 1000000:
            raise InputError("offset must be an integer from 0 to 1000000.")
        with closing(self._phish_connection()) as connection:
            rows = connection.execute(
                """SELECT endpoint, request_path, page, http_status, attempts_json, item_count,
                          fetched_at_utc, response_sha256, error_summary
                   FROM phish_sync_pages WHERE sync_run_id=? ORDER BY endpoint, page LIMIT ? OFFSET ?""",
                (run_id, limit, offset),
            ).fetchall()
        return {"run_id": run_id, "offset": offset, "pages": [dict(row) for row in rows]}

    def invoke(self, tool: str, arguments: Any) -> dict[str, Any]:
        """Call one allowlisted operation and record its result or failure."""
        operations: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            "find_customers": self._find_customers,
            "list_customer_orders": self._list_customer_orders,
            "get_order_details": self._get_order_details,
            "phish_find_shows": self._phish_find_shows,
            "phish_get_show": self._phish_get_show,
            "phish_find_song_performances": self._phish_find_song_performances,
            "audit_find_events": self._audit_find_events,
            "audit_get_event": self._audit_get_event,
            "audit_phish_sync_runs": self._audit_phish_sync_runs,
            "audit_phish_sync_pages": self._audit_phish_sync_pages,
        }
        try:
            if not isinstance(arguments, dict):
                raise InputError("Tool arguments must be an object.")
            operation = operations.get(tool)
            if operation is None:
                raise InputError("Unsupported tool.")
            data = operation(arguments)
            if "error" in data:
                response = {"ok": False, "error": data["error"]}
                outcome = "not_found"
                error = data["error"]
            else:
                response = {"ok": True, "data": data}
                outcome = "success"
                error = None
        except InputError as exc:
            response = {"ok": False, "error": {"code": "invalid_input", "message": str(exc)}}
            outcome = "invalid_input"
            error = response["error"]
        except Exception as exc:
            response = {"ok": False, "error": {"code": "lookup_failed", "message": "The local lookup could not be completed."}}
            outcome = "error"
            error = {"type": type(exc).__name__, "message": str(exc)[:500]}
        event = self.audit.make_event(
            tool=tool, arguments=arguments, outcome=outcome,
            result=response,
            error=error if outcome != "success" else None,
        )
        response["_audit"] = {"request_id": event["request_id"]}
        try:
            self.audit.write(event)
        except (OSError, TypeError, ValueError, OverflowError, RecursionError):
            return {"ok": False, "error": {"code": "audit_failure", "message": "The lookup was withheld because its audit record could not be written."}}
        return response
