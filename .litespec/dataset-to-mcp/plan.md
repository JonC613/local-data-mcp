---
feature: dataset-to-mcp
artifact: plan
status: done
owner: user
version: 0.2
created: 2026-11-06
updated: 2026-11-07
spec_version: 0.2
---

# Implementation Plan: Dataset-to-MCP authoring skill

## Technical approach

Add a concise skill under `.github/skills/dataset-to-mcp/` so Copilot can use it in the workspace. Give it a focused SQLite intake reference and instructions to inspect the existing server, lookup service, database helper, audit writer, and Copilot config before generating tools. The skill makes static, reviewable Python and configuration changes when a dataset is supplied; it does not install a runtime loader.

For a new dataset, bind its explicit operations to a dataset-specific local SQLite path, register namespaced MCP wrappers in code, and reuse the shared audit writer through `LookupService.invoke`. The existing service may need a small static per-dataset allowlist extension because it currently has a single operation map and one database path. Keep that change within the dataset-specific implementation task so its operations can be designed from the actual schema. No dataset was supplied in this task, so only the authoring workflow and integration contract are added.

## Key decisions

### KD-01 — Generate reviewed code at development time

- **Choice:** Use a project-local skill that creates static lookup handlers and explicit MCP registrations.
- **Rationale:** The user selected reviewed code generation. It keeps available operations inspectable in source control and avoids executing dataset-provided code at runtime.
- **Alternatives considered:** Dynamic dataset/tool attachment while the server runs.
- **Consequences:** Each dataset addition requires a code/config diff and focused coverage; no arbitrary SQL capability is introduced.

### KD-02 — SQLite for v1

- **Choice:** Consume SQLite schema, migrations, and relevant application source as context.
- **Rationale:** The current prototype is local Python/SQLite and has a read-only helper.
- **Alternatives considered:** PostgreSQL, API and file sources.
- **Consequences:** Other source types need a separate supported integration design.

### KD-03 — Preserve the shared audited service

- **Choice:** Dataset-specific service instances or an equivalent static allowlist route through `LookupService.invoke` and a shared `AuditWriter`.
- **Rationale:** This preserves the existing request IDs, bounded audit records, and fail-closed response path across datasets.
- **Alternatives considered:** Logging from dataset modules or bypassing the service wrapper.
- **Consequences:** New query data must be restricted to approved fields because successful output is logged locally. Audit integrity remains prototype-grade, not tamper-proof.

### KD-04 — Place the skill in the Copilot workspace

- **Choice:** Store it at `.github/skills/dataset-to-mcp/`.
- **Rationale:** The user selected GitHub Copilot. This is a project-level skill location supported by VS Code Copilot agent skills.
- **Alternatives considered:** A global personal skill, which would not travel with the repository.
- **Consequences:** Contributors open the repository in a compatible Copilot workspace to discover and use it.

## Impacted areas

| Area | Expected change | Related IDs |
|---|---|---|
| `.github/skills/dataset-to-mcp/SKILL.md` | Describe source assessment, reviewed code generation, deterministic query constraints, audit and privacy invariants | R-01–R-04 |
| `.github/skills/dataset-to-mcp/references/dataset-intake.md` | Provide a reusable context shape for schemas, code, questions, fields, and limits | R-01, R-03 |
| `README.md` | Document Copilot skill usage and audit/model data handling | R-05 |
| `src/local_data_mcp/service.py`, `server.py`, `.mcp.json` | Future dataset-specific additions; not changed until a dataset is supplied | R-02–R-04 |

## Technical detail

### Static extension shape

```text
SQLite database (local path from environment)
        -> dataset-bound lookup service
        -> fixed parameterized operation
        -> LookupService.invoke
        -> shared AuditWriter and MCP result
```

The dataset key prefixes tool names and forms the path variable, for example `billing_get_invoice` and `LOCAL_DATA_MCP_BILLING_DB_PATH`. Runtime arguments never choose a database, SQL fragment, table, or column.

## Risks and mitigations

| Risk | Impact | Mitigation | Evidence or trigger |
|---|---|---|---|
| Schema comments or source contain misleading instructions | Wrong or unsafe generated code | Treat supplied files as reference; inspect app behavior and ask about unresolved business rules | Review generated diff and query contract |
| Returned sensitive fields are captured in logs or sent to the model | Data exposure | Agree output and exclusion fields; current audit logs successful results; keep paths local | Review result schema and audit event |
| Additional operations bypass auditing | Untraceable tool activity | Require all wrappers to use `LookupService.invoke`; preserve fail-closed behavior | Inspect call path and focused audit coverage |
| Static operation map is not ready for multiple databases | Dataset A query reaches the wrong file | Bind each dataset to its own service/path and use a per-instance static allowlist | Dataset-specific integration review |

## Implementation phases

### Phase 1 — Provide the authoring workflow

- [x] **P1-T1 — Create the project skill**
  - Covers: R-01, R-02, R-03, R-04, AC-01.1, AC-01.2, AC-01.3, AC-01.4
  - Depends on: None
  - Work: Add Copilot-discoverable skill instructions for SQLite code generation, fixed queries, local paths, and audit integration.
  - Verify: Skill format validator and content review.
- [x] **P1-T2 — Add dataset intake context**
  - Covers: R-01, AC-01.1, AC-01.3
  - Depends on: P1-T1
  - Work: Add a focused intake reference for schema/code paths, desired questions, fields, limits, and privacy rules.
  - Verify: Check reference is linked from the skill and has no real dataset values.
- [x] **P1-T3 — Document Copilot use**
  - Covers: R-05, AC-01.5
  - Depends on: P1-T1
  - Work: Add skill usage instructions to README and describe local audit/model data exposure.
  - Verify: Cross-check location and scope against skill and existing MCP configuration.

### Phase 2 — Integrate a real SQLite dataset

- [ ] **P2-T1 — Generate the first dataset adapter**
  - Covers: R-02, R-03, R-04, AC-01.2, AC-01.3, AC-01.4
  - Depends on: None
  - Work: When a dataset is supplied, create schema-specific tools, static operation registration, a local database path configuration, and synthetic coverage using approved questions and fields.
  - Verify: Review and run focused query, read-only, MCP, determinism, and audit checks for the actual adapter.

## Release and rollback considerations

- **Release:** The project skill is available with this repository. Dataset tools are added only when requested with source context; inspect generated code/config before using them.
- **Rollback:** Revert the dataset-specific source and `.mcp.json` additions. The skill and existing mock tools remain independent.

## Amendment history

| Version | Date | Change | Reason | Affected IDs |
|---|---|---|---|---|
| 0.1 | 2026-11-06 | Initial draft | Derived from approved specification | All |
| 0.2 | 2026-11-07 | Selected static reviewed SQLite code generation in the Copilot workspace | User selections | KD-01–KD-04, P1-T1–P2-T1 |
