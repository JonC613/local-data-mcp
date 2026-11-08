"""Sync public Phish.in API v2 show and setlist data into local SQLite."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Iterator
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


API_BASE = "https://phish.in/api/v2"
ALLOWED_REDIRECT_HOSTS = {"phish.in", "www.phish.in"}
PER_PAGE = 1000
MAX_PAGES = 10_000
MAX_TOTAL_ROWS = 10_000_000
MAX_RESPONSE_BYTES = 32 * 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 30
MAX_ATTEMPTS = 5
PAGE_DELAY_SECONDS = 0.25
MAX_RETRY_DELAY_SECONDS = 30
USER_AGENT = "local-data-mcp/0.1 (local Phish.in catalog sync)"


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS phish_sync_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at_utc TEXT NOT NULL,
    finished_at_utc TEXT,
    status TEXT NOT NULL CHECK(status IN ('running', 'succeeded', 'failed')),
    api_base TEXT NOT NULL,
    shows_pages INTEGER NOT NULL DEFAULT 0,
    tracks_pages INTEGER NOT NULL DEFAULT 0,
    show_count INTEGER NOT NULL DEFAULT 0,
    track_count INTEGER NOT NULL DEFAULT 0,
    song_count INTEGER NOT NULL DEFAULT 0,
    error_summary TEXT
);

CREATE TABLE IF NOT EXISTS phish_sync_pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sync_run_id INTEGER NOT NULL REFERENCES phish_sync_runs(id),
    endpoint TEXT NOT NULL CHECK(endpoint IN ('shows', 'tracks')),
    request_path TEXT NOT NULL,
    page INTEGER NOT NULL,
    http_status INTEGER,
    attempts_json TEXT NOT NULL,
    item_count INTEGER,
    fetched_at_utc TEXT NOT NULL,
    response_sha256 TEXT,
    error_summary TEXT,
    UNIQUE(sync_run_id, endpoint, page)
);
CREATE INDEX IF NOT EXISTS phish_sync_pages_run ON phish_sync_pages(sync_run_id, endpoint, page);

CREATE TABLE IF NOT EXISTS phish_shows (
    id INTEGER PRIMARY KEY,
    show_date TEXT NOT NULL,
    venue_id INTEGER,
    venue_slug TEXT,
    venue_name TEXT,
    city TEXT,
    state TEXT,
    country TEXT,
    tour_name TEXT,
    audio_status TEXT,
    duration_ms INTEGER,
    source_updated_at TEXT,
    last_synced_run_id INTEGER NOT NULL REFERENCES phish_sync_runs(id)
);
CREATE INDEX IF NOT EXISTS phish_shows_date_id ON phish_shows(show_date, id);
CREATE INDEX IF NOT EXISTS phish_shows_venue_date ON phish_shows(venue_name, show_date, id);

CREATE TABLE IF NOT EXISTS phish_tracks (
    id INTEGER PRIMARY KEY,
    show_id INTEGER NOT NULL REFERENCES phish_shows(id) ON DELETE CASCADE,
    slug TEXT,
    title TEXT NOT NULL,
    set_name TEXT,
    position INTEGER NOT NULL CHECK(position >= 0),
    duration_ms INTEGER,
    jam_starts_at_second INTEGER,
    audio_status TEXT,
    source_updated_at TEXT,
    last_synced_run_id INTEGER NOT NULL REFERENCES phish_sync_runs(id)
);
CREATE INDEX IF NOT EXISTS phish_tracks_show_order ON phish_tracks(show_id, position, id);
CREATE INDEX IF NOT EXISTS phish_tracks_title ON phish_tracks(title, id);

CREATE TABLE IF NOT EXISTS phish_songs (
    id INTEGER PRIMARY KEY,
    slug TEXT,
    title TEXT NOT NULL,
    last_synced_run_id INTEGER NOT NULL REFERENCES phish_sync_runs(id)
);
CREATE INDEX IF NOT EXISTS phish_songs_title ON phish_songs(title, id);

CREATE TABLE IF NOT EXISTS phish_track_songs (
    track_id INTEGER NOT NULL REFERENCES phish_tracks(id) ON DELETE CASCADE,
    song_id INTEGER NOT NULL REFERENCES phish_songs(id),
    association_order INTEGER NOT NULL CHECK(association_order >= 0),
    PRIMARY KEY(track_id, association_order)
);
CREATE INDEX IF NOT EXISTS phish_track_songs_song_track ON phish_track_songs(song_id, track_id);

CREATE TABLE IF NOT EXISTS phish_stage_shows (
    sync_run_id INTEGER NOT NULL REFERENCES phish_sync_runs(id) ON DELETE CASCADE,
    id INTEGER NOT NULL,
    show_date TEXT NOT NULL,
    venue_id INTEGER,
    venue_slug TEXT,
    venue_name TEXT,
    city TEXT,
    state TEXT,
    country TEXT,
    tour_name TEXT,
    audio_status TEXT,
    duration_ms INTEGER,
    source_updated_at TEXT,
    PRIMARY KEY(sync_run_id, id)
);

CREATE TABLE IF NOT EXISTS phish_stage_tracks (
    sync_run_id INTEGER NOT NULL REFERENCES phish_sync_runs(id) ON DELETE CASCADE,
    id INTEGER NOT NULL,
    show_id INTEGER NOT NULL,
    show_date TEXT NOT NULL,
    slug TEXT,
    title TEXT NOT NULL,
    set_name TEXT,
    position INTEGER NOT NULL CHECK(position >= 0),
    duration_ms INTEGER,
    jam_starts_at_second INTEGER,
    audio_status TEXT,
    source_updated_at TEXT,
    PRIMARY KEY(sync_run_id, id),
    FOREIGN KEY(sync_run_id, show_id) REFERENCES phish_stage_shows(sync_run_id, id) DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE IF NOT EXISTS phish_stage_track_songs (
    sync_run_id INTEGER NOT NULL,
    track_id INTEGER NOT NULL,
    song_id INTEGER NOT NULL,
    association_order INTEGER NOT NULL CHECK(association_order >= 0),
    slug TEXT,
    title TEXT NOT NULL,
    PRIMARY KEY(sync_run_id, track_id, association_order),
    FOREIGN KEY(sync_run_id, track_id) REFERENCES phish_stage_tracks(sync_run_id, id) ON DELETE CASCADE
);
"""


class PhishSyncError(RuntimeError):
    """Raised when the remote snapshot cannot be validated or published."""


class _SafeRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urlsplit(newurl)
        if (
            target.scheme != "https"
            or (target.hostname or "").lower() not in ALLOWED_REDIRECT_HOSTS
            or target.port not in (None, 443)
            or target.username is not None
            or target.password is not None
        ):
            raise HTTPError(req.full_url, code, "redirect blocked by Phish.in host policy", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _PageRequestError(PhishSyncError):
    def __init__(self, message: str, *, status: int | None, attempts: list[dict[str, Any]], digest: str | None):
        super().__init__(message)
        self.status = status
        self.attempts = attempts
        self.digest = digest


@contextmanager
def _transaction(connection: sqlite3.Connection) -> Iterator[None]:
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield
    except Exception:
        connection.rollback()
        raise
    else:
        connection.commit()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _resolve_database_path(path: Path | None) -> Path:
    configured = path or Path(
        os.environ.get("LOCAL_DATA_MCP_PHISH_DB_PATH", "data/phish.sqlite")
    )
    resolved = configured.expanduser().resolve()
    mock_path = os.environ.get("LOCAL_DATA_MCP_DB_PATH")
    if mock_path and resolved == Path(mock_path).expanduser().resolve():
        raise ValueError("The Phish catalog must use a separate SQLite file from the mock database.")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    return connection


def _initialize(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA)
    _migrate_zero_positions(connection)
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat(timespec="seconds").replace("+00:00", "Z")
    with _transaction(connection):
        stale = connection.execute(
            "SELECT id FROM phish_sync_runs WHERE status = 'running' AND started_at_utc < ?", (cutoff,)
        ).fetchall()
        for row in stale:
            run_id = row["id"]
            _clear_stage(connection, run_id)
            connection.execute(
                "UPDATE phish_sync_runs SET status='failed', finished_at_utc=?, error_summary=? WHERE id=?",
                (_utc_now(), "Previous sync was interrupted; temporary rows were cleared.", run_id),
            )


def _migrate_zero_positions(connection: sqlite3.Connection) -> None:
    """Allow the source's legitimate zero positions without losing an existing catalog."""
    definitions = {
        "phish_tracks": """CREATE TABLE phish_tracks_position_migration (
            id INTEGER PRIMARY KEY,
            show_id INTEGER NOT NULL REFERENCES phish_shows(id) ON DELETE CASCADE,
            slug TEXT, title TEXT NOT NULL, set_name TEXT,
            position INTEGER NOT NULL CHECK(position >= 0),
            duration_ms INTEGER, jam_starts_at_second INTEGER, audio_status TEXT,
            source_updated_at TEXT,
            last_synced_run_id INTEGER NOT NULL REFERENCES phish_sync_runs(id)
        )""",
        "phish_stage_tracks": """CREATE TABLE phish_stage_tracks_position_migration (
            sync_run_id INTEGER NOT NULL REFERENCES phish_sync_runs(id) ON DELETE CASCADE,
            id INTEGER NOT NULL, show_id INTEGER NOT NULL, show_date TEXT NOT NULL,
            slug TEXT, title TEXT NOT NULL, set_name TEXT,
            position INTEGER NOT NULL CHECK(position >= 0),
            duration_ms INTEGER, jam_starts_at_second INTEGER, audio_status TEXT,
            source_updated_at TEXT,
            PRIMARY KEY(sync_run_id, id),
            FOREIGN KEY(sync_run_id, show_id) REFERENCES phish_stage_shows(sync_run_id, id) DEFERRABLE INITIALLY DEFERRED
        )""",
    }
    connection.execute("PRAGMA foreign_keys = OFF")
    try:
        with _transaction(connection):
            for table, create_sql in definitions.items():
                row = connection.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
                ).fetchone()
                if row is None or "position>0" not in row["sql"].replace(" ", "").lower():
                    continue
                temporary = f"{table}_position_migration"
                connection.execute(f"DROP TABLE IF EXISTS {temporary}")
                connection.execute(create_sql)
                column_names = [column[1] for column in connection.execute(f"PRAGMA table_info({table})")]
                columns = ", ".join(column_names)
                connection.execute(
                    f"INSERT INTO {temporary} ({columns}) SELECT {columns} FROM {table}"
                )
                connection.execute(f"DROP TABLE {table}")
                connection.execute(f"ALTER TABLE {temporary} RENAME TO {table}")
        connection.execute("CREATE INDEX IF NOT EXISTS phish_tracks_show_order ON phish_tracks(show_id, position, id)")
        connection.execute("CREATE INDEX IF NOT EXISTS phish_tracks_title ON phish_tracks(title, id)")
    finally:
        connection.execute("PRAGMA foreign_keys = ON")
    violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise PhishSyncError("The SQLite catalog has foreign key violations after schema migration.")


def _clear_stage(connection: sqlite3.Connection, run_id: int) -> None:
    connection.execute("DELETE FROM phish_stage_track_songs WHERE sync_run_id = ?", (run_id,))
    connection.execute("DELETE FROM phish_stage_tracks WHERE sync_run_id = ?", (run_id,))
    connection.execute("DELETE FROM phish_stage_shows WHERE sync_run_id = ?", (run_id,))


def _start_run(connection: sqlite3.Connection) -> int:
    with _transaction(connection):
        running = connection.execute(
            "SELECT id FROM phish_sync_runs WHERE status='running' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if running is not None:
            raise PhishSyncError(f"Phish sync run {running['id']} is already running.")
        cursor = connection.execute(
            "INSERT INTO phish_sync_runs(started_at_utc, status, api_base) VALUES (?, 'running', ?)",
            (_utc_now(), API_BASE),
        )
        return int(cursor.lastrowid)


def _optional_text(value: Any, label: str, *, maximum: int = 500) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise PhishSyncError(f"{label} must be text or null.")
    cleaned = value.strip()
    if len(cleaned) > maximum or any(ord(char) < 32 and char not in "\t\n\r" for char in cleaned):
        raise PhishSyncError(f"{label} is outside the accepted text bounds.")
    return cleaned or None


def _required_text(value: Any, label: str, *, maximum: int = 500) -> str:
    cleaned = _optional_text(value, label, maximum=maximum)
    if not cleaned:
        raise PhishSyncError(f"{label} is required.")
    return cleaned


def _positive_integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PhishSyncError(f"{label} must be a positive integer.")
    return value


def _optional_nonnegative_integer(value: Any, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PhishSyncError(f"{label} must be a non-negative integer or null.")
    return value


def _show_date(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) < 10:
        raise PhishSyncError(f"{label} must contain an ISO show date.")
    date_text = value[:10]
    try:
        parsed = date.fromisoformat(date_text)
    except ValueError as exc:
        raise PhishSyncError(f"{label} is not a valid ISO show date.") from exc
    if parsed.isoformat() != date_text:
        raise PhishSyncError(f"{label} is not a canonical ISO show date.")
    return date_text


def _show_row(item: Any) -> tuple[Any, ...]:
    if not isinstance(item, dict):
        raise PhishSyncError("A show row is not an object.")
    venue = item.get("venue") or {}
    if not isinstance(venue, dict):
        raise PhishSyncError("A show's venue is not an object.")
    return (
        _positive_integer(item.get("id"), "show.id"),
        _show_date(item.get("date"), "show.date"),
        _optional_nonnegative_integer(venue.get("id"), "venue.id"),
        _optional_text(venue.get("slug"), "venue.slug"),
        _optional_text(item.get("venue_name") or venue.get("name"), "venue name"),
        _optional_text(venue.get("city") or item.get("city"), "venue city"),
        _optional_text(venue.get("state") or item.get("state"), "venue state"),
        _optional_text(venue.get("country") or item.get("country"), "venue country"),
        _optional_text(item.get("tour_name"), "tour_name"),
        _optional_text(item.get("audio_status"), "audio_status"),
        _optional_nonnegative_integer(item.get("duration"), "show.duration"),
        _optional_text(item.get("updated_at"), "show.updated_at"),
    )


def _track_rows(item: Any) -> tuple[tuple[Any, ...], list[tuple[Any, ...]]]:
    if not isinstance(item, dict):
        raise PhishSyncError("A track row is not an object.")
    show = item.get("show")
    if not isinstance(show, dict):
        raise PhishSyncError("A track is missing its nested show object.")
    track_id = _positive_integer(item.get("id"), "track.id")
    show_id = _positive_integer(show.get("id"), "track.show.id")
    source_date = _show_date(item.get("show_date") or show.get("date"), "track.show_date")
    position = _optional_nonnegative_integer(item.get("position"), "track.position")
    if position is None:
        raise PhishSyncError("track.position is required.")
    track = (
        track_id,
        show_id,
        source_date,
        _optional_text(item.get("slug"), "track.slug"),
        _required_text(item.get("title"), "track.title"),
        _optional_text(item.get("set_name"), "track.set_name", maximum=40),
        position,
        _optional_nonnegative_integer(item.get("duration"), "track.duration"),
        _optional_nonnegative_integer(item.get("jam_starts_at_second"), "track.jam_starts_at_second"),
        _optional_text(item.get("audio_status"), "track.audio_status"),
        _optional_text(item.get("updated_at"), "track.updated_at"),
    )
    songs = item.get("songs") or []
    if not isinstance(songs, list):
        raise PhishSyncError("track.songs must be an array or null.")
    associations: list[tuple[Any, ...]] = []
    for order, song in enumerate(songs):
        if not isinstance(song, dict):
            raise PhishSyncError("A track song association is not an object.")
        associations.append((
            track_id,
            _positive_integer(song.get("id"), "song.id"),
            order,
            _optional_text(song.get("slug"), "song.slug"),
            _required_text(song.get("title"), "song.title"),
        ))
    return track, associations


def _redirect_safe_opener():
    return build_opener(_SafeRedirectHandler())


def _retry_delay(attempt: int, retry_after: str | None) -> float:
    if retry_after:
        try:
            return min(MAX_RETRY_DELAY_SECONDS, max(0.0, float(retry_after)))
        except ValueError:
            try:
                when = parsedate_to_datetime(retry_after)
                if when.tzinfo is None:
                    when = when.replace(tzinfo=timezone.utc)
                return min(MAX_RETRY_DELAY_SECONDS, max(0.0, (when - datetime.now(timezone.utc)).total_seconds()))
            except (TypeError, ValueError, OverflowError):
                pass
    return min(MAX_RETRY_DELAY_SECONDS, 0.5 * (2 ** (attempt - 1)))


def _request_page(path: str, page: int, sort: str) -> tuple[bytes, int, list[dict[str, Any]], str]:
    query = urlencode({
        "page": page,
        "per_page": PER_PAGE,
        "sort": sort,
        "audio_status": "any",
    })
    relative_path = f"/{path}?{query}"
    url = f"{API_BASE}/{path}?{query}"
    request = Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    attempts: list[dict[str, Any]] = []
    opener = _redirect_safe_opener()
    last_status: int | None = None
    last_digest: str | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            with opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
                status = int(response.status)
                if len(body) > MAX_RESPONSE_BYTES:
                    body = body[:MAX_RESPONSE_BYTES]
                    digest = hashlib.sha256(body).hexdigest()
                    attempts.append({"attempt": attempt, "status": status, "result": "response_too_large"})
                    raise _PageRequestError(
                        f"{path} page {page} exceeded the {MAX_RESPONSE_BYTES}-byte response limit.",
                        status=status,
                        attempts=attempts,
                        digest=digest,
                    )
                digest = hashlib.sha256(body).hexdigest()
                attempts.append({"attempt": attempt, "status": status})
                if status != 200:
                    raise _PageRequestError(
                        f"{path} page {page} returned HTTP {status}.",
                        status=status,
                        attempts=attempts,
                        digest=digest,
                    )
                return body, status, attempts, digest
        except HTTPError as exc:
            last_status = exc.code
            try:
                body = exc.read(MAX_RESPONSE_BYTES + 1)
            except Exception:
                body = b""
            last_digest = hashlib.sha256(body[:MAX_RESPONSE_BYTES]).hexdigest() if body else None
            attempts.append({"attempt": attempt, "status": exc.code})
            if exc.code not in (429, 500, 502, 503, 504) or attempt == MAX_ATTEMPTS:
                raise _PageRequestError(
                    f"{path} page {page} returned HTTP {exc.code}.",
                    status=exc.code,
                    attempts=attempts,
                    digest=last_digest,
                ) from exc
            time.sleep(_retry_delay(attempt, exc.headers.get("Retry-After") if exc.headers else None))
        except _PageRequestError:
            raise
        except URLError as exc:
            attempts.append({"attempt": attempt, "status": None, "result": type(exc).__name__})
            if attempt == MAX_ATTEMPTS:
                raise _PageRequestError(
                    f"{path} page {page} could not be fetched after {MAX_ATTEMPTS} attempts.",
                    status=last_status,
                    attempts=attempts,
                    digest=last_digest,
                ) from exc
            time.sleep(_retry_delay(attempt, None))
        except TimeoutError as exc:
            attempts.append({"attempt": attempt, "status": None, "result": "timeout"})
            if attempt == MAX_ATTEMPTS:
                raise _PageRequestError(
                    f"{path} page {page} timed out after {MAX_ATTEMPTS} attempts.",
                    status=last_status,
                    attempts=attempts,
                    digest=last_digest,
                ) from exc
            time.sleep(_retry_delay(attempt, None))

    raise _PageRequestError(
        f"{path} page {page} could not be fetched.",
        status=last_status,
        attempts=attempts,
        digest=last_digest,
    )


def _log_page(
    connection: sqlite3.Connection,
    *,
    run_id: int,
    endpoint: str,
    path: str,
    page: int,
    status: int | None,
    attempts: list[dict[str, Any]],
    item_count: int | None,
    digest: str | None,
    error: str | None,
) -> None:
    query = urlencode({"page": page, "per_page": PER_PAGE, "sort": "date:asc" if endpoint == "shows" else "id:asc", "audio_status": "any"})
    with _transaction(connection):
        connection.execute(
            """INSERT INTO phish_sync_pages
               (sync_run_id, endpoint, request_path, page, http_status, attempts_json,
                item_count, fetched_at_utc, response_sha256, error_summary)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (run_id, endpoint, f"/{path}?{query}", page, status,
             json.dumps(attempts, separators=(",", ":")), item_count, _utc_now(), digest,
             error[:500] if error else None),
        )


def _page_metadata(payload: Any, *, endpoint: str, page: int) -> tuple[list[Any], int, int, int]:
    if not isinstance(payload, dict):
        raise PhishSyncError(f"{endpoint} page {page} response must be a JSON object.")
    items = payload.get(endpoint)
    if not isinstance(items, list):
        raise PhishSyncError(f"{endpoint} page {page} is missing its '{endpoint}' array.")
    current_page = _positive_integer(payload.get("current_page"), f"{endpoint}.current_page")
    total_pages = _optional_nonnegative_integer(payload.get("total_pages"), f"{endpoint}.total_pages")
    total_entries = _optional_nonnegative_integer(payload.get("total_entries"), f"{endpoint}.total_entries")
    if total_pages is None or total_entries is None:
        raise PhishSyncError(f"{endpoint} page {page} is missing pagination totals.")
    if current_page != page:
        raise PhishSyncError(f"{endpoint} page {page} returned current_page={current_page}.")
    if total_pages > MAX_PAGES or total_entries > MAX_TOTAL_ROWS:
        raise PhishSyncError(f"{endpoint} pagination exceeds configured safety limits.")
    if len(items) > PER_PAGE:
        raise PhishSyncError(f"{endpoint} page {page} contains more than {PER_PAGE} rows.")
    if total_entries and total_pages == 0:
        raise PhishSyncError(f"{endpoint} reports entries but no pages.")
    if total_entries == 0 and items:
        raise PhishSyncError(f"{endpoint} reports zero entries but returned rows.")
    if not total_entries and (total_pages not in (0, 1)):
        raise PhishSyncError(f"{endpoint} reports an invalid empty pagination state.")
    return items, total_pages, total_entries, current_page


def _record_page_failure(
    connection: sqlite3.Connection,
    *,
    run_id: int,
    endpoint: str,
    path: str,
    page: int,
    error: Exception,
    status: int | None = None,
    attempts: list[dict[str, Any]] | None = None,
    digest: str | None = None,
    item_count: int | None = None,
) -> None:
    if isinstance(error, _PageRequestError):
        status = error.status
        attempts = error.attempts
        digest = error.digest
    try:
        _log_page(
            connection,
            run_id=run_id,
            endpoint=endpoint,
            path=path,
            page=page,
            status=status,
            attempts=attempts or [],
            item_count=item_count,
            digest=digest,
            error=f"{type(error).__name__}: {error}",
        )
    except sqlite3.IntegrityError:
        # A page may already have a success ledger row if staging failed afterward.
        with _transaction(connection):
            connection.execute(
                "UPDATE phish_sync_pages SET error_summary=? WHERE sync_run_id=? AND endpoint=? AND page=?",
                (f"{type(error).__name__}: {error}"[:500], run_id, endpoint, page),
            )


def _sync_endpoint(
    connection: sqlite3.Connection,
    *,
    run_id: int,
    endpoint: str,
    array_key: str,
    sort: str,
) -> tuple[int, int]:
    page = 1
    expected_pages: int | None = None
    expected_entries: int | None = None
    total_items = 0
    while True:
        try:
            body, status, attempts, digest = _request_page(endpoint, page, sort)
            try:
                payload = json.loads(body)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise PhishSyncError(f"{endpoint} page {page} returned invalid JSON.") from exc
            items, total_pages, total_entries, current_page = _page_metadata(
                payload, endpoint=array_key, page=page
            )
            if expected_pages is None:
                expected_pages, expected_entries = total_pages, total_entries
            elif total_pages != expected_pages or total_entries != expected_entries:
                raise PhishSyncError(f"{endpoint} pagination totals changed during the sync.")
            if expected_pages and page > expected_pages:
                raise PhishSyncError(f"{endpoint} returned an unexpected page beyond total_pages.")

            show_rows: list[tuple[Any, ...]] = []
            track_rows: list[tuple[Any, ...]] = []
            song_rows: list[tuple[Any, ...]] = []
            if endpoint == "shows":
                show_rows = [_show_row(item) for item in items]
            else:
                for item in items:
                    track, songs = _track_rows(item)
                    track_rows.append(track)
                    song_rows.extend(songs)

            try:
                with _transaction(connection):
                    if endpoint == "shows":
                        connection.executemany(
                            """INSERT INTO phish_stage_shows
                               (sync_run_id, id, show_date, venue_id, venue_slug, venue_name,
                                city, state, country, tour_name, audio_status, duration_ms, source_updated_at)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            [(run_id, *row) for row in show_rows],
                        )
                    else:
                        connection.executemany(
                            """INSERT INTO phish_stage_tracks
                               (sync_run_id, id, show_id, show_date, slug, title, set_name,
                                position, duration_ms, jam_starts_at_second, audio_status, source_updated_at)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            [(run_id, *row) for row in track_rows],
                        )
                        connection.executemany(
                            """INSERT INTO phish_stage_track_songs
                               (sync_run_id, track_id, song_id, association_order, slug, title)
                               VALUES (?, ?, ?, ?, ?, ?)""",
                            [(run_id, *row) for row in song_rows],
                        )
                    connection.execute(
                        """INSERT INTO phish_sync_pages
                           (sync_run_id, endpoint, request_path, page, http_status, attempts_json,
                            item_count, fetched_at_utc, response_sha256)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (run_id, endpoint,
                         f"/{endpoint}?{urlencode({'page': page, 'per_page': PER_PAGE, 'sort': sort, 'audio_status': 'any'})}",
                         page, status, json.dumps(attempts, separators=(",", ":")), len(items),
                         _utc_now(), digest),
                    )
                    page_count_column = "shows_pages" if endpoint == "shows" else "tracks_pages"
                    connection.execute(
                        f"UPDATE phish_sync_runs SET {page_count_column}=? WHERE id=?",
                        (page, run_id),
                    )
            except Exception as exc:
                _record_page_failure(
                    connection, run_id=run_id, endpoint=endpoint, path=endpoint, page=page,
                    error=exc, status=status, attempts=attempts, digest=digest, item_count=len(items),
                )
                raise

            total_items += len(items)
            if current_page >= total_pages or total_entries == 0:
                break
            page += 1
            time.sleep(PAGE_DELAY_SECONDS)
        except _PageRequestError as exc:
            _record_page_failure(connection, run_id=run_id, endpoint=endpoint, path=endpoint, page=page, error=exc)
            raise
        except Exception as exc:
            # Keep a digest and HTTP status for responses that reached the parser but failed validation.
            if "status" in locals() and "digest" in locals() and not connection.execute(
                "SELECT 1 FROM phish_sync_pages WHERE sync_run_id=? AND endpoint=? AND page=?",
                (run_id, endpoint, page),
            ).fetchone():
                _record_page_failure(
                    connection, run_id=run_id, endpoint=endpoint, path=endpoint, page=page,
                    error=exc, status=status, attempts=attempts, digest=digest,
                    item_count=len(items) if "items" in locals() and isinstance(items, list) else None,
                )
            raise

    if expected_entries is None or total_items != expected_entries:
        raise PhishSyncError(
            f"{endpoint} yielded {total_items} rows but reported {expected_entries} total entries."
        )
    staged_count = connection.execute(
        f"SELECT count(*) FROM phish_stage_{'shows' if endpoint == 'shows' else 'tracks'} WHERE sync_run_id=?",
        (run_id,),
    ).fetchone()[0]
    if staged_count != expected_entries:
        raise PhishSyncError(f"{endpoint} staged {staged_count} unique rows but reported {expected_entries}.")
    return int(expected_pages or 0), int(expected_entries)


def _validate_staging(connection: sqlite3.Connection, run_id: int) -> None:
    missing = connection.execute(
        """SELECT count(*) FROM phish_stage_tracks t
           LEFT JOIN phish_stage_shows s ON s.sync_run_id=t.sync_run_id AND s.id=t.show_id
           WHERE t.sync_run_id=? AND (s.id IS NULL OR s.show_date <> t.show_date)""",
        (run_id,),
    ).fetchone()[0]
    if missing:
        raise PhishSyncError(f"{missing} track rows do not match a staged show ID/date.")
    song_rows = connection.execute(
        "SELECT count(*) FROM phish_stage_track_songs WHERE sync_run_id=?", (run_id,)
    ).fetchone()[0]
    bad_songs = connection.execute(
        """SELECT count(*) FROM phish_stage_track_songs s
           LEFT JOIN phish_stage_tracks t ON t.sync_run_id=s.sync_run_id AND t.id=s.track_id
           WHERE s.sync_run_id=? AND t.id IS NULL""",
        (run_id,),
    ).fetchone()[0]
    if bad_songs:
        raise PhishSyncError(f"{bad_songs} song associations do not match a staged track.")


def _publish(connection: sqlite3.Connection, run_id: int, show_count: int, track_count: int) -> int:
    song_count = int(connection.execute(
        "SELECT count(DISTINCT song_id) FROM phish_stage_track_songs WHERE sync_run_id=?", (run_id,)
    ).fetchone()[0])
    with _transaction(connection):
        connection.execute(
            """INSERT INTO phish_shows
               (id, show_date, venue_id, venue_slug, venue_name, city, state, country, tour_name,
                audio_status, duration_ms, source_updated_at, last_synced_run_id)
               SELECT id, show_date, venue_id, venue_slug, venue_name, city, state, country, tour_name,
                      audio_status, duration_ms, source_updated_at, sync_run_id
               FROM phish_stage_shows WHERE sync_run_id=?
               ON CONFLICT(id) DO UPDATE SET
                 show_date=excluded.show_date, venue_id=excluded.venue_id, venue_slug=excluded.venue_slug,
                 venue_name=excluded.venue_name, city=excluded.city, state=excluded.state,
                 country=excluded.country, tour_name=excluded.tour_name, audio_status=excluded.audio_status,
                 duration_ms=excluded.duration_ms, source_updated_at=excluded.source_updated_at,
                 last_synced_run_id=excluded.last_synced_run_id""",
            (run_id,),
        )
        connection.execute(
            """INSERT INTO phish_songs(id, slug, title, last_synced_run_id)
               SELECT song_id, MIN(slug), MIN(title), ? FROM phish_stage_track_songs WHERE sync_run_id=?
               GROUP BY song_id
               ON CONFLICT(id) DO UPDATE SET slug=excluded.slug, title=excluded.title,
                 last_synced_run_id=excluded.last_synced_run_id""",
            (run_id, run_id),
        )
        connection.execute(
            """INSERT INTO phish_tracks
               (id, show_id, slug, title, set_name, position, duration_ms, jam_starts_at_second,
                audio_status, source_updated_at, last_synced_run_id)
               SELECT id, show_id, slug, title, set_name, position, duration_ms, jam_starts_at_second,
                      audio_status, source_updated_at, sync_run_id
               FROM phish_stage_tracks WHERE sync_run_id=?
               ON CONFLICT(id) DO UPDATE SET
                 show_id=excluded.show_id, slug=excluded.slug, title=excluded.title,
                 set_name=excluded.set_name, position=excluded.position, duration_ms=excluded.duration_ms,
                 jam_starts_at_second=excluded.jam_starts_at_second, audio_status=excluded.audio_status,
                 source_updated_at=excluded.source_updated_at, last_synced_run_id=excluded.last_synced_run_id""",
            (run_id,),
        )
        connection.execute(
            """DELETE FROM phish_track_songs
               WHERE track_id IN (SELECT id FROM phish_stage_tracks WHERE sync_run_id=?)""",
            (run_id,),
        )
        connection.execute(
            """INSERT INTO phish_track_songs(track_id, song_id, association_order)
               SELECT track_id, song_id, association_order FROM phish_stage_track_songs WHERE sync_run_id=?""",
            (run_id,),
        )
        connection.execute(
            """DELETE FROM phish_tracks
               WHERE NOT EXISTS (SELECT 1 FROM phish_stage_tracks s WHERE s.sync_run_id=? AND s.id=phish_tracks.id)""",
            (run_id,),
        )
        connection.execute(
            """DELETE FROM phish_shows
               WHERE NOT EXISTS (SELECT 1 FROM phish_stage_shows s WHERE s.sync_run_id=? AND s.id=phish_shows.id)""",
            (run_id,),
        )
        connection.execute(
            "DELETE FROM phish_songs WHERE NOT EXISTS (SELECT 1 FROM phish_track_songs ts WHERE ts.song_id=phish_songs.id)"
        )
        _clear_stage(connection, run_id)
        connection.execute(
            """UPDATE phish_sync_runs SET status='succeeded', finished_at_utc=?,
               show_count=?, track_count=?, song_count=?, error_summary=NULL WHERE id=?""",
            (_utc_now(), show_count, track_count, song_count, run_id),
        )
    return song_count


def _mark_failed(connection: sqlite3.Connection, run_id: int, exc: Exception) -> None:
    with _transaction(connection):
        _clear_stage(connection, run_id)
        connection.execute(
            """UPDATE phish_sync_runs SET status='failed', finished_at_utc=?, error_summary=?
               WHERE id=? AND status='running'""",
            (_utc_now(), f"{type(exc).__name__}: {exc}"[:500], run_id),
        )


def sync_phish_catalog(path: Path | None = None) -> dict[str, Any]:
    """Fetch and atomically publish a full public Phish.in show/track snapshot."""
    database_path = _resolve_database_path(path)
    connection = _connect(database_path)
    run_id: int | None = None
    try:
        _initialize(connection)
        run_id = _start_run(connection)
        show_pages, show_count = _sync_endpoint(
            connection, run_id=run_id, endpoint="shows", array_key="shows", sort="date:asc"
        )
        track_pages, track_count = _sync_endpoint(
            connection, run_id=run_id, endpoint="tracks", array_key="tracks", sort="id:asc"
        )
        _validate_staging(connection, run_id)
        song_count = _publish(connection, run_id, show_count, track_count)
        return {
            "database": str(database_path),
            "sync_run_id": run_id,
            "status": "succeeded",
            "shows": show_count,
            "tracks": track_count,
            "songs": song_count,
            "show_pages": show_pages,
            "track_pages": track_pages,
            "api_base": API_BASE,
        }
    except Exception as exc:
        if run_id is not None:
            try:
                _mark_failed(connection, run_id, exc)
            except sqlite3.Error:
                pass
        raise
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="phish-import",
        description="Fetch public Phish.in API v2 shows and setlists into local SQLite.",
    )
    parser.add_argument(
        "--db",
        type=Path,
        help="SQLite path; defaults to LOCAL_DATA_MCP_PHISH_DB_PATH or data/phish.sqlite",
    )
    args = parser.parse_args()
    try:
        result = sync_phish_catalog(args.db)
    except Exception as exc:
        parser.exit(1, f"Phish sync failed: {type(exc).__name__}: {exc}\n")
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))


if __name__ == "__main__":
    main()
