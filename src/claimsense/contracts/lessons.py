"""Reflexion playbook lessons (Signature B). Only APPROVED lessons are retrieved."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class LessonStatus(StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class Lesson(BaseModel):
    lesson_id: str
    text: str  # e.g. "check the policy year before applying a sub-limit"
    applies_when: str
    clause_ids: list[str] = Field(default_factory=list)
    source_case_id: str  # a development case, never held-out
    status: LessonStatus = LessonStatus.PROPOSED
    reviewer_id: str | None = None
    review_note: str | None = None  # required when rejected
    created_at: datetime
