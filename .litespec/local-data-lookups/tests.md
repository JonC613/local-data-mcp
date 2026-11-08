---
feature: local-data-lookups
artifact: tests
status: done
owner: user
version: 0.3
created: 2026-11-06
updated: 2026-11-06
spec_version: 0.3
plan_version: 0.3
---

# Test Plan: Local data lookup prototype

## Strategy
Use temporary SQLite fixtures for component tests and a local MCP client for discovery and invocation. Validate the portable Copilot workspace config automatically; actual Copilot app startup remains environment-specific.

## Acceptance traceability
| Acceptance criterion | Test IDs | Method | Status |
|---|---|---|---|
| AC-01.1 | T-01 | Automated | Passed |
| AC-02.1 | T-02 | Automated | Passed |
| AC-02.2 | T-03 | Automated | Passed |
| AC-02.3 | T-04 | Automated | Passed |
| AC-02.4 | T-05 | Automated | Passed |
| AC-03.1 | T-06 | Automated protocol test | Passed; live Copilot check pending |
| AC-03.2 | T-07 | Automated config check and manual | Config passed; live Copilot check pending |
| AC-04.1 | T-08 | Automated | Passed |
| AC-04.2 | T-09 | Automated | Passed |

## Critical user flows
### T-01 — Seed reproducibility
- Covers: AC-01.1
- Level: integration
- Setup: Two fresh temporary locations.
- Action: Run documented setup in each.
- Expected: Identical table contents; existing database not silently replaced.

### T-02 — Customer search
- Covers: AC-02.1
- Level: component
- Setup: Names include duplicates and no-match search.
- Action: Search customers.
- Expected: Matching IDs and names stably sorted, or empty list.

### T-03 — Customer orders
- Covers: AC-02.2
- Level: component
- Setup: Multiple customers and orders including sorting ties.
- Action: List one customer's orders at boundary limits.
- Expected: Only their orders, bounded and stably sorted.

### T-04 — Order detail
- Covers: AC-02.3
- Level: component
- Setup: Order with multiple products and quantities.
- Action: Retrieve the order and a nonexistent ID.
- Expected: Correct customer, lines and integer-cent totals; defined not-found response.

### T-05 — Repeatability and invalid input
- Covers: AC-02.4
- Level: component
- Setup: Unchanged seed database.
- Action: Repeat calls and submit invalid, oversized and SQL-like inputs and unsupported operations.
- Expected: Equal `data` payloads across repeated calls even though `_audit.request_id` changes; invalid calls rejected, no mutation or arbitrary SQL.

### T-06 — MCP tools
- Covers: AC-03.1
- Level: integration
- Setup: Register the server with the official MCP SDK and connect an SDK client to its in-memory protocol transport against a temporary seed.
- Action: Discover and invoke all three tools with the test client.
- Expected: Tool names and structured results match the lookup contract. The separate stdio process and live Copilot client launch remain manual checks.

### T-07 — Copilot setup configuration
- Covers: AC-03.2
- Level: integration
- Setup: Fresh local project with Copilot in VS Code.
- Action: Check documented commands and follow configuration and example questions.
- Expected: Portable config parses and identifies the installed local server; live Copilot startup is recorded as M-01.

### T-08 — Audit records
- Covers: AC-04.1
- Level: integration
- Setup: Isolated audit destination.
- Action: Make successful, invalid and failed calls.
- Expected: One parseable record per call with required schema, safe inputs, result or error, and unique IDs; returned `_audit.request_id` matches its record.

## Failure and recovery cases
### T-09 — Audit storage failure
- Covers: AC-04.2
- Level: integration
- Setup: Inject an audit writer failure.
- Action: Invoke a valid lookup.
- Expected: Audit failure returned without successful data or recursive logging; restore writer and verify recovery.

## Automated checks
Ran the unittest suite: 10 tests passed, including isolated database checks, MCP discovery and invocation, and Copilot config parsing. Live Copilot startup remains a manual check (M-01).

## Manual exceptions
### M-01 — Copilot connection
- Covers: AC-03.2
- Automation limitation: Copilot host version and workspace trust state are environment-specific.
- Method: Open the project in VS Code with the Copilot harness, list the MCP servers, invoke the sample tools, and inspect returned data and the audit file.
- Status: Not run; live Copilot configuration and startup remain unverified in this environment.
- Expected evidence: Record VS Code and Copilot harness versions, server status, discovery and results; report mismatches.

## Test data and setup
- Synthetic seed includes duplicate names, multiple customers and orders, multiple lines, empty results and sorting ties.
- Tests use temporary database and audit paths and clean them up; no real data or AWS account required.

## Completion criteria
- [x] Automated evidence passes for current-release behavior; live Copilot use is listed as a manual limitation.
- [x] Critical flows and failure cases pass, including audit failure and read-only checks.
- [x] Copilot manual exception is explicitly marked unverified.
- [x] No unresolved automated failure blocks a current-release requirement.

## Amendment history

| Version | Date | Change | Reason | Affected IDs |
|---|---|---|---|---|
| 0.1 | 2026-11-06 | Initial planning package | User discovery | All |
| 0.2 | 2026-11-06 | Verify returned audit request ID and deterministic data boundary | Enable future conversation correlation | AC-02.4, AC-04.1, T-05, T-08 |
| 0.3 | 2026-11-06 | Validate portable GitHub Copilot configuration | User selected Copilot instead of Cursor | AC-03.2, T-07, M-01 |

