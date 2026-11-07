"""Mahesh's tool hooks installed once per claim, with a fresh budget per claim. Off by default."""

import pytest

from claimsense.graph import LocalRunner
from claimsense.graph.nodes import Nodes
from claimsense.hooks.hooks import AuditLog, HookedToolBelt, ToolBudgetExceeded

from .conftest import approve, room_breach_packet

AGENTS = ("extraction", "coverage", "fraud", "critic", "settlement")


def belts(team):
    return [getattr(team, a).belt for a in AGENTS]


def test_hooks_are_off_by_default(team):
    LocalRunner(team).run(room_breach_packet(), approve())
    assert not any(isinstance(b, HookedToolBelt) for b in belts(team))


def test_hooks_installed_for_the_claim_and_restored_after_a_local_run(team):
    seen = []

    def reviewer(p):
        seen.append([isinstance(b, HookedToolBelt) for b in belts(team)])
        return approve()(p)

    LocalRunner(team, tool_hooks=True, hook_options={"audit": AuditLog()}).run(
        room_breach_packet(), reviewer
    )
    assert seen and all(all(row) for row in seen)  # hooked while the claim runs
    assert not any(isinstance(b, HookedToolBelt) for b in belts(team))  # plain afterwards


def test_budget_is_charged_and_blocks_over_the_ceiling(team):
    runner = LocalRunner(team, tool_hooks=True, hook_options={"per_claim": 2, "audit": AuditLog()})
    with pytest.raises(ToolBudgetExceeded):
        runner.run(room_breach_packet(), approve())
    assert not any(isinstance(b, HookedToolBelt) for b in belts(team))  # restored on error too


def test_each_claim_gets_a_fresh_budget(team):
    nodes = Nodes(team, approve(), tool_hooks=True, hook_options={"audit": AuditLog()})
    nodes.ensure_hooks("CLM-A")
    team.coverage.belt.call("get_policy", policy_number="POL-001")
    first = nodes.hook_guard
    assert first.budget.total == 1
    nodes.ensure_hooks("CLM-A")  # same claim (e.g. resume after a pause): same budget
    assert nodes.hook_guard is first
    nodes.ensure_hooks("CLM-B")
    assert nodes.hook_guard is not first and nodes.hook_guard.budget.total == 0
    nodes.restore_hooks()
    assert not any(isinstance(b, HookedToolBelt) for b in belts(team))


def test_build_graph_accepts_the_option(team):
    pytest.importorskip("langgraph")
    from claimsense.graph import build_graph, memory_checkpointer, resume, start

    app = build_graph(
        team,
        checkpointer=memory_checkpointer(),
        tool_hooks=True,
        hook_options={"audit": AuditLog()},
    )
    out, cfg = start(app, room_breach_packet())
    assert all(isinstance(b, HookedToolBelt) for b in belts(team))  # still hooked while paused
    out = resume(app, cfg, {"decision": "approve", "approver_id": "adj-1"})
    assert out["status"] == "settled"
