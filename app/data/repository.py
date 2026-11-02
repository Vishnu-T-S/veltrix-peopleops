"""All SQL lives here. Nothing else in the code base writes queries."""
from __future__ import annotations

import sqlite3
from datetime import date
from typing import Iterable, List, Optional, Set

from app.data.models import Employee, LeaveRequest


def _employee(row: sqlite3.Row) -> Employee:
    return Employee(
        employee_id=row["employee_id"],
        full_name=row["full_name"],
        email=row["email"],
        phone=row["phone"],
        region=row["region"],
        join_date=row["join_date"],
        level=row["level"],
        role=row["role"],
        manager_id=row["manager_id"],
    )


def _request(row: sqlite3.Row) -> LeaveRequest:
    return LeaveRequest(
        request_id=row["request_id"],
        employee_id=row["employee_id"],
        leave_type=row["leave_type"],
        start_date=row["start_date"],
        end_date=row["end_date"],
        working_days=row["working_days"],
        status=row["status"],
        created_at=row["created_at"],
    )


# ---- employees -------------------------------------------------------------

def get_employee(conn: sqlite3.Connection, employee_id: str) -> Optional[Employee]:
    row = conn.execute(
        "SELECT * FROM employees WHERE employee_id = ?", (employee_id,)
    ).fetchone()
    return _employee(row) if row else None


def get_direct_reports(conn: sqlite3.Connection, manager_id: str) -> List[Employee]:
    rows = conn.execute(
        "SELECT * FROM employees WHERE manager_id = ? ORDER BY employee_id",
        (manager_id,),
    ).fetchall()
    return [_employee(r) for r in rows]


# ---- balances --------------------------------------------------------------

def get_balance(conn: sqlite3.Connection, employee_id: str, leave_type: str) -> float:
    """Missing row means no entitlement recorded: treated as 0."""
    row = conn.execute(
        "SELECT balance_days FROM leave_balances WHERE employee_id = ? AND leave_type = ?",
        (employee_id, leave_type),
    ).fetchone()
    return float(row["balance_days"]) if row else 0.0


def get_balances(conn: sqlite3.Connection, employee_id: str) -> dict:
    rows = conn.execute(
        "SELECT leave_type, balance_days FROM leave_balances WHERE employee_id = ?",
        (employee_id,),
    ).fetchall()
    return {r["leave_type"]: float(r["balance_days"]) for r in rows}


def adjust_balance(
    conn: sqlite3.Connection, employee_id: str, leave_type: str, delta: float
) -> None:
    conn.execute(
        """
        INSERT INTO leave_balances (employee_id, leave_type, balance_days)
        VALUES (?, ?, ?)
        ON CONFLICT (employee_id, leave_type)
        DO UPDATE SET balance_days = balance_days + excluded.balance_days
        """,
        (employee_id, leave_type, delta),
    )


# ---- leave requests --------------------------------------------------------

def get_request(conn: sqlite3.Connection, request_id: str) -> Optional[LeaveRequest]:
    row = conn.execute(
        "SELECT * FROM leave_requests WHERE request_id = ?", (request_id,)
    ).fetchone()
    return _request(row) if row else None


def list_requests(
    conn: sqlite3.Connection, employee_id: str, status: Optional[str] = None
) -> List[LeaveRequest]:
    sql = "SELECT * FROM leave_requests WHERE employee_id = ?"
    params: list = [employee_id]
    if status:
        sql += " AND status = ?"
        params.append(status)
    sql += " ORDER BY start_date, created_at, request_id"
    return [_request(r) for r in conn.execute(sql, params).fetchall()]


def overlapping_requests(
    conn: sqlite3.Connection,
    employee_id: str,
    start: date,
    end: date,
    statuses: Iterable[str] = ("pending", "approved"),
) -> List[LeaveRequest]:
    """Requests that share at least one calendar date with [start, end]."""
    statuses = tuple(statuses)
    marks = ",".join("?" for _ in statuses)
    rows = conn.execute(
        f"""
        SELECT * FROM leave_requests
        WHERE employee_id = ?
          AND status IN ({marks})
          AND start_date <= ? AND end_date >= ?
        ORDER BY start_date
        """,
        (employee_id, *statuses, end.isoformat(), start.isoformat()),
    ).fetchall()
    return [_request(r) for r in rows]


def team_requests(
    conn: sqlite3.Connection, manager_id: str, start: date, end: date
) -> List[sqlite3.Row]:
    """Pending and approved leave of a manager's direct reports overlapping the range."""
    return conn.execute(
        """
        SELECT r.*, e.full_name AS full_name
        FROM leave_requests r
        JOIN employees e ON e.employee_id = r.employee_id
        WHERE e.manager_id = ?
          AND r.status IN ('pending', 'approved')
          AND r.start_date <= ? AND r.end_date >= ?
        ORDER BY r.start_date, r.employee_id
        """,
        (manager_id, end.isoformat(), start.isoformat()),
    ).fetchall()


def insert_request(
    conn: sqlite3.Connection,
    request_id: str,
    employee_id: str,
    leave_type: str,
    start: date,
    end: date,
    working_days: int,
    status: str,
    created_at: str,
) -> None:
    conn.execute(
        """
        INSERT INTO leave_requests
            (request_id, employee_id, leave_type, start_date, end_date,
             working_days, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (request_id, employee_id, leave_type, start.isoformat(), end.isoformat(),
         working_days, status, created_at),
    )


def set_request_status(conn: sqlite3.Connection, request_id: str, status: str) -> None:
    conn.execute(
        "UPDATE leave_requests SET status = ? WHERE request_id = ?", (status, request_id)
    )


# ---- holidays --------------------------------------------------------------

def holiday_dates(
    conn: sqlite3.Connection, region: str, today: date, year: int
) -> Set[date]:
    """Public-holiday dates of `year` for `region`, from the calendar that applies.

    Several calendars can exist for a region (for example 2025 and 2026). The one
    that applies is the most recently effective calendar, already in force on
    `today`, that lists holidays in `year`. Restricted holidays are optional days
    when the office stays open, so they are never returned here.
    """
    row = conn.execute(
        """
        SELECT doc_id FROM holidays
        WHERE region = ? AND kind = 'public'
          AND effective_date <= ?
          AND substr(holiday_date, 1, 4) = ?
        ORDER BY effective_date DESC, doc_id
        LIMIT 1
        """,
        (region, today.isoformat(), str(year)),
    ).fetchone()
    if row is None:
        return set()
    rows = conn.execute(
        """
        SELECT holiday_date FROM holidays
        WHERE region = ? AND kind = 'public' AND doc_id = ?
          AND substr(holiday_date, 1, 4) = ?
        """,
        (region, row["doc_id"], str(year)),
    ).fetchall()
    return {date.fromisoformat(r["holiday_date"]) for r in rows}
