"""Same scenarios through real LangGraph with a checkpointer and interrupt(). Skips if LangGraph
isn't installed. Run this on day 1: it is the only test that exercises pause/resume."""

from decimal import Decimal

import pytest

pytest.importorskip("langgraph")

from claimsense.agents import clauses as C  # noqa: E402
from claimsense.graph import build_graph, memory_checkpointer, resume, run_claim, start  # noqa: E402

from .conftest import approve, room_breach_packet  # noqa: E402


def test_pauses_for_approval_then_settles(team):
    app = build_graph(team, checkpointer=memory_checkpointer())
    out, cfg = start(app, room_breach_packet())
    assert out["__interrupt__"][0].value["level"] == "adjudicator"
    assert app.get_state(cfg).next == ("human_review",)
    out = resume(app, cfg, {"decision": "approve", "approver_id": "adj-1"})
    assert out["status"] == "settled"


def test_edit_reenters_pipeline(team, services):
    services.senior_threshold = Decimal("10000")
    app = build_graph(team, checkpointer=memory_checkpointer())
    out, cfg = start(app, room_breach_packet())
    h1 = out["__interrupt__"][0].value["worksheet_hash"]
    out = resume(app, cfg, {"decision": "approve", "approver_id": "adj-1"})
    assert out["__interrupt__"][0].value["level"] == "senior"
    out = resume(app, cfg, {"decision": "edit", "approver_id": "sen-1", "edits": [
        {"line_id": "L3", "clause_id": C.NON_PAYABLE_ITEMS, "reason": "test"}]})
    p = out["__interrupt__"][0].value
    assert p["level"] == "adjudicator" and p["worksheet_hash"] != h1
    assert app.get_state(cfg).values["approvals"] == []


def test_run_claim_helper(team):
    app = build_graph(team, checkpointer=memory_checkpointer())
    final = run_claim(app, room_breach_packet(), approve())
    assert final["status"] == "settled"
