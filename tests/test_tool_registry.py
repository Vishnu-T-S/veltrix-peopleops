import inspect

from app.tools.leave_tools import DRY_RUNS, TOOLS


def test_exactly_the_five_tools_from_the_brief_exist():
    assert set(TOOLS) == {
        "get_leave_balance", "list_leave_requests", "get_team_leave",
        "apply_leave", "cancel_leave",
    }


def test_argument_names_match_the_brief():
    def args(name):
        # drop the first parameter: ctx is supplied by the orchestrator, not the LLM
        return list(inspect.signature(TOOLS[name]).parameters)[1:]

    assert args("get_leave_balance") == ["employee_id", "leave_type"]
    assert args("list_leave_requests") == ["employee_id", "status"]
    assert args("get_team_leave") == ["start_date", "end_date"]
    assert args("apply_leave") == ["leave_type", "start_date", "end_date"]
    assert args("cancel_leave") == ["request_id"]


def test_write_tools_have_dry_runs_with_the_same_arguments():
    for name in ("apply_leave", "cancel_leave"):
        assert list(inspect.signature(DRY_RUNS[name]).parameters) == list(
            inspect.signature(TOOLS[name]).parameters
        )


def test_no_tool_accepts_a_requester_argument():
    # Identity must never be something the LLM can supply
    for name, fn in TOOLS.items():
        params = list(inspect.signature(fn).parameters)[1:]
        assert not {"requester", "requester_id", "role", "region"} & set(params), name
