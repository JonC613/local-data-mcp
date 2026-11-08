---
feature: mock-seed-100
artifact: tests
status: done
owner: user
version: 0.1
created: 2026-11-07
updated: 2026-11-07
spec_version: 0.1
plan_version: 0.1
---

# Test Plan: Expand synthetic mock database

## Strategy
Run focused synthetic SQLite and audit tests plus the existing project suite, then inspect the user's seeded mock database and audit events read-only.

## Acceptance traceability
| Acceptance criterion | Test IDs | Method | Status |
|---|---|---|---|
| AC-01.1 | T-01, M-01 | Automated and local inspection | Passed |
| AC-01.2 | T-01, M-01 | Automated and local inspection | Passed |
| AC-01.3 | T-01 | Two independent fixtures and hashes | Passed |
| AC-02.1 | T-01, T-02 | Repeat and conflict/rollback tests | Passed |
| AC-02.2 | T-03, M-01 | Audit event and local inspection | Passed |
| AC-02.3 | T-04 | Audit failure injection | Passed |

## Critical user flows
### T-01 — Deterministic linked fixture
- Covers: AC-01.1, AC-01.2, AC-01.3, AC-02.1
- Level: integration
- Setup: Two separate small fixture databases.
- Action: Expand each, compare all tables and hashes, then repeat the expansion.
- Expected: 100 rows per table; unchanged original rows, valid foreign keys, same data and no duplicates.

### T-03 — Audited seed
- Covers: AC-02.2
- Level: integration
- Setup: A fixture database and temporary audit file.
- Action: Seed through the command implementation.
- Expected: Correlated start and success events record counts and fixture fingerprint.

## Failure and recovery cases
### T-02 — Conflicting existing records
- Covers: AC-02.1
- Level: integration
- Setup: A modified fixture row.
- Action: Attempt expansion.
- Expected: The transaction rolls back and preserves the modified row.

### T-04 — Audit write failures
- Covers: AC-02.3
- Level: integration
- Setup: Fail the start or completion audit write.
- Action: Invoke seeding.
- Expected: Start failure prevents mutation; completion failure explicitly reports a committed update.

## Automated checks
The full unittest suite passed all 25 tests, including focused fixture, conflict, and audit tests.

## Manual exceptions
### M-01 — Apply to the existing mock database
- Covers: AC-01.1, AC-01.2, AC-02.2
- Automation limitation: The requested user-local state must be checked separately from synthetic temporary test fixtures.
- Method: Execute the seed command and inspect counts, foreign keys, preserved examples, and corresponding JSONL records.
- Expected evidence: 100 rows in each table, zero foreign-key errors, preserved examples, and correlated audit events.
- Observed: The local seed completed as run b9a3bfd3-bf90-49fc-963d-a6ebb2abe48f. All four tables have 100 rows, all original fixture rows match, SQLite returned no foreign-key violations, and start/success audit events were recorded. A live MCP lookup traversed synthetic customer 5, order 1005, and product 13.

## Test data and setup
Use temporary copies of the synthetic fixture; do not modify the local Phish catalog.

## Completion criteria
- [x] The suite passes with fixture, transaction, and audit checks.
- [x] The existing mock database has 100 rows per table and valid foreign keys.
- [x] Local audit records are present and correlated.
- [x] Report that preserved original relationships leave some parents without children.

## Amendment history
| Version | Date | Change | Reason | Affected IDs |
|---|---|---|---|---|
| 0.1 | 2026-11-07 | Initial implementation checks | User requested a larger mock seed | All |
