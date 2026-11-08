---
feature: audited-question-routing
artifact: tests
status: done
owner: user
version: 0.1
created: 2026-11-07
updated: 2026-11-07
spec_version: 0.1
plan_version: 0.1
---

# Test Plan: Audited MCP question routing

## Strategy
Use synthetic mock SQLite and JSONL fixtures to verify question records, request correlation, failed audits, and the MCP transport. Re-run the user's previous count through a fresh local MCP session as an operational check.

## Acceptance traceability
| Acceptance criterion | Test IDs | Method | Status |
|---|---|---|---|
| AC-01.1 | T-01 | MCP and synthetic audit tests | Passed |
| AC-01.2 | T-01 | Missing, forged, and unrelated ID tests | Passed |
| AC-01.3 | T-01, M-01 | Customer-count MCP checks | Passed |
| AC-02.1 | T-01, M-01 | Retrospective audit checks | Passed |
| AC-02.2 | T-02 | Audit failure injection | Passed |
| AC-02.3 | T-03 | Documentation and agent instruction review | Reviewed |

## Critical user flows
### T-01 — Record and correlate a question
- Covers: AC-01.1, AC-01.2, AC-01.3, AC-02.1
- Level: integration
- Setup: Synthetic SQLite fixture and audit log.
- Action: Record exact question text, count customers, inspect audit events, and attempt missing or unrelated IDs.
- Expected: Count and complete response correlate to the recorded question; invalid requests return no data and are audited.

## Failure and recovery cases
### T-02 — Audit unavailable
- Covers: AC-02.2
- Level: unit/integration
- Setup: Audit writer that fails.
- Action: Record a question and count customers.
- Expected: Both return audit_failure and withhold successful output.

## Automated checks
The project unittest suite passed all 27 tests, including MCP discovery, missing and unrelated question IDs, complete question recording, retrospective markers, and audit failure behavior.

## Manual exceptions
### M-01 — Re-run the prior question
- Covers: AC-01.3, AC-02.1
- Automation limitation: Verify the requested local database separately from synthetic fixtures.
- Method: Record the prior customer-count question retrospectively and call the fixed count tool through a fresh local MCP session.
- Expected evidence: Recorded retrospective question and linked count audit IDs, with the current customer count.
- Observed: The earlier customer-count question was recorded with the retrospective flag and the current count was returned as 100 by a fresh MCP session. The subsequent standard stdio MCP count also returned 100 with the same question ID and its own audit request ID. The earlier direct read remains unrecorded.

### T-03 — Review routing guidance
- Covers: AC-02.3
- Level: documentation review
- Setup: Project AGENTS.md and README.
- Action: Review the routing instruction, correlation requirement, and client limitations.
- Expected: No claim that MCP automatically captures unsent prompts or final answers.

## Test data and setup
Use temporary synthetic databases and logs for tests. The live count uses the user's already seeded mock database.

## Completion criteria
- [x] Automated tests pass.
- [x] The prior count is re-run via MCP with a retrospective question marker.
- [x] Client reload and conversation-capture limitations are documented for handoff.
- [x] No user-data answer during this implementation bypassed MCP.

## Amendment history
| Version | Date | Change | Reason | Affected IDs |
|---|---|---|---|---|
| 0.1 | 2026-11-07 | Initial implementation checks | User requested MCP-only question routing | All |
