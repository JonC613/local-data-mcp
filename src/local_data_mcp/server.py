"""MCP stdio server exposing only the fixed lookup operations."""

from __future__ import annotations

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .audit import AuditWriter
from .service import LookupService


def _path_from_env(name: str, default: str) -> Path:
    return Path(os.environ.get(name, default)).expanduser().resolve()


def create_server(
    database_path: Path | None = None,
    audit_path: Path | None = None,
    phish_database_path: Path | None = None,
) -> FastMCP:
    database_path = database_path or _path_from_env("LOCAL_DATA_MCP_DB_PATH", "data/mock.sqlite")
    audit_path = audit_path or _path_from_env("LOCAL_DATA_MCP_AUDIT_PATH", "data/audit.jsonl")
    phish_database_path = phish_database_path or _path_from_env(
        "LOCAL_DATA_MCP_PHISH_DB_PATH", "data/phish.sqlite"
    )
    service = LookupService(database_path, AuditWriter(audit_path), phish_database_path)
    server = FastMCP("local-data-lookups")

    @server.tool()
    def find_customers(query: str, limit: int = 20) -> dict:
        """Find mock customers by a substring of their name."""
        return service.invoke("find_customers", {"query": query, "limit": limit})

    @server.tool()
    def list_customer_orders(customer_id: int, limit: int = 20) -> dict:
        """List a customer's mock orders in date order."""
        return service.invoke("list_customer_orders", {"customer_id": customer_id, "limit": limit})

    @server.tool()
    def get_order_details(order_id: int) -> dict:
        """Get a mock order, its customer, product lines, and total in cents."""
        return service.invoke("get_order_details", {"order_id": order_id})

    @server.tool()
    def phish_find_shows(
        query: str | None = None,
        year: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 20,
    ) -> dict:
        """Find Phish shows by venue/city/tour text, year, or date range."""
        return service.invoke("phish_find_shows", {
            "query": query, "year": year, "start_date": start_date,
            "end_date": end_date, "limit": limit,
        })

    @server.tool()
    def phish_get_show(show_date: str) -> dict:
        """Get show details and ordered setlist/song associations for an ISO date."""
        return service.invoke("phish_get_show", {"show_date": show_date})

    @server.tool()
    def phish_find_song_performances(query: str, limit: int = 20) -> dict:
        """Find matching song titles and the shows and sets where they were performed."""
        return service.invoke("phish_find_song_performances", {"query": query, "limit": limit})

    @server.tool()
    def audit_find_events(tool: str | None = None, limit: int = 20) -> dict:
        """List latest local audit event summaries, optionally filtered by exact tool name."""
        return service.invoke("audit_find_events", {"tool": tool, "limit": limit})

    @server.tool()
    def audit_get_event(request_id: str) -> dict:
        """Retrieve one recorded local audit event by its request UUID."""
        return service.invoke("audit_get_event", {"request_id": request_id})

    @server.tool()
    def audit_phish_sync_runs(limit: int = 20) -> dict:
        """List local Phish import audit runs, newest first."""
        return service.invoke("audit_phish_sync_runs", {"limit": limit})

    @server.tool()
    def audit_phish_sync_pages(run_id: int, limit: int = 50, offset: int = 0) -> dict:
        """List recorded Phish API page audit details for a sync run."""
        return service.invoke("audit_phish_sync_pages", {"run_id": run_id, "limit": limit, "offset": offset})

    return server


def main() -> None:
    create_server().run(transport="stdio")


if __name__ == "__main__":
    main()
