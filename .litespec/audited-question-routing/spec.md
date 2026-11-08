---
feature: audited-question-routing
artifact: spec
status: done
owner: user
version: 0.1
created: 2026-11-07
updated: 2026-11-07
---

# Specification: Audited MCP question routing

## Summary
Record user questions through MCP and link subsequent MCP data and audit lookups to the recorded question. Add a fixed customer-count tool.

## Problem
A customer count was obtained through direct SQLite access, so that read was not recorded by the MCP audit service. The existing server also did not receive the natural-language question.

## Desired outcome
Questions about this project are explicitly recorded through MCP, and successful MCP lookups reference the question's audit ID.

## Boundaries
### Goals
- Capture exact submitted questions and correlate MCP lookup events.
- Require recorded question IDs for MCP lookups and add customer count.
### Non-goals
- Automatic interception of every client message or final answer, blocking OS-level file access, or claiming tamper-proof auditing.
### Constraints
- Keep query operations fixed, deterministic, local, read-only, and fail closed if auditing fails.
- Existing MCP clients must adopt question recording; the server cannot guarantee the client sends the current question.

## Requirements
### Current release
- **R-01:** Add question recording and require a valid recorded question ID on MCP lookups.
- **R-02:** Add a fixed audited customer count and project instructions for MCP-only answers.
- **R-03:** Mark retrospective question recording and document client-side limitations.
### Deferred
- **D-01:** A client or gateway that intercepts every prompt and final natural-language response automatically.

## User stories
### US-01 — Link questions to lookups
**Story:** As a user, I want my question and the lookup it caused recorded together so I can inspect the audit trail.
**Rationale:** A database answer should have traceable input and output.
**Acceptance criteria:**
- **AC-01.1:** The MCP question tool records the exact supplied question, retrospective flag, and unique request ID.
- **AC-01.2:** Successful MCP lookup and audit tools require a question ID referencing a successful recorded question; missing, malformed, and unrelated IDs are rejected and audited.
- **AC-01.3:** The fixed customer-count MCP tool returns the exact read-only count and logs its input and full response with the question ID.
**Edge cases:** Empty question, missing log, invalid UUID, stale client, unrecordable audit event.

### US-02 — Understand audit boundaries
**Story:** As a user, I want the routing rule and audit limitations made explicit so I can distinguish recorded tool activity from complete conversation capture.
**Rationale:** The server cannot observe messages that the client does not send.
**Acceptance criteria:**
- **AC-02.1:** An earlier question may be recorded with a retrospective marker; its timestamp represents the later recording time.
- **AC-02.2:** If recording the question or lookup fails, no successful response is returned.
- **AC-02.3:** Project instructions require MCP routing for questions, and documentation explains client cooperation, final-answer limitations, and restart requirements.
**Edge cases:** Client reuses a question ID, MCP server is unavailable, client bypasses MCP, or audit file is unwriteable.

## Non-functional requirements
- **NFR-01:** Customer counts are computed through read-only SQLite and a fixed query.
- **NFR-02:** Questions and complete tool responses remain local in the existing audit log.

## Codebase context
The local FastMCP server wraps fixed lookups through LookupService and AuditWriter. The JSONL writer stores full version 2 tool inputs and outputs; the client does not automatically forward entire conversations.

## Assumptions and open questions
### Assumptions
- **A-01:** Require a question ID for all MCP lookups while retaining direct service use for temporary development fixtures.
### Open questions
- None blocking the requested project-level routing.

## Amendment history
| Version | Date | Change | Reason | Affected IDs |
|---|---|---|---|---|
| 0.1 | 2026-11-07 | Initial implementation | User requested all questions use MCP auditing | All |
