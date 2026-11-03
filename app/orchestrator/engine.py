"""The orchestrator: one function that turns a message into a response.

Principle: the LLM understands and writes; code decides. Permissions live in the
tools, the rules in the resolver, and the confirmation state here, never in a prompt.

Order of work for each message:
    injection guard -> pending confirmation? -> plan (LLM, no corpus) -> route:
        refuse | clarify | read tools | propose a write | policy answer (RAG) | both
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from app.config import parse_iso_date
from app.data import repository
from app.data.models import Employee
from app.llm.client import LLM, LLMError
from app.orchestrator.planner import (Plan, is_confirmation, is_decline, looks_like_injection,
                                       plan_message)
from app.orchestrator.session import Pending, SessionState
from app.privacy import sanitize
from app.rag.answering import answer_policy_question
from app.retrieval.retriever import Retriever
from app.tools import permissions
from app.tools.common import fmt
from app.tools.context import ToolContext
from app.tools.leave_tools import DRY_RUNS, TOOLS
from app.tools.results import FORBIDDEN_EMPLOYEE_MESSAGE, ToolResult

logger = logging.getLogger("veltrix.orchestrator")

SCOPE_MESSAGE = ("I can help with Veltrix HR policies and holidays, and with your leave: checking balances, "
                 "listing requests, applying for leave and cancelling it. I can't help with that request.")
MANIPULATION_MESSAGE = ("I can't help with that request. I can answer questions about Veltrix HR policies and "
                        "holidays and help you manage your leave.")
BULK_MESSAGE = ("I can't share leave data for many employees at once. I can look up one employee at a time "
                "if you're allowed to see them.")
NO_ANSWER_MESSAGE = ("The HR documents available to you do not cover this question. Please contact the HR team "
                     "for help.")
GREETING = "Hello! I can help with Veltrix HR policies and holidays, and with your leave. What would you like to know?"
UNAVAILABLE = "Sorry, I couldn't process that just now. Please try again in a moment."


@dataclass
class ChatResponse:
    answer: str
    route: str
    citations: List[Dict[str, str]] = field(default_factory=list)
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    pending_confirmation: bool = False
    history_text: Optional[str] = None   # what later turns may see (employee names replaced by IDs)

    def to_dict(self, request_id: str) -> Dict[str, Any]:
        return {
            "request_id": request_id, "answer": self.answer, "route": self.route,
            "citations": self.citations, "tool_calls": self.tool_calls,
            "pending_confirmation": self.pending_confirmation,
        }


def refuse(message: str) -> ChatResponse:
    return ChatResponse(message, "refuse")


def clarify(message: str) -> ChatResponse:
    return ChatResponse(message, "clarify")


def _call(name: str, args: Dict[str, Any], status: str) -> Dict[str, Any]:
    return {"name": name, "args": args, "status": status}


class Orchestrator:
    def __init__(self, retriever: Retriever, llm: LLM):
        self.retriever = retriever
        self.llm = llm

    # ------------------------------------------------------------------ entry point
    def handle(self, conn, requester: Employee, state: SessionState, message: str, today: date) -> ChatResponse:
        ctx = ToolContext(conn, requester, today)
        try:
            response = self._handle(ctx, state, message)
        except LLMError as exc:
            logger.error("employee=%s llm_unavailable reason=%s", requester.employee_id, exc)
            state.pending = None
            response = clarify(UNAVAILABLE)
        response.answer = sanitize(response.answer)
        state.history.append(("user", message[:500]))
        state.history.append(("assistant", sanitize(response.history_text or response.answer)[:500]))
        return response

    def _handle(self, ctx: ToolContext, state: SessionState, message: str) -> ChatResponse:
        if looks_like_injection(message):
            state.pending = None
            return refuse(MANIPULATION_MESSAGE)
        if state.pending:
            if is_confirmation(message):
                return self._execute_pending(ctx, state)
            if is_decline(message):
                state.pending = None
                return clarify("Okay, I won't go ahead with that. Is there anything else I can help with?")

        plan = plan_message(self.llm, ctx.requester, message, ctx.today, state.history,
                            state.pending.summary if state.pending else None)
        state.pending = None   # anything other than a confirmation discards the proposal

        intent = plan.intent
        if intent == "manipulation":
            return refuse(MANIPULATION_MESSAGE)
        if intent == "bulk_request":
            return refuse(BULK_MESSAGE)
        if intent == "out_of_scope":
            return refuse(SCOPE_MESSAGE)
        if intent == "smalltalk":
            return clarify(GREETING)
        if intent == "apply_leave":
            return self._propose_apply(ctx, state, plan)
        if intent == "cancel_leave":
            return self._propose_cancel(ctx, state, plan)
        if intent == "leave_data":
            return self._leave_data(ctx, plan)
        if intent == "policy_and_data":
            return self._hybrid(ctx, plan, message)
        return self._policy(ctx, plan, message)

    # ------------------------------------------------------------------ write actions
    def _propose_apply(self, ctx: ToolContext, state: SessionState, plan: Plan) -> ChatResponse:
        needs = []
        if not plan.leave_type:
            needs.append("whether this is annual or sick leave")
        if not plan.start_date:
            needs.append("the start date")
        if not plan.end_date:
            needs.append("the end date")
        start = parse_iso_date(plan.start_date) if plan.start_date else None
        problem = plan.date_problem == "ambiguous" or plan.date_problem == "past" or (start and start < ctx.today)
        if needs or problem:
            parts = []
            if needs:
                parts.append("To apply for leave I still need " + ", ".join(needs) + ".")
            if problem:
                parts.append("The dates you mentioned are ambiguous or already in the past, so please give the exact "
                             "start and end dates (for example 2026-11-16 to 2026-11-18).")
            return clarify(" ".join(parts))

        args = {"leave_type": plan.leave_type, "start_date": plan.start_date, "end_date": plan.end_date}
        check = DRY_RUNS["apply_leave"](ctx, **args)
        if not check.ok:
            return ChatResponse(check.error or "That request can't be made.", "tool", tool_calls=[_call("apply_leave", args, "error")])
        d = check.data
        summary = (f"apply for {d['leave_type']} leave from {d['start_date']} to {d['end_date']} "
                   f"({d['working_days']} working day(s))")
        state.pending = Pending("apply_leave", args, summary)
        answer = (f"Please confirm: {summary}. Your {d['leave_type']} balance would go from {fmt(d['balance_before'])} "
                  f"to {fmt(d['balance_after'])} day(s). Reply \"yes\" to confirm.")
        return ChatResponse(answer, "tool", tool_calls=[_call("apply_leave", args, "pending_confirmation")],
                            pending_confirmation=True)

    def _propose_cancel(self, ctx: ToolContext, state: SessionState, plan: Plan) -> ChatResponse:
        me = ctx.requester.employee_id
        request_id = plan.request_id
        if not request_id:
            open_requests = [r for r in repository.list_requests(ctx.conn, me)
                             if r.status in ("pending", "approved") and parse_iso_date(r.start_date) > ctx.today]
            pool = [r for r in open_requests
                    if (not plan.leave_type or r.leave_type == plan.leave_type)
                    and (not plan.start_date or r.start_date == plan.start_date)]
            hinted = bool(plan.leave_type or plan.start_date)
            if not open_requests:
                args = {"employee_id": me}
                result = TOOLS["list_leave_requests"](ctx, **args)
                return ChatResponse("You have no leave requests that can be cancelled. Only pending or approved "
                                    "requests that start after today can be cancelled.", "tool",
                                    tool_calls=[_call("list_leave_requests", args, "success" if result.ok else "error")])
            if hinted and not pool:
                pool, force_ask = open_requests, True
            else:
                force_ask = False
            if len(pool) != 1 or force_ask:
                lines = "\n".join(f"- {r.request_id}: {r.leave_type} leave {r.start_date} to {r.end_date} "
                                  f"({r.working_days} working day(s), {r.status})" for r in pool)
                return clarify("Which request would you like to cancel? Please give the request ID:\n" + lines)
            request_id = pool[0].request_id

        args = {"request_id": request_id}
        check = DRY_RUNS["cancel_leave"](ctx, **args)
        if not check.ok:
            return ChatResponse(check.error or "That request can't be cancelled.", "tool",
                                tool_calls=[_call("cancel_leave", args, "error")])
        d = check.data
        summary = (f"cancel your {d['leave_type']} leave request {d['request_id']} from {d['start_date']} to "
                   f"{d['end_date']} ({d['working_days']} working day(s))")
        state.pending = Pending("cancel_leave", args, summary)
        return ChatResponse(f"Please confirm: {summary}. The days will be returned to your balance. Reply \"yes\" to confirm.",
                            "tool", tool_calls=[_call("cancel_leave", args, "pending_confirmation")],
                            pending_confirmation=True)

    def _execute_pending(self, ctx: ToolContext, state: SessionState) -> ChatResponse:
        pending, state.pending = state.pending, None
        result = TOOLS[pending.name](ctx, **pending.args)
        call = _call(pending.name, pending.args, "success" if result.ok else "error")
        if not result.ok:
            return ChatResponse(f"I couldn't complete that: {result.error}", "tool", tool_calls=[call])
        d = result.data
        if pending.name == "apply_leave":
            answer = (f"Done. Your {d['leave_type']} leave from {d['start_date']} to {d['end_date']} "
                      f"({d['working_days']} working day(s)) is submitted as pending. Request ID: {d['request_id']}. "
                      f"Your remaining {d['leave_type']} balance is {fmt(d['balance_after'])} day(s).")
        else:
            answer = (f"Done. Your {d['leave_type']} leave request {d['request_id']} ({d['start_date']} to "
                      f"{d['end_date']}) is cancelled and {d['working_days_returned']} day(s) were returned. "
                      f"Your {d['leave_type']} balance is now {fmt(d['balance_after'])} day(s).")
        return ChatResponse(answer, "tool", tool_calls=[call])

    # ------------------------------------------------------------------ reading leave data
    def _resolve_target(self, ctx: ToolContext, plan: Plan) -> Tuple[Optional[str], Optional[ChatResponse]]:
        ref = (plan.employee_ref or "").strip()
        me = ctx.requester.employee_id
        if not ref or ref.lower() in ("me", "myself", "self", "i", "my"):
            return me, None
        if re.fullmatch(r"[A-Za-z]{1,3}\d+", ref):
            return ref.upper(), None        # the tool decides; its refusal is the same for any ID
        matches = repository.find_employees_by_name(ctx.conn, ref)
        viewable = [m for m in matches if permissions.can_view_employee(ctx, m.employee_id)]
        if not viewable:
            return None, refuse(FORBIDDEN_EMPLOYEE_MESSAGE)
        if len(viewable) > 1:
            return None, clarify("More than one employee matches that name. Which employee ID do you mean?")
        return viewable[0].employee_id, None

    def _run_reads(self, ctx: ToolContext, plan: Plan):
        """Returns (results, calls, early_response). Permission checks happen inside the tools."""
        ops = [op for op in ("balance", "requests", "team") if op in (plan.data or ["balance"])]
        target, early = (None, None)
        if any(op in ("balance", "requests") for op in ops):
            target, early = self._resolve_target(ctx, plan)
            if early:
                return [], [], early
        if "team" in ops and not (plan.start_date and plan.end_date):
            return [], [], clarify("For which dates should I check your team's leave? Please give a start and end date.")

        results: List[Tuple[str, Dict[str, Any], ToolResult]] = []
        calls: List[Dict[str, Any]] = []
        for op in ops:
            if op == "balance":
                name, args = "get_leave_balance", {"employee_id": target}
                if plan.leave_type:
                    args["leave_type"] = plan.leave_type
            elif op == "requests":
                name, args = "list_leave_requests", {"employee_id": target}
                if plan.status:
                    args["status"] = plan.status
            else:
                name, args = "get_team_leave", {"start_date": plan.start_date, "end_date": plan.end_date}
            result = TOOLS[name](ctx, **args)
            if result.code == "forbidden":
                return [], [], refuse(result.error)
            if result.code == "managers_only":
                return [], [], refuse(result.error)
            results.append((name, args, result))
            calls.append(_call(name, args, "success" if result.ok else "error"))
        return results, calls, None

    def _render_reads(self, ctx: ToolContext, results, show_names: bool) -> str:
        me = ctx.requester.employee_id
        paragraphs: List[str] = []
        for name, args, result in results:
            if not result.ok:
                paragraphs.append(result.error or "That request could not be completed.")
                continue
            d = result.data
            if name == "get_leave_balance":
                target = d["employee_id"]
                owner = "Your" if target == me else f"{self._label(ctx, target, show_names)}'s"
                parts = ", ".join(f"{t}: {fmt(v)} day(s)" for t, v in d["balances"].items())
                paragraphs.append(f"{owner} leave balance is {parts}.")
            elif name == "list_leave_requests":
                target = d["employee_id"]
                owner = "Your" if target == me else f"{self._label(ctx, target, show_names)}'s"
                if not d["requests"]:
                    paragraphs.append(f"{owner} has no leave requests matching that." if owner != "Your"
                                      else "You have no leave requests matching that.")
                else:
                    lines = "\n".join(f"- {r['request_id']}: {r['leave_type']} leave {r['start_date']} to {r['end_date']} "
                                      f"({r['working_days']} working day(s), {r['status']})" for r in d["requests"])
                    paragraphs.append(f"{owner} leave requests:\n{lines}")
            else:
                if not d["leave"]:
                    paragraphs.append(f"None of your direct reports have pending or approved leave between "
                                      f"{d['start_date']} and {d['end_date']}.")
                else:
                    lines = "\n".join(
                        f"- {(r['full_name'] + ' (' + r['employee_id'] + ')') if show_names else r['employee_id']}: "
                        f"{r['leave_type']} leave {r['start_date']} to {r['end_date']} "
                        f"({r['working_days']} working day(s), {r['status']})" for r in d["leave"])
                    paragraphs.append(f"Team leave between {d['start_date']} and {d['end_date']}:\n{lines}")
        return "\n\n".join(paragraphs)

    @staticmethod
    def _label(ctx: ToolContext, employee_id: str, show_names: bool) -> str:
        if not show_names:
            return employee_id
        person = repository.get_employee(ctx.conn, employee_id)
        return f"{person.full_name} ({employee_id})" if person else employee_id

    def _leave_data(self, ctx: ToolContext, plan: Plan) -> ChatResponse:
        results, calls, early = self._run_reads(ctx, plan)
        if early:
            return early
        return ChatResponse(self._render_reads(ctx, results, True), "tool", tool_calls=calls,
                            history_text=self._render_reads(ctx, results, False))

    # ------------------------------------------------------------------ policy answers
    def _policy_outcome(self, ctx: ToolContext, plan: Plan, message: str, extra_data: str = ""):
        reference, include_upcoming = ctx.today, True
        if plan.as_of_date and plan.as_of_date < ctx.today:
            reference, include_upcoming = plan.as_of_date, False   # a question about a past date
        return answer_policy_question(self.llm, self.retriever, ctx.requester, plan.question or message,
                                      plan.search_query, reference, include_upcoming, extra_data)

    def _policy(self, ctx: ToolContext, plan: Plan, message: str) -> ChatResponse:
        outcome = self._policy_outcome(ctx, plan, message)
        if outcome.no_answer:
            return ChatResponse(NO_ANSWER_MESSAGE, "no_answer")
        return ChatResponse(outcome.text, "rag", citations=outcome.citations)

    def _hybrid(self, ctx: ToolContext, plan: Plan, message: str) -> ChatResponse:
        results, calls, early = self._run_reads(ctx, plan)
        if early:
            return early
        data_for_llm = self._render_reads(ctx, results, False)   # employee IDs only, never names
        outcome = self._policy_outcome(ctx, plan, message, data_for_llm)
        if outcome.no_answer:
            text = self._render_reads(ctx, results, True) + "\n\nThe HR documents available to you do not cover the policy part of this question; please contact the HR team."
            return ChatResponse(text, "tool", tool_calls=calls)
        return ChatResponse(outcome.text, "hybrid", citations=outcome.citations, tool_calls=calls)
