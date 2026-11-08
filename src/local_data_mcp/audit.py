"""Append-only JSONL tool audit writer for the local prototype."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


AUDIT_SCHEMA_VERSION = 2


class AuditWriter:
    def __init__(self, path: Path):
        self.path = path.expanduser().resolve()
        self._lock = threading.Lock()

    def make_event(
        self, *, tool: str, arguments: Any, outcome: str, result: Any = None, error: Any = None
    ) -> dict[str, Any]:
        return {
            "schema_version": AUDIT_SCHEMA_VERSION,
            "request_id": str(uuid4()),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "tool": tool,
            "tool_version": "1",
            "arguments": arguments,
            "outcome": outcome,
            "result": result,
            "error": error,
        }

    def write(self, event: dict[str, Any]) -> None:
        """Append one complete line; failures are surfaced to the caller."""
        line = (json.dumps(event, ensure_ascii=True, allow_nan=False, separators=(",", ":")) + "\n").encode("utf-8")
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a+b") as stream:
                stream.seek(0, os.SEEK_END)
                if stream.tell():
                    stream.seek(-1, os.SEEK_END)
                    if stream.read(1) != b"\n":
                        raise OSError("Audit log ends with an incomplete line; append refused.")
                stream.write(line)
                stream.flush()
                os.fsync(stream.fileno())
