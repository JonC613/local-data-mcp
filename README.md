# Local data lookup MCP prototype

A local Python MCP server over synthetic SQLite data. It exposes three fixed, read-only operations: customer search, customer order listing, and order details. Each call writes a structured JSONL audit event before returning data. The same inputs and unchanged database produce the same lookup data; request IDs and timestamps are audit metadata, and LLM tool choices and wording are not deterministic.

## Requirements

- Python 3.11 or newer
- VS Code with GitHub Copilot Chat or Copilot CLI for client use

The database and audit file stay on this machine. Copilot may send prompts and tool results to the model provider configured for the session. Use only the included synthetic data in this prototype.

## Install and seed

From this project directory in PowerShell:

    py -3.11 -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -e .
    .\.venv\Scripts\python.exe -m local_data_mcp.cli --init-db

This creates data/mock.sqlite and refuses to overwrite an existing database. To deliberately recreate it:

    .\.venv\Scripts\python.exe -m local_data_mcp.cli --init-db --reset

The audit log is created at data/audit.jsonl on the first tool call. Override paths with LOCAL_DATA_MCP_DB_PATH and LOCAL_DATA_MCP_AUDIT_PATH if needed. Preserve these files to inspect local results; delete them manually to clear mock data and logs.

## Import Phish.in shows to local SQLite

The Python importer reads the public Phish.in API v2 and stores show, venue, track, and song association metadata in `data/phish.sqlite`. It does not download audio or media files. The API requires no key for these public reads. It performs a full snapshot sync, records each page's HTTP status, retry attempts, item count, fetch time, and SHA-256 response hash, then publishes the new snapshot in one SQLite transaction. A failed or incomplete fetch leaves the previous catalog in place. Each successful sync is recorded in `phish_sync_runs`.

Run this from the project directory after installation:

    .\.venv\Scripts\python.exe -m local_data_mcp.phish_importer

To choose a different local SQLite file, pass `--db C:\path\to\phish.sqlite` or set `LOCAL_DATA_MCP_PHISH_DB_PATH`. Do not point it at the mock customer database. Set the same path in your local MCP configuration.

The sync uses the official [Phish.in API v2](https://github.com/jcraigk/phishin/blob/main/app/javascript/components/pages/ApiDocs.jsx) show and track endpoints. Pagination is capped at 1,000 rows per page by the API, and the importer verifies page totals, row shapes, show-to-track IDs/dates, and song links before publishing. Results reflect the public source data as of the sync timestamp.

The MCP provides fixed, read-only Phish tools: `phish_find_shows` searches venue/city/tour text or filters by year/date range; `phish_get_show` returns the show or shows on a date with ordered tracks and song names; `phish_find_song_performances` finds matching song titles with show, set, and position. Inputs are bounded and parameterized. Each call uses the shared local JSONL audit writer. The API sync itself is separately auditable from the SQLite run and page ledgers.

Example questions after the first import: “Find Phish shows at Madison Square Garden in 1995”, “Show the setlist for 1997-11-17”, and “Find performances of Harry Hood.”

## View local databases and audits

From this project folder, start the local browser viewer:

    .\.venv\Scripts\python.exe -m local_data_mcp.viewer

The command opens a browser and prints a session link. Keep the terminal open while using the viewer; press Ctrl+C to stop it. If a browser does not open automatically, copy the complete printed link into a browser. The link contains the local session secret, so do not share it. Pass `--no-browser` to skip opening a browser, or `--port 8765` to use a specific loopback port.

Choose **Mock database** or **Phish database**, select an approved table, and use a column filter and pagination to browse its rows. Select a cell to inspect its complete value. The **Audit log** view filters by tool, outcome, request ID, and time; select an event to inspect its recorded arguments and response. Version 1 records may contain earlier truncation markers. The viewer keeps the audit list at a fixed file snapshot while paging; refresh the view to include later events.

The viewer defaults to `data/mock.sqlite`, `data/phish.sqlite`, and `data/audit.jsonl` relative to the launch folder. Override them using `LOCAL_DATA_MCP_DB_PATH`, `LOCAL_DATA_MCP_PHISH_DB_PATH`, and `LOCAL_DATA_MCP_AUDIT_PATH`, or the `--mock-db`, `--phish-db`, and `--audit-log` options. SQLite connections are read-only and there is no SQL console. The service binds to `127.0.0.1` with a per-launch session secret; it is intended for local use, not a multi-user or remote deployment.

Viewing data is itself recorded to the configured audit log, including the complete request and response. Viewing prior audit records can therefore duplicate data in the log and increase its size. If writing the audit record fails, the viewer withholds the data. The log remains editable and is not tamper-proof.

If the audit log ends with an incomplete JSONL line, new audit appends are refused to avoid joining a new event to the damaged line. The viewer identifies the incomplete line and withholds data until the log is repaired or an intact audit path is configured.

## Use with GitHub Copilot

Copy `.mcp.example.json` to `.mcp.json` and replace each `<PROJECT_ROOT>` with the absolute path of this checkout (JSON paths on Windows require doubled backslashes). The example uses the Windows virtual environment path; on other platforms use the appropriate Python executable and path separators. The local `.mcp.json` is ignored by Git because its paths are specific to your machine.

Open this folder in VS Code, select the Copilot harness in Chat, then run MCP: List Servers from the Command Palette. Confirm local-data-lookups is listed and start it if needed. Copilot may ask before each tool call. Try:

- Find customers named Jordan Lee and show their IDs.
- List customer 1's orders.
- Show order 1001 with its products and total.
- Find a customer named No Such Customer.

Inspect tool arguments and results in Copilot and the matching request_id in data/audit.jsonl. The actual Copilot host may require workspace trust and MCP support to be enabled. For current guidance, see [VS Code MCP configuration](https://code.visualstudio.com/docs/agents/reference/mcp-configuration) and [GitHub Copilot MCP servers](https://docs.github.com/en/copilot/how-tos/copilot-in-your-ide/customize-copilot/extend-copilot-with-tools-and-context/extend-copilot-chat-with-mcp).

Copilot CLI can also read the portable workspace .mcp.json format when run from this project. This server is local stdio; cloud-hosted Copilot sessions cannot access this machine's local database.

## Use with Codex

This is already a standard MCP stdio server. Codex CLI, the Codex desktop app, and the IDE extension share MCP configuration from the user's Codex profile ([official setup guide](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)). From this project directory in PowerShell, register it once:

    $ProjectRoot = (Get-Location).Path
    codex mcp add local-data-lookups --env "LOCAL_DATA_MCP_DB_PATH=$ProjectRoot\data\mock.sqlite" --env "LOCAL_DATA_MCP_AUDIT_PATH=$ProjectRoot\data\audit.jsonl" --env "LOCAL_DATA_MCP_PHISH_DB_PATH=$ProjectRoot\data\phish.sqlite" -- "$ProjectRoot\.venv\Scripts\python.exe" -m local_data_mcp.server

Confirm the server is listed with `codex mcp list`. In Codex, use `/mcp` to inspect connected servers, then try “Find Acme customers”, “List customer 1's orders”, “Show order 1001 with its products and total”, or “Find Phish shows at Madison Square Garden in 1995.” If the open Codex session does not see new tools after registration, restart that Codex client. Tool calls use the existing local audit log at `data/audit.jsonl`.

## Add another dataset with the project skill

The repository includes the `dataset-to-mcp` skill at `.github/skills/dataset-to-mcp/SKILL.md`. In Copilot Chat, ask it to use `dataset-to-mcp` to add a lookup, then provide the SQLite schema or migrations, paths to relevant application code, example questions, fields to return, and fields to exclude. For example: “Use `dataset-to-mcp` to add read-only lookups for invoice status and line items. Use `db/schema.sql` and `src/billing/` as context. Return invoice ID, status, date, and total; exclude payment tokens.” The optional intake shape is in `.github/skills/dataset-to-mcp/references/dataset-intake.md`.

The skill creates reviewed static Python tools for SQLite. It does not attach a dataset dynamically or expose arbitrary SQL. Each added database gets a local dataset-specific environment path; the generated wrappers use the shared audit service, and the server is updated with explicit tool registrations. Review the generated code and `.mcp.json` before using a new dataset. The audit file contains returned fields, so only include fields approved for local logging and model use. The model provider may receive prompts and tool results, as described above.

## Tools

| Tool | Input | Result |
|---|---|---|
| find_customers | query, optional limit (1–50) | Matching customers sorted by normalized name and ID |
| list_customer_orders | customer_id, optional limit (1–50) | That customer's orders sorted by date and ID |
| get_order_details | order_id | Customer, product lines, and total in integer cents |
| phish_find_shows | optional query, year, date range, limit (1–50) | Matching local Phish shows, in date and ID order |
| phish_get_show | show_date (YYYY-MM-DD) | Show metadata, ordered tracks, and associated song names |
| phish_find_song_performances | query, optional limit (1–50) | Matching song performances, in show/set order |
| audit_find_events | optional exact tool name and limit (1–50) | Newest lookup audit summaries in append order |
| audit_get_event | request_id UUID | The stored audit event, including its arguments and response |
| audit_phish_sync_runs | optional limit (1–50) | Most recent Phish import audit runs |
| audit_phish_sync_pages | run_id, optional limit (1–50) and offset | Phish import page status, counts, and response hashes |

No lookup tool accepts SQL or changes either database. Search treats %, _, and backslash literally. Responses place deterministic lookup fields under data and include an _audit.request_id metadata field; audit metadata varies by call.

## Audit record

Each new JSONL event uses schema version 2 and contains a unique request ID, UTC timestamp, tool and tool version, complete JSON arguments, outcome, and the full tool response (including errors and request ID). Events cover successful, invalid, not-found, and failed lookups. If an event cannot be serialized or written, the service returns audit_failure and withholds the lookup result. Version 1 events retain their original depth and size limits; values already truncated cannot be recovered from the log. The local file is editable and is not tamper-proof. It records tool activity only, not Copilot prompts or final responses.

Only calls reaching `LookupService.invoke` can be recorded here; MCP protocol or schema errors rejected before the tool wrapper runs are outside this log. An audit write failure itself cannot be guaranteed to appear in the unavailable log. Full arguments and responses can contain sensitive data and can grow the file substantially; protect and retain the file accordingly.

Try “Show the latest audit events”, “Find audit events for phish_get_show”, “Show audit request [request ID]”, or “Show Phish import runs and the pages for run 3”. Audit lookups and their full responses are also logged. Reading audit lookup events can duplicate previous records inside new records, so the file can grow quickly. Detailed event lookups return previously recorded arguments and results to the MCP client and its configured model provider. Sync pages can be paged with `offset`.

## Run locally without Copilot

    $env:LOCAL_DATA_MCP_DB_PATH = (Resolve-Path .\data\mock.sqlite).Path
    $env:LOCAL_DATA_MCP_AUDIT_PATH = (Join-Path (Get-Location) 'data\audit.jsonl')
    .\.venv\Scripts\python.exe -m local_data_mcp.server

The server uses MCP stdio, so VS Code or another MCP client should start and manage the process. To run the project test suite during development:

    .\.venv\Scripts\python.exe -m unittest discover -s tests -v

## Continuous integration

GitHub Actions installs the project and runs the test suite on pushes, pull requests, and manual runs. The matrix covers Windows and Linux with Python 3.11 and 3.13. The checks use temporary synthetic data and do not upload the local SQLite databases or audit log.

## Future work

The lookup service can be reused by a local chatbot that calls Amazon Bedrock with client-side tool use. The database can stay local, but prompts and selected lookup results sent for generation would leave the network. Before using real records, add user identity and authorization, decide which fields may leave the network, and replace local JSONL with protected audit storage and a retention policy. Full prompt/response capture requires the chatbot layer; this MCP server cannot see the entire conversation.
