"""SQLite schema and reproducible synthetic fixtures."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE customers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE
);
CREATE TABLE products (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    sku TEXT NOT NULL UNIQUE
);
CREATE TABLE orders (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    ordered_at TEXT NOT NULL,
    status TEXT NOT NULL
);
CREATE INDEX orders_customer_date ON orders(customer_id, ordered_at, id);
CREATE TABLE order_items (
    id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    quantity INTEGER NOT NULL CHECK(quantity > 0),
    unit_price_cents INTEGER NOT NULL CHECK(unit_price_cents >= 0)
);
CREATE INDEX order_items_order ON order_items(order_id, id);
"""

SEED_CUSTOMERS = (
    (1, "Acme Analytics", "orders@acme.example"),
    (2, "Jordan Lee", "jordan.lee1@example.test"),
    (3, "Jordan Lee", "jordan.lee2@example.test"),
    (4, "Northwind Traders", "purchasing@northwind.example"),
)
SEED_PRODUCTS = (
    (10, "Field Notebook", "NOTE-01"),
    (11, "Desk Lamp", "LAMP-02"),
    (12, "USB-C Hub", "HUB-03"),
)
SEED_ORDERS = (
    (1001, 1, "2026-10-01T09:00:00Z", "shipped"),
    (1002, 1, "2026-10-10T14:30:00Z", "processing"),
    (1003, 2, "2026-10-10T14:30:00Z", "delivered"),
    (1004, 4, "2026-10-15T08:15:00Z", "cancelled"),
)
SEED_ITEMS = (
    (1, 1001, 10, 4, 350),
    (2, 1001, 12, 1, 2499),
    (3, 1002, 11, 2, 4250),
    (4, 1003, 10, 1, 350),
    (5, 1004, 12, 3, 2499),
)

MOCK_SEED_VERSION = "mock-100-v1"


def mock_seed_rows() -> dict[str, tuple[tuple, ...]]:
    """Generate the same 100 synthetic rows per table on every run."""
    customers = SEED_CUSTOMERS + tuple(
        (i, f"Synthetic Customer {i:03d}", f"customer{i:03d}@example.test")
        for i in range(5, 101)
    )
    product_types = ("Notebook", "Desk Lamp", "USB Hub", "Water Bottle", "Travel Bag", "Pen Set")
    products = SEED_PRODUCTS + tuple(
        (i, f"Synthetic {product_types[(i - 13) % len(product_types)]} {i:03d}", f"SYN-{i:03d}")
        for i in range(13, 110)
    )
    statuses = ("processing", "shipped", "delivered", "cancelled")
    start = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    orders = SEED_ORDERS + tuple(
        (i, i - 1000, (start + timedelta(days=3 * (i - 1005))).strftime("%Y-%m-%dT%H:%M:%SZ"),
         statuses[(i - 1005) % len(statuses)])
        for i in range(1005, 1101)
    )
    items = SEED_ITEMS + tuple(
        (i, i + 999, i + 7, 1 + (i % 5), 250 + ((i * 137) % 4750))
        for i in range(6, 101)
    )
    return {"customers": customers, "products": products, "orders": orders, "order_items": items}


def mock_seed_fingerprint() -> str:
    payload = json.dumps(mock_seed_rows(), sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class SeedConflict(RuntimeError):
    """Raised before mutation if existing records differ from the known fixture."""


def expand_mock_database(path: Path) -> dict:
    """Add missing fixture rows atomically without changing existing mock records."""
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Mock database not found at {path}; initialize it first.")
    fixtures = mock_seed_rows()
    fingerprint = mock_seed_fingerprint()
    connection = sqlite3.connect(f"{path.as_uri()}?mode=rw", uri=True, timeout=10)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        inserted = {}
        for table, desired_rows in fixtures.items():
            # Table names are fixed by mock_seed_rows, never supplied by the caller.
            expected = {row[0]: row for row in desired_rows}
            existing = connection.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
            if any(row[0] not in expected or tuple(row) != expected[row[0]] for row in existing):
                raise SeedConflict(f"{table} contains rows that differ from the synthetic fixture; no rows were added.")
            present = {row[0] for row in existing}
            missing = [row for row in desired_rows if row[0] not in present]
            placeholders = ",".join("?" for _ in desired_rows[0])
            connection.executemany(f"INSERT INTO {table} VALUES ({placeholders})", missing)
            inserted[table] = len(missing)
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise SeedConflict("Foreign key validation failed; no rows were added.")
        counts = {table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in fixtures}
        if any(count != 100 for count in counts.values()):
            raise SeedConflict("The synthetic seed must contain exactly 100 rows per table.")
        connection.commit()
        return {"seed_version": MOCK_SEED_VERSION, "sha256": fingerprint,
                "counts": counts, "inserted": inserted}
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


class DatabaseAlreadyExists(RuntimeError):
    """Raised instead of silently replacing an existing database."""


def create_database(path: Path, *, reset: bool = False) -> None:
    """Create and seed a local database; reset is always explicit."""
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if not reset:
            raise DatabaseAlreadyExists(
                f"Database already exists at {path}; pass --reset to replace it."
            )
        path.unlink()

    connection = sqlite3.connect(path)
    try:
        connection.executescript(SCHEMA)
        connection.executemany("INSERT INTO customers VALUES (?, ?, ?)", SEED_CUSTOMERS)
        connection.executemany("INSERT INTO products VALUES (?, ?, ?)", SEED_PRODUCTS)
        connection.executemany("INSERT INTO orders VALUES (?, ?, ?, ?)", SEED_ORDERS)
        connection.executemany("INSERT INTO order_items VALUES (?, ?, ?, ?, ?)", SEED_ITEMS)
        connection.commit()
    except Exception:
        connection.close()
        if path.exists():
            path.unlink()
        raise
    finally:
        try:
            connection.close()
        except Exception:
            pass


def open_readonly(path: Path) -> sqlite3.Connection:
    """Open an existing database in SQLite read-only mode."""
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Database not found at {path}; run setup first.")
    connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection
