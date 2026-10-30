"""Shared fixtures: the brief's worked example (3 nights in a private room above the cap)."""

from datetime import date
from decimal import Decimal

import pytest

from claimsense.agents import PolicyInfo, Team, make_stub_services
from claimsense.agents import clauses as C
from claimsense.contracts import ApprovalDecision


def span(text="row"):
    return {"document": "bill.txt", "start": 0, "end": len(text), "text": text}


def room_breach_packet(claim_id="CLM-DEV-001", **over):
    claim = {
        "claim_id": claim_id, "policy_number": "POL-001", "patient_pseudonym": "PT-7731",
        "admission_date": "2026-05-10", "discharge_date": "2026-05-13",
        "diagnosis": "acute appendicitis", "procedure": "Appendectomy",
        "room_category": "single_private", "sum_insured": "200000.00",
        "bill_lines": [
            {"line_id": "L1", "description": "Private room", "category": "room",
             "amount": "21000.00", "days": 3, "source": span()},
            {"line_id": "L2", "description": "Surgeon fees", "category": "doctor_fees",
             "amount": "15000.00", "source": span()},
            {"line_id": "L3", "description": "OT charges", "category": "ot",
             "amount": "30000.00", "source": span()},
            {"line_id": "L4", "description": "Pharmacy", "category": "medicines",
             "amount": "8000.00", "source": span()},
            {"line_id": "L5", "description": "Gloves and masks", "category": "consumables",
             "amount": "2000.00", "source": span()},
        ],
        "bill_total": "76000.00",
    }
    claim.update(over)
    return {"claim_id": claim_id, "claim": claim, "documents": {}}


POLICY = PolicyInfo(policy_number="POL-001", period_start=date(2026, 1, 1),
                    period_end=date(2026, 12, 31), first_inception=date(2024, 1, 1),
                    sum_insured=Decimal("200000"), insured_pseudonym="PT-7731")


@pytest.fixture
def services():
    return make_stub_services(policies={"POL-001": POLICY})


@pytest.fixture
def team(services):
    return Team(services)


def approve(level_ok=("adjudicator", "senior")):
    def reviewer(payload):
        assert payload["level"] in level_ok
        return {"decision": ApprovalDecision.APPROVE, "approver_id": f"{payload['level']}-1"}
    return reviewer


__all__ = ["C", "POLICY", "approve", "room_breach_packet"]
