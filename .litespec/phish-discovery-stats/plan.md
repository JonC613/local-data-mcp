---
feature: phish-discovery-stats
artifact: plan
status: done
owner: user
version: 0.1
created: 2026-11-08
updated: 2026-11-08
spec_version: 0.1
---

# Implementation Plan: Local Phish discovery and statistics

## Technical approach

Add three fixed read-only MCP operations. Each reads sync provenance and data in one SQLite read transaction, uses bounded parameterized queries with stable sorting, and returns explicit paging and metric metadata. Preserve question correlation and full argument/output auditing.

Use isolated SQLite fixtures and an MCP stdio integration test; document manual importer usage and question-to-tool examples. Implemented using the existing MCP server and its shared audit path.

## Key decisions

### KD-01 — Local snapshot and manual refresh

- **Choice:** Read the latest successful local import and reject missing provenance or mismatched subsequent pages.
- **Rationale:** Fits the selected workflow and makes freshness visible.
- **Alternatives considered:** Scheduled refresh or live upstream lookup.
- **Consequences:** Results can be stale; old sync IDs do not preserve historical data.

### KD-02 — Associated-track song counts

- **Choice:** Count distinct track IDs per song and label coverage and definition.
- **Rationale:** Available associations support repeatable counts without missing exclusion flags.
- **Alternatives considered:** Import additional fields to match official statistics.
- **Consequences:** Medleys count for each associated song and results can differ from upstream.

### KD-03 — Fixed and auditable operations

- **Choice:** Expose reviewed tools rather than general SQL, preserving existing audit behavior.
- **Rationale:** Limits the data surface and retains traceable arguments and responses.
- **Alternatives considered:** Generic query tool.
- **Consequences:** New questions may need reviewed code; local JSONL is editable and framework validation can precede audit logging.

## Impacted areas

| Area | Expected change | Related IDs |
|---|---|---|
| Database and existing Phish query modules | Read-only snapshot-aware aggregates | US-01, US-02, AC-03.1, AC-03.2 |
| Service and server modules | Register tools and retain question/audit behavior | US-01, US-02, AC-03.3 |
| Tests | Isolated fixtures and service/MCP integration coverage | US-01, US-02, US-03 |
| README | Examples, manual refresh, definitions and limitations | US-01, US-02, US-03 |

## Technical detail

- Proposed tools: `phish_list_years`, `phish_list_venues`, `phish_song_frequency`. Use a documented limit (maximum 50), offset and total/has-more; require `expected_sync_id` for nonzero offsets. Check sync and data in one read transaction.
- Years group shows by calendar year. Venues group non-null venue IDs; choose display metadata from each venue's latest show by date then show ID with deterministic null handling. Report the count of shows missing venue IDs. Filter chosen metadata by literal name/city substring and exact state/country; parameterize inputs. Sort by normalized name and ID.
- Song ranking counts distinct track IDs per song after optional year and venue filters, sorted by count descending, normalized title and song ID. Include unassociated-track count in that scope. Explain that local associations are counted without upstream exclusion rules.
- Validate bounds and filters. Audit service-level errors and fail closed if the audit write fails. Framework validation can occur before the service, and automatic capture of final model answers is out of scope.

## Risks and mitigations

| Risk | Impact | Mitigation | Evidence or trigger |
|---|---|---|---|
| Local counts differ from upstream | Misleading comparison | Label definition and exclusion limitation | Duplicate, medley and coverage tests |
| Import between pages | Mixed snapshots | Require and compare sync ID | Snapshot-change test |
| Audit mistaken for complete or immutable | False assurance | Document question recording, framework gap and editable logs | Failure tests and documentation |

## Implementation phases

### Phase 1 — Snapshot and discovery

- [x] **P1-T1 — Add snapshot-aware year and venue lookups**
  - Covers: US-01, AC-01.1, AC-01.2, AC-01.3, AC-03.1, AC-03.2
  - Depends on: None
  - Work: Add fixed read-only queries, validation, provenance, paging, and tool registration.
  - Verify: T-01, T-02, T-05, T-06 pass.

### Phase 2 — Song statistics

- [x] **P2-T1 — Add local song frequency tool**
  - Covers: US-02, AC-02.1, AC-02.2, AC-02.3, AC-03.1, AC-03.2
  - Depends on: P1-T1
  - Work: Implement distinct-track ranking, filters, unassociated coverage and metric labels.
  - Verify: T-03, T-04, T-05, T-06 pass.

### Phase 3 — Audit and handoff

- [x] **P3-T1 — Verify MCP audit and failure paths**
  - Covers: US-03, AC-03.3
  - Depends on: P1-T1, P2-T1
  - Work: Exercise question recording, all three calls, service errors and audit-write failure.
  - Verify: T-07 and relevant existing checks pass.
- [x] **P3-T2 — Document and demonstrate**
  - Covers: US-01, US-02, US-03
  - Depends on: P3-T1
  - Work: Document manual refresh, examples, freshness and audit limitations; review changes and CI results.
  - Verify: T-08 and completion criteria pass.

## Release and rollback considerations

- **Release:** Review the plan and request implementation; after tests, restart/reconnect MCP clients to discover tools. Refresh with the existing importer when desired.
- **Rollback:** Revert tool changes; this read-only feature has no schema migration and does not delete imported data or audits.

## Amendment history

| Version | Date | Change | Reason | Affected IDs |
|---|---|---|---|---|
| 0.1 | 2026-11-08 | Initial review draft | Derived from discovery specification | All |