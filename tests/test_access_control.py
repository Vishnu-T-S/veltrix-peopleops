"""Who can see whose leave data, for each role (employee, manager, hr)."""
from app.data import repository
from app.tools.leave_read import get_leave_balance, get_team_leave, list_leave_requests
from app.tools.results import FORBIDDEN_EMPLOYEE_MESSAGE

# Fixture org: H1 (hr) manages M1/M2/M3; M1 manages E1, E2; M2 manages E3; M3 manages E4.


# ---- employee --------------------------------------------------------------

def test_employee_can_see_own_balance(ctx_for):
    result = get_leave_balance(ctx_for("E1"), "E1")
    assert result.ok and result.data["balances"] == {"annual": 10.0, "sick": 12.0}


def test_employee_can_filter_own_balance_by_type(ctx_for):
    result = get_leave_balance(ctx_for("E1"), "E1", "sick")
    assert result.ok and result.data["balances"] == {"sick": 12.0}


def test_employee_can_list_own_requests(ctx_for):
    result = list_leave_requests(ctx_for("E1"), "E1")
    ids = [r["request_id"] for r in result.data["requests"]]
    assert result.ok and "req-e1-approved" in ids and "req-e2-pending" not in ids


def test_employee_can_filter_own_requests_by_status(ctx_for):
    result = list_leave_requests(ctx_for("E1"), "E1", "pending")
    assert [r["request_id"] for r in result.data["requests"]] == ["req-e1-pending"]


def test_employee_cannot_see_a_colleagues_balance(ctx_for):
    result = get_leave_balance(ctx_for("E1"), "E2")
    assert not result.ok and result.error == FORBIDDEN_EMPLOYEE_MESSAGE


def test_employee_cannot_see_a_colleagues_requests(ctx_for):
    result = list_leave_requests(ctx_for("E1"), "E2")
    assert not result.ok and result.error == FORBIDDEN_EMPLOYEE_MESSAGE
    assert result.data == {}


def test_employee_cannot_see_their_own_managers_data(ctx_for):
    assert get_leave_balance(ctx_for("E1"), "M1").error == FORBIDDEN_EMPLOYEE_MESSAGE


def test_employee_cannot_use_get_team_leave(ctx_for):
    result = get_team_leave(ctx_for("E1"), "2026-11-01", "2026-12-31")
    assert not result.ok and result.code == "managers_only"


def test_refusal_is_identical_for_real_and_unknown_employees(ctx_for):
    # An employee must not be able to tell a real colleague from a made-up ID
    for requester in ("E1", "M1"):
        real_but_forbidden = get_leave_balance(ctx_for(requester), "E3")
        unknown = get_leave_balance(ctx_for(requester), "E9999")
        assert real_but_forbidden.error == unknown.error == FORBIDDEN_EMPLOYEE_MESSAGE
        assert real_but_forbidden.code == unknown.code == "forbidden"
        assert real_but_forbidden.data == unknown.data == {}


def test_same_for_list_requests(ctx_for):
    a = list_leave_requests(ctx_for("E1"), "E3")
    b = list_leave_requests(ctx_for("E1"), "E9999")
    assert (a.status, a.code, a.error, a.data) == (b.status, b.code, b.error, b.data)


# ---- manager ---------------------------------------------------------------

def test_manager_can_see_own_balance(ctx_for):
    assert get_leave_balance(ctx_for("M1"), "M1").ok


def test_manager_can_see_a_direct_reports_balance_and_requests(ctx_for):
    assert get_leave_balance(ctx_for("M1"), "E1").ok
    assert list_leave_requests(ctx_for("M1"), "E2").ok


def test_manager_cannot_see_another_teams_employee(ctx_for):
    assert get_leave_balance(ctx_for("M1"), "E3").error == FORBIDDEN_EMPLOYEE_MESSAGE
    assert list_leave_requests(ctx_for("M1"), "E4").error == FORBIDDEN_EMPLOYEE_MESSAGE


def test_manager_cannot_see_another_manager_or_hr(ctx_for):
    assert get_leave_balance(ctx_for("M1"), "M2").error == FORBIDDEN_EMPLOYEE_MESSAGE
    assert get_leave_balance(ctx_for("M1"), "H1").error == FORBIDDEN_EMPLOYEE_MESSAGE


def test_get_team_leave_returns_only_direct_reports(ctx_for):
    result = get_team_leave(ctx_for("M1"), "2026-11-01", "2026-12-31")
    assert result.ok
    people = {row["employee_id"] for row in result.data["leave"]}
    assert people == {"E1", "E2"}  # E3 (other team) is absent


def test_get_team_leave_hides_cancelled_requests(ctx_for):
    result = get_team_leave(ctx_for("M1"), "2026-11-01", "2026-12-31")
    statuses = {row["status"] for row in result.data["leave"]}
    assert statuses <= {"pending", "approved"}


def test_get_team_leave_only_includes_overlapping_dates(ctx_for):
    result = get_team_leave(ctx_for("M1"), "2026-11-16", "2026-11-16")
    assert [r["employee_id"] for r in result.data["leave"]] == ["E1"]


def test_get_team_leave_counts_partial_overlap(ctx_for):
    # Approved request runs 7-9 Dec; a window that only touches its last day still overlaps
    result = get_team_leave(ctx_for("M1"), "2026-12-09", "2026-12-20")
    assert [r["employee_id"] for r in result.data["leave"]] == ["E1"]


def test_get_team_leave_empty_window(ctx_for):
    result = get_team_leave(ctx_for("M1"), "2027-01-01", "2027-01-31")
    assert result.ok and result.data["leave"] == []


def test_get_team_leave_validates_dates(ctx_for):
    assert get_team_leave(ctx_for("M1"), "soon", "2026-12-31").code == "invalid_date"
    assert get_team_leave(ctx_for("M1"), "2026-12-31", "2026-12-01").code == "end_before_start"


# ---- hr ---------------------------------------------------------------------

def test_hr_can_see_any_one_employee_in_any_region(ctx_for):
    for target in ("E1", "E3", "E4", "M2"):
        assert get_leave_balance(ctx_for("H1"), target).ok
        assert list_leave_requests(ctx_for("H1"), target).ok


def test_hr_gets_a_plain_not_found_for_an_unknown_id(ctx_for):
    # HR is allowed to look anyone up, so "no such employee" leaks nothing to them
    assert get_leave_balance(ctx_for("H1"), "E9999").code == "employee_not_found"


def test_hr_is_not_a_manager_for_team_leave(ctx_for):
    assert get_team_leave(ctx_for("H1"), "2026-11-01", "2026-12-31").code == "managers_only"


# ---- input checks and privacy ----------------------------------------------

def test_invalid_leave_type_and_status_are_rejected(ctx_for):
    assert get_leave_balance(ctx_for("E1"), "E1", "vacation").code == "invalid_leave_type"
    assert list_leave_requests(ctx_for("E1"), "E1", "done").code == "invalid_status"


def test_balance_tool_returns_no_personal_data(ctx_for):
    result = get_leave_balance(ctx_for("H1"), "E1")
    text = str(result.data)
    assert "Esha" not in text and "@" not in text


def test_employee_repr_does_not_contain_personal_data(conn):
    employee = repository.get_employee(conn, "E1")
    text = repr(employee)
    assert "Esha" not in text and "veltrix.example" not in text and "+00" not in text
    assert "E1" in text
