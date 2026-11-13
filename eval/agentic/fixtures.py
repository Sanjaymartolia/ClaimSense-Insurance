"""Small synthetic claims for cases that need a controlled path. No real data."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from claimsense.agents import PolicyInfo
from claimsense.contracts import Claim


def span(text: str = "row") -> dict:
    return {"document": "bill.txt", "start": 0, "end": len(text), "text": text}


def _line(line_id: str, desc: str, category: str, amount: str, days: int | None = None) -> dict:
    return {
        "line_id": line_id,
        "description": desc,
        "category": category,
        "amount": amount,
        "days": days,
        "source": span(),
    }


def claim_dict(claim_id: str = "CLM-AG-001") -> dict:
    """Three nights in a private room above the 2% cap, on a Rs 2,00,000 policy."""
    return {
        "claim_id": claim_id,
        "policy_number": "POL-AG",
        "patient_pseudonym": "PT-AG-1",
        "admission_date": "2026-05-10",
        "discharge_date": "2026-05-13",
        "diagnosis": "synthetic appendicitis",
        "procedure": "Appendectomy",
        "room_category": "single_private",
        "sum_insured": "200000.00",
        "bill_lines": [
            _line("L1", "Private room", "room", "21000.00", 3),
            _line("L2", "Surgeon fees", "doctor_fees", "15000.00"),
            _line("L3", "OT charges", "ot", "30000.00"),
            _line("L4", "Pharmacy", "medicines", "8000.00"),
            _line("L5", "Gloves and masks", "consumables", "2000.00"),
        ],
        "bill_total": "76000.00",
    }


def packet(claim_id: str = "CLM-AG-001", documents: dict | None = None) -> dict:
    return {"claim_id": claim_id, "claim": claim_dict(claim_id), "documents": documents or {}}


def long_bill_packet(n_lines: int, claim_id: str = "CLM-AG-LONG") -> dict:
    claim = claim_dict(claim_id)
    claim["bill_lines"] = [
        _line(f"L{i}", f"Pharmacy item {i}", "medicines", "100.00") for i in range(1, n_lines + 1)
    ]
    claim["bill_total"] = f"{100 * n_lines}.00"
    return {"claim_id": claim_id, "claim": claim, "documents": {}}


def claim() -> Claim:
    return Claim.model_validate(claim_dict())


def policy(first_inception: date = date(2024, 1, 1)) -> PolicyInfo:
    return PolicyInfo(
        policy_number="POL-AG",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 12, 31),
        first_inception=first_inception,
        sum_insured=Decimal("200000"),
        insured_pseudonym="PT-AG-1",
    )


def inadmissible_policy() -> PolicyInfo:
    """Admission falls inside the 30-day initial waiting period."""
    return policy(first_inception=date(2026, 5, 1))
