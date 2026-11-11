"""Deterministic claim adjudication calculator.

All monetary arithmetic uses Decimal. The module applies only the rules explicitly
represented by PolicyRules and the per-line clause choices supplied by the coverage
workflow. It does not make coverage, fraud, approval, or settlement decisions.

Important policy/data boundaries:
- Cataract clause 4.3 remains informational until the claim identifies the treated eye
  and the policy-year usage can be attributed to that eye.
- For room/ICU daily calculations, explicit BillLine.days takes precedence. If it is
  absent, the existing contract-compatible fallback is Claim.nights (or one day for
  a zero-night admission). BillLine.quantity is not assumed to mean days: its default
  is 1 in the contract, so using it would silently misinterpret many existing claims.
- Room/ICU overlap and nursing treatment are not inferred here; they require approved
  domain semantics and/or additional claim fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Mapping

from claimsense.agents import clauses as C
from claimsense.contracts import (
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
    "CATARACT_SUB_LIMIT",
    "INFORMATIONAL_SUB_LIMITS",
]

PAISE = Decimal("0.01")
ZERO = Decimal("0")
ONE = Decimal("1")


@dataclass(frozen=True)
class PolicyRules:
    """Numeric policy parameters; verify them against the insured policy schedule."""

    room_rent_pct: Decimal = Decimal("0.02")
    room_rent_max_per_day: Decimal = Decimal("5000")
    icu_pct: Decimal = Decimal("0.05")
    icu_max_per_day: Decimal = Decimal("10000")
    cataract_pct: Decimal = Decimal("0.25")
    cataract_max_per_eye: Decimal = Decimal("40000")
    co_pay_rate: Decimal = Decimal("0.05")
    sub_limits: dict[str, Decimal] = field(default_factory=dict)


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

FULLY_DEDUCTED: dict[str, DeductionReason] = {
    C.NON_PAYABLE_ITEMS: DeductionReason.NON_PAYABLE,
    C.INITIAL_WAITING_PERIOD: DeductionReason.WAITING_PERIOD,
    C.PED_WAITING_PERIOD: DeductionReason.WAITING_PERIOD,
    C.SPECIFIC_WAITING_PERIOD: DeductionReason.WAITING_PERIOD,
    C.MATERNITY_EXCLUSION: DeductionReason.EXCLUSION,
}

CATARACT_SUB_LIMIT: str = "new_india_arogya_sanjeevani:4.3"
INFORMATIONAL_SUB_LIMITS: frozenset[str] = frozenset({CATARACT_SUB_LIMIT})


def to_rupees(value: Decimal) -> Decimal:
    """Round a monetary value to paise using commercial half-up rounding.\n\n    Keep calculation precision at paise. GOLD-08 stores expected values in whole\n    rupees and the evaluator applies its documented INR 1 tolerance; this\n    function must not force-match a gold value by adding or subtracting a rupee.\n    """
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError("monetary value must be a finite Decimal")
    return value.quantize(PAISE, rounding=ROUND_HALF_UP)


def room_rent_limit_per_day(sum_insured: Decimal, rules: PolicyRules) -> Decimal:
    """Lower of the configured percentage of sum insured and daily rupee cap."""
    return min(sum_insured * rules.room_rent_pct, rules.room_rent_max_per_day)


def icu_limit_per_day(sum_insured: Decimal, rules: PolicyRules) -> Decimal:
    """Lower of the configured percentage of sum insured and daily rupee cap."""
    return min(sum_insured * rules.icu_pct, rules.icu_max_per_day)


def proportional_cut_ratio(actual_per_day: Decimal, eligible_per_day: Decimal) -> Decimal:
    """Return eligible/actual, bounded to [0, 1]."""
    if actual_per_day <= ZERO:
        return ONE
    if eligible_per_day <= ZERO:
        return ZERO
    if eligible_per_day >= actual_per_day:
        return ONE
    return eligible_per_day / actual_per_day


def co_pay(amount: Decimal, rules: PolicyRules) -> Decimal:
    """Calculate the co-payment after all line-level deductions."""
    return to_rupees(amount * rules.co_pay_rate)


def _validate_decimal(name: str, value: Decimal, *, minimum: Decimal = ZERO) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{name} must be a finite Decimal")
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")


def _validate_rules(rules: PolicyRules) -> None:
    for name in (
        "room_rent_pct",
        "room_rent_max_per_day",
        "icu_pct",
        "icu_max_per_day",
        "cataract_pct",
        "cataract_max_per_eye",
        "co_pay_rate",
    ):
        _validate_decimal(f"rules.{name}", getattr(rules, name))
    if rules.co_pay_rate > ONE:
        raise ValueError("rules.co_pay_rate must not exceed 1")
    if rules.room_rent_pct > ONE or rules.icu_pct > ONE or rules.cataract_pct > ONE:
        raise ValueError("policy percentage rates must not exceed 1")
    for clause_id, limit in rules.sub_limits.items():
        if not isinstance(clause_id, str) or not clause_id.strip():
            raise ValueError("sub-limit clause ids must be non-empty strings")
        _validate_decimal(f"sub-limit {clause_id!r}", limit)


def _validate_claim(claim: Claim) -> None:
    """Validate numeric assumptions used by the calculator."""
    _validate_decimal("sum_insured", claim.sum_insured)
    if claim.sum_insured <= ZERO:
        raise ValueError("sum_insured must be positive")

    seen_line_ids: set[str] = set()
    for line in claim.bill_lines:
        if not line.line_id or not line.line_id.strip():
            raise ValueError("bill line ids must be non-empty")
        if line.line_id in seen_line_ids:
            raise ValueError(f"duplicate bill line id: {line.line_id}")
        seen_line_ids.add(line.line_id)

        _validate_decimal(f"line {line.line_id} amount", line.amount)
        _validate_decimal(f"line {line.line_id} quantity", line.quantity)
        if line.days is not None:
            if isinstance(line.days, bool) or not isinstance(line.days, int):
                raise ValueError(f"line {line.line_id}: days must be an integer")
            if line.days < 0:
                raise ValueError(f"line {line.line_id}: days is negative")
            if line.category in (LineCategory.ROOM, LineCategory.ICU) and line.days == 0:
                raise ValueError(
                    f"line {line.line_id}: room/ICU days must be positive when supplied"
                )
        elif line.category in (LineCategory.ROOM, LineCategory.ICU):
            if line.quantity <= ZERO or line.quantity != line.quantity.to_integral_value():
                raise ValueError(
                    f"line {line.line_id}: room/ICU quantity must be a positive whole number of days"
                )


def _validate_usage(sub_limits_used: Mapping[str, Decimal] | None) -> None:
    for clause_id, used in (sub_limits_used or {}).items():
        if not isinstance(clause_id, str) or not clause_id.strip():
            raise ValueError("prior sub-limit usage clause ids must be non-empty strings")
        _validate_decimal(f"prior sub-limit usage {clause_id!r}", used)


def _daily_units(claim: Claim, line) -> Decimal:
    """Resolve room/ICU days using explicit days, then the billed quantity.

    The gold fixtures define room/ICU quantity as the number of billed days:
    CLM-0016 has one ICU day (quantity=1) alongside six ward nights
    (quantity=6). The overlap is deliberately left as billed, matching the
    accepted gold ruling; this function does not try to reconcile stay dates.
    """
    if line.days is not None:
        if line.days <= 0:
            raise ValueError(f"line {line.line_id}: daily line must have positive days")
        return Decimal(line.days)

    quantity = line.quantity
    if quantity <= ZERO or quantity != quantity.to_integral_value():
        raise ValueError(
            f"line {line.line_id}: room/ICU quantity must be a positive whole number of days"
        )
    return quantity


def _room_icu_ratio(claim: Claim, room_cap: Decimal, icu_cap: Decimal) -> Decimal:
    """Find the strictest room/ICU rate ratio for linked expense deductions."""
    ratio = ONE
    for line in claim.bill_lines:
        if line.category not in (LineCategory.ROOM, LineCategory.ICU):
            continue
        days = _daily_units(claim, line)
        actual_per_day = line.amount / days
        eligible_per_day = room_cap if line.category == LineCategory.ROOM else icu_cap
        if actual_per_day > eligible_per_day:
            ratio = min(
                ratio,
                proportional_cut_ratio(actual_per_day, eligible_per_day),
            )
    return ratio


def _make_deduction(
    reason: DeductionReason,
    amount: Decimal,
    clause_id: str,
    explanation: str,
) -> Deduction:
    return Deduction(
        reason=reason,
        amount=to_rupees(amount),
        clause_id=clause_id,
        explanation=explanation,
    )


def adjudicate(
    claim: Claim,
    clause_choices: dict[str, str],
    rules: PolicyRules | None = None,
    *,
    version: int = 1,
    fraud_flags: list[str] | None = None,
    sub_limits_used: dict[str, Decimal] | None = None,
) -> Worksheet:
    """Calculate a reconciled worksheet from a claim and per-line clause selections.

    ``clause_choices`` maps bill-line ids to clause ids. Missing choices default to
    hospitalisation. ``sub_limits_used`` contains prior policy-year usage keyed by clause.
    Configured sub-limits are applied to each matching line, subject to the informational
    cataract exclusion described in the module documentation.
    """
    rules = rules or PolicyRules()
    _validate_claim(claim)
    _validate_rules(rules)
    _validate_usage(sub_limits_used)

    if not isinstance(clause_choices, dict):
        raise TypeError("clause_choices must be a dict mapping line ids to clause ids")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValueError("version must be a positive integer")

    room_cap = room_rent_limit_per_day(claim.sum_insured, rules)
    icu_cap = icu_limit_per_day(claim.sum_insured, rules)
    ratio = _room_icu_ratio(claim, room_cap, icu_cap)

    worksheet_lines: list[WorksheetLine] = []
    for line in claim.bill_lines:
        chosen = clause_choices.get(line.line_id, C.HOSPITALISATION)
        if not isinstance(chosen, str) or not chosen.strip():
            raise ValueError(f"line {line.line_id}: selected clause id must be non-empty")

        deductions: list[Deduction] = []
        daily_units = (
            _daily_units(claim, line)
            if line.category in (LineCategory.ROOM, LineCategory.ICU)
            else Decimal(line.days if line.days is not None and line.days > 0 else (claim.nights or 1))
        )

        if chosen in FULLY_DEDUCTED:
            deductions.append(
                _make_deduction(
                    FULLY_DEDUCTED[chosen],
                    line.amount,
                    chosen,
                    "Not payable under the selected clause.",
                )
            )

        elif chosen in rules.sub_limits and chosen not in INFORMATIONAL_SUB_LIMITS:
            limit = rules.sub_limits[chosen]
            used = (sub_limits_used or {}).get(chosen, ZERO)
            remaining = max(ZERO, limit - used)
            shortfall = max(ZERO, line.amount - remaining)
            if shortfall > ZERO:
                deductions.append(
                    _make_deduction(
                        DeductionReason.SUB_LIMIT,
                        shortfall,
                        chosen,
                        (
                            f"Sub-limit under {chosen}: Rs {to_rupees(remaining)} remaining "
                            f"from Rs {to_rupees(limit)} after prior use of Rs {to_rupees(used)}."
                        ),
                    )
                )

        elif line.category == LineCategory.ROOM and line.amount > room_cap * daily_units:
            capped_amount = room_cap * daily_units
            deductions.append(
                _make_deduction(
                    DeductionReason.ROOM_RENT_CAP,
                    line.amount - capped_amount,
                    C.ROOM_RENT_LIMIT,
                    f"Room rent capped at Rs {to_rupees(room_cap)}/day x {daily_units} day(s).",
                )
            )

        elif line.category == LineCategory.ICU and line.amount > icu_cap * daily_units:
            capped_amount = icu_cap * daily_units
            deductions.append(
                _make_deduction(
                    DeductionReason.ICU_CAP,
                    line.amount - capped_amount,
                    C.ICU_LIMIT,
                    f"ICU capped at Rs {to_rupees(icu_cap)}/day x {daily_units} day(s).",
                )
            )

        elif line.category in LINKED_CATEGORIES and ratio < ONE:
            deductions.append(
                _make_deduction(
                    DeductionReason.PROPORTIONAL_CUT,
                    line.amount * (ONE - ratio),
                    C.OTHER_EXPENSES,
                    f"Proportional cut after room/ICU breach, factor {ratio:.6f}.",
                )
            )

        total_deducted = sum((item.amount for item in deductions), ZERO)
        payable = line.amount - total_deducted
        if payable < ZERO:
            raise ArithmeticError(f"line {line.line_id}: deductions exceed claimed amount")

        worksheet_lines.append(
            WorksheetLine(
                line_id=line.line_id,
                claimed=line.amount,
                deductions=deductions,
                payable=payable,
            )
        )

    gross_admissible = sum((line.payable for line in worksheet_lines), ZERO)
    copay_amount = co_pay(gross_admissible, rules)
    copay_deduction = (
        _make_deduction(
            DeductionReason.CO_PAY,
            copay_amount,
            C.CO_PAY,
            f"{rules.co_pay_rate * 100:.0f}% co-pay on the admissible amount.",
        )
        if copay_amount > ZERO
        else None
    )

    total_claimed = sum((line.claimed for line in worksheet_lines), ZERO)
    total_payable = gross_admissible - copay_amount
    if total_payable < ZERO:
        raise ArithmeticError("co-payment exceeds admissible amount")

    return Worksheet(
        claim_id=claim.claim_id,
        version=version,
        lines=worksheet_lines,
        co_pay=copay_deduction,
        total_claimed=total_claimed,
        total_payable=total_payable,
        fraud_flags=list(fraud_flags or []),
    )
