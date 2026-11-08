"""Validated deterministic lookups and audit orchestration."""

from __future__ import annotations

from datetime import date, datetime, timezone
from collections import deque
import json
import os
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Callable
from uuid import UUID, uuid4

from .audit import AuditWriter
from .database import open_readonly
from .phishnet import PhishNet, SourceError


MAX_LIMIT = 50
DEFAULT_LIMIT = 20


class InputError(ValueError):
    pass


class CatalogError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


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


def _uuid(value: Any, label: str) -> str:
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError
    except (ValueError, AttributeError) as exc:
        raise InputError(f"{label} must be a canonical lowercase UUID.") from exc
    return value


class LookupService:
    """Small allowlisted interface over a read-only SQLite connection."""

    def __init__(self, database_path: Path, audit: AuditWriter, phish_database_path: Path | None = None,
                 require_question_id: bool = False, attendance_database_path: Path | None = None):
        self.database_path = database_path
        self.audit = audit
        self.phish_database_path = phish_database_path
        self.require_question_id = require_question_id
        self.attendance_database_path = (attendance_database_path or Path(os.environ.get(
            "LOCAL_DATA_MCP_ATTENDANCE_DB_PATH", "data/attendance.sqlite"))).expanduser().resolve()
        self.phishnet = PhishNet()

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

    def _count_customers(self, args: dict[str, Any]) -> dict[str, Any]:
        with closing(open_readonly(self.database_path)) as connection:
            count = connection.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
        return {"customer_count": count}

    def _find_customers_by_prefix(self, args: dict[str, Any]) -> dict[str, Any]:
        prefix = _search_query(args.get("prefix"), "prefix")
        limit = _limit(args.get("limit", DEFAULT_LIMIT))
        offset = args.get("offset", 0)
        if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= 1000000:
            raise InputError("offset must be an integer from 0 to 1000000.")
        escaped = prefix.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        with closing(open_readonly(self.database_path)) as connection:
            rows = connection.execute(
                """SELECT id, name, email FROM customers
                   WHERE lower(name) LIKE lower(?) ESCAPE '\\'
                   ORDER BY lower(name), id LIMIT ? OFFSET ?""",
                (f"{escaped}%", limit + 1, offset),
            ).fetchall()
        return {"customers": [dict(row) for row in rows[:limit]], "offset": offset,
                "limit": limit, "has_more": len(rows) > limit}

    def _audit_record_question(self, args: dict[str, Any]) -> dict[str, Any]:
        question = args.get("question")
        if not isinstance(question, str) or not question.strip():
            raise InputError("question must be a non-empty string.")
        if not isinstance(args.get("retrospective", False), bool):
            raise InputError("retrospective must be a boolean.")
        return {"recorded": True}

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

    def _attendance_path(self) -> Path:
        path = self.attendance_database_path
        protected = {self.database_path.expanduser().resolve(), self.audit.path.expanduser().resolve()}
        if self.phish_database_path is not None:
            protected.add(self.phish_database_path.expanduser().resolve())
        if path in protected:
            raise InputError("Attendance database path must differ from catalog, mock database and audit paths.")
        return path

    def _phish_add_attended_show(self, args: dict[str, Any]) -> dict[str, Any]:
        show_date = _iso_date(args.get("show_date"), "show_date")
        show_id = args.get("show_id")
        if show_id is not None:
            show_id = _positive_id(show_id, "show_id")
        path = self._attendance_path()
        with closing(self._phish_connection()) as catalog:
            rows = catalog.execute("""SELECT id AS show_id, show_date, venue_name, city, state, country
                FROM phish_shows WHERE show_date = ? AND (? IS NULL OR id = ?) ORDER BY id""",
                (show_date, show_id, show_id)).fetchall()
        if not rows:
            return {"error": {"code": "not_found", "message": "No matching show was found in the local catalog."}}
        if len(rows) != 1:
            return {"error": {"code": "ambiguous_show", "message": "Multiple shows match that date; specify show_id."}}
        show = dict(rows[0])
        mutation_id = str(uuid4())
        start = self.audit.make_event(tool="phish_add_attended_show_started",
                                      arguments={**args, "mutation_id": mutation_id}, outcome="started")
        try:
            self.audit.write(start)
        except (OSError, TypeError, ValueError, OverflowError, RecursionError):
            raise SourceError("audit_failure", "Attendance was not changed because the start audit failed.") from None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(path)) as connection:
                connection.execute("""CREATE TABLE IF NOT EXISTS attended_shows (
                    show_id INTEGER PRIMARY KEY, show_date TEXT NOT NULL, venue_name TEXT, city TEXT,
                    state TEXT, country TEXT, added_at_utc TEXT NOT NULL)""")
                now = datetime.now(timezone.utc).isoformat(timespec="seconds")
                cursor = connection.execute("""INSERT OR IGNORE INTO attended_shows
                    (show_id, show_date, venue_name, city, state, country, added_at_utc)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""", (*show.values(), now))
                inserted = cursor.rowcount == 1
                connection.row_factory = sqlite3.Row
                saved = dict(connection.execute("SELECT * FROM attended_shows WHERE show_id = ?", (show["show_id"],)).fetchone())
                connection.commit()
        except (OSError, sqlite3.Error) as exc:
            raise CatalogError("attendance_write_failed", f"Attendance save could not be confirmed (mutation {mutation_id}); retrying is safe.") from exc
        return {"added": inserted, "attendance": saved, "mutation_id": mutation_id}

    def _phish_list_attended_shows(self, args: dict[str, Any]) -> dict[str, Any]:
        year = args.get("year")
        if year is not None and (isinstance(year, bool) or not isinstance(year, int) or not 1900 <= year <= 2200):
            raise InputError("year must be an integer from 1900 to 2200.")
        limit = _limit(args.get("limit", DEFAULT_LIMIT))
        offset = args.get("offset", 0)
        if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= 1000000:
            raise InputError("offset must be an integer from 0 to 1000000.")
        path = self._attendance_path()
        if not path.exists():
            return {"shows": [], "total": 0, "limit": limit, "offset": offset, "has_more": False}
        where = " WHERE show_date >= ? AND show_date < ?" if year is not None else ""
        params = (f"{year:04d}-01-01", f"{year + 1:04d}-01-01") if year is not None else ()
        with closing(open_readonly(path)) as connection:
            connection.execute("BEGIN")
            total = connection.execute("SELECT COUNT(*) FROM attended_shows" + where, params).fetchone()[0]
            rows = connection.execute("SELECT * FROM attended_shows" + where +
                                      " ORDER BY show_date, show_id LIMIT ? OFFSET ?", (*params, limit, offset)).fetchall()
        return {"shows": [dict(row) for row in rows], "total": total, "limit": limit,
                "offset": offset, "has_more": offset + len(rows) < total}

    def _phishnet_refresh_show(self, args: dict[str, Any]) -> dict[str, Any]:
        show_date = _iso_date(args.get("show_date"), "show_date")
        # Record intent before any network request; failure prevents the request.
        event = self.audit.make_event(tool="phishnet_refresh_started", arguments=args,
                                      outcome="started", result={"show_date": show_date})
        try:
            self.audit.write(event)
        except (OSError, TypeError, ValueError, OverflowError, RecursionError):
            raise SourceError("audit_failure", "External retrieval was withheld because audit writing failed.") from None
        return self.phishnet.refresh(show_date)

    def _phish_get_show_reviews(self, args: dict[str, Any]) -> dict[str, Any]:
        date_value = _iso_date(args.get("show_date"), "show_date")
        limit = _limit(args.get("limit", DEFAULT_LIMIT))
        snap = self.phishnet.get(date_value)
        return {k: snap[k] for k in ("source", "source_url", "show_date", "snapshot_id", "retrieved_at_utc", "response_sha256", "possibly_truncated_endpoints")} | {
            "reviews": snap["reviews"][:limit], "total_in_snapshot": len(snap["reviews"]),
            "has_more": len(snap["reviews"]) > limit}

    def _phish_get_show_highlights(self, args: dict[str, Any]) -> dict[str, Any]:
        snap = self.phishnet.get(_iso_date(args.get("show_date"), "show_date"))
        return {k: snap[k] for k in ("source", "source_url", "show_date", "snapshot_id", "retrieved_at_utc", "response_sha256", "possibly_truncated_endpoints", "shows", "jamcharts")}

    def _phish_get_external_source_status(self, args: dict[str, Any]) -> dict[str, Any]:
        snap = self.phishnet.get(_iso_date(args.get("show_date"), "show_date"))
        return {k: snap[k] for k in ("source", "source_url", "show_date", "snapshot_id", "retrieved_at_utc", "response_sha256", "possibly_truncated_endpoints")}

    def _phish_page(self, connection: sqlite3.Connection, args: dict[str, Any]) -> tuple[int, int, dict[str, Any]]:
        limit = _limit(args.get("limit", DEFAULT_LIMIT))
        offset = args.get("offset", 0)
        if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= 1000000:
            raise InputError("offset must be an integer from 0 to 1000000.")
        expected = args.get("expected_sync_id")
        if expected is not None:
            expected = _positive_id(expected, "expected_sync_id")
        if offset and expected is None:
            raise InputError("expected_sync_id is required for subsequent pages.")
        connection.execute("BEGIN")
        sync = connection.execute("SELECT id, finished_at_utc FROM phish_sync_runs WHERE status='succeeded' AND finished_at_utc IS NOT NULL ORDER BY id DESC LIMIT 1").fetchone()
        if sync is None:
            raise CatalogError("catalog_unavailable", "The local catalog has no completed successful sync.")
        if expected is not None and expected != sync["id"]:
            raise CatalogError("snapshot_changed", "The catalog has changed; restart from the first page.")
        return limit, offset, {"catalog_sync_id": sync["id"], "catalog_synced_at": sync["finished_at_utc"]}

    def _phish_statistics(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        try:
            with closing(self._phish_connection()) as connection:
                limit, offset, metadata = self._phish_page(connection, args)
                if tool == "phish_list_years":
                    query = "SELECT substr(show_date,1,4) AS year, COUNT(*) AS show_count FROM phish_shows GROUP BY substr(show_date,1,4)"
                    params: list[Any] = []
                    key, order = "years", "year ASC"
                elif tool == "phish_list_venues":
                    query = """WITH ranked AS (SELECT venue_id, venue_name, city, state, country,
                        COUNT(*) OVER (PARTITION BY venue_id) AS show_count,
                        ROW_NUMBER() OVER (PARTITION BY venue_id ORDER BY show_date DESC, id DESC) AS rn
                        FROM phish_shows WHERE venue_id IS NOT NULL)
                        SELECT venue_id, venue_name, city, state, country, show_count FROM ranked WHERE rn=1"""
                    params = []
                    term = args.get("query")
                    if term is not None:
                        term = _search_query(term).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                        query += " AND (coalesce(venue_name,'') LIKE ? ESCAPE '\\' OR coalesce(city,'') LIKE ? ESCAPE '\\')"
                        params.extend([f"%{term}%"] * 2)
                    for field in ("state", "country"):
                        value = args.get(field)
                        if value is not None:
                            query += f" AND {field} = ? COLLATE NOCASE"
                            params.append(_search_query(value, field))
                    metadata["unidentified_venue_show_count"] = connection.execute("SELECT COUNT(*) FROM phish_shows WHERE venue_id IS NULL").fetchone()[0]
                    key, order = "venues", "lower(coalesce(venue_name,'')), venue_id"
                else:
                    where, params = [], []
                    year = args.get("year")
                    if year is not None:
                        if isinstance(year, bool) or not isinstance(year, int) or not 1900 <= year <= 2200:
                            raise InputError("year must be an integer from 1900 to 2200.")
                        where.append("sh.show_date >= ? AND sh.show_date < ?")
                        params.extend([f"{year:04d}-01-01", f"{year + 1:04d}-01-01"])
                    venue_id = args.get("venue_id")
                    if venue_id is not None:
                        where.append("sh.venue_id = ?")
                        params.append(_positive_id(venue_id, "venue_id"))
                    predicate = " AND ".join(where) if where else "1=1"
                    query = f"""SELECT s.id AS song_id, s.title, s.slug, COUNT(DISTINCT t.id) AS track_count
                        FROM phish_songs s JOIN phish_track_songs ts ON ts.song_id=s.id
                        JOIN phish_tracks t ON t.id=ts.track_id JOIN phish_shows sh ON sh.id=t.show_id
                        WHERE {predicate} GROUP BY s.id, s.title, s.slug"""
                    metadata["unassociated_track_count"] = connection.execute(
                        f"""SELECT COUNT(*) FROM phish_tracks t JOIN phish_shows sh ON sh.id=t.show_id
                            WHERE {predicate} AND NOT EXISTS (SELECT 1 FROM phish_track_songs ts WHERE ts.track_id=t.id)""", params).fetchone()[0]
                    metadata["metric_definition"] = "Distinct locally associated tracks per song; medleys count for each linked song. Phish.in exclusion rules are not applied; this is not the official Phish.in statistic."
                    key, order = "songs", "track_count DESC, lower(title), song_id"
                total = connection.execute(f"SELECT COUNT(*) FROM ({query})", params).fetchone()[0]
                rows = connection.execute(f"SELECT * FROM ({query}) ORDER BY {order} LIMIT ? OFFSET ?", (*params, limit, offset)).fetchall()
                return {**metadata, key: [dict(row) for row in rows], "total": total, "limit": limit,
                        "offset": offset, "has_more": offset + len(rows) < total}
        except (sqlite3.Error, FileNotFoundError) as exc:
            raise CatalogError("catalog_unavailable", "The local catalog is missing or incompatible.") from exc

    def _phish_list_years(self, args: dict[str, Any]) -> dict[str, Any]:
        return self._phish_statistics("phish_list_years", args)

    def _phish_list_venues(self, args: dict[str, Any]) -> dict[str, Any]:
        return self._phish_statistics("phish_list_venues", args)

    def _phish_song_frequency(self, args: dict[str, Any]) -> dict[str, Any]:
        return self._phish_statistics("phish_song_frequency", args)

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

    def _phish_count_shows_by_state(self, args: dict[str, Any]) -> dict[str, Any]:
        state = args.get("state")
        if not isinstance(state, str) or len(state) != 2 or not state.isascii() or not state.isalpha():
            raise InputError("state must be a two-letter ASCII state or province code.")
        state = state.upper()
        year = args.get("year")
        if isinstance(year, bool) or not isinstance(year, int) or not 1900 <= year <= 2200:
            raise InputError("year must be an integer from 1900 to 2200.")
        country = args.get("country")
        if country is not None:
            country = _search_query(country, "country")
        where = "state = ? COLLATE NOCASE AND show_date >= ? AND show_date < ?"
        params: list[Any] = [state, f"{year:04d}-01-01", f"{year + 1:04d}-01-01"]
        if country is not None:
            where += " AND country = ? COLLATE NOCASE"
            params.append(country)
        with closing(self._phish_connection()) as connection:
            connection.execute("BEGIN")
            count = connection.execute(f"SELECT COUNT(*) FROM phish_shows WHERE {where}", params).fetchone()[0]
            rows = connection.execute(
                f"""SELECT id, show_date, venue_name, city, state, country
                    FROM phish_shows WHERE {where} ORDER BY show_date, id LIMIT 50""",
                params,
            ).fetchall()
        return {"state": state, "year": year, "country": country, "count": count,
                "shows": [dict(row) for row in rows], "has_more": count > len(rows)}

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

    def _phish_get_show_audio(self, args: dict[str, Any]) -> dict[str, Any]:
        show_date = _iso_date(args.get("show_date"), "show_date")
        with closing(self._phish_connection()) as connection:
            rows = connection.execute("""SELECT id AS show_id, show_date, venue_name, city, state, country, audio_status
                FROM phish_shows WHERE show_date=? ORDER BY id""", (show_date,)).fetchall()
        if not rows:
            return {"error": {"code": "not_found", "message": f"No show was found for {show_date}."}}
        return {"source": "Phish.in", "link_type": "show page", "availability_note": "Audio status is from the local catalog; the page and audio may have changed.",
                "shows": [{**dict(row), "url": f"https://phish.in/{show_date}"} for row in rows]}

    def _phish_find_song_audio(self, args: dict[str, Any]) -> dict[str, Any]:
        query = _search_query(args.get("query"))
        show_date = args.get("show_date")
        if show_date is not None:
            show_date = _iso_date(show_date, "show_date")
        limit = _limit(args.get("limit", DEFAULT_LIMIT))
        offset = args.get("offset", 0)
        if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= 1000000:
            raise InputError("offset must be an integer from 0 to 1000000.")
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        term = f"%{escaped}%"
        where = """(t.title LIKE ? ESCAPE '\\' OR EXISTS (
            SELECT 1 FROM phish_track_songs ts JOIN phish_songs s ON s.id=ts.song_id
            WHERE ts.track_id=t.id AND s.title LIKE ? ESCAPE '\\'))"""
        params: list[Any] = [term, term]
        if show_date is not None:
            where += " AND sh.show_date=?"
            params.append(show_date)
        with closing(self._phish_connection()) as connection:
            connection.execute("BEGIN")
            base = " FROM phish_tracks t JOIN phish_shows sh ON sh.id=t.show_id WHERE " + where
            total = connection.execute("SELECT COUNT(*)" + base, params).fetchone()[0]
            rows = connection.execute("""SELECT sh.id AS show_id, sh.show_date, sh.venue_name, sh.city, sh.state,
                t.id AS track_id, t.title AS track_title, t.slug, t.set_name, t.position, t.audio_status""" + base +
                " ORDER BY sh.show_date, sh.id, t.position, t.id LIMIT ? OFFSET ?", (*params, limit, offset)).fetchall()
        tracks = []
        for row in rows:
            track = dict(row)
            slug = track.pop("slug")
            try:
                safe_date = _iso_date(track["show_date"], "show_date")
            except InputError:
                safe_date = None
            track["url"] = (f"https://phish.in/{safe_date}/{slug}" if safe_date and isinstance(slug, str)
                            and re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug, flags=re.ASCII) else None)
            tracks.append(track)
        return {"source": "Phish.in", "link_type": "track page", "availability_note": "Audio status is from the local catalog; a medley links to the containing track. Page and audio availability may have changed.",
                "tracks": tracks, "total": total, "limit": limit, "offset": offset, "has_more": offset + len(tracks) < total}

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
        request_id = _uuid(args.get("request_id"), "request_id")
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
            "find_customers_by_prefix": self._find_customers_by_prefix,
            "count_customers": self._count_customers,
            "list_customer_orders": self._list_customer_orders,
            "get_order_details": self._get_order_details,
            "phish_find_shows": self._phish_find_shows,
            "phish_get_show": self._phish_get_show,
            "phish_count_shows_by_state": self._phish_count_shows_by_state,
            "phish_find_song_performances": self._phish_find_song_performances,
            "phish_get_show_audio": self._phish_get_show_audio,
            "phish_find_song_audio": self._phish_find_song_audio,
            "phish_list_years": self._phish_list_years,
            "phish_list_venues": self._phish_list_venues,
            "phish_song_frequency": self._phish_song_frequency,
            "phish_add_attended_show": self._phish_add_attended_show,
            "phish_list_attended_shows": self._phish_list_attended_shows,
            "phishnet_refresh_show": self._phishnet_refresh_show,
            "phish_get_show_reviews": self._phish_get_show_reviews,
            "phish_get_show_highlights": self._phish_get_show_highlights,
            "phish_get_external_source_status": self._phish_get_external_source_status,
            "audit_find_events": self._audit_find_events,
            "audit_record_question": self._audit_record_question,
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
            question_id = arguments.get("question_id")
            if self.require_question_id and tool != "audit_record_question" and question_id is None:
                raise InputError("Record the user's question with audit_record_question first, then pass its request ID as question_id.")
            if question_id is not None:
                question_id = _uuid(question_id, "question_id")
                if not any(
                    event.get("request_id") == question_id
                    and event.get("tool") == "audit_record_question"
                    and event.get("outcome") == "success"
                    for event in self._audit_events()
                ):
                    raise InputError("question_id does not identify a recorded question.")
            data = operation(arguments)
            if "error" in data:
                response = {"ok": False, "error": data["error"]}
                outcome = "not_found"
                error = data["error"]
            else:
                response = {"ok": True, "data": data}
                outcome = "success"
                error = None
        except (CatalogError, SourceError) as exc:
            response = {"ok": False, "error": {"code": exc.code, "message": str(exc)}}
            outcome = "error"
            error = response["error"]
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
            message = ("Attendance may have been saved, but its completion audit failed; retrying the same show is safe."
                       if tool == "phish_add_attended_show" and outcome == "success" else
                       "The result was withheld because its audit record could not be written.")
            return {"ok": False, "error": {"code": "audit_failure", "message": message}}
        return response
