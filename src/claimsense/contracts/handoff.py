"""Typed hand-off messages between the supervisor and specialist agents (L11)."""

from enum import StrEnum

from pydantic import BaseModel, Field


class AgentName(StrEnum):
    SUPERVISOR = "supervisor"
    EXTRACTION = "extraction"
    COVERAGE = "coverage"
    FRAUD = "fraud"
    CRITIC = "critic"
    SETTLEMENT = "settlement"


class Handoff(BaseModel):
    sender: AgentName
    recipient: AgentName
    claim_id: str
    step: str  # plan step this hand-off belongs to
    summary: str
    artifact_refs: list[str] = Field(default_factory=list)  # ids in graph state, not raw text


class PlanStep(BaseModel):
    name: str
    agent: AgentName
    status: str = "pending"  # pending | running | done | failed | skipped


class Plan(BaseModel):
    """Shown to the user; replanned when a tool result contradicts it (L10)."""

    claim_id: str
    steps: list[PlanStep]
    revision: int = 0
