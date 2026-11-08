"""Setup and launch commands for the local prototype."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from uuid import uuid4

from .audit import AuditWriter
from .database import MOCK_SEED_VERSION, create_database, expand_mock_database


def seed_mock_100(path: Path, audit_path: Path) -> dict:
    """Record a seed intent and its outcome around the atomic database update."""
    path = path.expanduser().resolve()
    writer = AuditWriter(audit_path)
    run_id = str(uuid4())
    arguments = {"database": str(path), "seed_version": MOCK_SEED_VERSION, "seed_run_id": run_id}
    try:
        writer.write(writer.make_event(tool="seed_mock_100", arguments=arguments, outcome="started"))
    except (OSError, TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise RuntimeError("No rows were added: the seed-start audit record could not be written.") from exc
    try:
        result = {"database": str(path), "seed_run_id": run_id, **expand_mock_database(path)}
    except Exception as exc:
        error = {"type": type(exc).__name__, "message": str(exc)}
        try:
            writer.write(writer.make_event(tool="seed_mock_100", arguments=arguments, outcome="error",
                                           result={"ok": False, "error": error}, error=error))
        except (OSError, TypeError, ValueError, OverflowError, RecursionError) as audit_exc:
            raise RuntimeError(f"Seeding failed and its outcome audit could not be written; run ID {run_id}.") from audit_exc
        raise
    try:
        writer.write(writer.make_event(tool="seed_mock_100", arguments=arguments, outcome="success", result=result))
    except (OSError, TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise RuntimeError(f"The database was updated, but its completion audit could not be written; run ID {run_id}.") from exc
    return result


def main() -> None:
    parser = argparse.ArgumentParser(prog="local-data-mcp")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--init-db", action="store_true", help="Create the synthetic local database")
    actions.add_argument("--seed-100", action="store_true", help="Add the audited 100-row synthetic fixture to an existing mock database")
    parser.add_argument("--reset", action="store_true", help="Replace the database (requires --init-db)")
    parser.add_argument("--db", type=Path, help="Database path; defaults to LOCAL_DATA_MCP_DB_PATH or data/mock.sqlite")
    args = parser.parse_args()
    if args.reset and not args.init_db:
        parser.error("--reset requires --init-db")
    if args.init_db:
        path = args.db or Path(os.environ.get("LOCAL_DATA_MCP_DB_PATH", "data/mock.sqlite"))
        create_database(path, reset=args.reset)
        print(f"Created mock database at {path.expanduser().resolve()}")
        return
    if args.seed_100:
        path = args.db or Path(os.environ.get("LOCAL_DATA_MCP_DB_PATH", "data/mock.sqlite"))
        audit = Path(os.environ.get("LOCAL_DATA_MCP_AUDIT_PATH", "data/audit.jsonl"))
        try:
            result = seed_mock_100(path, audit)
        except Exception as exc:
            parser.exit(1, f"Mock seed failed: {exc}\n")
        print(json.dumps(result, ensure_ascii=True, sort_keys=True))
        return
    from .server import main as run_server
    run_server()


if __name__ == "__main__":
    main()
