"""cancel_leave rules (Section 6.3). Fixture date: Thursday 2026-10-15."""
from datetime import date

import pytest

from app.data import repository
from app.tools.leave_apply import apply_leave
from app.tools.leave_cancel import cancel_leave, check_cancel_leave


def test_cancelling_a_future_pending_request_returns_the_days(conn, ctx_for):
    result = cancel_leave(ctx_for("E1"), "req-e1-pending")  # 16-17 Nov, 2 days
    assert result.ok and result.data["working_days_returned"] == 2
    assert repository.get_request(conn, "req-e1-pending").status == "cancelled"
    assert repository.get_balance(conn, "E1", "annual") == 12.0
    assert result.data["balance_after"] == 12.0


def test_cancelling_a_future_approved_request_works_too(conn, ctx_for):
    result = cancel_leave(ctx_for("E1"), "req-e1-approved")  # 7-9 Dec, 3 days
    assert result.ok
    assert repository.get_balance(conn, "E1", "annual") == 13.0


def test_days_go_back_to_the_right_leave_type(conn, ctx_for):
    cancel_leave(ctx_for("E2"), "req-e2-pending")  # sick, 2 days
    assert repository.get_balance(conn, "E2", "sick") == 14.0
    assert repository.get_balance(conn, "E2", "annual") == 10.0


def test_request_that_already_started_cannot_be_cancelled(conn, ctx_for):
    result = cancel_leave(ctx_for("E1"), "req-e1-past")
    assert result.code == "not_cancellable" and "2026-02-16" in result.error
    assert repository.get_request(conn, "req-e1-past").status == "approved"
    assert repository.get_balance(conn, "E1", "annual") == 10.0


def test_request_starting_today_cannot_be_cancelled(ctx_for):
    # req-e1-approved starts 2026-12-07: on that day it is too late, the day before it is fine
    assert cancel_leave(ctx_for("E1", today=date(2026, 12, 7)), "req-e1-approved").code == "not_cancellable"
    assert cancel_leave(ctx_for("E1", today=date(2026, 12, 6)), "req-e1-approved").ok


def test_already_cancelled_request_cannot_be_cancelled_again(conn, ctx_for):
    result = cancel_leave(ctx_for("E1"), "req-e1-cancelled")
    assert result.code == "already_cancelled"
    assert repository.get_balance(conn, "E1", "annual") == 10.0


def test_cancelling_twice_only_returns_the_days_once(conn, ctx_for):
    cancel_leave(ctx_for("E1"), "req-e1-pending")
    again = cancel_leave(ctx_for("E1"), "req-e1-pending")
    assert again.code == "already_cancelled"
    assert repository.get_balance(conn, "E1", "annual") == 12.0


# ---- only your own requests ------------------------------------------------------------

def test_employee_cannot_cancel_someone_elses_request(conn, ctx_for):
    result = cancel_leave(ctx_for("E2"), "req-e1-pending")
    assert result.code == "request_not_found"
    assert repository.get_request(conn, "req-e1-pending").status == "pending"
    assert repository.get_balance(conn, "E1", "annual") == 10.0


@pytest.mark.parametrize("requester", ["M1", "H1"])
def test_managers_and_hr_can_only_cancel_their_own_requests(conn, ctx_for, requester):
    result = cancel_leave(ctx_for(requester), "req-e1-pending")
    assert result.code == "request_not_found"
    assert repository.get_request(conn, "req-e1-pending").status == "pending"


def test_someone_elses_request_looks_the_same_as_a_missing_one(ctx_for):
    other = cancel_leave(ctx_for("E2"), "req-e1-pending")
    missing = cancel_leave(ctx_for("E2"), "no-such-request")
    assert (other.code, other.error, other.data) == (missing.code, missing.error, missing.data)


@pytest.mark.parametrize("bad", [None, ""])
def test_missing_request_id_is_rejected(ctx_for, bad):
    assert cancel_leave(ctx_for("E1"), bad).code == "request_not_found"


# ---- dry run and atomicity ----------------------------------------------------------------

def test_check_cancel_leave_writes_nothing(conn, ctx_for):
    result = check_cancel_leave(ctx_for("E1"), "req-e1-pending")
    assert result.ok and result.data["working_days"] == 2
    assert repository.get_request(conn, "req-e1-pending").status == "pending"
    assert repository.get_balance(conn, "E1", "annual") == 10.0


def test_check_and_cancel_agree_on_rejections(ctx_for):
    for request_id in ("req-e1-past", "req-e1-cancelled", "req-e2-pending", "nope"):
        assert check_cancel_leave(ctx_for("E1"), request_id).code == cancel_leave(ctx_for("E1"), request_id).code


def test_failure_halfway_rolls_back_the_status_change(conn, ctx_for, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(repository, "adjust_balance", boom)
    with pytest.raises(RuntimeError):
        cancel_leave(ctx_for("E1"), "req-e1-pending")
    assert repository.get_request(conn, "req-e1-pending").status == "pending"
    assert repository.get_balance(conn, "E1", "annual") == 10.0
    assert not conn.in_transaction


# ---- apply and cancel together --------------------------------------------------------------

def test_apply_then_cancel_restores_the_balance(conn, ctx_for):
    ctx = ctx_for("E1")
    created = apply_leave(ctx, "annual", "2026-10-19", "2026-10-21")
    assert repository.get_balance(conn, "E1", "annual") == 7.0
    assert cancel_leave(ctx, created.data["request_id"]).ok
    assert repository.get_balance(conn, "E1", "annual") == 10.0


def test_dates_are_free_again_after_cancelling(ctx_for):
    ctx = ctx_for("E1")
    created = apply_leave(ctx, "annual", "2026-10-19", "2026-10-21")
    assert apply_leave(ctx, "annual", "2026-10-20", "2026-10-20").code == "overlapping_request"
    cancel_leave(ctx, created.data["request_id"])
    assert apply_leave(ctx, "annual", "2026-10-20", "2026-10-20").ok
