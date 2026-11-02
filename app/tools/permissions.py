"""Who may see whose leave data (Section 3.1 of the brief).

    employee   own data only
    manager    own data and direct reports' data
    hr         any one employee, one at a time

The role always comes from the database record of the requester.
"""
from __future__ import annotations

from app.data import repository
from app.tools.context import ToolContext


def can_view_employee(ctx: ToolContext, target_id: str) -> bool:
    """True if the requester may view leave data of `target_id`.

    This answers only from the requester's role and the reporting line. It does not
    reveal whether `target_id` exists: for an employee or a manager the answer is
    False for an unknown ID exactly as it is for a known but forbidden one.
    """
    requester = ctx.requester
    if target_id == requester.employee_id:
        return True
    if requester.role == "hr":
        return True
    if requester.role == "manager":
        target = repository.get_employee(ctx.conn, target_id)
        return target is not None and target.manager_id == requester.employee_id
    return False


def is_manager(ctx: ToolContext) -> bool:
    return ctx.requester.role == "manager"
