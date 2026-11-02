"""Read-only tools: get_leave_balance, list_leave_requests, get_team_leave.

Permissions are enforced here, in code, using the requester carried in the
ToolContext. They never depend on the prompt or on arguments the LLM chose.
"""
from __future__ import annotations

from typing import Optional

from app.config import parse_iso_date
from app.data import repository
from app.tools import permissions
from app.tools.common import LEAVE_TYPES, STATUSES, forbidden
from app.tools.context import ToolContext
from app.tools.results import ToolResult, failure, success


def get_leave_balance(
    ctx: ToolContext, employee_id: str, leave_type: Optional[str] = None
) -> ToolResult:
    if leave_type is not None and leave_type not in LEAVE_TYPES:
        return failure("invalid_leave_type", "Leave type must be 'annual' or 'sick'.")
    if not permissions.can_view_employee(ctx, employee_id):
        return forbidden()
    if repository.get_employee(ctx.conn, employee_id) is None:
        return failure("employee_not_found", "No employee with that ID was found.")

    if leave_type:
        balances = {leave_type: repository.get_balance(ctx.conn, employee_id, leave_type)}
    else:
        stored = repository.get_balances(ctx.conn, employee_id)
        balances = {t: stored.get(t, 0.0) for t in LEAVE_TYPES}
    return success(employee_id=employee_id, balances=balances)


def list_leave_requests(
    ctx: ToolContext, employee_id: str, status: Optional[str] = None
) -> ToolResult:
    if status is not None and status not in STATUSES:
        return failure("invalid_status", "Status must be 'pending', 'approved' or 'cancelled'.")
    if not permissions.can_view_employee(ctx, employee_id):
        return forbidden()
    if repository.get_employee(ctx.conn, employee_id) is None:
        return failure("employee_not_found", "No employee with that ID was found.")

    requests = repository.list_requests(ctx.conn, employee_id, status)
    return success(employee_id=employee_id, requests=[r.as_dict() for r in requests])


def get_team_leave(ctx: ToolContext, start_date: str, end_date: str) -> ToolResult:
    if not permissions.is_manager(ctx):
        return failure("managers_only", "Only managers can view team leave.")
    try:
        start, end = parse_iso_date(start_date), parse_iso_date(end_date)
    except (ValueError, TypeError):
        return failure("invalid_date", "Dates must be valid calendar dates in YYYY-MM-DD format.")
    if end < start:
        return failure("end_before_start", "The end date must be on or after the start date.")

    rows = repository.team_requests(ctx.conn, ctx.requester.employee_id, start, end)
    team = [
        {
            "employee_id": r["employee_id"],
            "full_name": r["full_name"],  # permitted: these are the manager's own direct reports
            "leave_type": r["leave_type"],
            "start_date": r["start_date"],
            "end_date": r["end_date"],
            "working_days": r["working_days"],
            "status": r["status"],
        }
        for r in rows
    ]
    return success(start_date=start_date, end_date=end_date, leave=team)
