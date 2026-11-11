"""AGT-02b: a claim that fails admissibility still gets a worksheet, computed by the calculator.

Every line is deducted in full and cites the gate's clause, so the person who confirms the
repudiation sees the same ₹0 the gold expects, and the rupees come from code (rule 1). The claim
still goes to a person, and the repudiation payload still hides the worksheet (rule 3).
"""

from datetime import date
from decimal import Decimal

import pytest

from claimsense.agents import PolicyInfo, Team, make_stub_services
from claimsense.agents.services import stub_clause
from claimsense.contracts import DeductionReason, RetrievedPassage
from claimsense.graph import LocalRunner, Status

from .conftest import POLICY, C, room_breach_packet

NEW_POLICY = POLICY.model_copy(update={"first_inception": date(2026, 5, 1)})  # 30-day wait running


def _out_of_period():
    return POLICY, room_breach_packet(admission_date="2025-12-20", discharge_date="2025-12-23")


def _initial_waiting():
    return NEW_POLICY, room_breach_packet()


def _maternity():
    return POLICY, room_breach_packet(diagnosis="lower segment caesarean section")


GATES = {
    "out_of_period": (_out_of_period, C.POLICY_PERIOD, DeductionReason.OTHER),
    "initial_waiting": (_initial_waiting, C.INITIAL_WAITING_PERIOD, DeductionReason.WAITING_PERIOD),
    "maternity": (_maternity, C.MATERNITY_EXCLUSION, DeductionReason.EXCLUSION),
}


def _run(policy: PolicyInfo, packet, decision="approve"):
    services = make_stub_services(policies={policy.policy_number: policy})
    seen = []

    def reviewer(payload):
        seen.append(payload)
        return {"decision": decision, "approver_id": "adj-1"}

    return LocalRunner(Team(services)).run(packet, reviewer), seen, services


@pytest.mark.parametrize("kind", sorted(GATES))
def test_an_inadmissible_claim_gets_a_zero_worksheet_from_the_calculator(kind):
    make, clause, reason = GATES[kind]
    out, _, services = _run(*make())
    assert not out["admissibility"].admissible
    ws = out["worksheet"]
    assert ws is not None and ws.total_payable == 0
    assert all(line.payable == 0 for line in ws.lines)
    for line in ws.lines:
        assert [(d.reason, d.clause_id) for d in line.deductions] == [(reason, clause)]
    assert any(e["tool"] == "calculate" and e["allowed"] for e in services.tool_log)


@pytest.mark.parametrize("kind", sorted(GATES))
def test_the_repudiation_review_is_unchanged(kind):
    make, _, _ = GATES[kind]
    out, seen, _ = _run(*make())
    assert [p["kind"] for p in seen] == ["repudiation"]
    assert seen[0]["worksheet"] is None  # a repudiation never shows a settlement worksheet
    assert out["status"] == Status.REPUDIATED
    assert out.get("clause_choices") in (None, {})  # the gate is not a per-line clause choice


def test_a_duplicate_line_on_a_gated_claim_cites_clause_2():
    """Gold CLM-0003 L06: the repeat is deducted as a repeat (ADR-0009), the rest by the gate."""
    policy, packet = _initial_waiting()
    lines = packet["claim"]["bill_lines"]
    lines.append({**lines[1], "line_id": "L9"})
    packet["claim"]["bill_total"] = "91000.00"
    out, _, _ = _run(policy, packet, decision="reject")
    by_line = {line.line_id: line for line in out["worksheet"].lines}
    assert [d.clause_id for d in by_line["L9"].deductions] == [C.OPERATIVE]
    assert [d.clause_id for d in by_line["L2"].deductions] == [C.INITIAL_WAITING_PERIOD]
    assert out["worksheet"].total_payable == 0


def test_an_override_recomputes_from_coverage_not_from_the_gate():
    policy, packet = _out_of_period()
    services = make_stub_services(policies={policy.policy_number: policy})
    calls = []

    def reviewer(payload):
        calls.append(payload["kind"])
        if len(calls) == 1:
            return {
                "decision": "edit",
                "approver_id": "adj-1",
                "edits": [{"line_id": "L5", "clause_id": C.NON_PAYABLE_ITEMS, "reason": "kit"}],
            }
        return {"decision": "approve", "approver_id": f"{payload['level']}-2"}

    out = LocalRunner(Team(services)).run(packet, reviewer)
    assert out["status"] == Status.SETTLED
    assert out["worksheet"].total_payable > 0
    cited = {d.clause_id for line in out["worksheet"].lines for d in line.deductions}
    assert C.POLICY_PERIOD not in cited


def test_no_worksheet_when_the_gate_names_no_clause():
    """Policy not found: there is no clause to cite, so there is nothing to compute."""
    services = make_stub_services(policies={})
    out = LocalRunner(Team(services)).run(
        room_breach_packet(), lambda p: {"decision": "reject", "approver_id": "a"}
    )
    assert not out["admissibility"].admissible
    assert out.get("worksheet") is None


@pytest.mark.parametrize("clause", sorted(C.CLAIM_LEVEL))
def test_a_claim_level_clause_is_never_a_per_line_choice(services, clause):
    """Clause 2 and the waiting/maternity clauses deduct a line in full. Only the admissibility
    gate may apply them. The real knowledge base can return one as a candidate (clause 2 is
    searchable), so a model that picks it for a line must fall back like any invalid pick."""
    search = services.policy_search

    def search_with_gate_clause(query, category=None, k=5):
        top = RetrievedPassage(clause=stub_clause(clause, "claim-level ruling"), score=1.0, rank=0)
        return [top, *search(query, category=category, k=k)]

    services.policy_search = search_with_gate_clause
    team = Team(services)
    team.coverage.chooser = lambda claim, cands, *_: {
        line.line_id: clause for line in claim.bill_lines
    }
    claim = team.extraction.run(room_breach_packet())[0]
    choices, _, notes = team.coverage.choose_clauses(claim)
    assert clause not in choices.values()
    assert len(notes) == len(claim.bill_lines)


def test_an_adjudicator_lock_still_wins_over_the_guard(services):
    team = Team(services)
    claim = team.extraction.run(room_breach_packet())[0]
    choices, _, _ = team.coverage.choose_clauses(claim, locked={"L2": C.POLICY_PERIOD})
    assert choices["L2"] == C.POLICY_PERIOD


def test_sum_insured_is_not_needed_to_zero_a_gated_claim():
    """A sanity check on the hand-worked side: the gated bill is the full bill."""
    _, packet = _out_of_period()
    out, _, _ = _run(POLICY, packet, decision="reject")
    assert out["worksheet"].total_claimed == Decimal("76000.00")
