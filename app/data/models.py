"""Plain data objects returned by the repository."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Employee:
    employee_id: str
    region: str
    join_date: str
    level: str
    role: str
    manager_id: Optional[str]
    # Personal data. Excluded from repr() so that logging an Employee by accident
    # cannot leak a name, email address or phone number.
    full_name: str = field(repr=False)
    email: str = field(repr=False)
    phone: str = field(repr=False)


@dataclass(frozen=True)
class LeaveRequest:
    request_id: str
    employee_id: str
    leave_type: str
    start_date: str
    end_date: str
    working_days: int
    status: str
    created_at: str

    def as_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "employee_id": self.employee_id,
            "leave_type": self.leave_type,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "working_days": self.working_days,
            "status": self.status,
        }
