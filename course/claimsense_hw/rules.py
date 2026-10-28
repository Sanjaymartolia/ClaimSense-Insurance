"""The money rules, already written for you.

These are the demo rules the gold worksheets were generated with (see data/README.md).
They are date arithmetic and percentages: copying them into `if` statements teaches
Python, not agentic AI, so we did it. `tests/test_contract.py` proves they reproduce
all 20 dev settlements to the rupee.

Rule 1 of the project: the model proposes, code decides. The agent never computes a
rupee itself; it calls the `compute_worksheet` tool, which runs this file.

Nothing here runs in the shipped program. It starts working when the agent calls
the tool (TODO 4).
"""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

ROOM_CAP_PCT, ROOM_CAP_MAX = Decimal("0.02"), Decimal("5000")
ICU_CAP_PCT, ICU_CAP_MAX = Decimal("0.05"), Decimal("10000")

# The only flags the gold uses. The agent must pick from these words exactly.
REVIEW_FLAGS = {
    "room_rent_breach",
    "duplicate_bill",
    "non_payable_items",
    "sub_limit",
    "waiting_period",
    "policy_period_inconsistency",
    # red-team set only (eval/redteam/gold.jsonl):
    "prompt_injection",  # RT-001, RT-007: TODO 5
    "bill_total_mismatch",  # RT-002: caught in code below
    "date_conflict",  # RT-004: a document disagrees with the claim form; the agent must read
}


def rupees(x):
    """Round to whole rupees, half up (₹3,756.55 -> ₹3,757). Never use float or round()."""
    return Decimal(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def admissibility(claim):
    """-> (status, reason_code). Claim-level gates checked before any line."""
    p, h = claim["policy"], claim["hospitalisation"]
    start, end = (
        date.fromisoformat(p["policy_start_date"]),
        date.fromisoformat(p["policy_end_date"]),
    )
    admitted, discharged = (
        date.fromisoformat(h["admission_date"]),
        date.fromisoformat(h["discharge_date"]),
    )
    if admitted < start or discharged > end:
        return "needs_review", "admission_or_discharge_outside_policy_period"
    # Dates count from the POLICY START, never from date.today().
    if (admitted - start).days < p["initial_waiting_period_days"]:
        return "not_admissible", "initial_waiting_period_not_elapsed"
    if h.get("pre_existing_condition_declared"):
        months = h.get("pre_existing_condition_wait_months_elapsed") or 0
        if months < p["pre_existing_disease_waiting_months"]:
            return "not_admissible", "pre_existing_disease_waiting_period"
    return "admissible", ""


def compute_worksheet(claim):
    """Every rupee for one claim. Returns a plain dict (JSON-safe, amounts as int)."""
    status, gate_reason = admissibility(claim)
    si = Decimal(claim["policy"]["sum_insured_inr"])
    room_cap = min(si * ROOM_CAP_PCT, ROOM_CAP_MAX)
    icu_cap = min(si * ICU_CAP_PCT, ICU_CAP_MAX)

    # proportional cut: if the room is dearer than the cap, room-linked lines shrink too
    cut = Decimal(1)
    for line in claim["bill_lines"]:
        cap = icu_cap if line["category"] == "icu" else room_cap
        if line["category"] in ("room_rent", "icu") and Decimal(line["unit_amount_inr"]) > cap:
            cut = min(cut, cap / Decimal(line["unit_amount_inr"]))

    lines, seen, notes = [], set(), set()
    for line in claim["bill_lines"]:
        amount, reasons = Decimal(line["amount_inr"]), []
        key = (line["category"], line["description"], line["amount_inr"])
        if key in seen:
            allowed, reasons = Decimal(0), ["duplicate_line"]
            notes.add("duplicate_line_found")
        elif not line["potentially_payable"]:
            allowed, reasons = Decimal(0), ["non_payable_item_demo_rule"]
            notes.add("non_payable_line_found")
        elif line["category"] in ("room_rent", "icu"):
            cap = icu_cap if line["category"] == "icu" else room_cap
            per_day = min(Decimal(line["unit_amount_inr"]), cap)
            allowed = per_day * Decimal(line["quantity"])
            if per_day < Decimal(line["unit_amount_inr"]):
                reasons = ["room_rent_daily_cap"]
                notes.add("room_rent_above_cap")
        elif cut < 1 and line.get("room_linked") and line["category"] != "procedure":
            # demo rule: the operation itself is never cut; only charges that scale
            # with the room (nursing, pharmacy, diagnostics). Skipped if the gate fails.
            allowed = rupees(amount * cut) if status == "admissible" else amount
            reasons = ["room_rent_proportional_reduction"] if status == "admissible" else []
        else:
            allowed = amount
        seen.add(key)
        if status != "admissible":
            allowed, reasons = Decimal(0), reasons + ["claim_level_admissibility_gate"]
        lines.append(
            {
                "line_id": line["line_id"],
                "allowed_before_copay_inr": int(rupees(allowed)),
                "reason_codes": reasons,
            }
        )

    if sum(Decimal(x["amount_inr"]) for x in claim["bill_lines"]) != Decimal(
        claim["bill_total_inr"]
    ):
        notes.add("bill_total_mismatch")  # we pay the lines, never the stated total
    payable = sum(Decimal(x["allowed_before_copay_inr"]) for x in lines)
    copay = rupees(payable * Decimal(str(claim["policy"]["co_pay_rate"])))
    return {
        "claim_id": claim["claim_id"],
        "admissibility": status,
        "reason_codes": [gate_reason] if gate_reason else [],
        "line_items": lines,
        "payable_before_copay_inr": int(payable),
        "copay_amount_inr": int(copay),
        "settlement_inr": int(payable - copay),
        "rule_notes": sorted(notes),  # facts for the agent to explain; NOT the flags
    }


def needs_human_review(worksheet):
    """-> (True/False, reason). A person must look before money moves.

    The gold sends a claim to a human when it is not admissible or a line looks
    duplicated (possible fraud). Note what is NOT here: sub-limits. Whether a
    diagnosis falls under a sub-limit is a policy-reading question, so the agent
    must find the clause (TODO 2) and decide.
    """
    if worksheet["admissibility"] != "admissible":
        return True, worksheet["reason_codes"][0]
    if "duplicate_line_found" in worksheet["rule_notes"]:
        return True, "possible_duplicate_billing"
    if "bill_total_mismatch" in worksheet["rule_notes"]:
        return True, "bill_total_differs_from_lines"
    return False, ""
