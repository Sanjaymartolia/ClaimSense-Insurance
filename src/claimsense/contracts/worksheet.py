"""The settlement worksheet: what the adjudicator approves."""

import hashlib
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

from .claim import Money


class DeductionReason(StrEnum):
    ROOM_RENT_CAP = "room_rent_cap"
    PROPORTIONAL_CUT = "proportional_cut"
    ICU_CAP = "icu_cap"
    SUB_LIMIT = "sub_limit"
    NON_PAYABLE = "non_payable"
    WAITING_PERIOD = "waiting_period"
    EXCLUSION = "exclusion"
    CO_PAY = "co_pay"
    OTHER = "other"


class Deduction(BaseModel):
    reason: DeductionReason
    amount: Money
    clause_id: str  # every deduction must cite a clause
    explanation: str


class WorksheetLine(BaseModel):
    line_id: str
    claimed: Money
    deductions: list[Deduction] = Field(default_factory=list)
    payable: Money

    @model_validator(mode="after")
    def _payable_adds_up(self) -> "WorksheetLine":
        deducted = sum((d.amount for d in self.deductions), Decimal("0"))
        if self.claimed - deducted != self.payable:
            raise ValueError(
                f"line {self.line_id}: claimed {self.claimed} - deductions {deducted} "
                f"!= payable {self.payable}"
            )
        return self


class Worksheet(BaseModel):
    claim_id: str
    version: int = Field(default=1, ge=1)
    lines: list[WorksheetLine]
    co_pay: Deduction | None = None
    total_claimed: Money
    total_payable: Money
    fraud_flags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _totals_add_up(self) -> "Worksheet":
        claimed = sum((line.claimed for line in self.lines), Decimal("0"))
        payable = sum((line.payable for line in self.lines), Decimal("0"))
        if self.co_pay is not None:
            payable -= self.co_pay.amount
        if claimed != self.total_claimed:
            raise ValueError(f"total_claimed {self.total_claimed} != sum of lines {claimed}")
        if payable != self.total_payable:
            raise ValueError(f"total_payable {self.total_payable} != computed {payable}")
        return self

    def content_hash(self) -> str:
        """Hash of the exact payload an approval is tied to (L14)."""
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()
