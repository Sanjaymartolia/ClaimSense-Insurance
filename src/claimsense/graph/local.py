"""A tiny dependency-free executor for the same topology as build.py.

Why it exists: unit tests and Reflexion dry runs should not need LangGraph, a checkpointer or
an API key. It calls the *same* Nodes and routers; the reviewer callback is called synchronously
where LangGraph would pause. Use build.run_claim for anything you demo.
"""

from __future__ import annotations

from typing import Callable

from claimsense.agents import Team

from .build import EDGES, conditional
from .nodes import Nodes
from .state import APPEND_KEYS, ClaimState, initial_state


class LocalRunner:
    def __init__(self, team: Team, max_steps: int = 60):
        self.team = team
        self.max_steps = max_steps
        self.edges = dict(EDGES)
        self.cond = conditional(team)

    def run(self, packet: dict, reviewer: Callable[[dict], dict]) -> ClaimState:
        nodes = Nodes(self.team, interrupt_fn=reviewer).table()
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
