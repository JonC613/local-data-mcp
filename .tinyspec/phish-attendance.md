---
feature: phish-attendance
artifact: tiny
status: done
owner: user
version: 0.1
created: 2026-11-08
updated: 2026-11-08
---

# Local Phish show attendance

## Summary

Allow the user to mark Phish shows in the existing local catalog as attended and look them up later from a separate local SQLite database.

## Scope

Single-user attendance records only; no assumed attendance, bulk import, removal, notes, cloud sync, or changes to the Phish catalog. Snapshot venue metadata at insertion; retain show ID and date to use existing setlist tools.

## Requirements

- **R-01:** Add a catalog show by ISO date, disambiguated by show ID when necessary; reject unknown shows and make duplicate additions idempotent.
- **R-02:** List attended shows with optional year, stable date/ID ordering, total count and bounded pagination; an uninitialized attendance database represents an empty list.
- **R-03:** Require existing question correlation and full arguments/output auditing. Write a start event before modifying attendance. If the final audit fails after commit, clearly report that a save may have occurred and a retry is safe.
- **R-04:** Keep the attendance SQLite database separate from the catalog, mock database and audit log; support a dedicated local path environment variable and do not prepopulate attendance.

## Implementation outline

Add reviewed static MCP tools through the existing service. Store local show ID, date, venue/location snapshot and add timestamp in a dedicated SQLite file created on first add. Validate path collisions; use parameterized SQL and atomic insert. List reads are read-only.

## Verification

Test duplicate writes, missing and ambiguous catalog shows, pagination and filters, read-only data access, question correlation, and audit failures before and after commit using temporary fixtures. Exercise MCP discovery and run the existing CI suite.

## Done when

The user can add and list attended shows through MCP with traceable audit records; tests and documentation are complete.

## Amendment history

| Version | Date | Change | Reason | Affected IDs |
|---|---|---|---|---|
| 0.1 | 2026-11-08 | Initial implementation | User requested attendance tracking | R-01–R-04 |
## Execution evidence

- 2026-11-08: Full unittest suite passed 47 tests on Windows, including attendance MCP integration and audit failure cases. No live attendance records were added.
