"""Wire the nodes into a LangGraph StateGraph with a checkpointer (L8).

The topology lives in EDGES / CONDITIONAL so the same spec drives LangGraph (here) and the
dependency-free LocalRunner (local.py) used by the unit tests.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from claimsense.agents import Team

from .nodes import Nodes, after_admissibility, after_critic, make_after_review
from .state import ClaimState, initial_state

EDGES: list[tuple[str, str]] = [
    ("START", "plan"),
    ("plan", "extract"),
    ("extract", "admissibility"),
    ("coverage", "fraud"),
    ("fraud", "critic"),
    ("revise", "coverage"),
    ("escalate", "human_review"),
    ("apply_edits", "critic"),
    ("settle", "memory_update"),
    ("repudiate", "memory_update"),
    ("memory_update", "END"),
]


def conditional(team: Team) -> dict[str, tuple[Callable, dict[str, str]]]:
    after_review = make_after_review(team)
    review_map = {
        "apply_edits": "apply_edits",
        "senior_review": "senior_review",
        "settle": "settle",
        "repudiate": "repudiate",
        "end": "END",
    }
    return {
        "admissibility": (
            after_admissibility,
            {"coverage": "coverage", "human_review": "human_review"},
        ),
        "critic": (
            after_critic,
            {"human_review": "human_review", "revise": "revise", "escalate": "escalate"},
        ),
        "human_review": (after_review, review_map),
        "senior_review": (after_review, review_map),
    }


def production_review_kwargs(identity_provider: Any = None) -> dict[str, Any]:
    """Review-gate wiring for a real run: build_graph(team, cp, **production_review_kwargs()).

    The gate must sign approvals into the same store claims_db.settle_claim verifies against, or
    every settlement is refused. Needs CLAIMSENSE_APPROVAL_SECRET (SqliteApprovalStore enforces it).
    DemoIdentityProvider is DEV/DEMO ONLY; the API layer should pass a real (SSO) provider.
    """
    from claimsense.mcp_servers import claims_db
    from claimsense.mcp_servers.approvals import DemoIdentityProvider

    return {
        "identity_provider": identity_provider or DemoIdentityProvider(),
        "approval_store": claims_db.get_db().approval_store,
    }


def build_graph(
    team: Team,
    checkpointer: Any = None,
    interrupt_fn=None,
    *,
    identity_provider: Any = None,
    approval_store: Any = None,
    tool_hooks: bool = False,
    hook_options: dict[str, Any] | None = None,
):
    """tool_hooks=True installs hooks.install_hooks once per claim with a fresh budget (see
    Nodes). The hooks stay on the team while a claim is paused and are swapped for a fresh set when
    the next claim id starts. Build one Team per concurrently running claim."""
    from langgraph.graph import END, START, StateGraph

    ends = {"START": START, "END": END}
    nodes = Nodes(
        team,
        interrupt_fn,
        identity_provider=identity_provider,
        approval_store=approval_store,
        tool_hooks=tool_hooks,
        hook_options=hook_options,
    )
    g = StateGraph(ClaimState)
    for name, fn in nodes.table().items():
        g.add_node(name, fn)
    for a, b in EDGES:
        g.add_edge(ends.get(a, a), ends.get(b, b))
    for src, (router, mapping) in conditional(team).items():
        g.add_conditional_edges(src, router, {k: ends.get(v, v) for k, v in mapping.items()})
    return g.compile(checkpointer=checkpointer)


def sqlite_checkpointer(path: str = "claimsense_checkpoints.sqlite"):
    """Durable pause/resume across processes (pip install langgraph-checkpoint-sqlite)."""
    import sqlite3

    from langgraph.checkpoint.sqlite import SqliteSaver

    return SqliteSaver(sqlite3.connect(path, check_same_thread=False))


def memory_checkpointer():
    from langgraph.checkpoint.memory import InMemorySaver

    return InMemorySaver()


# ------------------------------------------------------------------------------ driving it
def start(app, packet: dict, thread_id: str | None = None) -> tuple[dict, dict]:
    """Run until the first pause. Returns (result, config). result['__interrupt__'] holds the
    payload the case UI shows the adjudicator."""
    cfg = {"configurable": {"thread_id": thread_id or packet["claim_id"]}, "recursion_limit": 60}
    return app.invoke(initial_state(packet), cfg), cfg


def resume(app, cfg: dict, decision: dict) -> dict:
    """Called by the case UI / FastAPI handler when the adjudicator clicks approve/edit/reject."""
    from langgraph.types import Command

    return app.invoke(Command(resume=decision), cfg)


def run_claim(
    app,
    packet: dict,
    reviewer: Callable[[dict], dict],
    max_reviews: int = 8,
    thread_id: str | None = None,
) -> dict:
    """Run a claim to the end, answering every pause with `reviewer(payload) -> decision`.
    Used by the eval harness and Reflexion (reviewer = simulated adjudicator)."""
    out, cfg = start(app, packet, thread_id)
    for _ in range(max_reviews):
        if not out.get("__interrupt__"):
            break
        out = resume(app, cfg, reviewer(out["__interrupt__"][0].value))
    else:
        raise RuntimeError("too many review rounds")
    return app.get_state(cfg).values
