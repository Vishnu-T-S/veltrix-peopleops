"""cancel_leave and its dry-run twin check_cancel_leave (Section 6.3 of the brief)."""
from __future__ import annotations

from app.config import parse_iso_date
from app.data import repository
from app.data.db import transaction
from app.tools.context import ToolContext
from app.tools.results import ToolResult, failure, success


def _validate_cancel(ctx: ToolContext, request_id):
    request = repository.get_request(ctx.conn, request_id) if request_id else None
    # A request that does not exist and a request that belongs to someone else get the
    # same answer, so request IDs cannot be probed.
    if request is None or request.employee_id != ctx.requester.employee_id:
        return None, failure(
            "request_not_found", "I couldn't find that request among your own leave requests."
        )
    if request.status == "cancelled":
        return None, failure("already_cancelled", "That request is already cancelled.")
    if parse_iso_date(request.start_date) <= ctx.today:
        return None, failure(
            "not_cancellable",
            "Only requests that start after today can be cancelled; "
            f"this one starts on {request.start_date}.",
        )
    return request, None


def check_cancel_leave(ctx: ToolContext, request_id) -> ToolResult:
    """Dry run for the proposal step: nothing is written."""
    request, error = _validate_cancel(ctx, request_id)
    if error:
        return error
    return success(**request.as_dict())


def cancel_leave(ctx: ToolContext, request_id) -> ToolResult:
    """Cancel one of the requester's own requests and return its days, atomically."""
    with transaction(ctx.conn):
        request, error = _validate_cancel(ctx, request_id)
        if error:
            return error
        repository.set_request_status(ctx.conn, request.request_id, "cancelled")
        repository.adjust_balance(
            ctx.conn, request.employee_id, request.leave_type, request.working_days
        )
    balance = repository.get_balance(ctx.conn, request.employee_id, request.leave_type)
    return success(
        request_id=request.request_id,
        leave_type=request.leave_type,
        start_date=request.start_date,
        end_date=request.end_date,
        working_days_returned=request.working_days,
        status="cancelled",
        balance_after=balance,
    )
