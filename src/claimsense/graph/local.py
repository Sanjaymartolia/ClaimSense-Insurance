"""A tiny dependency-free executor for the same topology as build.py.

Why it exists: unit tests and Reflexion dry runs should not need LangGraph, a checkpointer or
an API key. It calls the *same* Nodes and routers; the reviewer callback is called synchronously
where LangGraph would pause. Use build.run_claim for anything you demo.
"""

from __future__ import annotations

from collections.abc import Callable

from claimsense.agents import Team

from .build import EDGES, conditional
from .nodes import Nodes
from .state import APPEND_KEYS, ClaimState, initial_state


class LocalRunner:
    def __init__(
        self,
        team: Team,
        max_steps: int = 60,
        *,
        identity_provider=None,
        approval_store=None,
        tool_hooks: bool = False,
        hook_options: dict | None = None,
    ):
        self.team = team
        self.max_steps = max_steps
        self.edges = dict(EDGES)
        self.cond = conditional(team)
        self.node_kwargs = {
            "identity_provider": identity_provider,
            "approval_store": approval_store,
            "tool_hooks": tool_hooks,
            "hook_options": hook_options,
        }

    def run(self, packet: dict, reviewer: Callable[[dict], dict]) -> ClaimState:
        node_obj = Nodes(self.team, interrupt_fn=reviewer, **self.node_kwargs)
        try:
            return self._run(node_obj.table(), packet)
        finally:
            node_obj.restore_hooks()  # the claim is over: plain belts back, budget dropped

    def _run(self, nodes: dict, packet: dict) -> ClaimState:
        state: dict = dict(initial_state(packet))
        cur = self.edges["START"]
        for _ in range(self.max_steps):
            update = nodes[cur](state)
            for k, v in update.items():
                state[k] = state.get(k, []) + v if k in APPEND_KEYS else v
            if cur in self.cond:
                router, mapping = self.cond[cur]
                cur = mapping[router(state)]
            else:
                cur = self.edges[cur]
            if cur == "END":
                return state
        raise RuntimeError("step limit hit")
