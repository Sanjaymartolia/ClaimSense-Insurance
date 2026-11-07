"""nodes._review delegates to approvals.ReviewGate: signed tokens, trusted identity, one
senior rule. Uses an in-memory approval store, so no secret or SQLite is needed."""

import hashlib
from decimal import Decimal

import pytest

from claimsense.contracts import ApprovalLevel
from claimsense.graph import LocalRunner, Status
from claimsense.graph.nodes import needs_senior
from claimsense.mcp_servers import approvals as appr

from .conftest import approve, room_breach_packet


def test_approval_is_signed_into_the_injected_store(team):
    store = appr.InMemoryApprovalStore()
    out = LocalRunner(team, approval_store=store).run(room_breach_packet(), approve())
    assert out["status"] == Status.SETTLED
    ws = out["worksheet"]
    recs = store.find(ws.claim_id, ws.content_hash())
    assert [r.token.level for r in recs] == [ApprovalLevel.ADJUDICATOR]
    assert all(r.signature_valid() for r in recs)
    assert recs[0].token == out["approvals"][0]


def test_identity_comes_from_the_provider_not_the_ui_reply(team):
    store = appr.InMemoryApprovalStore()
    runner = LocalRunner(team, identity_provider=appr.DemoIdentityProvider(), approval_store=store)
    out = runner.run(room_breach_packet(), approve())  # UI says "adjudicator-1"
    assert [a.approver_id for a in out["approvals"]] == ["demo-adjudicator"]


def test_no_provider_keeps_the_ui_approver_id(team):
    out = LocalRunner(team, approval_store=appr.InMemoryApprovalStore()).run(
        room_breach_packet(), approve()
    )
    assert [a.approver_id for a in out["approvals"]] == ["adjudicator-1"]


def test_repudiation_approval_is_signed_and_bound_to_the_admissibility_finding(team):
    store = appr.InMemoryApprovalStore()
    packet = room_breach_packet(admission_date="2025-12-20", discharge_date="2025-12-22")
    out = LocalRunner(team, approval_store=store).run(packet, approve())
    assert out["status"] == Status.REPUDIATED
    subject = hashlib.sha256(out["admissibility"].model_dump_json().encode()).hexdigest()
    (tok,) = out["approvals"]
    assert tok.worksheet_hash == subject
    assert store.find(tok.claim_id, subject)[0].signature_valid()


def test_plan_and_trace_are_still_added_on_top_of_the_gate(team):
    out = LocalRunner(team, approval_store=appr.InMemoryApprovalStore()).run(
        room_breach_packet(), approve()
    )
    assert any(s.name == "approve" and s.status == "done" for s in out["plan"].steps)
    assert any(t.startswith("adjudicator approved v") for t in out["trace"])


def test_reject_still_traces(team):
    def reject(_):
        return {"decision": "reject", "approver_id": "a1"}

    out = LocalRunner(team, approval_store=appr.InMemoryApprovalStore()).run(
        room_breach_packet(), reject
    )
    assert out["status"] == Status.REJECTED
    assert "adjudicator rejected" in out["trace"]


@pytest.mark.parametrize("delta, flags", [(-1, []), (0, []), (1, []), (-1, ["dup"])])
def test_router_senior_rule_matches_approvals(team, delta, flags):
    out = LocalRunner(team, approval_store=appr.InMemoryApprovalStore()).run(
        room_breach_packet(), approve()
    )
    ws = out["worksheet"]
    team.services.senior_threshold = ws.total_payable - Decimal(delta)
    s = {**out, "fraud_flags": flags}
    want = appr.needs_senior(ws, flags, threshold=team.services.senior_threshold)
    assert needs_senior(s, team) is want


def test_production_review_kwargs_use_the_claims_db_store(monkeypatch):
    from claimsense.graph.build import production_review_kwargs
    from claimsense.mcp_servers import claims_db

    sentinel = object()

    class FakeDb:
        approval_store = sentinel

    monkeypatch.setattr(claims_db, "get_db", lambda: FakeDb())
    kw = production_review_kwargs()
    assert kw["approval_store"] is sentinel
    assert isinstance(kw["identity_provider"], appr.DemoIdentityProvider)
