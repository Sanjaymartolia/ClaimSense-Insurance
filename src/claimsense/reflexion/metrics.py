"""Settlement error and adjudicator edit rate (what the brief asks you to report)."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel


class CaseResult(BaseModel):
    case_id: str
    proposed_total: Decimal | None  # first worksheet shown to the adjudicator
    gold_total: Decimal | None
    abs_error: Decimal  # |proposed - gold| in rupees; 0 when gold is missing; never tolerated away
    edited: bool  # did the adjudicator change anything?
    lines_edited: int
    critic_rejections: int
    lessons_used: list[str]
    status: str
    tolerance_rs: Decimal = Decimal("0")  # rounding tolerance the run was scored with (0 = strict)

    @property
    def matches_gold(self) -> bool:
        """Exact match, or within the rounding tolerance when one was set."""
        return self.abs_error <= self.tolerance_rs


def summarize(results: list[CaseResult]) -> dict:
    """`settlement_error_*` are exact rupees whatever the tolerance; `exact_match_rate` counts a
    case as matching when its error is within the tolerance it was scored with."""
    n = len(results) or 1
    total = sum((r.abs_error for r in results), Decimal(0))
    return {
        "cases": len(results),
        "settlement_error_total_rs": total,
        "settlement_error_mean_rs": (total / n).quantize(Decimal("0.01")),
        "exact_match_rate": round(sum(r.matches_gold for r in results) / n, 3),
        "edit_rate": round(sum(r.edited for r in results) / n, 3),
        "critic_rejection_rate": round(sum(r.critic_rejections > 0 for r in results) / n, 3),
    }


def compare_table(before: dict, after: dict) -> str:
    rows = ["| metric | before | after |", "|---|---|---|"]
    for k in (
        "settlement_error_total_rs",
        "settlement_error_mean_rs",
        "exact_match_rate",
        "edit_rate",
        "critic_rejection_rate",
    ):
        rows.append(f"| {k} | {before[k]} | {after[k]} |")
    return "\n".join(rows)
