---
feature: customer-prefix-lookup
artifact: tiny
status: done
owner: user
version: 0.1
created: 2026-11-08
updated: 2026-11-08
---

# TinySpec: Audited customer prefix lookup

## Summary
Add a fixed MCP lookup for customer names beginning with a supplied prefix, so the exact filtered results are produced and recorded by MCP.

## Scope
Include bounded pagination and question-ID correlation. Exclude arbitrary SQL or changes to customer data.

## Requirements
- **R-01:** Return matching customer IDs, names, and emails in stable normalized-name and ID order; expose offset, limit, and has_more.
- **R-02:** Treat SQL LIKE wildcard characters in the supplied prefix literally, validate bounds, and use a read-only connection.
- **R-03:** Require the server's existing question-ID validation and record complete lookup inputs and outputs in the audit log.

## Constraints and assumptions
The query uses SQLite's built-in case handling. Pagination is offset-based and reflects the database state at each request. Identical inputs and unchanged data produce the same page.

## Implementation outline
Add a parameterized service lookup, explicit MCP tool registration, documentation, and focused fixture/MCP tests. Use the recorded user question ID for the live prefix lookup.

## Verification
- The full unittest suite passed all 28 tests, including literal wildcard, stable pagination, and MCP discovery/call coverage.
- A fresh stdio MCP session returned the matching local customer and recorded the complete prefix lookup with its question ID.
- No human review is claimed.

## Done when
- [x] Lookup is fixed, read-only, paginated, and audited.
- [x] Synthetic tests and the requested live MCP lookup succeed.
- [x] User is told the result and audit ID.

## Amendment history
| Version | Date | Change | Reason |
|---|---|---|---|
| 0.1 | 2026-11-08 | Implement prefix lookup | User requested names starting with A through MCP |
