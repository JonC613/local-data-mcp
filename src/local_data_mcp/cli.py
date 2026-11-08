"""Setup and launch commands for the local prototype."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from .database import create_database


def main() -> None:
    parser = argparse.ArgumentParser(prog="local-data-mcp")
    parser.add_argument("--init-db", action="store_true", help="Create the synthetic local database")
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
    from .server import main as run_server
    run_server()


if __name__ == "__main__":
    main()
