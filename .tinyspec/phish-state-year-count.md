---
feature: phish-state-year-count
artifact: tiny
status: done
owner: user
version: 0.1
created: 2026-11-08
updated: 2026-11-08
---

# TinySpec: Audited Phish show count by state and year

## Summary
Provide a fixed MCP count of Phish shows by exact state/province code, year, and optional exact country. Include up to 50 ordered show details.

## Scope
Read the existing local Phish catalog through MCP; do not change or refresh the source data or expose arbitrary SQL.

## Requirements
- **R-01:** Count all matching show rows using an exact case-insensitive state code and year, with an optional exact case-insensitive country filter.
- **R-02:** Return the complete count, a stable date/ID ordered sample of up to 50 matching shows, and has_more.
- **R-03:** Require a recorded question ID and use the shared full request/response audit path.

## Constraints and assumptions
Use parameterized SQL and one read-only SQLite transaction for the count and sample. Catalog contents reflect the last Phish.in sync; country spelling must match the source representation.

## Implementation outline
Add a fixed service query and MCP tool, document it, test exact filters, full counts beyond the sample cap, input validation, and audit correlation.

## Verification
- All 29 project unit and integration tests passed.
- A fresh stdio MCP session counted Wisconsin/USA shows in 1999 against the local catalog and recorded the result.
- No human review is claimed.

## Done when
- [x] Fixed query returns an exact count and audited result.
- [x] Tests pass and the user's request is answered through MCP.

## Amendment history
| Version | Date | Change | Reason |
|---|---|---|---|
| 0.1 | 2026-11-08 | Implement exact state/year count | User requested Wisconsin show count through MCP |
