"""Constants and small helpers shared by the leave tools."""
from __future__ import annotations

from app.tools.results import FORBIDDEN_EMPLOYEE_MESSAGE, ToolResult, failure

LEAVE_TYPES = ("annual", "sick")
STATUSES = ("pending", "approved", "cancelled")
LEAVE_YEAR = 2026  # leave outside the 2026 calendar year is out of scope


def forbidden() -> ToolResult:
    """The one refusal used whenever another employee's data may not be shown."""
    return failure("forbidden", FORBIDDEN_EMPLOYEE_MESSAGE)


def fmt(number: float) -> str:
    """Format a balance without a trailing .0 (10.0 -> '10', 7.25 -> '7.25')."""
    return f"{number:g}"
