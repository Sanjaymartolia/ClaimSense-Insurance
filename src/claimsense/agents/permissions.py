"""Least-privilege tool access per agent (L11).

Every tool call an agent makes goes through its ToolBelt. A belt only contains the tools in
TOOL_ACL for that agent, and `call` re-checks the ACL, so a prompt-injected agent cannot reach
settle_claim. The Tools & Security pre-tool hook should check the same table (import it), and
settle_claim itself must verify the approval tokens: three independent locks.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from claimsense.contracts import AgentName

# Only the settlement agent can move money or write a repudiation.
SETTLEMENT_ONLY = frozenset({"settle_claim", "record_repudiation"})

TOOL_ACL: dict[AgentName, frozenset[str]] = {
    AgentName.SUPERVISOR: frozenset(),
    AgentName.EXTRACTION: frozenset(),  # reads only the documents it is handed
    AgentName.COVERAGE: frozenset(
        {"policy_search", "get_clause", "get_policy", "calculate", "retrieve_lessons"}
    ),
    AgentName.FRAUD: frozenset({"claim_history", "tariff_range", "get_policy"}),
    AgentName.CRITIC: frozenset({"calculate", "get_clause"}),
    AgentName.SETTLEMENT: frozenset({"settle_claim", "record_repudiation", "get_policy"}),
}

assert all(
    not (SETTLEMENT_ONLY & tools) for agent, tools in TOOL_ACL.items() if agent != AgentName.SETTLEMENT
), "settle_claim leaked to a non-settlement agent"


class ToolPermissionError(PermissionError):
    pass


class ToolBelt:
    """The only way an agent reaches a tool."""

    def __init__(self, agent: AgentName, registry: dict[str, Callable[..., Any]], log=None):
        self.agent = agent
        allowed = TOOL_ACL[agent]
        self._tools = {name: fn for name, fn in registry.items() if name in allowed}
        self._log = log if log is not None else []

    @property
    def names(self) -> set[str]:
        return set(self._tools)

    def call(self, name: str, /, **kwargs: Any) -> Any:
        if name not in TOOL_ACL[self.agent] or name not in self._tools:
            self._log.append({"agent": self.agent.value, "tool": name, "allowed": False})
            raise ToolPermissionError(f"{self.agent.value} may not call {name}")
        self._log.append({"agent": self.agent.value, "tool": name, "allowed": True})
        return self._tools[name](**kwargs)

    def as_langchain_tools(self):
        """For agents you later turn into ReAct loops (L8/L11 Agent class): bind ONLY these."""
        from langchain_core.tools import StructuredTool

        return [StructuredTool.from_function(fn, name=n) for n, fn in self._tools.items()]
