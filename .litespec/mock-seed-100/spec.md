---
feature: mock-seed-100
artifact: spec
status: done
owner: user
version: 0.1
created: 2026-11-07
updated: 2026-11-07
---

# Specification: Expand synthetic mock database

## Summary
Expand the existing mock SQLite catalog to 100 deterministic synthetic rows in each of its four tables, preserving the existing examples and valid relationships.

## Problem
The first database contains only four customers, three products, four orders, and five order items, which limits viewer and MCP exploration.

## Desired outcome
The existing mock database and separately created mock fixtures can be expanded repeatably through a documented, audited command.

## Boundaries
### Goals
- Preserve all existing fixture rows and add linked synthetic data.
- Update only the identified mock database, atomically and without overwriting conflicting data.
### Non-goals
- Modifying the Phish catalog or adding real customer information.
### Constraints
- Exactly 100 rows per existing table. All child foreign keys are valid.
- The user chose to preserve the original examples: one customer has no order, one order has no line item, and two products have not been ordered.

## Requirements
### Current release
- **R-01:** Add deterministic synthetic rows to the existing four tables without overwriting the original sample.
- **R-02:** Support a documented repeatable command with audited start and outcome, and reject incompatible existing records.
- **R-03:** Verify the local database and relationships after seeding.
### Deferred
- **D-01:** Editable seeding templates or a dynamically configurable generator.

## User stories
### US-01 — Explore a larger linked fixture
**Story:** As a user, I want 100 rows in each table so that I can explore realistic cross-table lookups.
**Rationale:** A larger deterministic fixture enables meaningful browsing.
**Acceptance criteria:**
- **AC-01.1:** Customers, products, orders, and order items each have exactly 100 rows.
- **AC-01.2:** Existing fixture records are unchanged and every foreign-key reference is valid.
- **AC-01.3:** The same starting fixture produces the same complete rows and fixture fingerprint.
**Edge cases:** Existing parent records without children remain possible by explicit user choice.

### US-02 — Repeat and audit the seed
**Story:** As a user, I want a repeatable and auditable seed command so that I can understand and safely recreate the data.
**Rationale:** Repeatability and traceable changes match the local project's operating model.
**Acceptance criteria:**
- **AC-02.1:** Rerunning the command adds no duplicate rows; a conflicting existing record aborts and rolls back the transaction.
- **AC-02.2:** A seed start and completion or error event share a run ID and include the fixture version and output counts/fingerprint.
- **AC-02.3:** A failed start audit prevents mutation; a completion audit failure after commit explicitly reports that the database changed.
**Edge cases:** Missing database, incomplete/unwritable audit log, and failure after database commit.

## Non-functional requirements
- **NFR-01:** Use deterministic generated values, fixed IDs, fixed timestamps, reserved example addresses, and SQLite foreign-key checks.
- **NFR-02:** Keep SQLite data and JSONL audit files local; no network or model calls.

## Codebase context
The mock schema has customers, products, orders, and order_items. The existing initializer creates a small fixture; read-only MCP tools and viewer query those tables. The JSONL AuditWriter records structured local events.

## Assumptions and open questions
### Assumptions
- **A-01:** The existing mock database is the intended first database; its current fixture rows should remain intact.
### Open questions
- None blocking implementation.

## Amendment history
| Version | Date | Change | Reason | Affected IDs |
|---|---|---|---|---|
| 0.1 | 2026-11-07 | Initial implementation | User requested 100 linked rows per table while preserving examples | All |
