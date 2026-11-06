"""Integration tests for the adjudication engine (``calc/adjudication.py``) against Role 3.

Run from this folder (no install needed)::

    python -m pytest test_adjudication_integration.py -v

The repo's ``claimsense`` package and this output folder are both put on ``sys.path``. The engine
file under test is registered as ``claimsense.calc.adjudication`` so that the Role 3 adapter
``agents.services.real_calculate`` (which imports that exact path) exercises *this* engine — a true
drop-in test, without copying anything into the repository. Override the repo location with
``CLAIMSENSE_SRC=/abs/path/to/ClaimSense-Insurance/src`` if your checkout differs.
"""

from __future__ import annotations

import os
import sys
from decimal import Decimal
from pathlib import Path

import pytest

# --- path bootstrap --------------------------------------------------------------------------
_OUT = Path(__file__).resolve().parent
_SRC = Path(os.environ["CLAIMSENSE_SRC"]) if os.environ.get("CLAIMSENSE_SRC") else (
    _OUT.parent / "ClaimSense-Insurance" / "src"
)
for _p in (str(_SRC), str(_OUT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import adjudication  # the engine under test (this output folder)

# Register the engine as claimsense.calc.adjudication so the Role 3 adapter resolves THIS file.
import claimsense.calc  # real (docstring-only) parent package; does not load the stub submodule

sys.modules["claimsense.calc.adjudication"] = adjudication
claimsense.calc.adjudication = adjudication  # keep the parent-attribute path consistent too

from claimsense.agents import clauses as C  # noqa: E402
from claimsense.agents import services  # noqa: E402
from claimsense.agents.permissions import ToolBelt, ToolPermissionError  # noqa: E402
from claimsense.contracts import AgentName, Claim, DeductionReason, Worksheet  # noqa: E402


# --- fixtures / helpers ----------------------------------------------------------------------
def _span(text: str = "row") -> dict:
    return {"document": "bill.txt", "start": 0, "end": len(text), "text": text}


def room_breach_claim() -> Claim:
    """Brief's worked example: 3 nights in a private room above the 2% cap (SI 200000)."""
    return Claim.model_validate(
        {
            "claim_id": "CLM-DEV-001",
            "policy_number": "POL-001",
            "patient_pseudonym": "PT-7731",
            "admission_date": "2026-05-10",
            "discharge_date": "2026-05-13",
            "diagnosis": "acute appendicitis",
            "procedure": "Appendectomy",
            "room_category": "single_private",
            "sum_insured": "200000.00",
            "bill_lines": [
                {"line_id": "L1", "description": "Private room", "category": "room",
                 "amount": "21000.00", "days": 3, "source": _span()},
                {"line_id": "L2", "description": "Surgeon fees", "category": "doctor_fees",
                 "amount": "15000.00", "source": _span()},
                {"line_id": "L3", "description": "OT charges", "category": "ot",
                 "amount": "30000.00", "source": _span()},
                {"line_id": "L4", "description": "Pharmacy", "category": "medicines",
                 "amount": "8000.00", "source": _span()},
                {"line_id": "L5", "description": "Gloves and masks", "category": "consumables",
                 "amount": "2000.00", "source": _span()},
            ],
            "bill_total": "76000.00",
        }
    )


CHOICES = {"L5": C.NON_PAYABLE_ITEMS}  # consumables non-payable; rest default to hospitalisation


def _line(ws: Worksheet, line_id: str):
    return next(wl for wl in ws.lines if wl.line_id == line_id)


def _financials(ws: Worksheet) -> dict:
    """Money-meaningful projection (ignores explanation wording, which may differ by implementation)."""
    return {
        "total_claimed": ws.total_claimed,
        "total_payable": ws.total_payable,
        "co_pay": (ws.co_pay.reason, ws.co_pay.amount, ws.co_pay.clause_id) if ws.co_pay else None,
        "lines": [
            (wl.line_id, wl.claimed, wl.payable,
             [(d.reason, d.amount, d.clause_id) for d in wl.deductions])
            for wl in ws.lines
        ],
    }


# --- 1. direct execution: structure + hand-worked numbers ------------------------------------
def test_direct_adjudicate_numbers_and_structure():
    ws = adjudication.adjudicate(room_breach_claim(), CHOICES, adjudication.PolicyRules())

    assert isinstance(ws, Worksheet)
    # L1 room: 21000 - 4000*3 = 9000 deducted -> payable 12000
    assert _line(ws, "L1").payable == Decimal("12000.00")
    assert _line(ws, "L1").deductions[0].reason == DeductionReason.ROOM_RENT_CAP
    # L2 / L3 linked: proportional cut by (1 - 4000/7000); medicines exempt
    assert _line(ws, "L2").payable == Decimal("8571.43")
    assert _line(ws, "L3").payable == Decimal("17142.86")
    assert _line(ws, "L3").deductions[0].reason == DeductionReason.PROPORTIONAL_CUT
    assert _line(ws, "L4").payable == Decimal("8000.00")
    assert _line(ws, "L4").deductions == []
    # L5 consumables: non-payable -> fully deducted
    assert _line(ws, "L5").payable == Decimal("0.00")
    assert _line(ws, "L5").deductions[0].reason == DeductionReason.NON_PAYABLE
    # totals + co-pay
    assert ws.total_claimed == Decimal("76000.00")
    assert ws.co_pay is not None and ws.co_pay.amount == Decimal("2285.71")
    assert ws.co_pay.clause_id == C.CO_PAY
    assert ws.total_payable == Decimal("43428.58")
    # every deduction cites a clause
    assert all(d.clause_id for wl in ws.lines for d in wl.deductions)


# --- 2. return type + reconciliation + Decimal ------------------------------------------------
def test_worksheet_reconciles_and_uses_decimal():
    ws = adjudication.adjudicate(room_breach_claim(), CHOICES)

    assert isinstance(ws, Worksheet)
    assert isinstance(ws.total_payable, Decimal)
    for wl in ws.lines:
        deducted = sum((d.amount for d in wl.deductions), Decimal("0"))
        assert wl.claimed - deducted == wl.payable           # line reconciliation
        assert isinstance(wl.payable, Decimal)
    gross = sum((wl.payable for wl in ws.lines), Decimal("0"))
    co = ws.co_pay.amount if ws.co_pay else Decimal("0")
    assert ws.total_payable == gross - co                    # worksheet reconciliation
    assert ws.total_claimed == sum((wl.claimed for wl in ws.lines), Decimal("0"))


# --- 3. drop-in compatibility with services.real_calculate ------------------------------------
def test_real_calculate_is_dropin():
    claim, choices = room_breach_claim(), CHOICES
    via_adapter = services.real_calculate(claim, choices, version=3, fraud_flags=["tariff_outlier"])
    direct = adjudication.adjudicate(claim, choices, adjudication.PolicyRules(),
                                     version=3, fraud_flags=["tariff_outlier"])

    assert isinstance(via_adapter, Worksheet)
    assert via_adapter.version == 3
    assert via_adapter.fraud_flags == ["tariff_outlier"]
    # real_calculate wraps THIS engine, so the full worksheets are identical.
    assert via_adapter.model_dump() == direct.model_dump()


# --- 4a. same money as the repo's development reference (no divergence) ------------------------
def test_matches_reference_calculate_money():
    claim, choices = room_breach_claim(), CHOICES
    ref = services.reference_calculate(claim, choices, version=1, fraud_flags=[])
    mine = adjudication.adjudicate(claim, choices, adjudication.PolicyRules())
    assert _financials(ref) == _financials(mine)


# --- 4b. arguments passed by Coverage and Critic, through the ToolBelt + ACL -------------------
def test_coverage_and_critic_reach_calculate_via_toolbelt():
    svc = services.make_stub_services()
    svc.calculate = services.real_calculate  # production wiring (uses this engine via injection)
    claim, choices = room_breach_claim(), CHOICES
    for agent in (AgentName.COVERAGE, AgentName.CRITIC):
        belt = ToolBelt(agent, svc.registry(), svc.tool_log)
        ws = belt.call("calculate", claim=claim, clause_choices=choices, version=1, fraud_flags=[])
        assert isinstance(ws, Worksheet)
        assert ws.total_payable == Decimal("43428.58")


def test_settlement_agent_cannot_reach_calculate():
    """Permissions unchanged: only coverage/critic may calculate; settlement is denied."""
    svc = services.make_stub_services()
    belt = ToolBelt(AgentName.SETTLEMENT, svc.registry(), svc.tool_log)
    with pytest.raises(ToolPermissionError):
        belt.call("calculate", claim=room_breach_claim(), clause_choices=CHOICES)


# --- 5a. helpers + the cataract assumption ----------------------------------------------------
def test_helpers_and_cataract_assumption():
    rules = adjudication.PolicyRules()
    assert adjudication.room_rent_limit_per_day(Decimal("200000"), rules) == Decimal("4000")
    assert adjudication.icu_limit_per_day(Decimal("300000"), rules) == Decimal("10000")  # capped
    assert adjudication.proportional_cut_ratio(Decimal("7000"), Decimal("4000")) == (
        Decimal("4000") / Decimal("7000")
    )
    assert adjudication.proportional_cut_ratio(Decimal("4000"), Decimal("5000")) == Decimal("1")
    assert adjudication.co_pay(Decimal("1000"), rules) == Decimal("50.00")
    # cataract parameters verified against the policy assumption (25% of SI vs Rs.40,000/eye).
    assert min(Decimal("200000") * rules.cataract_pct, rules.cataract_max_per_eye) == Decimal("40000")
    assert min(Decimal("100000") * rules.cataract_pct, rules.cataract_max_per_eye) == Decimal("25000")


# --- 5b. edge cases ---------------------------------------------------------------------------
def test_rejects_non_positive_sum_insured():
    bad = room_breach_claim().model_copy(update={"sum_insured": Decimal("0")})
    with pytest.raises(ValueError):
        adjudication.adjudicate(bad, CHOICES)


def test_no_breach_claim_only_co_pay():
    claim = Claim.model_validate(
        {
            "claim_id": "CLM-NB-1", "policy_number": "POL-001", "patient_pseudonym": "PT-1",
            "admission_date": "2026-05-10", "discharge_date": "2026-05-12",  # 2 nights
            "diagnosis": "fever", "room_category": "general_ward", "sum_insured": "500000.00",
            "bill_lines": [
                {"line_id": "L1", "description": "Room", "category": "room",
                 "amount": "6000.00", "days": 2, "source": _span()},   # 3000/day <= 5000 cap
                {"line_id": "L2", "description": "Doctor", "category": "doctor_fees",
                 "amount": "4000.00", "source": _span()},
            ],
            "bill_total": "10000.00",
        }
    )
    ws = adjudication.adjudicate(claim, {})
    assert all(wl.deductions == [] for wl in ws.lines)           # no caps breached
    assert ws.co_pay.amount == Decimal("500.00")                 # 5% of 10000
    assert ws.total_payable == Decimal("9500.00")


def test_missing_days_falls_back_to_nights():
    claim = Claim.model_validate(
        {
            "claim_id": "CLM-ND-1", "policy_number": "POL-001", "patient_pseudonym": "PT-1",
            "admission_date": "2026-05-10", "discharge_date": "2026-05-13",  # 3 nights
            "diagnosis": "x", "room_category": "single_private", "sum_insured": "200000.00",
            "bill_lines": [
                {"line_id": "L1", "description": "Room", "category": "room",
                 "amount": "21000.00", "source": _span()},  # days omitted -> use nights (3)
            ],
            "bill_total": "21000.00",
        }
    )
    ws = adjudication.adjudicate(claim, {})
    # cap 4000/day x 3 nights = 12000 -> deduct 9000 -> line payable 12000
    assert _line(ws, "L1").payable == Decimal("12000.00")
    assert _line(ws, "L1").deductions[0].reason == DeductionReason.ROOM_RENT_CAP
