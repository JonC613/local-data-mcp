---
feature: phish-show-import
artifact: plan
status: implementing
owner: user
version: 0.1
created: 2026-11-07
updated: 2026-11-07
spec_version: 0.1
---

# Implementation Plan: Phish.in show import to local SQLite

## Technical approach

Add a stdlib-only Python importer that GETs the fixed Phish.in v2 `/shows` and `/tracks` endpoints with pagination. Normalize only public show, track, and song-association fields into a dataset-specific SQLite file. Record each request's endpoint/page/status/row count/time and response SHA-256 in the database.

Stage the complete response before replacing live rows. Validate pagination totals, source IDs, and relationships; then apply upserts and stale-row cleanup in one SQLite transaction. On any fetch or validation error, discard that run's staging rows and preserve the last successful catalog. Register static read-only MCP functions against a separate environment path and route them through the existing `LookupService`/`AuditWriter`.

## Key decisions

### KD-01 — Use Phish.in API v2 public catalog endpoints

- **Choice:** Use HTTPS GET on `/api/v2/shows` and `/api/v2/tracks`, with page pagination and no API key.
- **Rationale:** Phish.in's official API source marks v2 as the recommended stable API and says v2 needs no key; its v1 API omits shows without audio. The [official API documentation source](https://github.com/jcraigk/phishin/blob/main/app/javascript/components/pages/ApiDocs.jsx) describes this boundary.
- **Alternatives considered:** The latest-show page scraper, v1 endpoint, or Phish.net API with a key.
- **Consequences:** A full sync is a manual rerun of the importer; the implementation does not schedule jobs or call a model.

### KD-02 — Page the source with a polite, bounded client

- **Choice:** Request at most 1,000 rows per page, use stable ordering, a 30-second timeout, capped response size and retries, and a short delay between pages.
- **Rationale:** Phish.in's [official pagination parameters](https://github.com/jcraigk/phishin/blob/main/app/api/api_v2/helpers/shared_params.rb) set a 1,000-item maximum. The [shows endpoint](https://github.com/jcraigk/phishin/blob/main/app/api/api_v2/shows.rb) and [tracks endpoint](https://github.com/jcraigk/phishin/blob/main/app/api/api_v2/tracks.rb) return page metadata.
- **Alternatives considered:** One detail request per date or an unbounded response.
- **Consequences:** The import records counts and response hashes and fails closed if page totals change mid-run.

### KD-03 — Stage, then atomically publish the full snapshot

- **Choice:** Persist page audit and normalized staging rows first; update live tables and remove rows absent from the validated full snapshot in one transaction.
- **Rationale:** A half-downloaded setlist archive must not appear as a complete local catalog.
- **Alternatives considered:** Immediate per-page live upserts, which leave mixed snapshots on interruption.
- **Consequences:** Staging is temporary and cleared on success/failure; sync page history remains in SQLite.

### KD-04 — Keep API import and MCP access separate

- **Choice:** Store the catalog at `data/phish.sqlite` by default, configurable with `LOCAL_DATA_MCP_PHISH_DB_PATH`; add explicit `phish_` tools and share the current audit writer.
- **Rationale:** The importer is the only writer. MCP lookups use the current read-only connection helper and cannot issue source writes or arbitrary SQL.
- **Alternatives considered:** Reusing the mock commerce database or adding a runtime connector.
- **Consequences:** `.mcp.json` and the Codex server environment need the new local path; restart the Codex client after tool registration.

### KD-05 — Preserve source positions exactly

- **Choice:** Accept nonnegative integer positions, including zero, and return tracks in source position then ID order.
- **Rationale:** The live API contains tracks at position zero. Rewriting those positions would add information that the source did not provide.
- **Consequences:** The live and staging schemas allow zero; the importer migrates an earlier local schema that required positive positions.

## Impacted areas

| Area | Expected change | Related IDs |
|---|---|---|
| `src/local_data_mcp/phish_importer.py` | Python API client, pagination, staging, upsert, and sync audit | R-01–R-03, AC-01.1–AC-01.4 |
| `src/local_data_mcp/service.py` | Fixed validated show/setlist/song queries | R-04, R-05, AC-02.1–AC-02.3 |
| `src/local_data_mcp/server.py` | Explicit Phish MCP registrations and dataset path | R-04, R-05 |
| `.mcp.json` and Codex user profile | Local Phish DB path passed to the MCP process | R-05 |
| `README.md` | Initial sync, refresh, MCP tools, source attribution, audit boundary | R-05, AC-02.4 |
| `data/phish.sqlite` | Locally synced public catalog and sync audit | R-01–R-03 |

## Technical detail

### Data model and run lifecycle

- `phish_shows`: source show ID/date, venue/location, tour, audio status, duration, and source update timestamp.
- `phish_tracks`: source track ID, show FK, title/slug, set name, position, duration, and audio status.
- `phish_songs` and `phish_track_songs`: source song IDs and ordered track-to-song associations, including medleys.
- `phish_sync_runs`: start/end, status, totals, and bounded failure summary.
- `phish_sync_pages`: run, endpoint, page, HTTP status, item count, fetch time, and response digest.
- Staging tables are keyed by run ID. Only a fully validated run updates live tables; old running runs are marked interrupted and their staging is cleared on next start.

### MCP operation contract

- `phish_find_shows(query?, year?, start_date?, end_date?, limit=20)` requires at least one filter; returns matching show metadata sorted by date then source ID.
- `phish_get_show(show_date)` returns all shows on that date and their tracks/song titles sorted by show ID, set, position, and track ID.
- `phish_find_song_performances(query, limit=20)` joins songs, track associations, tracks, and shows; sorts by date/show/position/track/song IDs.
- All limits are 1–50, all SQL is parameterized, and lookups use read-only SQLite connections.

## Risks and mitigations

| Risk | Impact | Mitigation | Evidence or trigger |
|---|---|---|---|
| API shape or totals change during a run | Incomplete or mismatched catalog | Validate each page envelope and stable totals; stage before publish | Per-page audit; failed run leaves live rows unchanged |
| API timeout, throttling, or outage | Refresh does not complete | Retry bounded 429/5xx/network failures; preserve last good snapshot | Failed run status and page records |
| Source content includes unrelated personal/media fields | Data leaves the intended boundary | Map only named public catalog fields; do not store media URLs, likes, notes, or user data | Review importer mapping and MCP result shape |
| MCP results enter the JSONL audit or configured model provider | Data exposure beyond SQLite | Restrict tool outputs to show/setlist fields and document current audit/provider behavior | Inspect sample result and README |

## External-input implementation notes

- **Boundary controls:** Fixed API host; HTTPS; same-host redirects only; typed JSON envelope validation; response cap; timeout; page cap; bounded retry/backoff.
- **Persistence lifecycle:** One local SQLite file, rerunnable full sync, page history retained, staging cleared after completion or failure; no raw response bodies or audio files.
- **Operational safeguards:** No credential; no arbitrary endpoint override; no API call during MCP lookup; fail-closed publication and audit failure behavior.

## Implementation phases

### Phase 1 — Import and query the public catalog

- [x] **P1-T1 — Build the auditable Phish.in sync**
  - Covers: US-01, AC-01.1, AC-01.2, AC-01.3, AC-01.4
  - Depends on: None
  - Work: Add the API client, schema/staging tables, page/run audit, validation, transactional upsert, and CLI.
  - Verify: Compile the package; execute the requested full sync; inspect run/page counts, response digests, and show/track/song counts read-only.

- [x] **P1-T2 — Add static read-only MCP tools**
  - Covers: US-02, AC-02.1, AC-02.2, AC-02.3
  - Depends on: P1-T1
  - Work: Add input validation and fixed joins; register three named tools through the shared lookup/audit service.
  - Verify: Review the operation allowlist, SQL parameters, stable ordering, limits, read-only path, and shared audit call path.

- [x] **P1-T3 — Configure and document local use**
  - Covers: AC-02.4, R-05
  - Depends on: P1-T1, P1-T2
  - Work: Add the dataset path to Copilot and Codex MCP configuration; document initial import, refresh, tool examples, attribution, and local audit behavior.
  - Verify: Parse configuration, list the Codex MCP server, and cross-check README commands/paths.

- [x] **P1-T4 — Populate the local catalog**
  - Covers: AC-01.1, AC-01.4
  - Depends on: P1-T1
  - Work: Run a full sync into the new local database.
  - Verify: The run is `succeeded`; shows/tracks/song links are non-empty and referentially consistent; no source credentials or raw payloads are stored.

## Release and rollback considerations

- **Release:** This is local-only. Run the importer once before opening Codex tools; restart the Codex client so it reloads the MCP environment and registrations.
- **Rollback:** Stop the importer, remove the Phish MCP environment/tool registrations, and move or delete only `data/phish.sqlite`. The existing mock database and JSONL tool audit are separate.

## Amendment history

| Version | Date | Change | Reason | Affected IDs |
|---|---|---|---|---|
| 0.1 | 2026-11-07 | Initial implementation plan | Derived from the approved API-to-SQLite feature | All |
| 0.2 | 2026-11-07 | Record zero-position source behavior and completed local sync | Live import identified two source tracks at position zero | KD-05, P1-T1–P1-T4 |
