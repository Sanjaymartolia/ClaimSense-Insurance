"""adjudication-calc MCP server. ClaimSense Role 4 (Tools, Control & Security), Signature A.

Every rupee is computed here in :class:`~decimal.Decimal`, never by a model and never with floats.
The model only *selects a clause per line* (coverage analyst); this module turns the claim plus the
selected clauses into a fully-reconciled :class:`~claimsense.contracts.Worksheet`.

Role 3 reaches it through ``Services.calculate`` (registry name ``calculate``; used by the coverage
analyst and the critic - see ``agents/permissions.TOOL_ACL``). The arithmetic here is intentionally
identical to the repository's development reference (``claimsense.agents.services.reference_calculate``)
so it is a drop-in replacement for the ``claimsense.calc.adjudication`` stub and preserves the
behaviour the orchestration tests already pin (room-rent cap + proportional cut, medicines exempt,
co-pay last).

Rule parameters come from the actual New India "Arogya Sanjeevani" wording in the repo:
    * clause 4.1(a): Room/Boarding/Nursing up to 2% of sum insured, max Rs.5000/day
    * clause 4.1(b): ICU/ICCU up to 5% of sum insured, max Rs.10,000/day
    * clause 4.1.1 Note b: on a room/ICU rate breach, all other expenses *except medicines* are
      paid in the same proportion (proportional deduction)
    * clause 4.3: cataract 25% of sum insured or Rs.40,000/eye, whichever is lower
    * clause 9.5: co-payment of 5% on every claim
Verify these against the policy schedule/endorsements before any real use.

``fastmcp`` is imported lazily in :func:`main`, so the module imports and runs for tests without it.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path


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

from pydantic import BaseModel  # noqa: E402

from claimsense.agents import clauses as C  # noqa: E402  (shared clause-id constants)
from claimsense.contracts import (  # noqa: E402
    Claim,
    Deduction,
    DeductionReason,
    LineCategory,
    Worksheet,
    WorksheetLine,
)

PAISE = Decimal("0.01")


class ToolError(BaseModel):
    """Structured error returned at the MCP boundary instead of raising to an agent."""

    error: str
    code: str = "calc_error"
    retryable: bool = False


@dataclass(frozen=True)
class PolicyRules:
    """Numeric rule parameters, sourced from the real Arogya Sanjeevani wording (see module docstring).

    Kept as a value object so a different policy version / schedule can be supplied without code
    changes. These are demo-grade defaults: confirm against the exact schedule before real use.
    """

    room_rent_pct: Decimal = Decimal("0.02")          # clause 4.1(a)
    room_rent_max_per_day: Decimal = Decimal("5000")  # clause 4.1(a)
    icu_pct: Decimal = Decimal("0.05")                # clause 4.1(b)
    icu_max_per_day: Decimal = Decimal("10000")       # clause 4.1(b)
    cataract_pct: Decimal = Decimal("0.25")           # clause 4.3
    cataract_max_per_eye: Decimal = Decimal("40000")  # clause 4.3
    co_pay_rate: Decimal = Decimal("0.05")            # clause 9.5


# Which line categories are "room-linked" and therefore shrink on a room/ICU breach (clause 4.1.1
# Note b). Medicines are explicitly exempt; consumables are handled via their own clause choice.
LINKED_CATEGORIES = frozenset(
    {
        LineCategory.NURSING,
        LineCategory.DOCTOR_FEES,
        LineCategory.OT,
        LineCategory.INVESTIGATIONS,
        LineCategory.PROCEDURE,
        LineCategory.OTHER,
    }
)

# Clause ids whose selection means the whole line is not payable (full deduction).
FULLY_DEDUCTED: dict[str, DeductionReason] = {
    C.NON_PAYABLE_ITEMS: DeductionReason.NON_PAYABLE,
    C.INITIAL_WAITING_PERIOD: DeductionReason.WAITING_PERIOD,
    C.PED_WAITING_PERIOD: DeductionReason.WAITING_PERIOD,
    C.SPECIFIC_WAITING_PERIOD: DeductionReason.WAITING_PERIOD,
}


def to_rupees(value: Decimal) -> Decimal:
    """Quantise to paise (2 dp), rounding half up."""
    return value.quantize(PAISE, rounding=ROUND_HALF_UP)


def room_rent_limit_per_day(sum_insured: Decimal, rules: PolicyRules) -> Decimal:
    """Lower of 2% of sum insured and the Rs.5000/day cap (clause 4.1(a))."""
    return min(sum_insured * rules.room_rent_pct, rules.room_rent_max_per_day)


def icu_limit_per_day(sum_insured: Decimal, rules: PolicyRules) -> Decimal:
    """Lower of 5% of sum insured and the Rs.10,000/day cap (clause 4.1(b))."""
    return min(sum_insured * rules.icu_pct, rules.icu_max_per_day)


def proportional_cut_ratio(actual_per_day: Decimal, eligible_per_day: Decimal) -> Decimal:
    """Admissible-to-actual ratio for linked charges after a room/ICU breach (clause 4.1.1 Note b).

    Returns ``1`` (no cut) when the actual rate is within the eligible rate.
    """
    if actual_per_day <= 0 or eligible_per_day >= actual_per_day:
        return Decimal("1")
    return eligible_per_day / actual_per_day


def co_pay(amount: Decimal, rules: PolicyRules) -> Decimal:
    """5% co-payment on the otherwise-payable amount (clause 9.5), applied after all deductions."""
    return to_rupees(amount * rules.co_pay_rate)


def _validate_claim(claim: Claim) -> None:
    """Defensive numeric validation (the contract already enforces >=0 / 2dp)."""
    if claim.sum_insured <= 0:
        raise ValueError("sum_insured must be positive")
    for line in claim.bill_lines:
        amt = line.amount
        if not amt.is_finite():
            raise ValueError(f"line {line.line_id}: amount is not finite")
        if amt < 0:
            raise ValueError(f"line {line.line_id}: amount is negative")
        if line.days is not None and line.days < 0:
            raise ValueError(f"line {line.line_id}: days is negative")


def adjudicate(
    claim: Claim,
    clause_choices: dict[str, str],
    rules: PolicyRules | None = None,
    *,
    version: int = 1,
    fraud_flags: list[str] | None = None,
) -> Worksheet:
    """Turn a claim + per-line clause choices into a reconciled worksheet (all amounts in code).

    ``clause_choices`` maps ``line_id -> clause_id`` (chosen by the coverage analyst). ``fraud_flags``
    are carried onto the worksheet for routing only - they never change any amount. This function
    does not decide admissibility; it applies the clause each line was assigned.
    """
    rules = rules or PolicyRules()
    _validate_claim(claim)
    si = claim.sum_insured
    room_cap = room_rent_limit_per_day(si, rules)
    icu_cap = icu_limit_per_day(si, rules)

    # Single proportional ratio from the worst room/ICU breach (clause 4.1.1 Note b).
    ratio = Decimal("1")
    for line in claim.bill_lines:
        days = Decimal(line.days or claim.nights or 1)
        per_day = line.amount / days if days else line.amount
        if line.category == LineCategory.ROOM and per_day > room_cap:
            ratio = min(ratio, proportional_cut_ratio(per_day, room_cap))
        elif line.category == LineCategory.ICU and per_day > icu_cap:
            ratio = min(ratio, proportional_cut_ratio(per_day, icu_cap))

    lines: list[WorksheetLine] = []
    for line in claim.bill_lines:
        chosen = clause_choices.get(line.line_id, C.HOSPITALISATION)
        days = Decimal(line.days or claim.nights or 1)
        deductions: list[Deduction] = []

        if chosen in FULLY_DEDUCTED:
            deductions.append(
                Deduction(
                    reason=FULLY_DEDUCTED[chosen],
                    amount=line.amount,
                    clause_id=chosen,
                    explanation="Not payable under the selected clause.",
                )
            )
        elif line.category == LineCategory.ROOM and line.amount > room_cap * days:
            amount = to_rupees(line.amount - room_cap * days)
            deductions.append(
                Deduction(
                    reason=DeductionReason.ROOM_RENT_CAP,
                    amount=amount,
                    clause_id=C.ROOM_RENT_LIMIT,
                    explanation=f"Room rent capped at Rs {to_rupees(room_cap)}/day x {days} day(s).",
                )
            )
        elif line.category == LineCategory.ICU and line.amount > icu_cap * days:
            amount = to_rupees(line.amount - icu_cap * days)
            deductions.append(
                Deduction(
                    reason=DeductionReason.ICU_CAP,
                    amount=amount,
                    clause_id=C.ICU_LIMIT,
                    explanation=f"ICU capped at Rs {to_rupees(icu_cap)}/day x {days} day(s).",
                )
            )
        elif line.category in LINKED_CATEGORIES and ratio < 1:
            amount = to_rupees(line.amount * (Decimal("1") - ratio))
            deductions.append(
                Deduction(
                    reason=DeductionReason.PROPORTIONAL_CUT,
                    amount=amount,
                    clause_id=C.OTHER_EXPENSES,
                    explanation=f"Proportional cut after room/ICU breach, factor {ratio:.4f}.",
                )
            )

        deducted = sum((d.amount for d in deductions), Decimal("0"))
        lines.append(
            WorksheetLine(line_id=line.line_id, claimed=line.amount, deductions=deductions,
                          payable=line.amount - deducted)
        )

    gross = sum((wl.payable for wl in lines), Decimal("0"))
    co = co_pay(gross, rules)
    co_pay_deduction = (
        Deduction(
            reason=DeductionReason.CO_PAY,
            amount=co,
            clause_id=C.CO_PAY,
            explanation=f"{rules.co_pay_rate * 100:.0f}% co-pay on the admissible amount.",
        )
        if co > 0
        else None
    )
    return Worksheet(
        claim_id=claim.claim_id,
        version=version,
        lines=lines,
        co_pay=co_pay_deduction,
        total_claimed=sum((wl.claimed for wl in lines), Decimal("0")),
        total_payable=gross - co,
        fraud_flags=list(fraud_flags or []),
    )


def _as_claim(claim: Claim | dict) -> Claim:
    return claim if isinstance(claim, Claim) else Claim.model_validate(claim)


def calculate(
    claim: Claim | dict,
    clause_choices: dict[str, str],
    version: int = 1,
    fraud_flags: list[str] | None = None,
    **_: object,
) -> Worksheet:
    """Services-facing entry (registry name ``calculate``).

    Accepts a :class:`Claim` (in-process agent call) or a plain ``dict`` (MCP/JSON call).
    """
    return adjudicate(_as_claim(claim), clause_choices or {}, PolicyRules(),
                      version=version, fraud_flags=fraud_flags)


def _tool_calculate(claim: dict, clause_choices: dict[str, str], version: int = 1,
                    fraud_flags: list[str] | None = None):
    """[read] Compute the settlement worksheet. Returns a worksheet or a structured error."""
    try:
        return calculate(claim, clause_choices, version=version, fraud_flags=fraud_flags)
    except (ValueError, InvalidOperation, KeyError, TypeError) as exc:
        return ToolError(error=str(exc), code="invalid_input")


def _tool_room_rent_limit(sum_insured: float | str):
    """[read] Room-rent daily limit (clause 4.1(a)) for a sum insured."""
    try:
        return {"room_rent_limit_per_day": str(room_rent_limit_per_day(Decimal(str(sum_insured)), PolicyRules()))}
    except (InvalidOperation, ValueError) as exc:
        return ToolError(error=str(exc), code="invalid_input")


def main() -> None:
    """Start the adjudication-calc MCP server (stdio). Requires the optional ``[mcp]`` extra."""
    from fastmcp import FastMCP  # lazy: optional dependency

    mcp = FastMCP("adjudication-calc")
    mcp.tool(name="calculate")(_tool_calculate)
    mcp.tool(name="room_rent_limit_per_day")(_tool_room_rent_limit)
    mcp.run()


if __name__ == "__main__":
    main()
