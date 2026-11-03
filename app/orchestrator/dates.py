"""Calendar facts handed to the planner so it never has to do date arithmetic itself.

All dates are calendar dates (no times, no zones). Weeks start on Monday.
"""
from __future__ import annotations

from datetime import date, timedelta

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _fmt(day: date) -> str:
    return f"{DAY_NAMES[day.weekday()]} {day.isoformat()}"


def calendar_hints(today: date) -> str:
    this_monday = today - timedelta(days=today.weekday())
    next_monday = this_monday + timedelta(days=7)
    next_friday = today + timedelta(days=(4 - today.weekday()) % 7 or 7)
    upcoming = ", ".join(_fmt(today + timedelta(days=i)) for i in range(1, 15))
    return "\n".join([
        f"Today: {_fmt(today)}",
        f"This week: {_fmt(this_monday)} to {_fmt(this_monday + timedelta(days=4))}",
        f"Next week (Monday to Friday of the following week): {_fmt(next_monday)} to {_fmt(next_monday + timedelta(days=4))}",
        f"Next Friday (the first Friday after today): {_fmt(next_friday)}",
        f"The next 14 days: {upcoming}",
    ])
