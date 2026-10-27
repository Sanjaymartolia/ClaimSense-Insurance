"""A claim packet as the extraction agent returns it."""

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, Field, model_validator

Money = Annotated[Decimal, Field(ge=0, decimal_places=2)]


class RoomCategory(StrEnum):
    GENERAL_WARD = "general_ward"
    SHARED = "shared"
    SINGLE_PRIVATE = "single_private"
    ICU = "icu"


class LineCategory(StrEnum):
    ROOM = "room"
    ICU = "icu"
    NURSING = "nursing"
    DOCTOR_FEES = "doctor_fees"
    OT = "ot"
    MEDICINES = "medicines"
    CONSUMABLES = "consumables"
    INVESTIGATIONS = "investigations"
    PROCEDURE = "procedure"
    OTHER = "other"


class SourceSpan(BaseModel):
    """Where in which uploaded document a value was read from."""

    document: str
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    text: str


class BillLine(BaseModel):
    line_id: str
    description: str
    category: LineCategory
    amount: Money
    quantity: Decimal = Decimal("1")
    days: int | None = Field(default=None, ge=0)
    source: SourceSpan


class Claim(BaseModel):
    claim_id: str
    policy_number: str
    patient_pseudonym: str  # never a real name
    admission_date: date
    discharge_date: date
    diagnosis: str
    procedure: str | None = None
    room_category: RoomCategory
    sum_insured: Money
    bill_lines: list[BillLine]
    bill_total: Money

    @model_validator(mode="after")
    def _dates_in_order(self) -> "Claim":
        if self.discharge_date < self.admission_date:
            raise ValueError("discharge_date is before admission_date")
        return self

    @property
    def nights(self) -> int:
        return (self.discharge_date - self.admission_date).days

    def lines_total(self) -> Decimal:
        return sum((line.amount for line in self.bill_lines), Decimal("0"))

    def total_matches_lines(self) -> bool:
        """A bill whose total differs from its lines is a red-team case (L15)."""
        return self.lines_total() == self.bill_total
