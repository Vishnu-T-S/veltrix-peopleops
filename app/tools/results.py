"""The value every tool returns, and the exact wording of its refusals."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

# Used whenever the requester may not see another employee's data. The message is
# identical whether or not that employee exists, so it cannot be used to probe
# which employee IDs are real.
FORBIDDEN_EMPLOYEE_MESSAGE = "I can't share information about that employee."


@dataclass
class ToolResult:
    status: str  # "success" | "error"
    data: Dict[str, Any] = field(default_factory=dict)
    code: Optional[str] = None     # short machine-readable reason
    error: Optional[str] = None    # specific, user-safe reason shown in the answer

    @property
    def ok(self) -> bool:
        return self.status == "success"


def success(**data: Any) -> ToolResult:
    return ToolResult(status="success", data=data)


def failure(code: str, message: str, **data: Any) -> ToolResult:
    return ToolResult(status="error", code=code, error=message, data=data)
