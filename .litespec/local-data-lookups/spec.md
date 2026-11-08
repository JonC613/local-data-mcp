---
feature: local-data-lookups
artifact: spec
status: done
owner: user
version: 0.3
created: 2026-11-06
updated: 2026-11-06
---

# Specification: Local data lookup prototype

## Summary
Provide GitHub Copilot in VS Code with approved read-only lookup tools over a local mock database. Consistent inputs and unchanged data produce consistent results, and tool activity is auditable.

## Problem
An LLM needs useful cross-table data without unrestricted database access. Tool calls must be inspectable and results reproducible under defined conditions.

## Desired outcome
A developer can seed mock data, connect Copilot, find a customer, inspect orders and items, and inspect records of tool activity.

## Boundaries
### Goals
- Run database and lookup components locally on one developer machine.
- Keep lookup operations independent of MCP for a future chatbot.

### Non-goals
- Production data or deployment, multi-user identity, general SQL, database writes through tools, Bedrock connectivity, and a custom chatbot.
- Deterministic model tool choice or wording. Copilot may send prompts and tool results to its configured model provider.

### Constraints
- Synthetic data only. Explicit limits, stable sorting, and integer cents for money.
- Local audit records are development evidence, not tamper-proof production logs.

## Requirements
### Current release
- **R-01:** Reproducible local database and fixed cross-table lookups.
- **R-02:** GitHub Copilot MCP tools for local VS Code use and setup instructions.
- **R-03:** Structured records of successful, invalid, and failed tool calls.

### Deferred
- **D-01:** Bedrock chatbot using shared lookup operations and the local database; review outbound data before real use.
- **D-02:** Full prompt and response capture correlated with tool activity.
- **D-03:** Production identity, authorization, protected audit storage, retention, and real database integration.

## User stories

### US-01 — Recreate mock data
**Story:** As a developer, I want repeatable mock data, so that tests and examples are reproducible.
**Rationale:** Stable synthetic fixtures are safe to compare.

**Acceptance criteria:**
- **AC-01.1:** A documented setup command creates the same customers, orders, order items, and products on a fresh local database.

**Edge cases:** Existing data is not silently overwritten; reset is explicit.

### US-02 — Look up related records
**Story:** As a user, I want customer, order and item lookups, so that I can answer cross-table questions.
**Rationale:** Fixed operations provide useful joins without arbitrary SQL.

**Acceptance criteria:**
- **AC-02.1:** Customer search returns matching identifiers and names in stable order, or an empty list.
- **AC-02.2:** Listing a customer's orders returns only their orders in a stable bounded order.
- **AC-02.3:** Order details return the associated customer, products, quantities and integer-cent totals; unknown orders return a defined not-found response.
- **AC-02.4:** Identical valid inputs against unchanged data return identical lookup data under `data`; audit metadata may vary. Invalid inputs and unsupported operations are rejected without arbitrary SQL or data modification.

**Edge cases:** Duplicate names, missing IDs, invalid IDs, empty results, and limit boundaries.

### US-03 — Use tools from GitHub Copilot
**Story:** As a GitHub Copilot user, I want MCP lookup tools, so that my assistant can use mock records.
**Rationale:** MCP lets the client discover fixed operations.

**Acceptance criteria:**
- **AC-03.1:** GitHub Copilot in the local VS Code workspace discovers and can invoke each of the three tools through MCP.
- **AC-03.2:** Setup instructions provide a local Copilot configuration and reproducible example questions.

**Edge cases:** Setup and database failures are reported without exposing secrets or partial data.

### US-04 — Inspect tool activity
**Story:** As a developer, I want each tool call recorded, so that I can inspect its request and outcome.
**Rationale:** Local records support review and future correlation.

**Acceptance criteria:**
- **AC-04.1:** Each successful, invalid, or failed tool invocation writes a structured record with timestamp, unique request ID, tool and version, safely representable inputs, outcome, and result or error; returned `_audit.request_id` matches the record.
- **AC-04.2:** If an audit record cannot be written, the call returns an audit failure rather than a successful data result.

**Edge cases:** Safely bound malformed input in logs; avoid recursive logging on audit failure.

## Non-functional requirements
- **NFR-01:** Use read-only database access, parameterized fixed queries, explicit bounds and stable sorting.
- **NFR-02:** Use a versioned audit schema and return its request ID separately from lookup data for future conversation correlation; document file location and cleanup.
- **NFR-03:** Result determinism excludes timestamps, request IDs and LLM behavior; data changes invalidate repeatability.

## Codebase context
The project uses a Python package with a transport-independent SQLite lookup service, an MCP stdio adapter, JSONL auditing, and unittest coverage. It targets one local Windows developer environment; no production database or deployment surface is configured.

## Assumptions and open questions
### Assumptions
- **A-01:** One local developer uses the mock prototype; OS account permissions protect mock files.
- **A-02:** Python, SQLite and stdio MCP are suitable starting choices.
- **A-03:** Tool audit covers server inputs and outputs, not Copilot prompts or model responses.

### Open questions
None blocking this mock-only planning scope. Real data requires identity, authorization, retention, protected storage and outbound-data decisions.

## Amendment history

| Version | Date | Change | Reason | Affected IDs |
|---|---|---|---|---|
| 0.1 | 2026-11-06 | Initial planning package | User discovery | All |
| 0.2 | 2026-11-06 | Return audit request ID separately from deterministic data | Enable future conversation correlation without changing lookup determinism | AC-02.4, AC-04.1, NFR-02 |
| 0.3 | 2026-11-06 | Target GitHub Copilot portable workspace configuration | User selected Copilot instead of Cursor | R-02, US-03, AC-03.2, A-03 |

