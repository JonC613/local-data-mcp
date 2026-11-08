"""SQLite schema and reproducible synthetic fixtures."""

from __future__ import annotations

import sqlite3
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
