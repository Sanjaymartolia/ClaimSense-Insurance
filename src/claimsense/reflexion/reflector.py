"""Self-reflection: one mistake -> one short, general lesson naming its clause (L12 notebook).

The prompt follows the L12 `reflect()` cell: find the step that went wrong, write ONE mechanical
check, name the clause and its condition, never mention this claim's amounts or names.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from claimsense.agents.llm import get_llm

from .evaluator import Mistake


class LessonDraft(BaseModel):
    mistake: str = Field(description="one sentence: the exact step that went wrong")
    lesson: str = Field(description="one sentence: a concrete check someone could follow mechanically")
    applies_when: str = Field(description="when the lesson applies, in general terms "
                                          "(line category, room type, policy condition)")
    clause_ids: list[str] = Field(description="clause ids the lesson is about")


PROMPT = """You review health-insurance claim adjudications under the Arogya Sanjeevani policy.

MISTAKE RECORD
source: {source}
bill line category: {category}
clause chosen: {got}
clause expected: {expected}
detail: {detail}

CLAUSE TEXT
{clause_text}

Find the exact step where the coverage analyst went wrong: a clause misread, a rule skipped, or a
condition (dates, room type, policy year, sub-limit already used) not checked. Then write ONE lesson
for future claims: a concrete check naming the clause and its exact condition or limit. Never
mention this claim's amounts, names, ids or dates. Example of the style: "Check the policy year
before applying a sub-limit (clause X)."
"""

_SPECIFIC = re.compile(r"(\bRs\.?\s?\d|₹\s?\d|\b\d{4,}\b|CLM-|POL-|PT-)", re.IGNORECASE)


def too_specific(text: str) -> bool:
    """L12: 'Kabir's dinner was Rs 7,500' helps nobody. Block amounts and identifiers."""
    return bool(_SPECIFIC.search(text))


def reflect(m: Mistake, clause_text: str = "") -> LessonDraft | None:
    llm = get_llm("reflector")
    if llm is None:  # stub: a template lesson so the loop is testable offline
        if not m.expected_clause:
            return None
        return LessonDraft(
            mistake=f"{m.category} line was governed by {m.got_clause}",
            lesson=f"For {m.category} lines, check clause {m.expected_clause} before {m.got_clause}.",
            applies_when=f"{m.category} line on the bill",
            clause_ids=[c for c in (m.expected_clause, m.got_clause) if c])
    draft = llm.with_structured_output(LessonDraft).invoke(PROMPT.format(
        source=m.source, category=m.category, got=m.got_clause, expected=m.expected_clause,
        detail=m.detail, clause_text=clause_text[:1500] or "(not retrieved)"))
    if too_specific(draft.lesson) or too_specific(draft.applies_when):
        return None
    return draft
