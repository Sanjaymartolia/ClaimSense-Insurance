"""Policy wording, one record per numbered clause."""

from datetime import date

from pydantic import BaseModel


class Clause(BaseModel):
    clause_id: str  # e.g. "AS-NIA-2025:4.1.2"
    policy_name: str  # "Arogya Sanjeevani"
    insurer: str
    section: str  # clause number as printed in the wording
    title: str | None = None
    text: str
    effective_date: date
    source_url: str


class RetrievedPassage(BaseModel):
    clause: Clause
    score: float
    rank: int
