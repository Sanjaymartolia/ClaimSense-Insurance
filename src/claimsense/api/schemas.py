"""Request bodies of the case API. Responses are plain JSON built in `runner.py`."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

#: A case id doubles as the checkpoint thread id: letters, digits, dot, dash, underscore.
CASE_ID = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
#: Upload limit for a packet's documents, in characters. Synthetic packets are a few kilobytes.
MAX_DOCUMENT_CHARS = 500_000


class ClaimPacketIn(BaseModel):
    """A claim packet: the documents as text, and optionally a hand-extracted claim and the policy
    record and history that the stub claims database would return (synthetic data only).

    `policy_number` is the policy the intake system filed the claim under. With it, every tool may
    read only that policy (`graph/nodes.py::registered_policy`), and documents naming another
    policy send the claim to a person."""

    claim_id: str = Field(pattern=CASE_ID)
    policy_number: str | None = Field(default=None, max_length=64)
    documents: dict[str, str] = Field(default_factory=dict)
    claim: dict[str, Any] | None = None
    fixture_policy: dict[str, Any] | None = None
    fixture_history: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def _consistent(self) -> ClaimPacketIn:
        if sum(len(text) for text in self.documents.values()) > MAX_DOCUMENT_CHARS:
            raise ValueError(f"documents exceed {MAX_DOCUMENT_CHARS} characters")
        if self.claim is not None and self.claim.get("claim_id") != self.claim_id:
            raise ValueError("claim.claim_id must equal claim_id")
        return self


class LineEditIn(BaseModel):
    """Re-point a line to another clause, or correct a misread amount. Totals are never typed in:
    the calculator recomputes them."""

    line_id: str
    clause_id: str | None = None
    amount: Decimal | None = Field(default=None, ge=0)
    reason: str = Field(min_length=1, max_length=500)


class DecisionIn(BaseModel):
    """The reviewer's decision. Who decides comes from the bearer token, not from this body."""

    decision: Literal["approve", "edit", "reject"]
    edits: list[LineEditIn] = Field(default_factory=list)
    note: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _edits_match_the_decision(self) -> DecisionIn:
        if self.decision == "edit" and not self.edits:
            raise ValueError("an edit needs at least one line edit")
        if self.decision != "edit" and self.edits:
            raise ValueError("line edits come only with decision 'edit'")
        return self
