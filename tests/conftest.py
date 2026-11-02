"""Shared fixtures: a small synthetic database with the exact schema from the brief.

Tests never touch the real veltrix.db, because the reviewers will run against a
fresh copy that may contain different rows.

Fixture "today" is Thursday 2026-10-15.
"""
from __future__ import annotations

from datetime import date

import pytest

from app.data import db, repository

TODAY = date(2026, 10, 15)

SCHEMA = """
CREATE TABLE employees (
  employee_id TEXT PRIMARY KEY,
  full_name   TEXT NOT NULL,
  email       TEXT NOT NULL,
  phone       TEXT NOT NULL,
  region      TEXT NOT NULL,
  join_date   TEXT NOT NULL,
  level       TEXT NOT NULL,
  role        TEXT NOT NULL,
  manager_id TEXT REFERENCES employees(employee_id)
);
CREATE TABLE leave_balances (
  employee_id TEXT NOT NULL REFERENCES employees(employee_id),
  leave_type   TEXT NOT NULL,
  balance_days REAL NOT NULL,
  PRIMARY KEY (employee_id, leave_type)
);
CREATE TABLE leave_requests (
  request_id   TEXT PRIMARY KEY,
  employee_id TEXT NOT NULL REFERENCES employees(employee_id),
  leave_type   TEXT NOT NULL,
  start_date   TEXT NOT NULL,
  end_date     TEXT NOT NULL,
  working_days INTEGER NOT NULL,
  status       TEXT NOT NULL,
  created_at   TEXT NOT NULL
);
"""

# id, name, region, role, manager
EMPLOYEES = [
    ("H1", "Hema Rao", "IN", "hr", None),
    ("M1", "Manoj Iyer", "IN", "manager", "H1"),
    ("M2", "Mia Stone", "US", "manager", "H1"),
    ("M3", "Max Brandt", "DE", "manager", "H1"),
    ("E1", "Esha Nair", "IN", "employee", "M1"),
    ("E2", "Eli Das", "IN", "employee", "M1"),
    ("E3", "Erin Cole", "US", "employee", "M2"),
    ("E4", "Eva Klein", "DE", "employee", "M3"),
]

# (id, request_id, type, start, end, working_days, status)
REQUESTS = [
    ("E1", "req-e1-approved", "annual", "2026-12-07", "2026-12-09", 3, "approved"),
    ("E1", "req-e1-pending", "annual", "2026-11-16", "2026-11-17", 2, "pending"),
    ("E1", "req-e1-cancelled", "annual", "2026-11-23", "2026-11-24", 2, "cancelled"),
    ("E1", "req-e1-past", "annual", "2026-02-16", "2026-02-20", 5, "approved"),
    ("E2", "req-e2-pending", "sick", "2026-11-02", "2026-11-03", 2, "pending"),
    ("E3", "req-e3-approved", "annual", "2026-11-30", "2026-12-02", 3, "approved"),
]

# region, doc_id, effective, date, name, kind
HOLIDAYS = [
    ("IN", "CAL-IN-2026", "2026-01-01", "2026-11-01", "Kannada Rajyotsava", "public"),   # Sunday
    ("IN", "CAL-IN-2026", "2026-01-01", "2026-11-09", "Deepavali", "public"),            # Monday
    ("IN", "CAL-IN-2026", "2026-01-01", "2026-12-25", "Christmas Day", "public"),        # Friday
    ("IN", "CAL-IN-2026", "2026-01-01", "2026-11-24", "Guru Nanak Jayanti", "restricted"),
    ("IN", "CAL-IN-2025", "2025-01-01", "2025-12-25", "Christmas Day", "public"),
    ("US", "CAL-US-2026", "2026-01-01", "2026-11-26", "Thanksgiving Day", "public"),     # Thursday
    ("US", "CAL-US-2026", "2026-01-01", "2026-11-27", "Day after Thanksgiving", "public"),
    ("DE", "CAL-DE-2026", "2026-01-01", "2026-12-24", "Heiligabend", "public"),          # Thursday
    ("DE", "CAL-DE-2026", "2026-01-01", "2026-12-25", "1. Weihnachtstag", "public"),     # Friday
    ("DE", "CAL-DE-2026", "2026-01-01", "2026-12-26", "2. Weihnachtstag", "public"),     # Saturday
]


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(str(tmp_path / "test.db"))
    connection.executescript(SCHEMA)
    db.ensure_schema(connection)
    for emp_id, name, region, role, manager in EMPLOYEES:
        slug = name.lower().replace(" ", ".")
        connection.execute(
            "INSERT INTO employees VALUES (?,?,?,?,?,?,?,?,?)",
            (emp_id, name, f"{slug}@veltrix.example", "+00 000 000", region,
             "2020-01-01", "L3", role, manager),
        )
        connection.execute("INSERT INTO leave_balances VALUES (?,?,?)", (emp_id, "annual", 10.0))
        connection.execute("INSERT INTO leave_balances VALUES (?,?,?)", (emp_id, "sick", 12.0))
    for emp_id, request_id, leave_type, start, end, days, status in REQUESTS:
        connection.execute(
            "INSERT INTO leave_requests VALUES (?,?,?,?,?,?,?,?)",
            (request_id, emp_id, leave_type, start, end, days, status, "2026-10-01T09:00:00"),
        )
    for region, doc_id, effective, day, name, kind in HOLIDAYS:
        connection.execute(
            "INSERT INTO holidays VALUES (?,?,?,?,?,?)",
            (doc_id, region, day, name, kind, effective),
        )
    yield connection
    connection.close()


@pytest.fixture
def ctx_for(conn):
    """ctx_for("E1") -> a ToolContext acting as employee E1 on the fixture date."""

    from app.tools.context import ToolContext  # imported lazily: tools arrive after the data layer

    def make(employee_id: str, today: date = TODAY) -> "ToolContext":
        requester = repository.get_employee(conn, employee_id)
        assert requester is not None, employee_id
        return ToolContext(conn=conn, requester=requester, today=today)

    return make
