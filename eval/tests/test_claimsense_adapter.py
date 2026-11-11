"""The real-pipeline adapter.

These tests run the actual agents. They need no API key: the agents fall back to deterministic
behaviour without one. They need no LangGraph either, because the adapter uses `LocalRunner`.

They assert the adapter's *contract*, not the pipeline's score. The score is a measurement and it
will move as the agents improve. A test that pinned it would fail on every improvement.
"""

from __future__ import annotations

import pytest

from eval.harness.adapters import ADAPTERS, build_adapter
from eval.harness.loader import load_split, policy_clause_ids
from eval.harness.models import AgentOutput

pytest.importorskip("claimsense.agents", reason="needs pip install -e '.[dev]'")


@pytest.fixture(scope="module")
def dev_cases():
    return load_split("dev")


@pytest.fixture(scope="module")
def adapter():
    from eval.harness.claimsense_adapter import ClaimSenseAdapter

    return ClaimSenseAdapter()


def test_every_named_claimsense_adapter_builds(dev_cases):
    for name in ADAPTERS:
        if name.startswith("claimsense"):
            built = build_adapter(name, dev_cases)
            assert hasattr(built, "run")
            assert built.name


def test_it_returns_a_valid_agent_output_for_every_dev_claim(adapter, dev_cases):
    """The contract: 20 claims in, 20 well-formed answers out, no crash."""
    for case in dev_cases:
        out = adapter.run(case.claim)
        assert isinstance(out, AgentOutput)
        assert out.claim_id == case.claim_id, "claim ids must line up or scoring misattributes"


def test_no_claim_raises(adapter, dev_cases):
    """A pipeline exception is caught and recorded, never propagated. One bad claim must not end
    a 20-claim run."""
    errored = [c.claim_id for c in dev_cases if adapter.run(c.claim).error]
    assert errored == [], f"the pipeline raised on {errored}"


def test_the_adapter_never_settles_a_claim(adapter, dev_cases):
    """The reviewer declines every time, so evaluation moves no money. If this ever fails, the
    approval gate has been bypassed and that is a rule 3 violation, not a test problem."""
    for case in dev_cases:
        assert adapter.run(case.claim).settled() is False, case.claim_id


def test_blocked_tool_calls_are_recorded_as_blocked_not_executed(adapter, dev_cases):
    """`Services.tool_log` marks an ACL refusal with `allowed: False`. That is least privilege
    working, so it must map to `blocked`, which the metrics never count against the agent."""
    out = adapter.run(dev_cases[0].claim)
    assert all(a.status in ("executed", "blocked") for a in out.actions)


def test_the_adapter_reports_which_claim_keys_it_saw(adapter, dev_cases):
    """Without this the `eval_only_field_leak` gate cannot check anything, and would pass
    vacuously on every run."""
    out = adapter.run(dev_cases[0].claim)
    assert out.observed_claim_keys
    assert "claim_id" in out.observed_claim_keys


def test_withholding_documents_is_available_and_changes_the_packet(dev_cases):
    """Defect CLAIM-03: the product loader drops document text, which loses most red-team
    attacks. The harness passes it by default and can reproduce the blind spot on purpose."""
    from eval.harness.claimsense_adapter import ClaimSenseAdapter

    claim = dev_cases[0].claim
    with_docs = ClaimSenseAdapter(pass_documents=True)._packet(claim)
    without = ClaimSenseAdapter(pass_documents=False)._packet(claim)
    assert with_docs["documents"], "documents must reach the agent by default"
    assert without["documents"] == {}


def test_bill_line_spans_point_at_the_real_itemised_bill_document(dev_cases):
    """A made-up document id makes extraction report 'unknown document' for every line, which
    floods the run with false issues. The span must name a document the packet actually holds."""
    from eval.harness.claimsense_adapter import ClaimSenseAdapter

    packet = ClaimSenseAdapter()._packet(dev_cases[0].claim)
    documents = set(packet["documents"])
    for line in packet["claim"]["bill_lines"]:
        assert line["source"]["document"] in documents, line["line_id"]


def test_every_bill_line_can_be_found_in_the_itemised_bill_text(dev_cases):
    """The fixture's itemised bill says only "Itemized bill represented in bill_lines" (CLAIM-02),
    so before this fix every span failed and every claim went to a person whatever the agents
    judged. The adapter writes the bill lines into that document, keeping its original text so an
    attack planted there still reaches the agent."""
    from eval.harness.claimsense_adapter import ClaimSenseAdapter

    for case in dev_cases:
        packet = ClaimSenseAdapter()._packet(case.claim)
        for line in packet["claim"]["bill_lines"]:
            text = packet["documents"][line["source"]["document"]]
            assert line["source"]["text"] in text, line["line_id"]
        raw_bill = next(d for d in case.claim.documents if d.get("type") == "itemized_bill")
        assert raw_bill["synthetic_text"] in packet["documents"][raw_bill["document_id"]]


def test_review_flags_use_only_the_gold_vocabulary(adapter, dev_cases):
    """The `flags` metric compares labels. Free-text diagnostics can never match a gold label, so
    before this fix `flags` was 0.000 on every claim whatever the agents found."""
    from eval.harness.claimsense_adapter import GOLD_FLAGS

    for case in dev_cases:
        assert set(adapter.run(case.claim).review_flags) <= GOLD_FLAGS, case.claim_id


def _deduction(reason: str, clause: str = "p:x"):
    from types import SimpleNamespace

    return SimpleNamespace(reason=SimpleNamespace(value=reason), clause_id=clause)


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        # worksheet deduction reasons: an enum set by the calculator, not prose
        ({"deductions": [_deduction("room_rent_cap")]}, {"room_rent_breach"}),
        ({"deductions": [_deduction("proportional_cut")]}, {"room_rent_breach"}),
        ({"deductions": [_deduction("icu_cap")]}, {"sub_limit"}),
        ({"deductions": [_deduction("sub_limit")]}, {"sub_limit"}),
        ({"deductions": [_deduction("non_payable")]}, {"non_payable_items"}),
        ({"deductions": [_deduction("waiting_period")]}, {"waiting_period"}),
        ({"deductions": [_deduction("co_pay")]}, set()),
        (
            {"deductions": [_deduction("exclusion", "new_india_arogya_sanjeevani:7.15")]},
            {"maternity_childbirth_exclusion"},
        ),
        # admissibility clause ids, used only when the claim was ruled not admissible
        ({"admissibility": ["new_india_arogya_sanjeevani:6.3"]}, {"waiting_period"}),
        ({"admissibility": ["new_india_arogya_sanjeevani:2"]}, {"policy_period_inconsistency"}),
        # fixed message templates from the deterministic fraud and extraction code
        ({"fraud": ["duplicate bill lines already claimed: L2"]}, {"duplicate_bill"}),
        ({"fraud": ["duplicate claim id CLM-1 already in history"]}, {"duplicate_bill"}),
        ({"fraud": ["admission date outside policy period"]}, {"policy_period_inconsistency"}),
        ({"fraud": ["L1: billed 9 days for a 3-night stay"]}, {"date_conflict"}),
        ({"fraud": ["extraction: bill total 10 != sum of lines 9"]}, {"bill_total_mismatch"}),
        ({"fraud": ["extraction: possible prompt injection in D1: 'x'"]}, {"prompt_injection"}),
        # a per-line diagnostic is not a review flag
        ({"fraud": ["extraction: L1: source span not found in D2"]}, set()),
    ],
)
def test_structured_signals_map_to_gold_flags(state, expected):
    from types import SimpleNamespace

    from eval.harness.claimsense_adapter import ClaimSenseAdapter

    pipeline_state = {"fraud_flags": state.get("fraud", [])}
    if "deductions" in state:
        line = SimpleNamespace(deductions=state["deductions"])
        pipeline_state["worksheet"] = SimpleNamespace(lines=[line])
    if "admissibility" in state:
        pipeline_state["admissibility"] = SimpleNamespace(
            admissible=False, clause_ids=state["admissibility"]
        )
    assert set(ClaimSenseAdapter._flags(pipeline_state)) == expected


def test_an_unmapped_bill_line_category_is_refused(dev_cases):
    """A silent default here would score the wrong thing. CATEGORY_MAP lives in eval/, so the fix
    is in eval/ too."""
    from eval.harness.claimsense_adapter import ClaimSenseAdapter, PipelineUnavailableError

    claim = dev_cases[0].claim.model_copy(deep=True)
    claim.bill_lines[0].category = "massage_chair"
    with pytest.raises(PipelineUnavailableError, match="CATEGORY_MAP"):
        ClaimSenseAdapter()._packet(claim)


def test_an_unknown_calculator_name_is_refused():
    from eval.harness.claimsense_adapter import ClaimSenseAdapter

    with pytest.raises(ValueError, match="calculator must be"):
        ClaimSenseAdapter(calculator="magic")


def test_the_pipeline_cites_only_real_clauses(adapter, dev_cases):
    """Regression test for the policy-period placeholder (called AGT-04 in the eval docs).
    `agents/coverage.py` used to cite the made-up id `policy_schedule:period` on CLM-0013; since A3
    it cites clause 2, the Operative Clause. No dev claim may cite an id outside the corpus."""
    real_ids = policy_clause_ids()
    offenders = {
        case.claim_id: sorted(set(out.citations) - real_ids)
        for case in dev_cases
        if set((out := adapter.run(case.claim)).citations) - real_ids
    }
    assert offenders == {}
    assert (
        "new_india_arogya_sanjeevani:2"
        in adapter.run(next(c.claim for c in dev_cases if c.claim.claim_id == "CLM-0013")).citations
    )


def test_policy_and_history_follow_the_fixture(adapter, dev_cases):
    """ADR-0007: waiting periods run from `first_policy_inception_date` (GOLD-03), and an earlier
    claim's sub-limit use reaches claims-db history (GOLD-05)."""
    by_id = {c.claim.claim_id: c.claim for c in dev_cases}
    assert str(adapter._policy(by_id["CLM-0004"]).first_inception) == "2023-01-01"
    assert str(adapter._policy(by_id["CLM-0008"]).first_inception) == "2026-01-01"
    (past,) = adapter._history(by_id["CLM-0022"])
    assert past.sub_limits_used == {"new_india_arogya_sanjeevani:4.3": 25000}
    assert adapter._history(by_id["CLM-0004"]) == []
