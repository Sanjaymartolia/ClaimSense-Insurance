"""ADR-0009 rules in the dev reference calculator (`agents.services.reference_calculate`).

Every expected figure is hand-worked (shown in the comments), not read back from the code:
- DEC-01 (reading A): room + boarding + nursing share one all-inclusive cap of min(2% SI,
  Rs 5,000)/day, and Note 4.1.1(b) cuts the other expenses (never medicines) by
  cap / (room + nursing per day).
- DEC-04: an in-bill duplicate line is deducted in full, citing clause 2 (Operative Clause),
  reason `other`, and is left out of every rate calculation.
- CLM-0016 ruling: an ICU rate above min(5% SI, Rs 10,000)/day also triggers the Note (b) cut; with
  both a room and an ICU breach the lower ratio applies. Ward room/nursing inside its own cap is
  not cut again.
"""

from decimal import Decimal

from claimsense.agents import clauses as C
from claimsense.agents.services import reference_calculate
from claimsense.contracts import Claim, DeductionReason


def _claim(lines, si="500000", nights=2):
    return Claim.model_validate(
        {
            "claim_id": "CLM-T",
            "policy_number": "POL-T",
            "patient_pseudonym": "PT-1",
            "admission_date": "2026-05-10",
            "discharge_date": f"2026-05-{10 + nights}",
            "diagnosis": "test",
            "procedure": "Test procedure",
            "room_category": "general_ward",
            "sum_insured": si,
            "bill_total": str(sum(Decimal(x[2]) for x in lines)),
            "bill_lines": [
                {
                    "line_id": lid,
                    "description": desc,
                    "category": cat,
                    "amount": amt,
                    "days": days,
                    "source": {"document": "b", "start": 0, "end": 1, "text": "x"},
                }
                for lid, cat, amt, desc, days in [(*x, None)[:5] for x in lines]
            ],
        }
    )


def _lines(ws):
    return {line.line_id: line for line in ws.lines}


def test_nursing_inside_the_room_cap_creates_the_breach():
    # SI 5,00,000 -> cap 5,000/day. Room 4,500 + nursing 1,000 = 5,500/day > 5,000 (room alone
    # would be under the cap). ratio = 5,000 / 5,500 = 10/11.
    claim = _claim(
        [
            ("L1", "room", "9000", "General ward per day", 2),
            ("L2", "nursing", "2000", "Nursing per day"),
            ("L3", "procedure", "30000", "Appendectomy"),
            ("L4", "medicines", "5000", "Medicines"),
        ]
    )
    ws = reference_calculate(claim, {})
    by = _lines(ws)
    # room 9,000 x 10/11 = 8,181.82; nursing 2,000 x 10/11 = 1,818.18 -> together 10,000 = 5,000 x 2
    assert by["L1"].payable == Decimal("8181.82")
    assert by["L2"].payable == Decimal("1818.18")
    assert by["L2"].deductions[0].reason == DeductionReason.ROOM_RENT_CAP
    assert by["L2"].deductions[0].clause_id == C.ROOM_RENT_LIMIT
    # procedure 30,000 x 10/11 = 27,272.73 (Note 4.1.1(b)); medicines never cut
    assert by["L3"].payable == Decimal("27272.73")
    assert by["L3"].deductions[0].clause_id == C.OTHER_EXPENSES
    assert by["L4"].deductions == []
    # gross 42,272.73; co-pay 5% = 2,113.64; payable 40,159.09
    assert ws.co_pay.amount == Decimal("2113.64")
    assert ws.total_payable == Decimal("40159.09")


def test_room_and_nursing_under_the_cap_are_not_cut():
    # 3,000 + 1,000 = 4,000/day <= 5,000: nothing deducted but the co-pay.
    claim = _claim(
        [
            ("L1", "room", "6000", "General ward per day", 2),
            ("L2", "nursing", "2000", "Nursing per day"),
            ("L3", "procedure", "30000", "Appendectomy"),
        ]
    )
    ws = reference_calculate(claim, {})
    assert all(line.deductions == [] for line in ws.lines)
    assert ws.total_payable == Decimal("36100.00")  # 38,000 - 1,900


def test_an_in_bill_duplicate_is_deducted_citing_the_operative_clause():
    # L4 repeats L3 exactly. It is deducted in full and does not count towards any rate.
    claim = _claim(
        [
            ("L1", "room", "6000", "General ward per day", 2),
            ("L2", "procedure", "30000", "Appendectomy"),
            ("L3", "investigations", "2000", "Diagnostics and laboratory"),
            ("L4", "investigations", "2000", "Diagnostics and laboratory"),
        ]
    )
    ws = reference_calculate(claim, {})
    dup = _lines(ws)["L4"]
    assert dup.payable == 0
    assert dup.deductions[0].reason == DeductionReason.OTHER
    assert dup.deductions[0].clause_id == C.OPERATIVE
    assert _lines(ws)["L3"].deductions == []
    assert ws.total_payable == Decimal("36100.00")  # 38,000 - 5% co-pay 1,900


def test_a_duplicated_nursing_line_does_not_create_a_room_breach():
    # Without the repeat: 3,000 + 1,500 = 4,500/day, under the cap. Counting the repeat would
    # give 6,000/day and a false breach.
    claim = _claim(
        [
            ("L1", "room", "6000", "General ward per day", 2),
            ("L2", "nursing", "3000", "Nursing per day"),
            ("L3", "nursing", "3000", "Nursing per day"),
            ("L4", "procedure", "30000", "Appendectomy"),
        ]
    )
    ws = reference_calculate(claim, {})
    by = _lines(ws)
    assert by["L3"].payable == 0 and by["L3"].deductions[0].clause_id == C.OPERATIVE
    assert by["L1"].deductions == [] and by["L2"].deductions == [] and by["L4"].deductions == []


def test_an_icu_breach_cuts_other_expenses_but_not_the_capped_ward():
    # SI 3,00,000: ICU cap min(15,000, 10,000) = 10,000/day; room cap min(6,000, 5,000) = 5,000.
    # ICU 20,000 for 1 day -> ratio 0.5. Ward 4,000 + nursing 500 = 4,500/day, inside its cap.
    claim = _claim(
        [
            ("L1", "icu", "20000", "ICU per day", 1),
            ("L2", "room", "4000", "General ward per day", 1),
            ("L3", "nursing", "500", "Nursing"),
            ("L4", "procedure", "10000", "Procedure"),
            ("L5", "medicines", "3000", "Medicines"),
        ],
        si="300000",
    )
    ws = reference_calculate(claim, {})
    by = _lines(ws)
    assert by["L1"].payable == Decimal("10000.00")  # capped
    assert by["L4"].payable == Decimal("5000.00")  # 10,000 x 0.5
    assert by["L2"].deductions == [] and by["L3"].deductions == []
    assert by["L5"].deductions == []
    # gross 10,000 + 4,000 + 500 + 5,000 + 3,000 = 22,500; co-pay 1,125
    assert ws.total_payable == Decimal("21375.00")


def test_claim_level_gate_clauses_deduct_every_line_in_full():
    # ADR-0010: the admissibility gate gives every line its clause. Bill 9,000 + 30,000 + 6,000 =
    # 45,000. Every line is deducted in full -> payable 0, and no co-pay on 0.
    claim = _claim(
        [
            ("L1", "room", "9000", "General ward per day", 2),
            ("L2", "procedure", "30000", "LSCS"),
            ("L3", "medicines", "6000", "Medicines"),
        ]
    )
    for clause, reason in [
        (C.MATERNITY_EXCLUSION, DeductionReason.EXCLUSION),
        (C.POLICY_PERIOD, DeductionReason.OTHER),
        (C.INITIAL_WAITING_PERIOD, DeductionReason.WAITING_PERIOD),
    ]:
        ws = reference_calculate(claim, {lid: clause for lid in ("L1", "L2", "L3")})
        assert ws.total_payable == Decimal("0")
        assert ws.co_pay is None
        for line in ws.lines:
            assert [(d.reason, d.clause_id, d.amount) for d in line.deductions] == [
                (reason, clause, line.claimed)
            ]
