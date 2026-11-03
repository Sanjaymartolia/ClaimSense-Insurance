"""Human approval gate (L14). ClaimSense Role 4 (Tools, Control & Security).

The L14 gate already exists inside Role 3's ``graph/nodes.py`` (``_review`` / ``human_review`` /
``senior_review`` / ``apply_edits``). This module provides the **reusable, hardened L14 building
blocks** that those nodes inline, so the control logic lives in one Role 4-owned place and can be
tested independently - *without modifying any Role 3 file*.

What it offers
--------------
* :func:`build_review_payload` - the exact payload shape the adjudicator UI is shown (identical
  keys to ``nodes._review``), with the canonical ``worksheet_hash`` from ``Worksheet.content_hash``.
* :func:`parse_decision` - validate the UI's reply into the shared ``graph.state.ReviewDecision``.
* :func:`needs_senior_review` - high-value or fraud-flagged claims need a senior sign-off.
* :class:`ReviewGate` - wraps ``interrupt()`` (injectable, so it works with LangGraph *and* with
  the dependency-free ``LocalRunner`` used in tests) and returns a state update **identical in
  shape** to ``nodes._review``, but with the approval token issued through a *trusted identity*
  and bound+signed via :mod:`approval_security` (approve / edit / reject; an edit voids earlier
  approvals because the worksheet hash changes).
* :func:`run_with_review` - drives a built graph to completion, reusing Role 3's
  ``graph.build.run_claim`` (``interrupt`` + ``Command(resume=...)``).
* :func:`build_demo_gate` - a small standalone LangGraph that demonstrates pause/resume with the
  real contracts.

Role 3 can adopt it by having ``nodes._review`` delegate to :class:`ReviewGate`; until then the
shapes are kept byte-compatible so nothing breaks.
"""

from __future__ import annotations

import hashlib
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable


def _ensure_claimsense_on_path() -> None:
    try:
        import claimsense  # noqa: F401
        return
    except ModuleNotFoundError:
        pass
    env = os.environ.get("CLAIMSENSE_SRC")
    here = Path(__file__).resolve()
    candidates = [Path(env)] if env else []
    candidates += [
        here.parent.parent / "ClaimSense-Insurance" / "src",
        here.parent / "ClaimSense-Insurance" / "src",
    ]
    for cand in candidates:
        if (cand / "claimsense").is_dir():
            sys.path.insert(0, str(cand))
            return


_ensure_claimsense_on_path()

from claimsense.contracts import ApprovalDecision, ApprovalLevel, Worksheet  # noqa: E402
from claimsense.graph.state import ReviewDecision, Status  # noqa: E402

import approval_security  # noqa: E402  (sibling module)
from approval_security import AuthenticatedApprover, IdentityProvider  # noqa: E402


# --------------------------------------------------------------------------------------------
# Payload / decision helpers (shapes match graph/nodes._review)
# --------------------------------------------------------------------------------------------
def build_review_payload(
    state: dict,
    level: ApprovalLevel,
    *,
    render_plan: Callable[[Any], str] | None = None,
) -> dict:
    """Build the payload the adjudicator sees at ``interrupt()``. Mirrors ``nodes._review``.

    Health details are never included - only the worksheet, its hash, flags and routing context.
    """
    worksheet: Worksheet | None = state.get("worksheet")
    admissibility = state.get("admissibility")
    admissible = getattr(admissibility, "admissible", True)
    kind = "worksheet" if admissible else "repudiation"
    if kind == "worksheet" and worksheet is not None:
        subject_hash = worksheet.content_hash()
    elif admissibility is not None:
        subject_hash = hashlib.sha256(admissibility.model_dump_json().encode()).hexdigest()
    else:  # pragma: no cover - defensive
        subject_hash = ""
    plan = state.get("plan")
    return {
        "claim_id": state.get("claim_id"),
        "kind": kind,
        "level": level.value,
        "worksheet": worksheet.model_dump(mode="json") if worksheet and kind == "worksheet" else None,
        "worksheet_hash": subject_hash,
        "admissibility": admissibility.model_dump(mode="json") if admissibility is not None else None,
        "fraud_flags": state.get("fraud_flags", []),
        "critic": state["critic_report"].feedback() if state.get("critic_report") else [],
        "escalation": state.get("escalation"),
        "plan": render_plan(plan) if (render_plan and plan is not None) else None,
    }


def parse_decision(raw: Any) -> ReviewDecision:
    """Validate the UI reply (dict or ``ReviewDecision``) into a ``ReviewDecision``."""
    return raw if isinstance(raw, ReviewDecision) else ReviewDecision.model_validate(raw)


def needs_senior_review(worksheet: Worksheet | None, fraud_flags, threshold: Decimal | None = None) -> bool:
    """True when the claim needs a senior sign-off (high value or any fraud flag)."""
    if worksheet is None:
        return False
    return approval_security.needs_senior(worksheet, fraud_flags, threshold)


# --------------------------------------------------------------------------------------------
# ReviewGate
# --------------------------------------------------------------------------------------------
class ReviewGate:
    """Runs one review round and returns a state update identical in shape to ``nodes._review``.

    ``interrupt_fn`` is injected: pass ``langgraph.types.interrupt`` in production, or a test
    callback (as ``LocalRunner`` does) to answer synchronously. ``identity_provider`` supplies the
    *authenticated* approver; the approver id baked into the token comes from there, not from the
    UI payload (which is treated as untrusted).
    """

    def __init__(
        self,
        interrupt_fn: Callable[[dict], Any],
        identity_provider: IdentityProvider | None = None,
        *,
        store: "approval_security.ApprovalStore | None" = None,
        render_plan: Callable[[Any], str] | None = None,
    ):
        self.interrupt = interrupt_fn
        self.identity = identity_provider
        self.store = store
        self._render_plan = render_plan

    def _authenticate(self, claim_id: str, level: ApprovalLevel, decision: ReviewDecision) -> AuthenticatedApprover:
        if self.identity is not None:
            return self.identity.authenticate(claim_id, level)
        # Compatibility fallback: trust the decision's approver_id (documented as weaker). A real
        # deployment must pass an IdentityProvider so identity is not a free-form string.
        return AuthenticatedApprover(approver_id=decision.approver_id, level=level,
                                     auth_source="unverified", authenticated_at=datetime.now(timezone.utc))

    def review(self, state: dict, level: ApprovalLevel) -> dict:
        worksheet: Worksheet | None = state.get("worksheet")
        payload = build_review_payload(state, level, render_plan=self._render_plan)
        decision = parse_decision(self.interrupt(payload))
        base = {"review_decision": decision.decision.value}

        if decision.decision == ApprovalDecision.APPROVE:
            if worksheet is None:
                # repudiation approval: no money token needed, just record the decision
                return base
            approver = self._authenticate(state.get("claim_id", ""), level, decision)
            token = approval_security.issue_approval(worksheet, approver, store=self.store)
            return {**base, "approvals": [*state.get("approvals", []), token]}

        if decision.decision == ApprovalDecision.EDIT:
            prior = state.get("clause_choices") or {}
            edit_log = [
                {
                    "claim_id": state.get("claim_id"),
                    "level": level.value,
                    "line_id": e.line_id,
                    "old_clause": prior.get(e.line_id),
                    "new_clause": e.clause_id,
                    "new_amount": str(e.amount) if e.amount is not None else None,
                    "reason": e.reason,
                }
                for e in decision.edits
            ]
            return {**base, "pending_edits": decision.edits, "edit_log": edit_log}

        return {**base, "status": Status.REJECTED}


def make_node_review(
    interrupt_fn: Callable[[dict], Any],
    identity_provider: IdentityProvider | None = None,
    **kwargs: Any,
) -> Callable[[dict, ApprovalLevel], dict]:
    """Return a ``(state, level) -> update`` callable - the form ``nodes._review`` could delegate to."""
    gate = ReviewGate(interrupt_fn, identity_provider, **kwargs)
    return gate.review


# --------------------------------------------------------------------------------------------
# Drivers
# --------------------------------------------------------------------------------------------
def run_with_review(app: Any, packet: dict, reviewer: Callable[[dict], dict],
                    max_reviews: int = 8, thread_id: str | None = None) -> dict:
    """Drive a compiled graph to completion, answering each pause with ``reviewer(payload)``.

    Delegates to Role 3's ``graph.build.run_claim`` (``interrupt`` + ``Command(resume=...)``).
    """
    from claimsense.graph.build import run_claim

    return run_claim(app, packet, reviewer, max_reviews=max_reviews, thread_id=thread_id)


def build_demo_gate(identity_provider: IdentityProvider | None = None):
    """A small standalone LangGraph showing the pause/resume cycle with the real contracts.

    Requires ``langgraph``. State carries a ``Worksheet``; approval is issued via
    :mod:`approval_security`, and an edit re-pauses with a new worksheet hash so the old approval
    is void. Role 3's full pipeline is the production path; this is a focused L14 demo.
    """
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import interrupt

    from typing import TypedDict

    class GateState(TypedDict, total=False):
        claim_id: str
        worksheet: dict
        approvals: list
        review_decision: str
        status: str

    gate = ReviewGate(interrupt, identity_provider)

    def human_review(state: GateState) -> dict:
        ws = Worksheet.model_validate(state["worksheet"])
        s = {"claim_id": state["claim_id"], "worksheet": ws, "approvals": state.get("approvals", []),
             "admissibility": None}
        update = gate.review(s, ApprovalLevel.ADJUDICATOR)
        out: dict = {"review_decision": update["review_decision"]}
        if "approvals" in update:
            out["approvals"] = [t.model_dump(mode="json") for t in update["approvals"]]
            out["status"] = "approved"
        elif update["review_decision"] == ApprovalDecision.REJECT.value:
            out["status"] = Status.REJECTED
        else:
            out["status"] = "edited"
        return out

    g = StateGraph(GateState)
    g.add_node("human_review", human_review)
    g.add_edge(START, "human_review")
    g.add_edge("human_review", END)
    return g.compile(checkpointer=InMemorySaver())
