"""Adjudication calculator — Signature A. Owner: Tools & Security (T15).

Every rupee is computed here, in Decimal, never by a model.

Workflow: the Domain Lead and Eval write hand-worked cases from the downloaded wording into
tests/calc/test_adjudication.py FIRST; then implement until they pass.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from claimsense.contracts import Claim, Worksheet

PAISE = Decimal("0.01")


@dataclass(frozen=True)
class PolicyRules:
    """Numbers from New India Assurance's Arogya Sanjeevani CIS (March 2025), as quoted in the
    capstone brief. VERIFY each against the exact wording you downloaded and cite its clause."""

    room_rent_pct: Decimal = Decimal("0.02")  # of sum insured, per day
    room_rent_max_per_day: Decimal = Decimal("5000")
    icu_pct: Decimal = Decimal("0.05")
    icu_max_per_day: Decimal = Decimal("10000")
    cataract_pct: Decimal = Decimal("0.25")
    cataract_max_per_eye: Decimal = Decimal("40000")
    co_pay_rate: Decimal = Decimal("0.05")


def to_rupees(value: Decimal) -> Decimal:
    return value.quantize(PAISE, rounding=ROUND_HALF_UP)


def room_rent_limit_per_day(sum_insured: Decimal, rules: PolicyRules) -> Decimal:
    raise NotImplementedError("T15")


def icu_limit_per_day(sum_insured: Decimal, rules: PolicyRules) -> Decimal:
    raise NotImplementedError("T15")


def proportional_cut_ratio(actual_room_per_day: Decimal, eligible_room_per_day: Decimal) -> Decimal:
    """Ratio applied to linked charges after a room-rent breach. Confirm which line categories
    count as 'linked' from the wording and record the clause."""
    raise NotImplementedError("T15")


def co_pay(amount: Decimal, rules: PolicyRules) -> Decimal:
    raise NotImplementedError("T15")


def adjudicate(claim: Claim, clause_choices: dict[str, str], rules: PolicyRules) -> Worksheet:
    """clause_choices maps line_id -> clause_id selected by the coverage analyst."""
    raise NotImplementedError("T15")
