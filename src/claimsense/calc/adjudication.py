"""Deterministic claim adjudication calculator.

Implements ADR-0009 DEC-01/DEC-04 and the CLM-0016 ICU ruling. Monetary
arithmetic is Decimal; medicines are never proportionally reduced.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Mapping

from claimsense.agents import clauses as C
from claimsense.contracts import (
    Claim, Deduction, DeductionReason, LineCategory, Worksheet, WorksheetLine,
)

__all__ = [
    "PolicyRules", "PAISE", "to_rupees", "room_rent_limit_per_day",
    "icu_limit_per_day", "proportional_cut_ratio", "co_pay", "adjudicate",
    "CATARACT_SUB_LIMIT", "INFORMATIONAL_SUB_LIMITS",
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


# Nursing is part of the all-inclusive ward cap, not a Note 4.1.1(b) linked category.
LINKED_CATEGORIES: frozenset[LineCategory] = frozenset({
    LineCategory.DOCTOR_FEES, LineCategory.OT, LineCategory.INVESTIGATIONS,
    LineCategory.PROCEDURE, LineCategory.OTHER,
})
FULLY_DEDUCTED: dict[str, DeductionReason] = {
    C.NON_PAYABLE_ITEMS: DeductionReason.NON_PAYABLE,
    C.INITIAL_WAITING_PERIOD: DeductionReason.WAITING_PERIOD,
    C.PED_WAITING_PERIOD: DeductionReason.WAITING_PERIOD,
    C.SPECIFIC_WAITING_PERIOD: DeductionReason.WAITING_PERIOD,
    C.MATERNITY_EXCLUSION: DeductionReason.EXCLUSION,
}
CATARACT_SUB_LIMIT = "new_india_arogya_sanjeevani:4.3"
INFORMATIONAL_SUB_LIMITS = frozenset({CATARACT_SUB_LIMIT})


def to_rupees(value: Decimal) -> Decimal:
    """Round money to paise using commercial half-up rounding."""
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError("monetary value must be a finite Decimal")
    return value.quantize(PAISE, rounding=ROUND_HALF_UP)


def room_rent_limit_per_day(sum_insured: Decimal, rules: PolicyRules) -> Decimal:
    return min(sum_insured * rules.room_rent_pct, rules.room_rent_max_per_day)


def icu_limit_per_day(sum_insured: Decimal, rules: PolicyRules) -> Decimal:
    return min(sum_insured * rules.icu_pct, rules.icu_max_per_day)


def proportional_cut_ratio(actual_per_day: Decimal, eligible_per_day: Decimal) -> Decimal:
    if actual_per_day <= ZERO:
        return ONE
    if eligible_per_day <= ZERO:
        return ZERO
    return min(ONE, eligible_per_day / actual_per_day)


def co_pay(amount: Decimal, rules: PolicyRules) -> Decimal:
    return to_rupees(amount * rules.co_pay_rate)


def _validate_decimal(name: str, value: Decimal, *, minimum: Decimal = ZERO) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{name} must be a finite Decimal")
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")


def _validate_rules(rules: PolicyRules) -> None:
    for name in ("room_rent_pct", "room_rent_max_per_day", "icu_pct", "icu_max_per_day",
                 "cataract_pct", "cataract_max_per_eye", "co_pay_rate"):
        _validate_decimal(f"rules.{name}", getattr(rules, name))
    if rules.co_pay_rate > ONE or any(getattr(rules, n) > ONE for n in
                                      ("room_rent_pct", "icu_pct", "cataract_pct")):
        raise ValueError("policy percentage rates must not exceed 1")
    for clause_id, limit in rules.sub_limits.items():
        if not isinstance(clause_id, str) or not clause_id.strip():
            raise ValueError("sub-limit clause ids must be non-empty strings")
        _validate_decimal(f"sub-limit {clause_id!r}", limit)


def _validate_claim(claim: Claim) -> None:
    _validate_decimal("sum_insured", claim.sum_insured)
    if claim.sum_insured <= ZERO:
        raise ValueError("sum_insured must be positive")
    seen: set[str] = set()
    for line in claim.bill_lines:
        if not line.line_id or not line.line_id.strip():
            raise ValueError("bill line ids must be non-empty")
        if line.line_id in seen:
            raise ValueError(f"duplicate bill line id: {line.line_id}")
        seen.add(line.line_id)
        _validate_decimal(f"line {line.line_id} amount", line.amount)
        _validate_decimal(f"line {line.line_id} quantity", line.quantity)
        if line.days is not None:
            if isinstance(line.days, bool) or not isinstance(line.days, int) or line.days < 0:
                raise ValueError(f"line {line.line_id}: days must be a non-negative integer")
            if line.category in (LineCategory.ROOM, LineCategory.ICU) and line.days == 0:
                raise ValueError(f"line {line.line_id}: room/ICU days must be positive")
        elif line.category in (LineCategory.ROOM, LineCategory.ICU):
            if line.quantity <= ZERO or line.quantity != line.quantity.to_integral_value():
                raise ValueError(f"line {line.line_id}: room/ICU quantity must be positive whole days")


def _validate_usage(usage: Mapping[str, Decimal] | None) -> None:
    for clause_id, used in (usage or {}).items():
        if not isinstance(clause_id, str) or not clause_id.strip():
            raise ValueError("prior sub-limit usage clause ids must be non-empty strings")
        _validate_decimal(f"prior sub-limit usage {clause_id!r}", used)


def _daily_units(claim: Claim, line) -> Decimal:
    """Resolve room/ICU days; explicit days, then quantity, then contract stay fallback.

    ADR-0009 CLM-0016 fixture bills five ward nights plus one ICU day; overlap is
    left as billed and this function does not infer/reconcile stay dates.
    """
    if line.days is not None:
        if line.days <= 0:
            raise ValueError(f"line {line.line_id}: daily line must have positive days")
        return Decimal(line.days)
    if line.quantity > ZERO and line.quantity == line.quantity.to_integral_value():
        return line.quantity
    return Decimal(claim.nights or 1)


def _room_ratio(claim: Claim, room_cap: Decimal, excluded: set[str]) -> tuple[Decimal, Decimal]:
    """Return all-inclusive ward ratio and total ward days (DEC-01)."""
    ward_days = sum((_daily_units(claim, line) for line in claim.bill_lines
                     if line.category == LineCategory.ROOM and line.line_id not in excluded), ZERO)
    ward_total = sum((line.amount for line in claim.bill_lines
                      if line.category in (LineCategory.ROOM, LineCategory.NURSING)
                      and line.line_id not in excluded), ZERO)
    if ward_days <= ZERO:
        return ONE, ZERO
    rate = ward_total / ward_days
    return (min(ONE, room_cap / rate) if rate > room_cap else ONE), ward_days


def _make_deduction(reason: DeductionReason, amount: Decimal, clause_id: str,
                    explanation: str) -> Deduction:
    return Deduction(reason=reason, amount=to_rupees(amount), clause_id=clause_id,
                     explanation=explanation)


def adjudicate(claim: Claim, clause_choices: dict[str, str], rules: PolicyRules | None = None,
               *, version: int = 1, fraud_flags: list[str] | None = None,
               sub_limits_used: dict[str, Decimal] | None = None) -> Worksheet:
    """Calculate a reconciled worksheet using ADR-0009 ordering and ratios."""
    # Local import avoids services <-> adjudication module import cycle.
    from claimsense.agents.services import in_bill_duplicates

    rules = rules or PolicyRules()
    _validate_claim(claim)
    _validate_rules(rules)
    _validate_usage(sub_limits_used)
    if not isinstance(clause_choices, dict):
        raise TypeError("clause_choices must be a dict mapping line ids to clause ids")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValueError("version must be a positive integer")

    repeats = in_bill_duplicates(claim)
    repeated_ids = set(repeats)
    counted = [line for line in claim.bill_lines if line.line_id not in repeated_ids]
    room_cap = room_rent_limit_per_day(claim.sum_insured, rules)
    icu_cap = icu_limit_per_day(claim.sum_insured, rules)
    room_ratio, ward_days = _room_ratio(claim, room_cap, repeated_ids)

    overall_ratio = room_ratio
    for line in counted:
        if line.category == LineCategory.ICU:
            days = _daily_units(claim, line)
            rate = line.amount / days
            if rate > icu_cap:
                overall_ratio = min(overall_ratio, proportional_cut_ratio(rate, icu_cap))

    worksheet_lines: list[WorksheetLine] = []
    for line in claim.bill_lines:
        chosen = clause_choices.get(line.line_id, C.HOSPITALISATION)
        if not isinstance(chosen, str) or not chosen.strip():
            raise ValueError(f"line {line.line_id}: selected clause id must be non-empty")
        deductions: list[Deduction] = []
        daily_units = (_daily_units(claim, line) if line.category in
                       (LineCategory.ROOM, LineCategory.ICU) else
                       Decimal(line.days if line.days is not None and line.days > 0
                               else (claim.nights or 1)))

        # ADR-0009 precedence: duplicate first, even before exclusions or sub-limits.
        if line.line_id in repeats:
            first_id = repeats[line.line_id]
            deductions.append(_make_deduction(
                DeductionReason.OTHER, line.amount, C.OPERATIVE,
                f"Repeats {first_id} in the same bill; clause 2 indemnifies only expenses incurred.",
            ))
        elif chosen in FULLY_DEDUCTED:
            deductions.append(_make_deduction(FULLY_DEDUCTED[chosen], line.amount, chosen,
                                              "Not payable under the selected clause."))
        elif chosen in rules.sub_limits and chosen not in INFORMATIONAL_SUB_LIMITS:
            limit = rules.sub_limits[chosen]
            used = (sub_limits_used or {}).get(chosen, ZERO)
            remaining = max(ZERO, limit - used)
            shortfall = max(ZERO, line.amount - remaining)
            if shortfall > ZERO:
                deductions.append(_make_deduction(
                    DeductionReason.SUB_LIMIT, shortfall, chosen,
                    f"Sub-limit under {chosen}: Rs {to_rupees(remaining)} remaining from "
                    f"Rs {to_rupees(limit)} after prior use of Rs {to_rupees(used)}.",
                ))
        elif line.category in (LineCategory.ROOM, LineCategory.NURSING) and room_ratio < ONE:
            deductions.append(_make_deduction(
                DeductionReason.ROOM_RENT_CAP, line.amount * (ONE - room_ratio),
                C.ROOM_RENT_LIMIT,
                f"Room, boarding and nursing share Rs {to_rupees(room_cap)}/day x "
                f"{ward_days} ward day(s); factor {room_ratio:.6f}.",
            ))
        elif line.category == LineCategory.ICU and line.amount > icu_cap * daily_units:
            deductions.append(_make_deduction(
                DeductionReason.ICU_CAP, line.amount - icu_cap * daily_units, C.ICU_LIMIT,
                f"ICU capped at Rs {to_rupees(icu_cap)}/day x {daily_units} day(s).",
            ))
        elif line.category in LINKED_CATEGORIES and overall_ratio < ONE:
            deductions.append(_make_deduction(
                DeductionReason.PROPORTIONAL_CUT, line.amount * (ONE - overall_ratio),
                C.OTHER_EXPENSES,
                f"Proportional cut after room/ICU breach, factor {overall_ratio:.6f}.",
            ))
        # Medicines intentionally never receive the Note 4.1.1(b) proportional cut.

        total_deducted = sum((d.amount for d in deductions), ZERO)
        payable = line.amount - total_deducted
        if payable < ZERO:
            raise ArithmeticError(f"line {line.line_id}: deductions exceed claimed amount")
        worksheet_lines.append(WorksheetLine(line_id=line.line_id, claimed=line.amount,
                                             deductions=deductions, payable=payable))

    gross = sum((line.payable for line in worksheet_lines), ZERO)
    copay_amount = co_pay(gross, rules)
    copay_deduction = (_make_deduction(DeductionReason.CO_PAY, copay_amount, C.CO_PAY,
                                       f"{rules.co_pay_rate * 100:.0f}% co-pay on admissible amount.")
                       if copay_amount > ZERO else None)
    total_claimed = sum((line.claimed for line in worksheet_lines), ZERO)
    total_payable = gross - copay_amount
    if total_payable < ZERO:
        raise ArithmeticError("co-payment exceeds admissible amount")
    return Worksheet(claim_id=claim.claim_id, version=version, lines=worksheet_lines,
                     co_pay=copay_deduction, total_claimed=total_claimed,
                     total_payable=total_payable, fraud_flags=list(fraud_flags or []))
