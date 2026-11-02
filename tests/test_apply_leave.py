"""apply_leave rules (Section 6.2). Fixture date: Thursday 2026-10-15."""
import uuid

import pytest

from app.data import repository
from app.tools.leave_apply import apply_leave, check_apply_leave


def count_requests(conn):
    return conn.execute("SELECT COUNT(*) FROM leave_requests").fetchone()[0]


# ---- happy path --------------------------------------------------------------

def test_accepted_request_is_created_pending_with_balance_deducted(conn, ctx_for):
    before = count_requests(conn)
    result = apply_leave(ctx_for("E1"), "annual", "2026-10-19", "2026-10-21")  # Mon-Wed
    assert result.ok
    assert result.data["working_days"] == 3 and result.data["status"] == "pending"
    assert result.data["balance_after"] == 7.0
    assert count_requests(conn) == before + 1
    assert repository.get_balance(conn, "E1", "annual") == 7.0

    stored = repository.get_request(conn, result.data["request_id"])
    assert stored.status == "pending" and stored.working_days == 3
    assert stored.employee_id == "E1"
    assert (stored.start_date, stored.end_date) == ("2026-10-19", "2026-10-21")


def test_request_id_is_a_random_uuid4(ctx_for):
    first = apply_leave(ctx_for("E1"), "annual", "2026-10-19", "2026-10-19")
    second = apply_leave(ctx_for("E1"), "annual", "2026-10-20", "2026-10-20")
    assert uuid.UUID(first.data["request_id"]).version == 4
    assert first.data["request_id"] != second.data["request_id"]


def test_sick_leave_uses_the_sick_balance(conn, ctx_for):
    apply_leave(ctx_for("E1"), "sick", "2026-10-19", "2026-10-20")
    assert repository.get_balance(conn, "E1", "sick") == 10.0
    assert repository.get_balance(conn, "E1", "annual") == 10.0


def test_applying_as_a_manager_only_touches_the_managers_own_balance(conn, ctx_for):
    apply_leave(ctx_for("M1"), "annual", "2026-10-19", "2026-10-19")
    assert repository.get_balance(conn, "M1", "annual") == 9.0
    assert repository.get_balance(conn, "E1", "annual") == 10.0


def test_a_request_may_start_today(ctx_for):
    result = apply_leave(ctx_for("E1"), "annual", "2026-10-15", "2026-10-15")  # Thursday
    assert result.ok and result.data["working_days"] == 1


def test_request_for_exactly_the_remaining_balance_is_allowed(conn, ctx_for):
    conn.execute("UPDATE leave_balances SET balance_days = 3 WHERE employee_id='E2' AND leave_type='annual'")
    result = apply_leave(ctx_for("E2"), "annual", "2026-10-19", "2026-10-21")
    assert result.ok
    assert repository.get_balance(conn, "E2", "annual") == 0.0


def test_half_day_balances_are_handled(conn, ctx_for):
    conn.execute("UPDATE leave_balances SET balance_days = 2.5 WHERE employee_id='E2' AND leave_type='annual'")
    assert apply_leave(ctx_for("E2"), "annual", "2026-10-19", "2026-10-21").code == "insufficient_balance"
    assert apply_leave(ctx_for("E2"), "annual", "2026-10-19", "2026-10-20").ok
    assert repository.get_balance(conn, "E2", "annual") == 0.5


# ---- working days and holidays --------------------------------------------------

def test_weekend_only_range_is_rejected(ctx_for):
    result = apply_leave(ctx_for("E1"), "annual", "2026-10-17", "2026-10-18")
    assert result.code == "zero_working_days" and "no working days" in result.error


def test_range_spanning_a_weekend_charges_only_weekdays(ctx_for):
    result = check_apply_leave(ctx_for("E1"), "annual", "2026-10-16", "2026-10-19")  # Fri-Mon
    assert result.ok and result.data["working_days"] == 2


def test_india_holiday_only_range_is_rejected(ctx_for):
    # Christmas Day, Friday, public holiday in Bengaluru
    assert apply_leave(ctx_for("E1"), "annual", "2026-12-25", "2026-12-25").code == "zero_working_days"


def test_holidays_depend_on_the_requesters_region(ctx_for):
    # 24-25 Dec: Germany observes both days, India only the 25th
    germany = apply_leave(ctx_for("E4"), "annual", "2026-12-24", "2026-12-25")
    india = apply_leave(ctx_for("E1"), "annual", "2026-12-24", "2026-12-25")
    assert germany.code == "zero_working_days"
    assert india.ok and india.data["working_days"] == 1


def test_us_thanksgiving_week(ctx_for):
    result = check_apply_leave(ctx_for("E3"), "annual", "2026-11-25", "2026-11-27")  # Wed-Fri
    assert result.ok and result.data["working_days"] == 1


def test_restricted_holiday_still_counts_as_a_working_day(ctx_for):
    # 24 Nov 2026 is an optional day in India: the office is open
    result = check_apply_leave(ctx_for("E1"), "annual", "2026-11-24", "2026-11-24")
    assert result.ok and result.data["working_days"] == 1


def test_holiday_on_a_weekend_changes_nothing(ctx_for):
    result = check_apply_leave(ctx_for("E1"), "annual", "2026-10-30", "2026-11-03")  # Fri-Tue, Sun 1 Nov holiday
    assert result.data["working_days"] == 3


# ---- balance ----------------------------------------------------------------------

def test_insufficient_balance_is_rejected_with_the_numbers(conn, ctx_for):
    result = apply_leave(ctx_for("E1"), "annual", "2026-10-19", "2026-11-06")  # 15 weekdays (1 Nov is a Sunday)
    assert result.code == "insufficient_balance"
    assert "10" in result.error and "15" in result.error
    assert repository.get_balance(conn, "E1", "annual") == 10.0


def test_missing_balance_row_counts_as_zero(conn, ctx_for):
    conn.execute("DELETE FROM leave_balances WHERE employee_id='E2' AND leave_type='sick'")
    assert apply_leave(ctx_for("E2"), "sick", "2026-10-19", "2026-10-19").code == "insufficient_balance"


# ---- overlap ------------------------------------------------------------------------

def test_overlap_with_own_pending_request_is_rejected(ctx_for):
    result = apply_leave(ctx_for("E1"), "annual", "2026-11-17", "2026-11-18")
    assert result.code == "overlapping_request" and "2026-11-16" in result.error


def test_overlap_with_own_approved_request_is_rejected(ctx_for):
    assert apply_leave(ctx_for("E1"), "annual", "2026-12-09", "2026-12-11").code == "overlapping_request"


def test_overlap_is_checked_across_leave_types(ctx_for):
    assert apply_leave(ctx_for("E1"), "sick", "2026-12-08", "2026-12-08").code == "overlapping_request"


def test_sharing_a_single_date_counts_as_overlap(ctx_for):
    assert apply_leave(ctx_for("E1"), "annual", "2026-12-09", "2026-12-09").code == "overlapping_request"


def test_the_day_after_an_existing_request_is_fine(ctx_for):
    assert apply_leave(ctx_for("E1"), "annual", "2026-12-10", "2026-12-10").ok


def test_cancelled_requests_do_not_block(ctx_for):
    result = apply_leave(ctx_for("E1"), "annual", "2026-11-23", "2026-11-24")
    assert result.ok and result.data["working_days"] == 2


def test_other_peoples_requests_do_not_block(ctx_for):
    # E2 already has leave on 2-3 Nov; E1 may take the same days
    assert apply_leave(ctx_for("E1"), "annual", "2026-11-02", "2026-11-03").ok


# ---- dates and types --------------------------------------------------------------------

def test_start_before_today_is_rejected(ctx_for):
    assert apply_leave(ctx_for("E1"), "annual", "2026-10-14", "2026-10-14").code == "start_in_past"


def test_end_before_start_is_rejected(ctx_for):
    assert apply_leave(ctx_for("E1"), "annual", "2026-10-21", "2026-10-20").code == "end_before_start"


@pytest.mark.parametrize(
    "start, end",
    [("2027-01-04", "2027-01-05"), ("2025-12-31", "2026-01-02"), ("2026-12-30", "2027-01-04")],
)
def test_dates_outside_2026_are_rejected(ctx_for, start, end):
    assert apply_leave(ctx_for("E1"), "annual", start, end).code == "outside_2026"


@pytest.mark.parametrize("bad", ["next friday", "2026-13-01", "19/10/2026", "", None])
def test_malformed_dates_are_rejected(ctx_for, bad):
    assert apply_leave(ctx_for("E1"), "annual", bad, "2026-10-21").code == "invalid_date"


@pytest.mark.parametrize("bad", [None, "", "vacation", "Annual", "unpaid"])
def test_leave_type_must_be_annual_or_sick(ctx_for, bad):
    result = apply_leave(ctx_for("E1"), bad, "2026-10-19", "2026-10-19")
    assert result.code == "invalid_leave_type"


# ---- the dry run and atomicity -----------------------------------------------------------------

def test_check_apply_leave_writes_nothing(conn, ctx_for):
    before = count_requests(conn)
    result = check_apply_leave(ctx_for("E1"), "annual", "2026-10-19", "2026-10-21")
    assert result.ok and result.data["balance_after"] == 7.0
    assert count_requests(conn) == before
    assert repository.get_balance(conn, "E1", "annual") == 10.0


def test_check_and_apply_agree_on_rejections(ctx_for):
    for args in [("annual", "2026-10-17", "2026-10-18"), ("annual", "2026-11-17", "2026-11-18")]:
        assert check_apply_leave(ctx_for("E1"), *args).code == apply_leave(ctx_for("E1"), *args).code


def test_rejected_request_changes_nothing(conn, ctx_for):
    before = count_requests(conn)
    apply_leave(ctx_for("E1"), "annual", "2026-11-17", "2026-11-18")
    assert count_requests(conn) == before
    assert repository.get_balance(conn, "E1", "annual") == 10.0


def test_failure_halfway_rolls_back_the_request_too(conn, ctx_for, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(repository, "adjust_balance", boom)
    before = count_requests(conn)
    with pytest.raises(RuntimeError):
        apply_leave(ctx_for("E1"), "annual", "2026-10-19", "2026-10-21")
    # The request was inserted before the failure; the rollback must have removed it
    assert count_requests(conn) == before
    assert repository.get_balance(conn, "E1", "annual") == 10.0
    assert not conn.in_transaction


def test_data_changing_after_a_proposal_is_caught_on_execution(conn, ctx_for):
    ctx = ctx_for("E1")
    assert check_apply_leave(ctx, "annual", "2026-10-19", "2026-10-21").ok  # proposal
    conn.execute("UPDATE leave_balances SET balance_days = 1 WHERE employee_id='E1' AND leave_type='annual'")
    assert apply_leave(ctx, "annual", "2026-10-19", "2026-10-21").code == "insufficient_balance"
