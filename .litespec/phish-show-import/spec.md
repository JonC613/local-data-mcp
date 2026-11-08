---
feature: phish-show-import
artifact: spec
status: implementing
owner: user
version: 0.1
created: 2026-11-07
updated: 2026-11-07
---

# Specification: Phish.in show import to local SQLite

## Summary

Add a repeatable Python sync from Phish.in's public v2 API into a local SQLite catalog, then expose fixed audited MCP lookups for shows, setlists, and song performances.

## Problem

The local Phish helper only fetches one latest show and prints it. There is no local catalog that can be refreshed and queried across shows and tracks.

## Desired outcome

Run one Python command to populate or refresh `data/phish.sqlite`. The MCP provides deterministic read-only lookups over that catalog, while the sync log records each API page and whether a complete refresh succeeded.

## Boundaries

### Goals

- Import public Phish show and track metadata from the official Phish.in v2 API.
- Keep the database on this machine and connect it to the existing MCP using static Python tools.
- Make refreshes repeatable, recoverable, and auditable.

### Non-goals

- Writing data back to Phish.in, downloading audio, adding scheduled jobs, importing attendance or personal notes, or adding Bedrock calls.
- A generic API connector or arbitrary URL/SQL tool.

### Constraints

- The importer uses HTTPS GET only against the fixed `phish.in` API v2 host.
- Include only show, track, venue, and associated song fields needed for catalog lookups. Exclude likes, comments, user data, admin notes, audio files, and media URLs.
- Returned MCP fields are written to the existing local audit log and may be sent to the configured model provider.

## Requirements

### Current release

- **R-01:** A Python command imports all paginated public shows and tracks from Phish.in API v2 into a local SQLite database and can be rerun to add new shows and apply corrections.
- **R-02:** Validate response envelopes and pagination; apply bounded timeouts, response-size limits, same-host HTTPS redirects, polite pacing, and retry/backoff for transient errors.
- **R-03:** Log sync runs and per-page status, row count, timestamp, and SHA-256 response digest. Stage records so a failed or inconsistent full sync leaves the last good catalog unchanged.
- **R-04:** Add fixed, parameterized, read-only MCP lookups for filtered show search, show/setlist details, and song performances. Results are bounded and stably ordered.
- **R-05:** Route every lookup through the shared audit writer, preserve fail-closed audit behavior, use a dataset-specific local DB path, and document setup/refresh in README and MCP configuration.
- **R-06:** Do not import or expose personal records, user activity, audio binaries, or media URLs.

### Deferred

- **D-01:** Scheduled refreshes, selective incremental windows, external API connectors for other sources, audio playback, and cloud hosting.

## User stories

### US-01 — Refresh the local show catalog

**Story:** As a Phish fan, I want to sync Phish.in's public show archive into local SQLite, so that I can query it without fetching the API for every question.

**Rationale:** A local snapshot enables cross-table, repeatable lookups and keeps normal MCP queries independent of network availability.

**Acceptance criteria:**

- **AC-01.1:** The documented Python command imports paginated shows, tracks, and track-to-song associations into `data/phish.sqlite` and records Phish.in attribution.
- **AC-01.2:** Repeating a successful full sync updates existing source IDs and adds new ones without duplicates; stale rows are removed only after the full response set is validated.
- **AC-01.3:** A failed request, malformed page, changing pagination totals, or invalid relationship marks the run failed and leaves the previous live catalog intact.
- **AC-01.4:** The database records each sync run and fetched page, including status, page number, item count, fetch time, and response digest.

**Edge cases:** Empty pages, missing or invalid source IDs, duplicate IDs across pages, redirected hosts, oversized responses, timeouts, HTTP 429/5xx, and interruption during a staged run must not publish partial data.

### US-02 — Look up shows and songs through MCP

**Story:** As a Codex user, I want to find shows, read a show's setlist, and find performances of a song, so that I can ask questions over the local catalog.

**Rationale:** Static cross-table operations keep model access useful without exposing arbitrary SQL or remote API calls.

**Acceptance criteria:**

- **AC-02.1:** MCP registers `phish_find_shows`, `phish_get_show`, and `phish_find_song_performances`, all bound to `LOCAL_DATA_MCP_PHISH_DB_PATH` and using read-only parameterized SQL.
- **AC-02.2:** Inputs are validated, results are bounded and deterministically ordered, and only approved public fields are returned.
- **AC-02.3:** Every result goes through `LookupService.invoke`; the shared audit request ID matches its JSONL event, and audit failure withholds successful lookup data.
- **AC-02.4:** README explains the local sync command, database path, Codex/Copilot MCP setup, refresh behavior, and audit/model data exposure.

**Edge cases:** Invalid dates/years, empty filters, no matches, duplicate show dates, missing song associations, and audit-write failure return bounded errors without modifying the source database.

## Non-functional requirements

- **NFR-01 — Determinism:** Identical inputs against the same SQLite snapshot return the same data fields and ordering; audit IDs/timestamps are metadata.
- **NFR-02 — Atomicity:** The live catalog changes only after both paginated endpoints complete and their totals and relationships validate.
- **NFR-03 — Locality:** The SQLite catalog and tool audit log remain local; no credentials are required or stored.
- **NFR-04 — Request limits:** One page contains at most 1,000 items; each response is capped at 32 MiB; requests time out after 30 seconds, use a small inter-request delay, and cap retries/backoff.

## External input and data handling

- **Sources and validation:** Accept only JSON from the fixed `https://phish.in/api/v2/shows` and `/tracks` endpoints. Require expected arrays, pagination metadata, source IDs, dates, nonnegative integer track positions (including source value 0), and valid show/song relationships.
- **Remote retrieval:** HTTPS only; permit redirects only to `phish.in` or `www.phish.in`; send a descriptive User-Agent; never accept a model/user-provided URL. Fail safely on malformed, oversized, or incomplete responses.
- **Files:** Store normalized rows and sync audit metadata in the git-ignored local `data/phish.sqlite`; do not store raw response bodies or audio/media files. Preserve successful catalog rows on failed refresh.
- **Data and access:** Public show/track/song metadata only. No API key, authentication, personal records, or remote writes. The existing MCP prototype has no per-user authorization.

## Codebase context

The package is Python 3.11+ with stdlib `sqlite3` and a FastMCP stdio server. `LookupService.invoke` owns validation, outcomes, and shared JSONL auditing; `database.open_readonly` provides read-only connections. The server currently uses one mock DB, so the Phish dataset needs a separate environment path and an explicit allowlist. `data/` is already ignored by Git. The existing `dataset-to-mcp` skill covers SQLite lookup generation; this specifically authorized Phish.in API ingestion is a scoped importer feeding a SQLite dataset.

## Assumptions and open questions

### Assumptions

- **A-01:** Use Phish.in API v2 for the full public catalog; v2 requires no API key and uses `page`/`per_page` pagination up to 1,000 items.
- **A-02:** Full catalog refresh is acceptable instead of a scheduled or date-window updater; rerunning the command is the update process.
- **A-03:** Show, track, and track-to-song data are sufficient for the first MCP query set; audio playback and personal data are excluded.

### Open questions

- None blocking implementation.

## Amendment history

| Version | Date | Change | Reason | Affected IDs |
|---|---|---|---|---|
| 0.1 | 2026-11-07 | Initial feature spec | User requested Phish.in-to-local-SQLite uploader | All |
| 0.2 | 2026-11-07 | Preserve source track position zero | Live API records include position 0; retaining the exact public value avoids inventing an ordering | R-02, AC-01.1 |
