from datetime import date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from claimsense.contracts import (
    ApprovalLevel,
    ApprovalToken,
    BillLine,
    Claim,
    Deduction,
    DeductionReason,
    LineCategory,
    RoomCategory,
    SourceSpan,
    Worksheet,
    WorksheetLine,
)

SPAN = SourceSpan(document="bill.txt", start=0, end=10, text="Room 3 days")


def make_claim(**overrides) -> Claim:
    data = dict(
        claim_id="C-001",
        policy_number="SYN-POL-1",
        patient_pseudonym="P-0001",
        admission_date=date(2026, 3, 1),
        discharge_date=date(2026, 3, 4),
        diagnosis="appendicitis",
        room_category=RoomCategory.SINGLE_PRIVATE,
        sum_insured=Decimal("300000"),
        bill_lines=[
            BillLine(
                line_id="L1",
                description="Room",
                category=LineCategory.ROOM,
                amount=Decimal("21000"),
                days=3,
                source=SPAN,
            ),
            BillLine(
                line_id="L2",
                description="OT charges",
                category=LineCategory.OT,
                amount=Decimal("15000"),
                source=SPAN,
            ),
        ],
        bill_total=Decimal("36000"),
    )
    data.update(overrides)
    return Claim(**data)


def make_worksheet(room_deduction: str = "3000") -> Worksheet:
    ded = Decimal(room_deduction)
    lines = [
        WorksheetLine(
            line_id="L1",
            claimed=Decimal("21000"),
            payable=Decimal("21000") - ded,
            deductions=[
                Deduction(
                    reason=DeductionReason.ROOM_RENT_CAP,
                    amount=ded,
                    clause_id="AS:room",
                    explanation="cap",
                )
            ],
        ),
        WorksheetLine(line_id="L2", claimed=Decimal("15000"), payable=Decimal("15000")),
    ]
    return Worksheet(
        claim_id="C-001",
        lines=lines,
        total_claimed=Decimal("36000"),
        total_payable=Decimal("36000") - ded,
    )


def test_claim_nights_and_totals():
    claim = make_claim()
    assert claim.nights == 3
    assert claim.total_matches_lines()


def test_bill_total_mismatch_is_detectable():
    assert not make_claim(bill_total=Decimal("40000")).total_matches_lines()


def test_discharge_before_admission_rejected():
    with pytest.raises(ValidationError):
        make_claim(discharge_date=date(2026, 2, 1))


def test_worksheet_line_must_add_up():
    with pytest.raises(ValidationError):
        WorksheetLine(line_id="L1", claimed=Decimal("100"), payable=Decimal("90"))


def test_worksheet_totals_must_add_up():
    ws = make_worksheet()
    with pytest.raises(ValidationError):
        Worksheet(
            claim_id="C-001",
            lines=ws.lines,
            total_claimed=Decimal("36000"),
            total_payable=Decimal("36000"),
        )


def test_edit_invalidates_approval():
    ws = make_worksheet("3000")
    token = ApprovalToken(
        claim_id="C-001",
        worksheet_hash=ws.content_hash(),
        level=ApprovalLevel.ADJUDICATOR,
        approver_id="adj-1",
        decided_at=datetime(2026, 3, 5, 10, 0),
    )
    assert token.is_valid_for(ws)
    edited = make_worksheet("2500")
    assert not token.is_valid_for(edited)
