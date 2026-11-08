---
feature: local-data-lookups
artifact: plan
status: done
owner: user
version: 0.3
created: 2026-11-06
updated: 2026-11-06
spec_version: 0.3
---

# Implementation Plan: Local data lookup prototype

## Technical approach
Build a Python local process with a seeded SQLite database, transport-independent lookup layer, and MCP adapter over standard input/output. A shared wrapper validates calls, executes fixed read-only queries, and writes audit records before returning results.

## Key decisions
### KD-01 — Local storage and fixed operations
- **Choice:** SQLite and parameterized named queries; integer cents and stable tie-breakers.
- **Rationale:** Reproducible local fixture without a separate server.
- **Alternatives considered:** Local PostgreSQL or model-generated SQL.
- **Consequences:** SQLite targets the mock single-user phase; new questions require reviewed operations.

### KD-02 — Local MCP adapter
- **Choice:** Local stdio MCP calls a shared lookup layer.
- **Rationale:** Copilot integration without a network listener; later adapters can reuse operations.
- **Alternatives considered:** HTTP-only service.
- **Consequences:** Full Copilot conversations are not available to the server.

### KD-03 — Prototype audit
- **Choice:** Structured local versioned audit records, request IDs returned separately from lookup data, and fail closed on audit write failure.
- **Rationale:** Reviewable mock activity and future correlation without claiming tamper resistance.
- **Alternatives considered:** Protected production audit store.
- **Consequences:** No production audit or user identity guarantee.

## Impacted areas
| Area | Expected change | Related IDs |
|---|---|---|
| Database and fixtures | Schema, deterministic seed, read-only queries | US-01, US-02 |
| MCP and documentation | Three tools and Copilot instructions | US-03 |
| Audit and tests | Structured records and checks | US-04 |

## Technical detail
Tables: customers, orders, order_items, products, with foreign keys. Operations: find_customers, list_customer_orders, get_order_details. Validate types and length/limit bounds. Sort customer matches by normalized name then ID, orders by date then ID, and lines by line ID. Use a read-only connection after seeding. Return defined empty, invalid and not-found results. Exclude audit metadata from deterministic lookup results.

Audit schema v1 includes timestamp, request ID, operation and version, bounded safe inputs, outcome, and bounded result or error. Return the request ID in `_audit` metadata outside the deterministic `data` payload. Optional correlation fields leave room for later conversation capture. Avoid logging secrets.

## Risks and mitigations
| Risk | Impact | Mitigation | Evidence or trigger |
|---|---|---|---|
| Model invents an answer | Misleading result | Treat tool results as source and document model limitations | Compare example responses with results |
| Local logs can be altered | Weak audit assurance | Label prototype limitations; defer protected store and identity | Production readiness review |
| Audit write fails | Unrecorded disclosure | Return failure instead of result | Inject writer failure |

## Implementation phases
### Phase 1 — Seed and deterministic lookups
- [x] **P1-T1 — Create mock data**
  - Covers: US-01, AC-01.1
  - Depends on: None
  - Work: Define schema, fixtures, explicit reset, and setup documentation.
  - Verify: T-01.
- [x] **P1-T2 — Implement fixed operations**
  - Covers: US-02, AC-02.1, AC-02.2, AC-02.3, AC-02.4
  - Depends on: P1-T1
  - Work: Validate inputs and enforce read-only fixed queries, bounds and stable sorting.
  - Verify: T-02, T-03, T-04, T-05.

### Phase 2 — Audit and MCP access
- [x] **P2-T1 — Add tool audit**
  - Covers: US-04, AC-04.1, AC-04.2
  - Depends on: P1-T2
  - Work: Add versioned audit wrapper, failure handling and correlation-ready IDs.
  - Verify: T-08, T-09.
- [x] **P2-T2 — Expose and document MCP tools**
  - Covers: US-03, AC-03.1, AC-03.2
  - Depends on: P2-T1
  - Work: Implement stdio MCP adapter, client configuration, examples and cleanup.
  - Verify: T-06, T-07.

## Amendment history

| Version | Date | Change | Reason | Affected IDs |
|---|---|---|---|---|
| 0.1 | 2026-11-06 | Initial planning package | User discovery | All |
| 0.2 | 2026-11-06 | Return audit request ID separately from deterministic data | Enable future conversation correlation without changing lookup determinism | KD-03, technical detail, P2-T1 |
| 0.3 | 2026-11-06 | Target GitHub Copilot portable workspace configuration | User selected Copilot instead of Cursor | KD-02, impacted areas, P2-T2 |

