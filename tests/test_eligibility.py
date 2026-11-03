"""Eligibility: role may read the access level, region applies, effective on the date."""
from datetime import date

import pytest

from app.data import repository
from app.ingestion.models import DocMeta
from app.retrieval.eligibility import can_read, is_eligible, is_upcoming, region_applies

REF = date(2026, 10, 15)


def doc(access="all", regions=("GLOBAL",), effective="2026-01-01"):
    return DocMeta("D", "f", "T", "policy", regions, effective, access)


@pytest.mark.parametrize("role, access, allowed", [
    ("employee", "all", True), ("employee", "managers", False), ("employee", "hr", False),
    ("manager", "all", True), ("manager", "managers", True), ("manager", "hr", False),
    ("hr", "all", True), ("hr", "managers", True), ("hr", "hr", True),
])
def test_role_access_matrix(role, access, allowed):
    assert can_read(role, access) is allowed


@pytest.mark.parametrize("role, access", [
    ("intern", "all"), ("", "all"), ("HR", "hr"), ("employee", "secret"), ("hr", "ALL"), ("hr", ""),
])
def test_unknown_roles_and_levels_are_denied_by_default(role, access):
    assert can_read(role, access) is False


def test_region_matching():
    assert region_applies(doc(regions=("GLOBAL",)), "IN")
    assert region_applies(doc(regions=("IN", "US")), "US")
    assert region_applies(doc(regions=("DE",)), "de")
    assert not region_applies(doc(regions=("DE",)), "IN")


def test_effective_date_boundary(conn):
    employee = repository.get_employee(conn, "E1")
    assert is_eligible(doc(effective="2026-10-15"), employee, REF)         # effective today: applies
    assert not is_eligible(doc(effective="2026-10-16"), employee, REF)     # tomorrow: does not yet
    assert is_eligible(doc(effective="2025-01-01"), employee, REF)


def test_all_three_conditions_are_required(conn):
    employee = repository.get_employee(conn, "E1")       # employee, India
    assert is_eligible(doc(), employee, REF)
    assert not is_eligible(doc(access="hr"), employee, REF)
    assert not is_eligible(doc(regions=("DE",)), employee, REF)
    assert not is_eligible(doc(effective="2027-01-01"), employee, REF)


def test_upcoming_means_readable_regional_and_not_yet_effective(conn):
    employee = repository.get_employee(conn, "E1")
    assert is_upcoming(doc(effective="2027-01-01"), employee, REF)
    assert not is_upcoming(doc(effective="2026-01-01"), employee, REF)               # already in force
    assert not is_upcoming(doc(effective="2027-01-01", access="hr"), employee, REF)  # not readable
    assert not is_upcoming(doc(effective="2027-01-01", regions=("DE",)), employee, REF)  # wrong region


def test_an_unreadable_document_is_neither_eligible_nor_upcoming(conn):
    employee = repository.get_employee(conn, "E1")
    hidden = doc(access="managers", effective="2027-01-01")
    assert not is_eligible(hidden, employee, REF) and not is_upcoming(hidden, employee, REF)
