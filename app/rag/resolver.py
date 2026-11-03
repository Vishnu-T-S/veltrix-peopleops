"""The precedence rules of Section 5, applied in plain code (no LLM).

The LLM only *reads* the passages and reports claims: (rule, value, document). This
module decides which claim wins. Citations are built from the winners, so what is
cited is exactly what was used.

    1. Authority: policy/addendum/memo/handbook/calendar outrank faq/wiki.
    2. Scope:     a regional document outranks a GLOBAL one.
    3. Recency:   a later effective_date outranks an earlier one.
    Still undecided with different values -> a conflict: both values, both documents.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Sequence

from app.config import parse_iso_date
from app.ingestion.models import DocMeta

HIGH_AUTHORITY = {"policy", "addendum", "memo", "handbook", "calendar"}


@dataclass(frozen=True)
class Claim:
    rule: str       # what the claim is about, e.g. "volunteer_days_per_year"
    value: str      # short canonical value, e.g. "3 days"
    doc_id: str
    locator: str
    detail: str = ""


@dataclass
class Upcoming:
    claim: Claim
    effective_date: str


@dataclass
class RuleOutcome:
    rule: str
    status: str                                  # "decided" | "conflict" | "none"
    winners: List[Claim] = field(default_factory=list)
    upcoming: List[Upcoming] = field(default_factory=list)


def normalize_rule(rule: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", rule.lower()).strip("_")


def normalize_value(value: str) -> str:
    return re.sub(r"[^a-z0-9.%]+", " ", value.lower()).strip(" .")


def _authority(meta: DocMeta) -> int:
    return 1 if meta.doc_type in HIGH_AUTHORITY else 0


def _scope(meta: DocMeta) -> int:
    return 0 if {r.upper() for r in meta.regions} <= {"GLOBAL"} else 1


def _recency(meta: DocMeta) -> date:
    return parse_iso_date(meta.effective_date)


def pick_winners(claims: Sequence[Claim], metas: Dict[str, DocMeta]) -> List[Claim]:
    """Narrow the claims with the three tests, in order. Each test keeps only the best."""
    remaining = list(claims)
    for key in (_authority, _scope, _recency):
        if len(remaining) <= 1:
            break
        best = max(key(metas[c.doc_id]) for c in remaining)
        remaining = [c for c in remaining if key(metas[c.doc_id]) == best]
    return remaining


def _decide(claims: Sequence[Claim], metas: Dict[str, DocMeta]) -> RuleOutcome:
    if not claims:
        return RuleOutcome(rule="", status="none")
    winners = pick_winners(claims, metas)
    if len({normalize_value(c.value) for c in winners}) > 1:
        return RuleOutcome(rule=winners[0].rule, status="conflict", winners=winners)
    return RuleOutcome(rule=winners[0].rule, status="decided", winners=winners)


def resolve(claims: Sequence[Claim], metas: Dict[str, DocMeta], reference_date: date) -> List[RuleOutcome]:
    """Resolve every rule. `metas` holds the documents the requester may use or be told about."""
    by_rule: Dict[str, List[Claim]] = {}
    for claim in claims:
        if claim.doc_id in metas:
            by_rule.setdefault(normalize_rule(claim.rule), []).append(claim)

    outcomes: List[RuleOutcome] = []
    for rule, rule_claims in by_rule.items():
        in_force = [c for c in rule_claims if _recency(metas[c.doc_id]) <= reference_date]
        future = [c for c in rule_claims if _recency(metas[c.doc_id]) > reference_date]
        current = _decide(in_force, metas)
        current.rule = rule

        shown = {normalize_value(c.value) for c in current.winners}
        seen = set()
        for candidate in sorted(future, key=lambda c: metas[c.doc_id].effective_date):
            when = _recency(metas[candidate.doc_id])
            # What would apply on that day? Everything effective by then competes.
            on_that_day = [c for c in rule_claims if _recency(metas[c.doc_id]) <= when]
            future_outcome = _decide(on_that_day, metas)
            wins = any(w.doc_id == candidate.doc_id for w in future_outcome.winners)
            if wins and normalize_value(candidate.value) not in shown and candidate.doc_id not in seen:
                current.upcoming.append(Upcoming(candidate, metas[candidate.doc_id].effective_date))
                seen.add(candidate.doc_id)
        if current.status != "none" or current.upcoming:
            outcomes.append(current)
    return outcomes


def facts_text(outcomes: Sequence[RuleOutcome]) -> str:
    """The resolved facts as text for the answer-writing call (this is corpus-derived, so it is counted)."""
    lines: List[str] = []
    for outcome in outcomes:
        lines.append(f"Rule: {outcome.rule}")
        if outcome.status == "decided":
            for c in outcome.winners:
                extra = f" ({c.detail})" if c.detail else ""
                lines.append(f"  Applies now: {c.value}{extra} [source {c.doc_id}]")
        elif outcome.status == "conflict":
            parts = " vs ".join(f"{c.value} [source {c.doc_id}]" for c in outcome.winners)
            lines.append(
                "  CONFLICT: the applicable documents give different values and none outranks the "
                f"others: {parts}. Report both values and say the documents conflict."
            )
        for up in outcome.upcoming:
            lines.append(f"  Upcoming change from {up.effective_date}: {up.claim.value} [source {up.claim.doc_id}]")
    return "\n".join(lines)


def citations_for(outcomes: Sequence[RuleOutcome]) -> List[Dict[str, str]]:
    """One citation per document passage actually used: winners, conflicting documents, upcoming changes."""
    seen, result = set(), []
    for outcome in outcomes:
        used = list(outcome.winners) + [u.claim for u in outcome.upcoming]
        for claim in used:
            key = (claim.doc_id, claim.locator)
            if key not in seen:
                seen.add(key)
                result.append({"doc_id": claim.doc_id, "locator": claim.locator})
    return result
