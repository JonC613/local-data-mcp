---
feature: phish-discovery-stats
artifact: spec
status: done
owner: user
version: 0.1
created: 2026-11-08
updated: 2026-11-08
---

# Specification: Local Phish discovery and statistics

## Summary

Add read-only MCP discovery for years, venues, and song frequencies in the local Phish catalog, with explicit definitions, snapshot provenance, and the existing audit trail.

## Problem

The local server can find shows and song performances but lacks year and venue discovery and ranked song counts. Phish.in provides richer statistics, but its source data and exclusions differ from the fields stored locally.

## Desired outcome

A connected assistant can answer these questions with repeatable, qualified results from an identified local snapshot, recording inputs and outputs.

## Boundaries

### Goals

- Provide year, venue, and song discovery with fixed reviewed queries.
- Refresh manually with the existing importer and show the latest successful sync.

### Non-goals

- Live requests per question, scheduled imports, arbitrary SQL, viewer changes, Bedrock integration, or importer changes.
- Official Phish.in statistic parity or tamper-proof audit storage.

### Constraints

- SQLite remains local; lookups are read-only and follow the existing question and tool audit workflow.
- Tool choices and model wording are not deterministic; identical queries against an unchanged snapshot are.

## Requirements

### Current release

- **R-01:** Discover calendar years and venues with stable ordering and bounded pagination.
- **R-02:** Rank songs by distinct associated local tracks, with optional year and venue filters.
- **R-03:** Return provenance and metric definitions; reject unavailable snapshots and stale subsequent pages.
- **R-04:** Use existing question and tool audit paths, preserving arguments and outputs.

### Deferred

- **D-01:** Import missing exclusion fields to reproduce the official Phish.in statistic.
- **D-02:** Scheduled refresh, historical snapshots, automatic capture of complete conversations, and tamper-evident audit storage.

## User stories

### US-01 — Explore years and venues

**Story:** As a listener, I want to discover years and venues, so I can explore when and where shows occurred.

**Rationale:** Existing show lookup requires prior knowledge of the shows.

**Acceptance criteria:**

- **AC-01.1:** Year results contain represented calendar years and show counts, ordered by year, with bounded pages, total and has-more.
- **AC-01.2:** Venue results group known venue IDs, return show counts and deterministic name/location metadata, and report shows lacking venue IDs.
- **AC-01.3:** Name/city search and exact state/country filters return matching venue groups with deterministic ordering and bounded pages.

**Edge cases:** Empty snapshots produce empty results; unknown venue metadata is explicit; pagination is checked against the snapshot identity.

### US-02 — Understand song frequency

**Story:** As a listener, I want song frequencies in the local catalog, so I can compare song appearances.

**Rationale:** A transparent local statistic is useful without claiming upstream parity.

**Acceptance criteria:**

- **AC-02.1:** A song count is the number of distinct associated track IDs; duplicate links do not inflate it and a medley contributes once per linked song.
- **AC-02.2:** Optional year and venue filters constrain results ordered by descending count and stable title/ID tie breakers, with total and paging metadata.
- **AC-02.3:** Results describe the local metric, report the number of unassociated tracks in the filtered scope, and distinguish it from the official Phish.in statistic.

**Edge cases:** No matches return an empty list; tracks without associations do not contribute; tracks are not necessarily unique shows.

### US-03 — Trust and trace a lookup

**Story:** As an operator, I want snapshot provenance and audit records, so I can understand and reproduce results when the same data is available.

**Rationale:** Refreshes can change answers, and audit records do not preserve old database snapshots.

**Acceptance criteria:**

- **AC-03.1:** Successful results include latest successful sync ID and finish time, read consistently with data; unavailable catalog or provenance yields a clear error.
- **AC-03.2:** A later page requires the prior sync ID; a changed snapshot produces an explicit error.
- **AC-03.3:** Each new tool requires question correlation and records full arguments and output, including service-level errors, through the audit writer; audit-write failure follows the existing fail-closed policy.

**Edge cases:** Reject invalid input. MCP framework validation can happen before the service runs and may not be captured by its audit.

## Non-functional requirements

- **NFR-01:** Use fixed, parameterized, read-only SQL; never accept model-supplied SQL.
- **NFR-02:** Document default page size; maximum page size is 50, with stable tie breakers and pagination metadata.
- **NFR-03:** The caller must explicitly record user questions; final model answers are not automatically captured. Local JSONL is editable and not tamper-proof.

## Codebase context

The importer stores shows, tracks, songs, track-song associations, and sync runs in SQLite. Fixed MCP operations use the shared lookup service and JSONL writer. Repeated associations require distinct track IDs. Venue metadata is attached to shows, not a separate venue table. Preserve existing uncommitted changes.

Phish.in's [song analyzer](https://github.com/jcraigk/phishin/blob/d6ec3d071f40745c5dd554ee49996466b2996ef2/app/services/performance_analysis/song_frequency_analyzer.rb) also counts distinct tracks, but its [base filters](https://github.com/jcraigk/phishin/blob/d6ec3d071f40745c5dd554ee49996466b2996ef2/app/services/performance_analysis/base_analyzer.rb) use exclusions and show metadata not all stored locally. Counts may differ, including for soundchecks and excluded performances.

## Assumptions and open questions

### Assumptions

- **A-01:** The existing manual importer creates a complete local snapshot and successful sync record.
- **A-02:** Clients use the existing explicit question-recording workflow; server logs alone do not prove full conversation capture.

### Open questions

- None blocking planning.

## Amendment history

| Version | Date | Change | Reason | Affected IDs |
|---|---|---|---|---|
| 0.1 | 2026-11-08 | Initial review draft | Discovery and scope choices | All |