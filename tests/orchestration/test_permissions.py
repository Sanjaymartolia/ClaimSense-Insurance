import pytest

from claimsense.agents import TOOL_ACL, ToolPermissionError
from claimsense.contracts import AgentName


def test_only_settlement_agent_has_settle_claim():
    holders = {a for a, tools in TOOL_ACL.items() if "settle_claim" in tools}
    assert holders == {AgentName.SETTLEMENT}


@pytest.mark.parametrize("agent", ["extraction", "coverage", "fraud", "critic"])
def test_other_agents_are_refused(team, agent):
    belt = getattr(team, agent).belt
    assert "settle_claim" not in belt.names
    with pytest.raises(ToolPermissionError):
        belt.call("settle_claim", claim_id="X", worksheet=None, approvals=[], needs_senior=False)
    assert team.services.tool_log[-1] == {"agent": agent, "tool": "settle_claim", "allowed": False}
