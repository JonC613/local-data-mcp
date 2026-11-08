---
feature: phish-audio-links
artifact: tiny
status: done
owner: user
version: 0.1
created: 2026-11-08
updated: 2026-11-08
---

# Local Phish audio links

## Summary

Return audited, deterministic links to show and individual performance pages on Phish.in, the recording source linked by Phish.net.

## Scope

Use existing local catalog dates, track slugs and audio status; no remote request, downloading, streaming or database changes. Links lead to webpages; they are not guaranteed direct audio files.

## Requirements

- **R-01:** Return show page URLs and catalog audio status for an exact show date; return not-found for missing shows.
- **R-02:** Find tracks by literal song or track title with optional show date, stable bounded pagination, and individual track page URLs; show audio status and safely omit links for missing or invalid slugs.
- **R-03:** Use parameterized read-only local queries, question correlation and the existing fail-closed audit path; medley links refer to the containing track.
- **R-04:** Document that the catalog is a snapshot and links or audio availability can change without a new import.

## Implementation outline

Register fixed show and song link operations through LookupService and the MCP server. Construct only validated Phish.in URLs from ISO dates and source slugs.

## Verification

Use temporary fixture data to test show links, medley matches, missing audio/slugs, literal search, pagination, input rejection, auditing and MCP discovery; run the CI suite.

## Done when

Both tools are callable with auditable results and usage is documented; no live data is changed.

## Amendment history

| Version | Date | Change | Reason | Affected IDs |
|---|---|---|---|---|
| 0.1 | 2026-11-08 | Initial implementation | Requested show and song audio links | R-01–R-04 |
## Execution evidence

- 2026-11-08: Full unittest suite passed 51 tests, including the audio link and MCP tests. A fresh MCP session returned the local show and track links for 2000-09-24.
