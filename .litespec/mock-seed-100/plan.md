---
feature: mock-seed-100
artifact: plan
status: done
owner: user
version: 0.1
created: 2026-11-07
updated: 2026-11-07
spec_version: 0.1
---

# Implementation Plan: Expand synthetic mock database

## Technical approach
Generate fixed synthetic rows in Python around the existing seed constants. Add a separate seed command that checks existing rows against the known fixture, inserts only missing rows within one SQLite transaction, validates foreign keys and exact counts, and records start/outcome events in the existing JSONL audit.

## Key decisions
### KD-01 — Preserve original samples
- **Choice:** Keep original rows intact and generate only missing rows.
- **Rationale:** The user selected preservation, including Acme and order examples.
- **Alternatives considered:** Reassign original relationships to ensure every parent has a child.
- **Consequences:** A few parent rows remain unused, but all actual foreign-key references are valid.

### KD-02 — Separate database commit and audit events
- **Choice:** Write an intent before the transaction and an outcome after it, correlated with a seed run ID.
- **Rationale:** A start-audit failure can prevent mutation, and an incomplete run remains identifiable.
- **Alternatives considered:** Claiming an atomic commit across SQLite and JSONL.
- **Consequences:** If the final audit write fails after commit, report explicitly that the database was updated and its completion event is missing.

## Impacted areas
| Area | Expected change | Related IDs |
|---|---|---|
| database.py | Fixed synthetic generator and transactional expansion | AC-01.1, AC-01.2, AC-01.3, AC-02.1 |
| cli.py and README | Audited seed command and recovery guidance | AC-02.2, AC-02.3 |
| tests and local mock SQLite | Synthetic coverage and user-requested population | AC-01.1, AC-01.2, AC-01.3 |

## Implementation phases
### Phase 1 — Implement and populate
- [x] **P1-T1 — Generate and validate fixture**
  - Covers: US-01, AC-01.1, AC-01.2, AC-01.3, AC-02.1
  - Depends on: None
  - Work: Add deterministic values, transactional inserts, compatibility checks, and foreign-key validation.
  - Verify: Synthetic fixture and rollback tests.
- [x] **P1-T2 — Audit and document command**
  - Covers: US-02, AC-02.2, AC-02.3
  - Depends on: P1-T1
  - Work: Write correlated start and completion/error events and document the command.
  - Verify: Audit failure and completion-failure tests.
- [x] **P1-T3 — Populate existing database**
  - Covers: US-01, AC-01.1, AC-01.2
  - Depends on: P1-T1, P1-T2
  - Work: Run the seed on the existing mock database.
  - Verify: Inspect row counts, foreign keys, unchanged sample data, and audit records read-only.

## Amendment history
| Version | Date | Change | Reason | Affected IDs |
|---|---|---|---|---|
| 0.1 | 2026-11-07 | Initial implementation | User authorized seeding and preservation | All |
