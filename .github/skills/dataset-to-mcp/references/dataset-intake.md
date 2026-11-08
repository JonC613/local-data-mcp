# Dataset context for new MCP lookups

Provide only the context needed to create and review a fixed lookup. A SQLite file path is optional when a schema or migrations are available; the skill should not need a copy of production data.

```yaml
dataset_key: billing
sqlite_path: C:\path\to\billing.sqlite
schema_or_migrations:
  - path: db\schema.sql
  - path: db\migrations\
application_context:
  - path: src\billing\invoice_rules.py
  - note: "Invoice status meanings are defined by this module."
questions:
  - "Find an invoice by its external reference."
  - "Show the line items and total for an invoice."
return_fields:
  - invoice id, status, issued date, line item descriptions, total cents
excluded_fields:
  - payment token
  - customer tax identifier
limits:
  max_rows: 50
  max_search_length: 100
data_may_be_sent_to_model: "Only approved fields listed above"
```

Replace the example paths and fields with repository paths and domain terms. Mark unanswered values as unknown instead of guessing. Do not attach credentials or paste real records; synthetic examples are enough to clarify formats. The user must confirm any rule that changes who can see a field or how a business value is calculated.

## Generated integration contract

- Tool names are prefixed by a normalized dataset key.
- The local database path is configured separately from lookup arguments, using `LOCAL_DATA_MCP_<DATASET>_DB_PATH`.
- Each dataset has an explicit code-level operation allowlist and explicit server registration.
- All wrappers use `LookupService.invoke`; successful output fields are therefore present in the local audit record as well as the MCP result.
- Queries are fixed, parameterized, read-only, bounded, and stably ordered. Model input never selects SQL identifiers or SQL text.
- Dataset integration changes repository code and configuration for review. It does not load Python code or tool definitions from a dataset at runtime.
