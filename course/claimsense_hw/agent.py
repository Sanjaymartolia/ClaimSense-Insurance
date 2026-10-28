"""The one entry point every script and test uses, so they never drift apart."""

import sqlite3
import time
import traceback

from langchain_community.callbacks import get_openai_callback
from langgraph.checkpoint.sqlite import SqliteSaver

from . import config, trace
from .graph import ClaimGraph


class ClaimAgent:
    def __init__(self, persist=False, interrupt_before=None):
        """persist=True saves every step to .state/checkpoints.sqlite, so a run paused
        for approval in one terminal command can be resumed by another (TODO 6c)."""
        self.checkpointer = None
        if persist:
            config.STATE_DB.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(config.STATE_DB, check_same_thread=False)
            self.checkpointer = SqliteSaver(conn)
        self.interrupt_before = interrupt_before

    def resolve(self, claim, question=None, thread_id=None):
        """Run one claim end to end. Returns a trace dict; never raises."""
        started = time.time()
        g = ClaimGraph(claim, self.checkpointer, self.interrupt_before)
        with get_openai_callback() as usage:
            try:
                final = g.run(claim["claim_id"], question, thread_id)
            except Exception as e:  # noqa: BLE001 — never lose a row
                traceback.print_exc()  # the full stack, so you can see WHERE it broke
                final = {
                    "answer": f"(agent error: {type(e).__name__}: {e})",
                    "route": "needs_review",
                    "steps": ["error"],
                    "actions": g.ctx.actions,
                }
        return trace.build(
            claim_id=claim["claim_id"],
            route=final.get("route", "needs_review"),
            answer=final.get("answer", ""),
            citations=final.get("citations", []),
            review_flags=final.get("review_flags", []),
            worksheet=final.get("worksheet"),
            actions=final.get("actions", []),
            handover=ClaimGraph.handover(final),
            meta={
                "latency_s": round(time.time() - started, 2),
                "tokens": usage.total_tokens,
                "cost_usd": round(usage.total_cost, 5),
                "model": config.TOOL_MODEL,
                "retrieval_mode": config.RETRIEVAL_MODE,
                "graph_path": final.get("steps", []),
                "paused_before": list(
                    g.graph.get_state(
                        {"configurable": {"thread_id": thread_id or claim["claim_id"]}}
                    ).next
                )
                if self.checkpointer
                else [],
            },
        )

    def resume(self, thread_id, approved, approver_id="adjudicator-demo"):
        """TODO 6c — carry on after a human approves or rejects. Lecture 8.

        The graph paused before `settle` and its state is saved under thread_id.
          1. Rebuild the ClaimGraph for that claim (the claim id is in the saved state;
             load the claim from config.DEV_CLAIMS).
          2. g.graph.get_state(cfg).values  -> the worksheet it was about to settle.
          3. Approved: build claimsense.contracts.ApprovalToken(claim_id=...,
             worksheet_hash=tools.worksheet_hash(worksheet), level="adjudicator",
             approver_id=..., decided_at=datetime.now(UTC)) and
             g.graph.update_state(cfg, {"approval": token.model_dump(mode="json")}).
             Rejected: update_state(cfg, {"route": "needs_review"}) instead.
          4. g.graph.invoke(None, cfg)  # None = carry on from where it stopped
        Your settle node must turn state["approval"] back into an ApprovalToken and
        put it on self.ctx.approval before calling settle_claim.
        """
        raise NotImplementedError("TODO 6c — see the docstring")
