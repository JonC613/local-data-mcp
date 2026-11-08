---
feature: phish-show-import
artifact: tests
status: implementing
owner: user
version: 0.1
created: 2026-11-07
updated: 2026-11-07
spec_version: 0.1
plan_version: 0.1
---

# Test Plan: Phish.in show import to local SQLite

## Strategy

Use the requested full API sync as an operational integration run, then inspect the resulting SQLite schema, sync audit, and referential counts read-only. Review static MCP registrations, query allowlists, parameterization, limits, and environment configuration. No test files or test suite are added or run in this slice.

## Acceptance traceability

| Acceptance criterion | Evidence IDs | Method | Status |
|---|---|---|---|
| AC-01.1 | M-01 | Live full import and read-only database inspection | Verified |
| AC-01.2 | T-01 | Upsert/key/stale-row code review; repeat sync is a future operational check | Reviewed; repeat sync not run |
| AC-01.3 | T-02 | Staging/transaction/failure-path code review; forced failures are not exercised | Reviewed; failure injection not run |
| AC-01.4 | M-01 | Sync run/page ledger inspection and digest format review | Verified |
| AC-02.1 | T-03 | Static tool registration and SQL review | Configured; Codex reload pending |
| AC-02.2 | T-03 | Input bounds, result order, and field-map review | Reviewed |
| AC-02.3 | T-04 | Shared audit call-path review | Reviewed |
| AC-02.4 | T-05 | README/configuration command and path review | Configured; Codex reload pending |

## Critical user flows

### M-01 — Populate the local catalog

- Covers: AC-01.1, AC-01.4
- Level: operational integration
- Setup: Fresh `data/phish.sqlite`; public network access to Phish.in v2.
- Action: Run `python -m local_data_mcp.phish_importer`.
- Expected: One successful sync run; non-empty show/track rows; every track references a show; page records include request status, row count, timestamp, and SHA-256; no raw payload or media files are stored.
- Result: Verified on 2026-11-07. Sync run 3 imported 2,151 shows, 39,464 tracks, 982 songs, and 40,102 track/song associations across 3 show pages and 40 track pages. Every page has a 64-character SHA-256 digest; `PRAGMA foreign_key_check` returned no violations. Date range: 1983-12-02 through 2026-10-12.

### T-01 — Idempotent full-snapshot update

- Covers: AC-01.2
- Level: code review plus repeat operational run
- Setup: Existing local catalog and a later API snapshot.
- Action: Inspect primary keys/upserts and full-snapshot cleanup, then rerun the importer when a fresh refresh is requested.
- Expected: Stable source IDs do not duplicate; corrected fields update; stale rows are removed only after both endpoints validate.
- Status: Repeat run not performed in this implementation.

### T-02 — Failed sync preserves the live catalog

- Covers: AC-01.3
- Level: code review
- Setup: Existing successful catalog and a failed, malformed, inconsistent, or interrupted API page.
- Action: Review staging cleanup and publication transaction boundaries.
- Expected: Failed run retains page/run evidence, removes its staging rows, and leaves previous live show/track/song rows unchanged.
- Status: Runtime failure injection not performed.

### T-03 — Fixed deterministic MCP operations

- Covers: AC-02.1, AC-02.2
- Level: code review
- Setup: Phish lookup service and server registration.
- Action: Inspect the three static tool wrappers and fixed SQL.
- Expected: Separate dataset path, read-only SQLite, parameterized predicates, input validation, 1–50 result bounds, deterministic tie-breakers, and only approved public fields.

### T-04 — Shared audit and fail-closed path

- Covers: AC-02.3
- Level: code review
- Setup: Existing `LookupService.invoke` and `AuditWriter`.
- Action: Trace each Phish tool wrapper through the shared service and audit writer.
- Expected: Each tool name and bounded result/error is audited; the returned request ID is the event ID; an audit write failure withholds successful data.

### T-05 — Local client configuration

- Covers: AC-02.4
- Level: configuration/documentation review
- Setup: `.mcp.json`, Codex profile, and README.
- Action: Compare the configured Phish DB path and documented sync command.
- Expected: Both local MCP clients receive `LOCAL_DATA_MCP_PHISH_DB_PATH`; README explains local-only storage, refresh, and audit/model exposure.

## Failure and recovery cases

- Malformed JSON, wrong page list, changed totals, invalid IDs/dates, non-HTTPS or cross-host redirect, oversized response, API 429/5xx, and timeout are bounded failures; code review only in this slice.
- A successful API sync followed by an unavailable API leaves the last good catalog queryable; not runtime-injected in this slice.

## Manual exceptions

### M-02 — Codex loads new tool definitions

- Covers: AC-02.1, AC-02.4
- Automation limitation: The already-open Codex client may cache MCP tool definitions until it restarts.
- Method: Restart Codex, open `/mcp`, confirm `local-data-lookups`, then try “Find Phish shows at Red Rocks” and “Show the setlist for 1997-11-22.”
- Expected evidence: The three `phish_` tools are listed and results include an audit request ID.
- Status: MCP profile updated; requires client restart to load the three new tool definitions.

## Test data and setup

- No API payloads or real rows are copied into the repository; the imported public catalog stays under git-ignored `data/phish.sqlite`.
- Test suite and test files are intentionally unchanged in this slice.

## Completion criteria

- [x] Initial full sync succeeds and its local page/run audit can be inspected.
- [x] Static query, privacy, transaction, and audit paths have been reviewed.
- [x] README and both MCP configurations point to the local Phish database.
- [ ] Codex discovery is checked after the client reloads.
- [x] No test files or test suite were added or run; package syntax was checked with `py_compile`.

## Amendment history

| Version | Date | Change | Reason | Affected IDs |
|---|---|---|---|---|
| 0.1 | 2026-11-07 | Initial verification plan | Derived from the Phish.in import requirements | All |
| 0.2 | 2026-11-07 | Record successful full import and client reload limitation | Catalog populated; this running Codex session still has the old MCP tool list | AC-01.1, AC-01.4, AC-02.1, AC-02.4 |
