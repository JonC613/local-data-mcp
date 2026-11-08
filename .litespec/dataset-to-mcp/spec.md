---
feature: dataset-to-mcp
artifact: spec
status: done
owner: user
version: 0.2
created: 2026-11-06
updated: 2026-11-07
---

# Specification: Dataset-to-MCP authoring skill

## Summary

Provide a project-local Copilot skill that turns supplied SQLite schema and application context into small, reviewed, static MCP lookup tools that preserve deterministic query results and the existing audit path.

## Problem

The prototype has a fixed lookup service for one mock database. There is no repeatable workflow for using another dataset's schema and code as context to add useful tools without weakening the fixed-query and audit boundaries.

## Desired outcome

A developer can give Copilot a SQLite schema or database path, business code context, intended questions, and field restrictions. The skill adds dataset-specific code and local MCP configuration for review. Tools are explicit allowlisted operations and every invocation is recorded through the existing audit service.

## Boundaries

### Goals

- Make dataset-to-tool authoring reusable through a project-local skill discoverable in Copilot workspaces.
- Support relational data starting with SQLite.
- Generate reviewed code during development, with explicit server registration and a local path per dataset.
- Preserve fixed, parameterized, read-only queries, bounded deterministic results, and fail-closed auditing.

### Non-goals

- Runtime dataset attachment, dynamic Python imports, model-generated SQL, or a generic query tool.
- PostgreSQL or other database engines, APIs, files, Bedrock integration, production deployment, or multi-user authorization in this release.
- Deterministic model tool selection or response wording.

### Constraints

- SQLite databases and JSONL audit files stay local.
- Only fields approved for model use and local audit logging may be returned. The current audit writer captures successful results.
- Use synthetic data for examples and tests; do not copy real records into repository artifacts.
- One shared audit writer records the namespaced tool, bounded arguments, outcome, and result or error. Audit failure withholds successful lookup data.

## Requirements

### Current release

- **R-01:** Provide a repository-local `dataset-to-mcp` skill and concise intake guide for SQLite schema, code context, questions, and field restrictions.
- **R-02:** Direct the skill to generate reviewed static Python lookup code and explicit Copilot MCP registration for each dataset.
- **R-03:** Generated lookups use fixed parameterized read-only queries, input validation, bounds, stable ordering, namespaced tool names, and dataset-specific local database paths.
- **R-04:** Every generated tool routes through `LookupService.invoke` and the shared audit writer, preserving request IDs, deterministic data separation, and fail-closed behavior.
- **R-05:** Document how to invoke the skill and explain that successful tool results are recorded locally and may be sent to the configured model provider.

### Deferred

- **D-01:** Support for non-SQLite sources, runtime attachments, filesystem/API connectors, or another database engine.
- **D-02:** Bedrock chatbot integration and full prompt/response correlation.
- **D-03:** Production authorization, tamper-resistant audit storage, retention, and policy enforcement.

## User stories

### US-01 — Add a SQLite dataset with reviewed code

**Story:** As a developer, I want to provide a dataset schema and relevant application code as context, so that Copilot can create useful lookup tools that I can inspect before use.

**Rationale:** Reusing schema and domain logic avoids re-deriving relationships while keeping runtime behavior explicit and reviewable.

**Acceptance criteria:**

- **AC-01.1:** The repository contains a valid project-local skill with a discriminating description and an intake guide for SQLite paths/schemas, code context, questions, output fields, and exclusions.
- **AC-01.2:** The skill directs generated additions to use dataset-prefixed fixed tools, explicit server registration, and a local dataset-specific path configuration.
- **AC-01.3:** The skill requires parameterized read-only SQLite operations, validated and bounded arguments, stable ordering, and no model-provided SQL or runtime code loading.
- **AC-01.4:** The skill requires every tool call to pass through `LookupService.invoke` and shared audit writing; audit write failure must not return successful data.
- **AC-01.5:** README explains how to invoke the skill and disclose that returned fields appear in local audit logs and may be sent to the configured model provider.

**Edge cases:** Missing business rules require clarification; unknown or excluded fields remain out of tool results; real rows are not copied into fixtures or documentation.

## Non-functional requirements

- **NFR-01 — Determinism:** New lookup data is stable for the same inputs against unchanged data; audit metadata and model behavior are excluded.
- **NFR-02 — Auditability:** New operations use the current audit schema and request ID behavior, and retain fail-closed handling.
- **NFR-03 — Privacy:** Database inspection is read-only and minimal. Tool results contain only approved fields because the audit writer records successful results.

## External input and data handling

- **Sources and validation:** Accept SQLite schema/DDL/migrations, a user-identified SQLite path inspected read-only, relevant source code paths, example questions, and field rules. Do not execute supplied code or migrations.
- **Remote retrieval:** None.
- **Files:** Do not copy databases or real records into the repository. Use synthetic fixtures; avoid full-table dumps.
- **Data and access:** Database and audit paths are local. The skill must surface returned-field exposure to both local audit and the configured model provider. Existing prototype does not provide per-user authorization.

## Codebase context

The Python package exposes three operations from `src/local_data_mcp/server.py`. `LookupService` in `service.py` validates and allowlists operations and sends each call through `AuditWriter` in `audit.py`; `database.py` provides the read-only SQLite connection helper. The current server binds a single database path from `LOCAL_DATA_MCP_DB_PATH` and registers typed FastMCP functions directly. A new dataset therefore needs a separately bound local path, explicit per-dataset operations, and static tool registration while sharing the audit writer. `.mcp.json` is the local Copilot workspace configuration. No new dataset was supplied for this release, so no dataset-specific adapter is generated now.

## Assumptions and open questions

### Assumptions

- **A-01:** Copilot in VS Code is the target authoring client; the skill is stored under `.github/skills/`.
- **A-02:** New datasets will be SQLite and the user can provide the code context needed to explain business semantics.
- **A-03:** Dataset-specific code is reviewed before a new MCP tool is used.

### Open questions

- None blocking the creation of the reusable skill. A real dataset may introduce business or access questions that must be resolved before its tools are generated.

## Amendment history

| Version | Date | Change | Reason | Affected IDs |
|---|---|---|---|---|
| 0.1 | 2026-11-06 | Initial draft | Initial discovery | All |
| 0.2 | 2026-11-07 | Set v1 to Copilot, SQLite, and reviewed development-time code generation | User selections | R-01–R-05, US-01, A-01–A-03 |
