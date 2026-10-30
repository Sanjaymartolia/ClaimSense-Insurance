"""Graph state (L8: a typed schema + reducers) and the adjudicator's review decision."""

from __future__ import annotations

import operator
from decimal import Decimal
from typing import Annotated, TypedDict

from pydantic import BaseModel, Field

from claimsense.agents.coverage import Admissibility
from claimsense.agents.critic import CriticReport
from claimsense.contracts import ApprovalDecision, ApprovalToken, Claim, Handoff, Plan, Worksheet

MAX_REVISIONS = 1  # critic may send the worksheet back once (brief, step 6)


class Status:
    RUNNING = "running"
    AWAITING_REVIEW = "awaiting_review"
    SETTLED = "settled"
    REPUDIATED = "repudiated"
    REJECTED = "rejected"  # adjudicator rejected the worksheet; claim goes back to the desk
    ESCALATED = "escalated"


class LineEdit(BaseModel):
    """One adjudicator correction. Either re-point the line to another clause, or fix an amount
    the extraction misread. Totals are always recomputed by the calculator, never typed in."""

    line_id: str
    clause_id: str | None = None
    amount: Decimal | None = None
    reason: str = Field(description="why: becomes Reflexion feedback")


class ReviewDecision(BaseModel):
    decision: ApprovalDecision
    approver_id: str
    edits: list[LineEdit] = Field(default_factory=list)
    note: str | None = None


class ClaimState(TypedDict, total=False):
    # input
    claim_id: str
    packet: dict
    # plan (L10)
    plan: Plan
    # specialists' outputs
    claim: Claim
    extraction_issues: list[str]
    admissibility: Admissibility
    clause_choices: dict[str, str]
    locked_choices: dict[str, str]  # adjudicator overrides; agents may not change them
    lessons_used: list[str]
    coverage_notes: list[str]
    worksheet: Worksheet
    fraud_flags: list[str]
    critic_report: CriticReport
    # loop control
    revisions: int
    max_revisions: int
    human_edited: bool
    escalation: str | None
    # human control
    approvals: list[ApprovalToken]
    review_decision: str | None
    pending_edits: list[LineEdit]
    # outputs
    settlement: dict
    letter: str
    status: str
    # append-only logs (reducers) — trace holds ids and amounts only, never health details
    trace: Annotated[list[str], operator.add]
    handoffs: Annotated[list[Handoff], operator.add]
    critic_history: Annotated[list[CriticReport], operator.add]
    edit_log: Annotated[list[dict], operator.add]


APPEND_KEYS = {"trace", "handoffs", "critic_history", "edit_log"}


def initial_state(packet: dict, max_revisions: int = MAX_REVISIONS) -> ClaimState:
    return ClaimState(
        claim_id=packet["claim_id"], packet=packet, revisions=0, max_revisions=max_revisions,
        human_edited=False, approvals=[], locked_choices={}, fraud_flags=[], escalation=None,
        status=Status.RUNNING, trace=[], handoffs=[], critic_history=[], edit_log=[],
    )
