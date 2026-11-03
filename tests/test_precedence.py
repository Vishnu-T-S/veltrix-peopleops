"""Section 5 precedence rules, including the brief's worked example."""
from datetime import date

from app.ingestion.models import DocMeta
from app.rag.resolver import Claim, citations_for, facts_text, resolve

TODAY = date(2026, 9, 15)


def meta(doc_id, doc_type, regions, effective):
    return DocMeta(doc_id, "f", doc_id, doc_type, tuple(regions), effective, "all")


V1 = meta("V1", "policy", ["GLOBAL"], "2025-01-01")
V2 = meta("V2", "policy", ["GLOBAL"], "2026-04-01")
FAQ = meta("FAQ", "faq", ["GLOBAL"], "2026-05-01")
DE = meta("DE", "addendum", ["DE"], "2025-06-01")
V3 = meta("V3", "policy", ["GLOBAL"], "2027-01-01")
VALUES = {"V1": "2 days", "V2": "3 days", "FAQ": "2 days", "DE": "5 days", "V3": "4 days"}


def claims_for(*metas):
    return [Claim("volunteer_days", VALUES[m.doc_id], m.doc_id, f"loc {m.doc_id}") for m in metas]


def run(metas, reference=TODAY):
    by_id = {m.doc_id: m for m in metas}
    return resolve(claims_for(*metas), by_id, reference)


def test_india_employee_gets_v2_and_hears_about_v3():
    (outcome,) = run([V1, V2, FAQ, V3])           # the Germany addendum is not for India
    assert outcome.status == "decided"
    assert [(c.doc_id, c.value) for c in outcome.winners] == [("V2", "3 days")]
    assert [(u.claim.doc_id, u.claim.value, u.effective_date) for u in outcome.upcoming] == [("V3", "4 days", "2027-01-01")]
    assert citations_for([outcome]) == [{"doc_id": "V2", "locator": "loc V2"}, {"doc_id": "V3", "locator": "loc V3"}]


def test_germany_employee_gets_the_addendum_and_v3_is_not_mentioned():
    (outcome,) = run([V1, V2, FAQ, DE, V3])
    assert [(c.doc_id, c.value) for c in outcome.winners] == [("DE", "5 days")]
    assert outcome.upcoming == []                   # the addendum would still win on scope in 2027
    assert [c["doc_id"] for c in citations_for([outcome])] == ["DE"]


def test_question_about_a_past_date_uses_only_what_was_in_force():
    (outcome,) = run([V1], reference=date(2025, 8, 1))
    assert [(c.doc_id, c.value) for c in outcome.winners] == [("V1", "2 days")]
    assert outcome.upcoming == []


def test_authority_beats_recency():
    (outcome,) = run([V2, FAQ])                     # the FAQ is newer but is only a FAQ
    assert [c.doc_id for c in outcome.winners] == ["V2"]


def test_scope_beats_recency_and_ties_on_authority():
    newer_global = meta("NEW", "policy", ["GLOBAL"], "2026-08-01")
    regional = meta("REG", "memo", ["IN"], "2025-01-01")
    claims = [Claim("r", "10 days", "NEW", "a"), Claim("r", "12 days", "REG", "b")]
    (outcome,) = resolve(claims, {"NEW": newer_global, "REG": regional}, TODAY)
    assert [c.doc_id for c in outcome.winners] == ["REG"]


def test_recency_decides_between_equals():
    (outcome,) = run([V1, V2])
    assert [c.doc_id for c in outcome.winners] == ["V2"]


def test_wiki_and_faq_are_equal_in_authority_so_recency_decides():
    wiki = meta("WIKI", "wiki", ["GLOBAL"], "2025-01-01")
    claims = [Claim("r", "1 day", "WIKI", "a"), Claim("r", "2 days", "FAQ", "b")]
    (outcome,) = resolve(claims, {"WIKI": wiki, "FAQ": FAQ}, TODAY)
    assert [c.doc_id for c in outcome.winners] == ["FAQ"]


def test_unresolved_conflict_reports_both_values_and_cites_both():
    a = meta("A", "policy", ["GLOBAL"], "2026-01-01")
    b = meta("B", "handbook", ["GLOBAL"], "2026-01-01")
    claims = [Claim("r", "3 days", "A", "x"), Claim("r", "4 days", "B", "y")]
    (outcome,) = resolve(claims, {"A": a, "B": b}, TODAY)
    assert outcome.status == "conflict"
    assert {c.doc_id for c in outcome.winners} == {"A", "B"}
    assert {c["doc_id"] for c in citations_for([outcome])} == {"A", "B"}
    assert "CONFLICT" in facts_text([outcome])


def test_same_value_in_two_equal_documents_is_not_a_conflict():
    a = meta("A", "policy", ["GLOBAL"], "2026-01-01")
    b = meta("B", "handbook", ["GLOBAL"], "2026-01-01")
    claims = [Claim("r", "3 days", "A", "x"), Claim("r", "3 Days.", "B", "y")]
    (outcome,) = resolve(claims, {"A": a, "B": b}, TODAY)
    assert outcome.status == "decided"


def test_upcoming_change_that_would_not_win_is_not_mentioned():
    future_faq = meta("FF", "faq", ["GLOBAL"], "2027-03-01")
    claims = [Claim("r", "3 days", "V2", "x"), Claim("r", "9 days", "FF", "y")]
    (outcome,) = resolve(claims, {"V2": V2, "FF": future_faq}, TODAY)
    assert outcome.upcoming == []


def test_upcoming_change_with_the_same_value_is_not_worth_mentioning():
    same = meta("S", "policy", ["GLOBAL"], "2027-01-01")
    claims = [Claim("r", "3 days", "V2", "x"), Claim("r", "3 days", "S", "y")]
    (outcome,) = resolve(claims, {"V2": V2, "S": same}, TODAY)
    assert outcome.upcoming == []


def test_a_claim_about_an_unknown_document_is_ignored():
    outcomes = resolve([Claim("r", "1 day", "GHOST", "x")], {"V2": V2}, TODAY)
    assert outcomes == []


def test_different_rules_are_resolved_separately():
    claims = [Claim("volunteer_days", "3 days", "V2", "a"), Claim("parental_leave", "20 weeks", "V1", "b")]
    outcomes = resolve(claims, {"V1": V1, "V2": V2}, TODAY)
    assert {o.rule: o.winners[0].doc_id for o in outcomes} == {"volunteer_days": "V2", "parental_leave": "V1"}
