---
feature: phish-discovery-stats
artifact: tests
status: done
owner: user
version: 0.1
created: 2026-11-08
updated: 2026-11-08
spec_version: 0.1
plan_version: 0.1
---

# Test Plan: Local Phish discovery and statistics

## Strategy

Use deterministic SQLite fixtures for aggregates and pagination, service tests for audit failures, and an MCP stdio integration test for client-visible behavior and question correlation. Do not use live APIs or production data.

## Acceptance traceability

| Acceptance criterion | Test IDs | Method | Status |
|---|---|---|---|
| AC-01.1 | T-01 | Automated | Passed |
| AC-01.2 | T-02 | Automated | Passed |
| AC-01.3 | T-02 | Automated | Passed |
| AC-02.1 | T-03 | Automated | Passed |
| AC-02.2 | T-04 | Automated | Passed |
| AC-02.3 | T-03 | Automated | Passed |
| AC-03.1 | T-05 | Automated | Passed |
| AC-03.2 | T-06 | Automated | Passed |
| AC-03.3 | T-07 | Automated | Passed |

## Critical user flows

### T-01 — Year discovery

- Covers: AC-01.1
- Level: component
- Setup: Shows across years and a successful sync.
- Action: List years in multiple pages and query an empty snapshot.
- Expected: Correct chronological counts, total and has-more; no invented years.

### T-02 — Venue grouping and filters

- Covers: AC-01.2, AC-01.3
- Level: component
- Setup: Repeated venue IDs with changed metadata, null IDs, ties and wildcard characters.
- Action: List and filter venues across page boundaries.
- Expected: One group per known ID, correct counts and latest metadata, unknown-ID count, literal filtering and stable order.

### T-03 — Song count and coverage

- Covers: AC-02.1, AC-02.3
- Level: component
- Setup: Duplicate links, a medley, an unassociated track and a track potentially excluded upstream.
- Action: Request frequencies.
- Expected: Distinct tracks counted once per linked song; coverage and local definition reported with no parity claim.

### T-04 — Filtered ranking and paging

- Covers: AC-02.2
- Level: component
- Setup: Multiple years and venues, tied song counts.
- Action: Filter by year and venue, retrieve pages, and request no matches.
- Expected: Correct scoped ranking, stable ties, totals and paging; empty results when appropriate.

### T-05 — Consistent snapshot provenance

- Covers: AC-03.1
- Level: integration
- Setup: Successful sync fixture; separately missing database, incompatible schema and missing successful sync.
- Action: Call each new tool.
- Expected: Responses identify the snapshot ID and time from the same read transaction; unavailable snapshots fail clearly.

## Failure and recovery cases

### T-06 — Snapshot change between pages

- Covers: AC-03.2
- Level: integration
- Setup: First page from one snapshot, followed by a second successful import fixture.
- Action: Request next page with old ID, then restart from page one; omit ID on a later page.
- Expected: Old or absent expected ID fails clearly; new first page identifies new snapshot.

### T-07 — Question and tool audits

- Covers: AC-03.3
- Level: end-to-end
- Setup: Temporary catalog and audit path; MCP client and injectable audit failure.
- Action: Record a question, call all tools with its ID, trigger service error, invalid correlation and audit-write failure.
- Expected: Linked events preserve full arguments and outputs for calls reaching the service; errors follow fail-closed policy and audit-write failure never returns success.

### T-08 — Documented workflow

- Covers: US-01, US-02, US-03
- Level: integration
- Setup: Temporary imported fixture and MCP client.
- Action: Exercise documented examples and pagination.
- Expected: Examples, freshness and limitations match the implementation.

## Automated checks

- Run targeted query, service and MCP tests, then the repository's required CI suite.
- Check invalid bounds, literal filter escaping, no-match inputs and no database mutations.

## Manual exceptions

None for acceptance criteria.

## Test data and setup

- Use temporary SQLite fixtures and JSONL audit files, never the user's live catalog or log.
- Cover duplicate associations, medleys, missing venue IDs, missing associations, sync changes and invalid inputs.

## Completion criteria

- [x] Every current-release acceptance criterion maps to passing automated evidence.
- [x] Critical flows and failure/recovery cases pass.
- [x] Relevant existing CI checks pass and documentation reflects actual behavior and audit limits.
- [x] No unresolved failure blocks a current-release requirement.

## Amendment history

| Version | Date | Change | Reason | Affected IDs |
|---|---|---|---|---|
| 0.1 | 2026-11-08 | Initial review draft | Derived from specification and plan | All |
## Execution evidence

- 2026-11-08: `.\.venv\Scripts\python.exe -m unittest discover -s tests -v` passed all 36 tests on Windows/Python 3.11, including MCP stdio and in-memory client checks. The stdio subprocess required execution outside the Windows sandbox to create named pipes.
