"""SQLite connection handling.

We only ever ADD tables and indexes to veltrix.db. The three existing tables
(employees, leave_balances, leave_requests) are never altered or dropped.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

# Public holidays and restricted holidays extracted from the calendar documents
# during ingestion. `doc_id` and `effective_date` record which calendar a row came
# from, so the right calendar can be chosen when several exist for a region.
EXTRA_SCHEMA = """
CREATE TABLE IF NOT EXISTS holidays (
    doc_id         TEXT NOT NULL,
    region         TEXT NOT NULL,
    holiday_date   TEXT NOT NULL,
    name           TEXT NOT NULL,
    kind           TEXT NOT NULL CHECK (kind IN ('public', 'restricted')),
    effective_date TEXT NOT NULL,
    PRIMARY KEY (doc_id, region, holiday_date, kind)
);
CREATE INDEX IF NOT EXISTS idx_holidays_region_date
    ON holidays (region, holiday_date);
CREATE INDEX IF NOT EXISTS idx_leave_requests_employee
    ON leave_requests (employee_id, status);
CREATE INDEX IF NOT EXISTS idx_employees_manager
    ON employees (manager_id);
"""


def connect(db_path: str) -> sqlite3.Connection:
    """Open a connection. Transactions are managed explicitly via transaction()."""
    conn = sqlite3.connect(db_path, isolation_level=None, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(EXTRA_SCHEMA)


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """All-or-nothing block. BEGIN IMMEDIATE takes the write lock up front, so two
    concurrent requests cannot both pass a balance check and then both write."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
