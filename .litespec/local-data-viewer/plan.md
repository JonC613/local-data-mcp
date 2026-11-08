---
feature: local-data-viewer
artifact: plan
status: done
owner: user
version: 0.1
created: 2026-11-07
updated: 2026-11-07
spec_version: 0.1
---

# Implementation Plan: Local SQLite and audit viewer

## Technical approach
Add a separate local Python viewer process with a lightweight server and static browser UI. It uses the existing configured mock, Phish, and audit paths; it does not change the MCP transport. Present a sidebar for sources, a table browser, and an audit timeline with an expandable detail pane.

Reuse the audit writer and read-only SQLite helper while adding narrowly scoped viewer operations. Each request reads a consistent page, records its complete inputs and response, and only then returns data. Explicitly account for log growth caused by recording audit views.

## Key decisions
### KD-01 — Local browser application
- **Choice:** Python local service with a browser UI and loopback-only binding.
- **Rationale:** Fits the existing Python environment and works without a separate desktop installer.
- **Alternatives considered:** Native desktop shell or an MCP-only interface.
- **Consequences:** Browser requests need a session secret and origin/host checks; final framework choice is an implementation decision.

### KD-02 — Read-only configured sources
- **Choice:** Use startup-configured database and JSONL paths; show tables and columns from an explicit allowlist.
- **Rationale:** Keeps access scoped and query construction reviewable.
- **Alternatives considered:** Arbitrary file chooser and SQL console.
- **Consequences:** New datasets require reviewed configuration and allowlist changes in v1; values are parameterized and identifiers checked and quoted.

### KD-03 — Record full viewer actions
- **Choice:** Apply the current schema version 2 full-input/full-output audit policy to viewer data access, including audit views.
- **Rationale:** Matches the user's existing auditability requirement.
- **Alternatives considered:** Summary-only viewer audit events.
- **Consequences:** Repeatedly inspecting audit records may grow the JSONL log quickly; the audit view fixes a file boundary and makes the behavior visible.

## Impacted areas
| Area | Expected change | Related IDs |
|---|---|---|
| Python viewer service and UI | Local HTTP process, pages, source selection, controls | US-01, US-02, US-03 |
| SQLite read-only helper and source configuration | Scoped table discovery, parameterized filtering and stable pagination | AC-01.1, AC-01.2, AC-01.3 |
| Existing JSONL writer and audit reader | Full viewer access events, snapshot paging, malformed-line handling | AC-02.1, AC-02.2, AC-02.3, AC-03.2, AC-03.3 |
| README and project metadata | Startup instructions and dependencies | US-01, US-03 |

## Technical detail
- Source paths come from existing LOCAL_DATA_MCP_DB_PATH, LOCAL_DATA_MCP_PHISH_DB_PATH, and LOCAL_DATA_MCP_AUDIT_PATH; use explicit local defaults resolved from the project.
- Database browsing uses read-only connections, a reviewed dataset/table allowlist, and parameterized filter values. Only use verified and quoted identifiers. Stable ordering uses a primary key or verified rowid; disallow pagination without a safe stable key.
- Each database request uses one read transaction; show that data can change between page requests. The viewer never invokes arbitrary SQL or writes to the databases.
- JSONL listing scans complete records up to a captured byte boundary. Maintain a stable ordering and offset/cursor tied to that boundary; surface an explicit error for malformed or partial lines. Filtering and detail preserve legacy markers.
- Browser session binds to localhost with a per-launch secret; restrict Host and Origin, protect state-changing/audit-generating calls against cross-site requests, and send no data to third-party services.
- Full logging applies to data-bearing viewer requests; define the audit contract for the initial audit access and its errors so that a failed append withholds the result. Viewing old audit outputs may duplicate them in the log.
- Refuse appends to an audit file ending in an incomplete line, preserving the damaged bytes and returning an explicit fail-closed error until repaired.
- Default page size 50, maximum 100; filters bounded. Expand large fields without silent truncation. Inspect JSON as text, not executable HTML.

## Risks and mitigations
| Risk | Impact | Mitigation | Evidence or trigger |
|---|---|---|---|
| Local browser access to private records | Data exposure | Loopback binding, session secret, Host/Origin restrictions, no external assets | Tests for unauthorized and cross-origin requests |
| Audit log duplication | File growth from viewing events | Fixed snapshot boundary, bounded pages, visible warning and documentation | Tests of append behavior and full captured outputs |
| Malformed or large JSONL | Misleading or stalled display | Stream, paginate, identify malformed lines, do not silently discard | Invalid/large fixture checks |
| Changing data or missing stable key | Unstable pages | Stable key, short read transactions, disclose updates between requests | Pagination tests and concurrent update checks |

## Implementation phases

### Phase 1 — Read-only local viewer foundation
- [x] **P1-T1 — Add local server and source controls**
  - Covers: US-03, AC-03.1, AC-03.3, AC-01.3
  - Depends on: None
  - Work: Implement startup configuration, loopback and session protections, read-only source opening, and fail-closed audit wrapper.
  - Verify: Integration checks for local access, unauthorized requests, missing sources, and audit failure.
- [x] **P1-T2 — Add database browser**
  - Covers: US-01, AC-01.1, AC-01.2
  - Depends on: P1-T1
  - Work: Add allowed-table listing, row and column views, filtering, ordering, and pagination.
  - Verify: SQLite fixture checks and browser flow covering common and composite-key tables.

### Phase 2 — Audit review and handoff
- [x] **P2-T1 — Add audit timeline and detail**
  - Covers: US-02, AC-02.1, AC-02.2, AC-02.3, AC-03.2
  - Depends on: P1-T1
  - Work: Implement snapshot-boundary JSONL reading, filters, event detail, and explicit malformed-file and legacy markers.
  - Verify: Fixture checks for nested results, legacy events, malformed lines, concurrent append, and full audited viewer outputs.
- [x] **P2-T2 — Document and validate user workflows**
  - Covers: US-01, US-02, US-03
  - Depends on: P1-T2, P2-T1
  - Work: Document startup, data paths, limitations, retention, and client exposure; validate UI with representative local fixtures.
  - Verify: Automated checks and a recorded manual screen review.

## Release and rollback considerations
- **Release:** Run as an optional local process; existing MCP configuration remains usable. No database migration is required.
- **Rollback:** Stop the viewer and remove its entry point and UI; retain existing database and audit files.

## Amendment history
| Version | Date | Change | Reason | Affected IDs |
|---|---|---|---|---|
| 0.1 | 2026-11-07 | Initial review plan | Plan requested by user | All |
| 0.2 | 2026-11-07 | Complete viewer and incomplete-log append safeguard | Implemented after user confirmation | P1-T1–P2-T2 |
