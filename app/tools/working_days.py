"""Working-day arithmetic.

A working day is a Monday to Friday date that is not a public holiday for the
employee's region. Holidays that fall on a weekend are already excluded by the
weekday test, so they are never subtracted twice.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable, List, Set


def daterange(start: date, end: date) -> Iterable[date]:
    """Every calendar date from start to end, both inclusive."""
    for offset in range((end - start).days + 1):
        yield start + timedelta(days=offset)


def working_dates(start: date, end: date, holidays: Set[date]) -> List[date]:
    if end < start:
        return []
    return [d for d in daterange(start, end) if d.weekday() < 5 and d not in holidays]


def count_working_days(start: date, end: date, holidays: Set[date]) -> int:
    return len(working_dates(start, end, holidays))
