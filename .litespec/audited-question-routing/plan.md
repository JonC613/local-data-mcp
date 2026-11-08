---
feature: audited-question-routing
artifact: plan
status: done
owner: user
version: 0.1
created: 2026-11-07
updated: 2026-11-07
spec_version: 0.1
---

# Implementation Plan: Audited MCP question routing

## Technical approach
Add a question-recording tool and a customer count to the existing service and MCP server. Enforce and validate question IDs for server-wrapped lookup and audit operations while retaining direct service use in fixture tests. Write a project agent instruction to route questions through MCP.

## Key decisions
### KD-01 — Require question correlation
- **Choice:** Keep question_id optional in the protocol schema so the wrapper can audit missing IDs, but require a valid recorded question for successful lookups.
- **Rationale:** Missing or fabricated correlation must not return data.
- **Alternatives considered:** Optional correlation for all clients.
- **Consequences:** Existing clients must record questions and reload tool definitions.

### KD-02 — Distinguish retrospective records
- **Choice:** Store a retrospective boolean on explicitly backfilled questions.
- **Rationale:** A later replay cannot represent the time or audit trail of an earlier direct database read.
- **Alternatives considered:** Treating the replay as the original event.
- **Consequences:** The original unaudited direct access remains unrecorded.

## Impacted areas
| Area | Expected change | Related IDs |
|---|---|---|
| MCP server and service | Question recording, ID validation, customer count | AC-01.1, AC-01.2, AC-01.3, AC-02.2 |
| AGENTS.md and README | Agent routing and audit limitations | AC-02.3 |
| Tests | MCP protocol, count, correlation, and audit failures | US-01, US-02 |

## Implementation phases
### Phase 1 — Add audited routing
- [x] **P1-T1 — Add MCP tools and question enforcement**
  - Covers: US-01, AC-01.1, AC-01.2, AC-01.3, AC-02.2
  - Depends on: None
  - Work: Implement exact question capture, validated IDs, audited read-only count, and fail-closed behavior.
  - Verify: Fixture and real MCP transport checks.
- [x] **P1-T2 — Establish routing guidance**
  - Covers: US-02, AC-02.1, AC-02.3
  - Depends on: P1-T1
  - Work: Document agent routing, retrospective marker, and conversation capture limitations.
  - Verify: Review project instructions and README.
- [x] **P1-T3 — Re-run prior question honestly**
  - Covers: AC-02.1, AC-01.3
  - Depends on: P1-T1
  - Work: Record the prior count question as retrospective and rerun the count through MCP.
  - Verify: Confirm recorded question ID and linked MCP count result.

## Amendment history
| Version | Date | Change | Reason | Affected IDs |
|---|---|---|---|---|
| 0.1 | 2026-11-07 | Initial implementation | User requested MCP-only question routing | All |
