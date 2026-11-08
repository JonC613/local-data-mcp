---
feature: codex-mcp-connection
artifact: tiny
status: done
owner: user
version: 0.1
created: 2026-11-07
updated: 2026-11-07
---

# TinySpec: Connect the local lookup server to Codex

## Summary

Register the existing local stdio MCP server with Codex so the user can invoke its fixed lookup tools from Codex like other MCP servers.

## Scope

### Included

- Register the server in the user's Codex MCP configuration with the local Python environment, mock SQLite database, and audit path.
- Document the Codex CLI command, shared configuration behavior, example lookup prompts, and audit location.
- Verify registration, tool discovery and calls, and matching audit request IDs.

### Excluded

- A separate chat UI or MCP client, a new transport, model/API integration, and changes to the lookup queries.

## Requirements

- **R-01:** Codex can launch the existing server using stdio, the project virtual environment, and explicit local database and audit paths.
- **R-02:** README explains registration, confirmation, example prompts, and where local audit records are written.
- **R-03:** Codex lists the server as enabled, and the existing MCP verification confirms tool discovery, successful calls, and matching audit request IDs.

## Constraints and assumptions

- The server already uses MCP stdio and the database remains local/read-only.
- `codex mcp add` configures the user's Codex profile; the command, local paths, and environment variables contain no credentials.
- Codex can use MCP tools only when the local server process can start. A model's selection and wording remain nondeterministic.

## Implementation outline

- Register `local-data-lookups` in Codex using `codex mcp add` with the project virtual environment and explicit local database/audit paths.
- Add concise setup and usage instructions to README while retaining the Copilot `.mcp.json` entry.

## Verification

- Confirm `codex mcp list` shows `local-data-lookups` enabled.
- Run the existing local MCP checks and verify the three tools can be discovered/called and their response request IDs match local audit records.
- Verify the TinySpec and README instructions.

## Done when

- [x] Codex has a valid local stdio MCP registration (`codex mcp list` shows `local-data-lookups` enabled).
- [x] README documents how to connect and try the mock tools.
- [x] MCP and audit behavior have passing evidence; README states that a Codex client may need a restart after registration.

## Amendment history

| Version | Date | Change | Reason |
|---|---|---|---|
| 0.1 | 2026-11-07 | Define Codex MCP connection scope | User clarified they want a regular Codex MCP server |
| 0.2 | 2026-11-07 | Register server in Codex profile and document completion | Codex lists `local-data-lookups` as enabled |
