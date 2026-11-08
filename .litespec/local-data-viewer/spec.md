---
feature: local-data-viewer
artifact: spec
status: done
owner: user
version: 0.1
created: 2026-11-07
updated: 2026-11-07
---

# Specification: Local SQLite and audit viewer

## Summary
Provide a locally running browser interface for exploring the configured mock and Phish SQLite databases and investigating JSONL audit records.

## Problem
The catalogs and audit logs are useful through MCP and command-line tools, but there is no visual way to browse tables, inspect records, or follow a lookup's audit trail.

## Desired outcome
Start one local viewer, select a configured source, browse and filter database rows, or inspect audit events and their arguments and outputs.

## Boundaries
### Goals
- Browse configured SQLite data and Phish sync history; search and expand lookup audits.
- Preserve local-only operation and the existing full audit policy.
### Non-goals
- Database edits, arbitrary SQL, remote access, user authentication, model integration, scheduled imports, and cloud deployment.
### Constraints
- The UI reads only locally configured sources; database connections are read-only.
- Viewer actions are logged using the existing audit writer, including arguments and returned data, subject to the existing fail-closed behavior.

## Requirements
### Current release
- **R-01:** Provide a local browser UI for the configured mock and Phish SQLite databases, with safe browsing and pagination.
- **R-02:** Provide a searchable, paginated JSONL audit view with complete event details and explicit version 1 truncation indicators.
- **R-03:** Record viewer data accesses and protect the local endpoint; fail closed if audit writing fails.
- **R-04:** Surface missing files, malformed log lines, and unavailable data clearly.
### Deferred
- **D-01:** Editing, custom SQL, export, adding datasets from the UI, streaming subscriptions, and remote multi-user access.

## User stories

### US-01 — Explore local database tables
**Story:** As a user, I want to browse the configured SQLite databases and their tables so that I can inspect their data visually.
**Rationale:** I can understand the data without writing SQL.
**Acceptance criteria:**
- **AC-01.1:** The viewer lists the configured mock and Phish databases and their approved tables, and presents their columns and paginated rows.
- **AC-01.2:** Users can select a table and apply supported filters, and pagination produces a deterministic order with a stable key.
- **AC-01.3:** Missing or unreadable databases and tables produce a clear error without creating or changing database files.
**Edge cases:** Empty tables, nulls, binary values, large text, tables with composite keys, and data changing between requests.

### US-02 — Inspect audit records
**Story:** As a user, I want to find and expand audit events so that I can understand what a lookup received and returned.
**Rationale:** The current JSONL format is inconvenient to inspect manually.
**Acceptance criteria:**
- **AC-02.1:** The audit view lists timestamp, tool, outcome, and request ID and filters by tool, outcome, request ID, and time.
- **AC-02.2:** Selecting an event displays its complete recorded arguments, response, error, and schema version, with a warning for any legacy truncation markers.
- **AC-02.3:** A malformed or incomplete line is identified by location and presented as an error; missing and empty files are distinguished.
**Edge cases:** Large records, legacy version 1 entries, concurrent appends, missing fields, and invalid JSON.

### US-03 — Keep access local and auditable
**Story:** As the local operator, I want viewer access to be logged and restricted to this machine so that I can account for data access.
**Rationale:** Both the database and audit records can contain sensitive information.
**Acceptance criteria:**
- **AC-03.1:** The server binds to loopback and rejects untrusted requests using a session secret and host/origin checks.
- **AC-03.2:** Every data access through the viewer records its arguments and complete response in the shared audit log before returning data.
- **AC-03.3:** If its audit event cannot be written, the viewer withholds the requested data and reports an audit failure.

## Non-functional requirements
- **NFR-01:** Source SQLite files are opened read-only, and the viewer exposes no SQL execution or write operations.
- **NFR-02:** Rows and audit records are paged; the interface does not require loading an entire catalog into browser memory.
- **NFR-03:** Audit scans retain a fixed file boundary for a browsing session so appended viewer audit events do not move existing pages.

## External input and data handling
- **Sources and validation:** Only paths configured at process startup are available; SQLite schema identifiers are verified against discovered tables and safely quoted; values use SQL parameters.
- **Files:** SQLite and JSONL stay local. JSONL is streamed, with a defined snapshot boundary and explicit malformed-line reporting.
- **Data and access:** Full viewer outputs and inputs are logged locally, including audit detail views. Repeated audit viewing can expand the log; display this operational behavior. Existing version 1 truncations cannot be reconstructed.

## Codebase context
The Python project has a FastMCP stdio server, read-only SQLite helper, a mock catalog, a Phish catalog, and version 1/2 JSONL audit events. The version 2 writer stores full arguments and results. There is no existing browser UI or general HTTP server.

## Assumptions and open questions
### Assumptions
- **A-01:** A local browser UI is the preferred first interface; configured mock and Phish paths are the starting sources.
- **A-02:** Viewing any approved table is permitted for the person running the local viewer.
### Open questions
- Should additional local SQLite files be selectable in the UI in a later release?
- Is a standalone desktop window preferred over a browser interface?

## Amendment history
| Version | Date | Change | Reason | Affected IDs |
|---|---|---|---|---|
| 0.1 | 2026-11-07 | Initial review plan | User requested a viewer plan | All |
| 0.2 | 2026-11-07 | Implement local viewer and protect incomplete audit logs | User confirmed implementation; incomplete-line review exposed an append hazard | US-01, US-02, US-03 |
