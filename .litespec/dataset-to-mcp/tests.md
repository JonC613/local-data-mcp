---
feature: dataset-to-mcp
artifact: tests
status: done
owner: user
version: 0.2
created: 2026-11-06
updated: 2026-11-07
spec_version: 0.2
plan_version: 0.2
---

# Test Plan: Dataset-to-MCP authoring skill

## Strategy

Validate the skill structure and review its critical instructions and README references. No dataset adapter is included because the user has not supplied a dataset; the adapter-specific query, MCP, and audit checks are a gate for that later task. Live discovery in Copilot is environment-specific and remains a manual check.

## Acceptance traceability

| Acceptance criterion | Test IDs | Method | Status |
|---|---|---|---|
| AC-01.1 | T-01, T-02 | Structural validation and content review | Passed |
| AC-01.2 | T-02 | Content review | Passed |
| AC-01.3 | T-02 | Content review | Passed |
| AC-01.4 | T-02 | Content review against `service.py` and `audit.py` | Passed |
| AC-01.5 | T-03 | Documentation cross-check | Passed |

## Critical user flows

### T-01 — Skill structure and metadata

- Covers: AC-01.1
- Level: structural validation
- Setup: Project-local skill folder under `.github/skills/dataset-to-mcp/`.
- Action: Run the skill creator's `quick_validate.py` against the skill folder.
- Expected: Valid skill metadata, name, and no unfinished scaffold placeholders.

### T-02 — Source and integration contract review

- Covers: AC-01.1, AC-01.2, AC-01.3, AC-01.4
- Level: manual review
- Setup: Skill, dataset intake reference, current lookup service, server, database helper, and audit writer.
- Action: Check the workflow against the required SQLite scope and current audit behavior.
- Expected: Static dataset-prefixed tools; a separate local path per dataset; fixed parameterized read-only operations; validation, bounds, stable order; no runtime loader or SQL tool; every invocation through `LookupService.invoke` and shared auditing.

### T-03 — README usage and data exposure

- Covers: AC-01.5
- Level: documentation review
- Setup: README and skill files.
- Action: Follow the instructions to locate the skill and prepare dataset context.
- Expected: Copilot skill path and intake reference are clear; the README explains local audit result capture and model-provider exposure.

## Failure and recovery cases

### T-04 — Future adapter audit-write failure

- Covers: AC-01.4
- Level: integration
- Setup: A generated dataset adapter with the shared audit writer configured to fail.
- Action: Invoke a valid dataset lookup.
- Expected: The new adapter returns an audit failure and withholds successful lookup data; after restoring the audit writer, the lookup succeeds and records the matching request ID.
- Status: Planned for the first dataset adapter; not run in this skill-only change.

## Manual exceptions

### M-01 — Live Copilot skill discovery

- Covers: AC-01.1
- Automation limitation: Copilot host version and workspace trust/settings vary by environment.
- Method: Open the repository in VS Code with Copilot Chat, ask it to use `dataset-to-mcp`, and confirm it can read the intake reference.
- Expected evidence: Copilot identifies the project skill and its SQLite-only scope.
- Status: Not run.

### M-02 — First dataset adapter

- Covers: R-02–R-04
- Automation limitation: No target dataset or schema was supplied in this task.
- Method: On the first dataset request, provide its SQLite schema, domain code paths, intended questions, and approved result fields; inspect generated code and run the focused adapter checks in P2-T1.
- Expected evidence: Explicit MCP discovery and invocation, stable query data for unchanged input/data, read-only database access, and matching audit request IDs for success and failure paths.
- Status: Deferred until a dataset is supplied.

## Test data and setup

- No dataset or real records were added. Future generated tests use synthetic SQLite fixtures in temporary paths.
- Structural skill validation does not exercise a generated dataset adapter or prove live Copilot discovery.

## Completion criteria

- [x] Skill structure and metadata pass validation.
- [x] Core workflow and README cover the approved boundaries and audit path.
- [x] Live Copilot discovery and future dataset-specific behavior are explicitly recorded as unverified/deferred.
- [x] No unresolved issue blocks delivery of the reusable skill.

## Amendment history

| Version | Date | Change | Reason | Affected IDs |
|---|---|---|---|---|
| 0.1 | 2026-11-06 | Initial draft | Derived from approved specification and plan | All |
| 0.2 | 2026-11-07 | Scope tests to skill validation; defer adapter checks until a dataset exists | No dataset supplied | All |
