"""apply_leave and its dry-run twin check_apply_leave (Section 6.2 of the brief).

check_apply_leave applies every rule and writes nothing: it powers the "propose"
step of the confirmation flow. apply_leave re-checks inside a database transaction
and then writes, so data that changed since the proposal is caught.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime

from app.config import parse_iso_date
from app.data import repository
from app.data.db import transaction
from app.tools.common import LEAVE_TYPES, LEAVE_YEAR, fmt
from app.tools.context import ToolContext
from app.tools.results import ToolResult, failure, success
from app.tools.working_days import count_working_days


@dataclass
class _ValidApply:
    leave_type: str
    start: date
    end: date
    working_days: int
    balance_before: float


def _validate_apply(ctx: ToolContext, leave_type, start_date, end_date):
    """Return (_ValidApply, None) if the request is acceptable, else (None, error)."""
    if leave_type not in LEAVE_TYPES:
        return None, failure(
            "invalid_leave_type", "Leave type must be 'annual' or 'sick'. Please tell me which one."
        )
    try:
        start, end = parse_iso_date(start_date), parse_iso_date(end_date)
    except (ValueError, TypeError):
        return None, failure(
            "invalid_date", "Dates must be valid calendar dates in YYYY-MM-DD format."
        )
    if start.year != LEAVE_YEAR or end.year != LEAVE_YEAR:
        return None, failure("outside_2026", "Leave can only be requested for dates in 2026.")
    if start < ctx.today:
        return None, failure(
            "start_in_past",
            f"The start date must be today ({ctx.today.isoformat()}) or later.",
        )
    if end < start:
        return None, failure("end_before_start", "The end date must be on or after the start date.")

    requester = ctx.requester
    holidays = repository.holiday_dates(ctx.conn, requester.region, ctx.today, LEAVE_YEAR)
    days = count_working_days(start, end, holidays)
    if days == 0:
        return None, failure(
            "zero_working_days",
            "That range has no working days: it only covers weekends and public holidays.",
            working_days=0,
        )

    balance = repository.get_balance(ctx.conn, requester.employee_id, leave_type)
    if days > balance:
        return None, failure(
            "insufficient_balance",
            f"You have {fmt(balance)} {leave_type} leave day(s) left, "
            f"but this request needs {days} working day(s).",
            working_days=days,
            balance=balance,
        )

    overlaps = repository.overlapping_requests(ctx.conn, requester.employee_id, start, end)
    if overlaps:
        other = overlaps[0]
        return None, failure(
            "overlapping_request",
            f"These dates overlap your existing {other.status} {other.leave_type} request "
            f"from {other.start_date} to {other.end_date}.",
            working_days=days,
        )
    return _ValidApply(leave_type, start, end, days, balance), None


def check_apply_leave(ctx: ToolContext, leave_type, start_date, end_date) -> ToolResult:
    """Dry run: every rule is applied, nothing is written."""
    valid, error = _validate_apply(ctx, leave_type, start_date, end_date)
    if error:
        return error
    return success(
        leave_type=valid.leave_type,
        start_date=valid.start.isoformat(),
        end_date=valid.end.isoformat(),
        working_days=valid.working_days,
        balance_before=valid.balance_before,
        balance_after=valid.balance_before - valid.working_days,
    )


def apply_leave(ctx: ToolContext, leave_type, start_date, end_date) -> ToolResult:
    """Create a pending request for the requester and deduct the balance, atomically."""
    with transaction(ctx.conn):
        # Re-check inside the transaction: data may have changed since the proposal.
        valid, error = _validate_apply(ctx, leave_type, start_date, end_date)
        if error:
            return error
        request_id = str(uuid.uuid4())
        repository.insert_request(
            ctx.conn,
            request_id=request_id,
            employee_id=ctx.requester.employee_id,
            leave_type=valid.leave_type,
            start=valid.start,
            end=valid.end,
            working_days=valid.working_days,
            status="pending",
            created_at=datetime.now().replace(microsecond=0).isoformat(),
        )
        repository.adjust_balance(
            ctx.conn, ctx.requester.employee_id, valid.leave_type, -valid.working_days
        )
    return success(
        request_id=request_id,
        leave_type=valid.leave_type,
        start_date=valid.start.isoformat(),
        end_date=valid.end.isoformat(),
        working_days=valid.working_days,
        status="pending",
        balance_after=valid.balance_before - valid.working_days,
    )
