"""The memory policy (docs/memory-policy.md), checked against claims-db. Synthetic data only."""

import sqlite3
from datetime import date
from decimal import Decimal

import pytest

from claimsense.agents import clauses as C
from claimsense.agents.services import line_fingerprint
from claimsense.contracts import Claim, Deduction, DeductionReason, Worksheet, WorksheetLine
from claimsense.memory import HistoryStore

DIAGNOSIS = "Senile cataract, left eye"
PROCEDURE = "Phacoemulsification with IOL"
LINES = (
    ("Cataract surgery package - left eye", "procedure", "50000.00"),
    ("Pharmacy - eye drops", "medicines", "2000.00"),
)
DESCRIPTIONS = tuple(desc for desc, _, _ in LINES)


def make_claim(claim_id="CLM-T31-001", policy="POL-T31-A", admitted=date(2026, 5, 10)) -> Claim:
    lines = [
        {
            "line_id": f"L{n}",
            "description": desc,
            "category": category,
            "amount": amount,
            "source": {"document": "bill.txt", "start": 0, "end": len(desc), "text": desc},
        }
        for n, (desc, category, amount) in enumerate(LINES, start=1)
    ]
    return Claim.model_validate(
        {
            "claim_id": claim_id,
            "policy_number": policy,
            "patient_pseudonym": "PT-T31",
            "admission_date": admitted,
            "discharge_date": admitted,
            "diagnosis": DIAGNOSIS,
            "procedure": PROCEDURE,
            "room_category": "general_ward",
            "sum_insured": "300000.00",
            "bill_lines": lines,
            "bill_total": "52000.00",
        }
    )


def sub_limit_worksheet(claim: Claim) -> Worksheet:
    """Cataract limit 40,000 on a 50,000 package: 10,000 deducted, 40,000 of the limit used."""
    cut = Deduction(
        reason=DeductionReason.SUB_LIMIT,
        amount=Decimal("10000.00"),
        clause_id=C.OTHER_EXPENSES,
        explanation="Cataract sub-limit.",
    )
    lines = [
        WorksheetLine(
            line_id="L1", claimed=Decimal("50000.00"), deductions=[cut], payable=Decimal("40000.00")
        ),
        WorksheetLine(line_id="L2", claimed=Decimal("2000.00"), payable=Decimal("2000.00")),
    ]
    return Worksheet(
        claim_id=claim.claim_id,
        lines=lines,
        total_claimed=Decimal("52000.00"),
        total_payable=Decimal("42000.00"),
    )


def test_claims_db_is_the_history_store(db):
    assert isinstance(db, HistoryStore)


def test_recorded_bill_lines_come_back_as_fingerprints(db):
    claim = make_claim()
    db.record_history(claim)

    [past] = db.claim_history(claim.policy_number)
    expected = {line_fingerprint(claim, line.description, line.amount) for line in claim.bill_lines}
    assert past.claim_id == claim.claim_id
    assert set(past.bill_fingerprints) == expected


def test_same_bill_resubmitted_under_new_claim_id_is_caught(db):
    db.record_history(make_claim("CLM-T31-001"))
    resubmitted = make_claim("CLM-T31-002")

    seen = {
        fp for past in db.claim_history(resubmitted.policy_number) for fp in past.bill_fingerprints
    }
    assert all(
        line_fingerprint(resubmitted, line.description, line.amount) in seen
        for line in resubmitted.bill_lines
    )


def test_recording_a_claim_twice_adds_nothing(db):
    claim = make_claim()
    db.record_history(claim)
    db.record_history(claim)

    [past] = db.claim_history(claim.policy_number)
    assert len(past.bill_fingerprints) == len(claim.bill_lines)


def test_history_is_scoped_to_one_policy(db):
    db.record_history(make_claim(policy="POL-T31-A"))
    assert db.claim_history("POL-T31-B") == []


def test_no_health_details_are_stored(db):
    claim = make_claim()
    db.record_history(claim, sub_limit_worksheet(claim))

    conn = sqlite3.connect(db.path)
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
    stored = " ".join(
        str(value).lower()
        for table in tables
        for row in conn.execute(f"SELECT * FROM {table}")  # noqa: S608 - names from sqlite_master
        for value in row
    )
    conn.close()
    for secret in (DIAGNOSIS, PROCEDURE, *DESCRIPTIONS):
        assert secret.lower() not in stored


def test_sub_limit_deduction_is_recorded_under_its_clause(db):
    claim = make_claim()
    db.record_history(claim, sub_limit_worksheet(claim))

    [past] = db.claim_history(claim.policy_number)
    assert set(past.sub_limits_used) == {C.OTHER_EXPENSES}


@pytest.mark.xfail(
    strict=True,
    reason="claims-db stores the amount deducted, not the amount used "
    "of the sub-limit (ADR-0005, Tools & Security to fix)",
)
def test_sub_limit_used_is_the_amount_paid_against_it(db):
    claim = make_claim()
    db.record_history(claim, sub_limit_worksheet(claim))

    [past] = db.claim_history(claim.policy_number)
    assert past.sub_limits_used[C.OTHER_EXPENSES] == Decimal("40000.00")
