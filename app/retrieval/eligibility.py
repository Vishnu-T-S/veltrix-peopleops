"""Which documents a requester may read, and which apply to them (Section 5.1, rule 1).

A document is ELIGIBLE only if all three hold:
    1. the requester's role may read its access level,
    2. its regions include the requester's region, or GLOBAL,
    3. its effective date is on or before the reference date.

Access is deny-by-default: an unknown role or an unknown access level grants nothing.
The role and region always come from the database record of the requester.
"""
from __future__ import annotations

from datetime import date

from app.data.models import Employee
from app.ingestion.models import DocMeta

ROLE_ACCESS = {
    "employee": frozenset({"all"}),
    "manager": frozenset({"all", "managers"}),
    "hr": frozenset({"all", "managers", "hr"}),
}


def can_read(role: str, access_level: str) -> bool:
    return access_level in ROLE_ACCESS.get(role, frozenset())


def region_applies(meta: DocMeta, region: str) -> bool:
    return "GLOBAL" in meta.regions or (region or "").upper() in meta.regions


def is_eligible(meta: DocMeta, requester: Employee, reference_date: date) -> bool:
    return (
        can_read(requester.role, meta.access_level)
        and region_applies(meta, requester.region)
        and date.fromisoformat(meta.effective_date) <= reference_date
    )


def is_upcoming(meta: DocMeta, requester: Employee, reference_date: date) -> bool:
    """Readable and for the requester's region, but not yet in force.

    These documents never answer a question. They are only candidates for an
    "upcoming change" note, and only if they would win once they take effect.
    """
    return (
        can_read(requester.role, meta.access_level)
        and region_applies(meta, requester.region)
        and date.fromisoformat(meta.effective_date) > reference_date
    )
