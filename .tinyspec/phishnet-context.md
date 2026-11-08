---
feature: phishnet-context
artifact: tiny
status: done
owner: user
version: 0.1
created: 2026-11-08
updated: 2026-11-08
---

# Audited Phish.net show context

## Summary

Connect the existing MCP to Phish.net API v5 for sourced reviews, show notes and jam highlights, with explicit refresh and deterministic reads from a bounded process-local snapshot.

## Requirements

- **R-01:** Refresh one show date from fixed Phish.net HTTPS endpoints with a locally configured key, bounded responses, no redirects, and no key in logs.
- **R-02:** Expose review, highlight and status MCP tools through question correlation and the existing full-result audit writer; write a refresh-start audit before network access and withhold output on audit failure.
- **R-03:** Preserve the most recent successful snapshot in server memory, identify it by hash and fetch time, reject stale reads after 24 hours and report unavailable data without silently fetching.
- **R-04:** Attribute Phish.net, validate inputs and responses, return stable sorted results with bounded limits and test using synthetic responses.

## Scope

Snapshots are process-local and lost on restart; audit records are separate and retain complete outputs. API content and personal data retention in the JSONL audit requires review against source terms before production use. This does not implement generic web search, permanent snapshot replay, automatic scheduling or Bedrock integration.

## Implementation outline

Add a fixed Phish.net adapter, register refresh and read tools with the existing service and MCP wrapper, document key setup using the existing WSL app without printing secrets, and add fixture-based tests.

## Verification

Run focused tests for source validation, errors, safe secret handling, audit failure and stable snapshots, then the repository CI test suite. Do not claim live API validation without a successful real request.

## Amendment history

| Version | Date | Change | Reason | Affected IDs |
|---|---|---|---|---|
| 0.1 | 2026-11-08 | Initial implementation | User requested integration | R-01–R-04 |
## Done when

All four tools are registered; refresh, audit and expiry behavior are tested. The full suite passed 42 tests; a real Phish.net MCP refresh returned 7 reviews, 1 show and 1 jam-chart record.
