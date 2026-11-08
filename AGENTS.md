# MCP audit routing

- For every user question in this project, first record the user's original question verbatim with the local-data-lookups MCP tool `audit_record_question`. Mark `retrospective` true only when recording an earlier question after the fact.
- Use the returned audit request ID as `question_id` when calling the project's MCP lookup or audit tools; record a new question for each distinct user question. Do not claim a question or lookup was audited if the audit tool failed or was unavailable.
- Answer questions about the project's database contents or audit records using MCP tools. Do not read those files directly to produce an answer. If an appropriate MCP lookup does not exist, explain the limitation or implement an approved fixed, audited tool.
- For development work, inspecting source code and running tests against temporary fixtures is permitted. Do not treat those checks as audited answers about the user's live data.
- If a client has stale tool definitions, use a freshly started standard MCP stdio session or ask the user to reload the client. Do not replace the MCP call with a direct SQLite or JSONL lookup.
- The MCP server does not automatically receive all client prompts or final natural-language answers. Do not imply that its audit log proves complete conversation capture.
