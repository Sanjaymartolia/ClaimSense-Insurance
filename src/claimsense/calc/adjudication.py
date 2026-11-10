"""Adjudication calculator — core engine. Owner: Tools & Security (T15).

Lives at ``src/claimsense/calc/adjudication.py``. Every rupee is computed here in
:class:`~decimal.Decimal`, never by a model and never with floats. The coverage analyst only
*selects one clause per bill line*; this engine turns the claim plus those clause choices into a
fully-reconciled shared :class:`~claimsense.contracts.Worksheet`.

Role 3 integration
------------------
``claimsense.agents.services`` is the seam. Its ``real_calculate`` adapter imports this module and
calls it exactly as::

    from claimsense.calc.adjudication import PolicyRules, adjudicate
    ws = adjudicate(claim, clause_choices, PolicyRules())

The *coverage* and *critic* agents reach it through the ``calculate`` service (``real_calculate`` in
production, ``reference_calculate`` in dev) — see ``agents/permissions.TOOL_ACL``. The arithmetic
here is intentionally identical to the repository's development reference
(``agents.services.reference_calculate``), so the two never disagree and the behaviour the
orchestration tests pin (room-rent cap + proportional cut, medicines exempt, 5% co-pay last) is
preserved. The MCP server that exposes this over FastMCP is a separate module (the
``adjudication-calc`` server); it must reuse this engine rather than re-implement the maths.

Rule parameters (New India *Arogya Sanjeevani* wording quoted in the repo; verify vs. the schedule)
    * 4.1(a)    room/boarding/nursing up to 2% of sum insured, max Rs.5,000/day
    * 4.1(b)    ICU/ICCU up to 5% of sum insured, max Rs.10,000/day
    * 4.1.1 b   on a room/ICU rate breach, all other expenses *except medicines* are paid in the
                same proportion (proportional deduction)
    * 4.3       cataract 25% of sum insured or Rs.40,000/eye, whichever is lower (parameters kept
                on :class:`PolicyRules`; not auto-applied by the reference ruleset — see note below)
    * 9.5       co-payment of 5% on every claim

The engine never approves, settles or repudiates: it only returns the Worksheet.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from claimsense.agents import clauses as C  # shared clause-id constants (single source of truth)
from claimsense.contracts import (  # shared contracts; never redefined here
    Claim,
    Deduction,
    DeductionReason,
    LineCategory,
    Worksheet,
    WorksheetLine,
)

__all__ = [
    "PolicyRules",
    "PAISE",
    "to_rupees",
    "room_rent_limit_per_day",
    "icu_limit_per_day",
    "proportional_cut_ratio",
    "co_pay",
    "adjudicate",
]

PAISE = Decimal("0.01")


@dataclass(frozen=True)
class PolicyRules:
    """Numeric rule parameters, from the real Arogya Sanjeevani wording (see module docstring).

    A frozen value object so a different policy version / schedule can be supplied without code
    changes. These are demo-grade defaults: confirm against the exact schedule before real use.

    Note: ``cataract_*`` are retained for policy completeness but are not auto-applied here — the
    reference ruleset (``agents.services.reference_calculate``) applies no cataract sub-limit, and
    there is no confirmed cataract clause id yet (``agents/clauses.py`` folds it into 4.1.1). A
    cataract sub-limit must be driven by an explicit clause choice once that id is agreed, so it is
    not invented in this engine.
    """

    room_rent_pct: Decimal = Decimal("0.02")  # clause 4.1(a)
    room_rent_max_per_day: Decimal = Decimal("5000")  # clause 4.1(a)
    icu_pct: Decimal = Decimal("0.05")  # clause 4.1(b)
    icu_max_per_day: Decimal = Decimal("10000")  # clause 4.1(b)
    cataract_pct: Decimal = Decimal("0.25")  # clause 4.3 (not auto-applied; see note)
    cataract_max_per_eye: Decimal = Decimal("40000")  # clause 4.3 (not auto-applied; see note)
    co_pay_rate: Decimal = Decimal("0.05")  # clause 9.5


# Room-linked categories that shrink in proportion after a room/ICU rate breach (clause 4.1.1
# Note b). Medicines are explicitly exempt; consumables are handled via their own clause choice.
LINKED_CATEGORIES: frozenset[LineCategory] = frozenset(
    {
        LineCategory.NURSING,
        LineCategory.DOCTOR_FEES,
        LineCategory.OT,
        LineCategory.INVESTIGATIONS,
        LineCategory.PROCEDURE,
        LineCategory.OTHER,
    }
)

# Selecting one of these clauses for a line makes the whole line non-payable (full deduction).
# These are claim-exclusions / waiting-period / non-payable clauses the coverage analyst may assign
# per line. The calculator receives only per-line clause choices (line_id -> clause_id); it has no
# claim-level exclusion flag, so a *whole* claim reaches Rs 0 only when every line is assigned the
# relevant clause upstream (coverage/orchestration).
FULLY_DEDUCTED: dict[str, DeductionReason] = {
    C.NON_PAYABLE_ITEMS: DeductionReason.NON_PAYABLE,
    C.INITIAL_WAITING_PERIOD: DeductionReason.WAITING_PERIOD,
    C.PED_WAITING_PERIOD: DeductionReason.WAITING_PERIOD,
    C.SPECIFIC_WAITING_PERIOD: DeductionReason.WAITING_PERIOD,
    # Maternity Expenses (clause 7.15, Code Excl18): childbirth/caesarean is excluded, so a line
    # assigned to 7.15 is deducted in full with reason EXCLUSION (fixes CLM-0018 / GOLD-01).
    C.MATERNITY_EXCLUSION: DeductionReason.EXCLUSION,
}


def to_rupees(value: Decimal) -> Decimal:
    """Quantise to paise (2 dp), rounding half up."""
    return value.quantize(PAISE, rounding=ROUND_HALF_UP)


# --------------------------------------------------------------------------------------------
# Per-rule helpers (the signatures the T15 stub declared, now implemented).
# --------------------------------------------------------------------------------------------
def room_rent_limit_per_day(sum_insured: Decimal, rules: PolicyRules) -> Decimal:
    """Lower of 2% of sum insured and the Rs.5,000/day cap (clause 4.1(a))."""
    return min(sum_insured * rules.room_rent_pct, rules.room_rent_max_per_day)


def icu_limit_per_day(sum_insured: Decimal, rules: PolicyRules) -> Decimal:
    """Lower of 5% of sum insured and the Rs.10,000/day cap (clause 4.1(b))."""
    return min(sum_insured * rules.icu_pct, rules.icu_max_per_day)


def proportional_cut_ratio(actual_per_day: Decimal, eligible_per_day: Decimal) -> Decimal:
    """Admissible-to-actual ratio for linked charges after a room/ICU breach (clause 4.1.1 Note b).

    Returns ``1`` (no cut) when the actual per-day rate is within the eligible rate.
    """
    if actual_per_day <= 0 or eligible_per_day >= actual_per_day:
        return Decimal("1")
    return eligible_per_day / actual_per_day


def co_pay(amount: Decimal, rules: PolicyRules) -> Decimal:
    """5% co-payment on the otherwise-payable amount (clause 9.5), applied after all deductions."""
    return to_rupees(amount * rules.co_pay_rate)


def _validate_claim(claim: Claim) -> None:
    """Numeric sanity checks beyond what the contract already enforces (>=0, 2 dp, date order)."""
    if claim.sum_insured <= 0:
        raise ValueError("sum_insured must be positive")
    for line in claim.bill_lines:
        amount = line.amount
        if not amount.is_finite():
            raise ValueError(f"line {line.line_id}: amount is not finite")
        if amount < 0:
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
    """Turn a claim + per-line clause choices into a reconciled :class:`Worksheet` (all maths here).

    ``clause_choices`` maps ``line_id -> clause_id`` (chosen by the coverage analyst); lines with no
    entry default to the hospitalisation clause. ``rules`` defaults to :class:`PolicyRules`.
    ``version`` and ``fraud_flags`` are carried onto the worksheet for routing only — they never
    change any amount (the adapter ``services.real_calculate`` sets them this way). Admissibility is
    decided upstream; this applies the clause each line was assigned and reconciles every rupee.
    """
    rules = rules or PolicyRules()
    _validate_claim(claim)
    room_cap = room_rent_limit_per_day(claim.sum_insured, rules)
    icu_cap = icu_limit_per_day(claim.sum_insured, rules)

    # One proportional ratio from the worst room/ICU rate breach (clause 4.1.1 Note b).
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
            deductions.append(
                Deduction(
                    reason=DeductionReason.ROOM_RENT_CAP,
                    amount=to_rupees(line.amount - room_cap * days),
                    clause_id=C.ROOM_RENT_LIMIT,
                    explanation=f"Room rent capped at Rs {to_rupees(room_cap)}/day x {days} day(s).",
                )
            )
        elif line.category == LineCategory.ICU and line.amount > icu_cap * days:
            deductions.append(
                Deduction(
                    reason=DeductionReason.ICU_CAP,
                    amount=to_rupees(line.amount - icu_cap * days),
                    clause_id=C.ICU_LIMIT,
                    explanation=f"ICU capped at Rs {to_rupees(icu_cap)}/day x {days} day(s).",
                )
            )
        elif line.category in LINKED_CATEGORIES and ratio < 1:
            deductions.append(
                Deduction(
                    reason=DeductionReason.PROPORTIONAL_CUT,
                    amount=to_rupees(line.amount * (Decimal("1") - ratio)),
                    clause_id=C.OTHER_EXPENSES,
                    explanation=f"Proportional cut after room/ICU breach, factor {ratio:.4f}.",
                )
            )

        deducted = sum((d.amount for d in deductions), Decimal("0"))
        lines.append(
            WorksheetLine(
                line_id=line.line_id,
                claimed=line.amount,
                deductions=deductions,
                payable=line.amount - deducted,
            )
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
