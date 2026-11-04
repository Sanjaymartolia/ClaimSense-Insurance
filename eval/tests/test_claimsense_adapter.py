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


def test_the_pipeline_still_cites_the_agt01_placeholder_clause_ids(adapter, dev_cases):
    """A regression test for a defect that is still open.

    `agents/clauses.py` lines 18-21 hold four placeholder constants that are not real clause ids.
    The harness found this independently through the `fabricated_citation` gate. When somebody
    fixes AGT-01, this test fails, and that failure is the signal to delete it.
    """
    real_ids = policy_clause_ids()
    offenders = {
        case.claim_id: sorted(set(adapter.run(case.claim).citations) - real_ids)
        for case in dev_cases
    }
    offenders = {k: v for k, v in offenders.items() if v}
    assert offenders, "AGT-01 appears fixed: delete this test and the note in the report"
    assert any("TODO" in bad for ids in offenders.values() for bad in ids)
