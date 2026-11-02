"""The five tools named in the brief, exposed through one module.

The orchestrator calls tools only through TOOLS (and the check_* dry runs), so the
set the LLM can ask for is exactly this set.
"""
from __future__ import annotations

from app.tools.leave_apply import apply_leave, check_apply_leave
from app.tools.leave_cancel import cancel_leave, check_cancel_leave
from app.tools.leave_read import get_leave_balance, get_team_leave, list_leave_requests

# Exact tool names from Section 6.1; they appear verbatim in the API's tool_calls.
TOOLS = {
    "get_leave_balance": get_leave_balance,
    "list_leave_requests": list_leave_requests,
    "get_team_leave": get_team_leave,
    "apply_leave": apply_leave,
    "cancel_leave": cancel_leave,
}

# Write tools take two steps (propose, then execute); these are the no-write checks.
DRY_RUNS = {
    "apply_leave": check_apply_leave,
    "cancel_leave": check_cancel_leave,
}

__all__ = [
    "TOOLS", "DRY_RUNS",
    "get_leave_balance", "list_leave_requests", "get_team_leave",
    "apply_leave", "check_apply_leave", "cancel_leave", "check_cancel_leave",
]
