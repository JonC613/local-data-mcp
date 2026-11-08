---
feature: local-data-viewer
artifact: tests
status: done
owner: user
version: 0.1
created: 2026-11-07
updated: 2026-11-07
spec_version: 0.1
plan_version: 0.1
---

# Test Plan: Local SQLite and audit viewer

## Strategy
Use synthetic SQLite and JSONL fixtures for service, HTTP integration, and browser workflows. Exercise data privacy and audit failures at the service boundary; manually inspect desktop layout after automated checks.

## Acceptance traceability
| Acceptance criterion | Test IDs | Method | Status |
|---|---|---|---|
| AC-01.1 | T-01, M-01 | SQLite/HTTP integration and browser walkthrough | Passed |
| AC-01.2 | T-01, M-01 | Filter and pagination integration and browser walkthrough | Passed |
| AC-01.3 | T-02 | Missing/unreadable source checks | Passed |
| AC-02.1 | T-03, M-01 | JSONL/HTTP integration and browser walkthrough | Passed |
| AC-02.2 | T-03, M-01 | Event detail fixture and browser walkthrough | Passed |
| AC-02.3 | T-04 | Invalid and missing JSONL fixture | Passed |
| AC-03.1 | T-05 | HTTP security integration | Passed |
| AC-03.2 | T-06 | Full event audit integration | Passed |
| AC-03.3 | T-06 | Audit write failure integration | Passed |

## Critical user flows
### T-01 — Browse tables and pages
- Covers: AC-01.1, AC-01.2
- Level: integration
- Setup: Synthetic databases with ordinary, composite-key, null, and large-field rows.
- Action: Select databases and tables, filter, move pages, and repeat.
- Expected: Correct columns and rows in deterministic key order; no arbitrary SQL or database writes.

### T-03 — Inspect audit entries
- Covers: AC-02.1, AC-02.2
- Level: integration
- Setup: Version 1 and 2 events with nested arguments and responses.
- Action: Filter by supported fields, page, and open details.
- Expected: Matching complete recorded fields and visible legacy truncation markers; no executable markup.

## Failure and recovery cases
### T-02 — Missing sources
- Covers: AC-01.3
- Level: integration
- Setup: Missing and unreadable database paths.
- Action: Open each source.
- Expected: Clear errors and no newly created database files.

### T-04 — Malformed logs and appends
- Covers: AC-02.3
- Level: integration
- Setup: Missing, empty, malformed, and incomplete JSONL logs, plus a log appended during browsing.
- Action: Open and page each source.
- Expected: Accurate error location and stable snapshot paging without silently skipping corrupted lines.

### T-05 — Local access protections
- Covers: AC-03.1
- Level: integration
- Setup: Local service with session secret.
- Action: Send requests with missing or invalid session secrets, Host, and Origin headers.
- Expected: Unauthorized requests fail and service listens on loopback only.

### T-06 — Viewer audit and failure
- Covers: AC-03.2, AC-03.3
- Level: integration
- Setup: Synthetic sources and writable or failing audit writer.
- Action: View data and audit records, then repeat with audit write denied.
- Expected: Complete arguments and response recorded for successful access; requested data withheld on audit failure.

## Automated checks
Executed `python -m unittest discover -s tests -v`: 20 tests passed. The new synthetic fixtures cover read-only databases, filtering and composite-key pagination, large/null/binary fields, audit snapshots and detail, malformed and incomplete logs, audit write failure, and loopback/token/Host/Origin enforcement. The HTTP integration exercises row browsing and audit detail through the actual local server.

## Manual exceptions
### M-01 — Browser workflow and visual review
- Covers: AC-01.1, AC-01.2, AC-02.1, AC-02.2 and usability across both views.
- Automation limitation: The repository has no browser test harness; browser layout and interaction were inspected separately from the automated HTTP fixtures.
- Method: Open the viewer at a desktop and narrow window width; browse a table and expand an audit event.
- Evidence: Codex opened the local viewer, filtered the Phish show date 1999-07-24, inspected a version 1 audit event and its truncation notice, and viewed the layout at desktop and 650-pixel widths. No human review is claimed.

## Test data and setup
Use temporary synthetic data; never include the user's actual database or audit records in test fixtures.

## Completion criteria
- [x] Every current-release acceptance criterion maps to passing evidence.
- [x] Security, fail-closed audit, and snapshot paging checks pass.
- [x] Manual visual review is recorded.
- [x] No implementation or test result is claimed before execution.

## Amendment history
| Version | Date | Change | Reason | Affected IDs |
|---|---|---|---|---|
| 0.1 | 2026-11-07 | Initial review plan | Plan requested by user | All |
| 0.2 | 2026-11-07 | Record implementation checks and browser walkthrough | Viewer implemented after confirmation | All |
