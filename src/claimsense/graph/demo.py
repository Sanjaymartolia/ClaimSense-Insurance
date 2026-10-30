"""Terminal demo of the brief's example: 3 nights in a private room above the cap.

    CLAIMSENSE_LLM=stub python -m claimsense.graph.demo          # offline
    python -m claimsense.graph.demo --edit                       # demo (3): edit voids approval

Uses real LangGraph + checkpointer + interrupt(). Swap the packet for a dev claim from eval/.
"""

from __future__ import annotations

import argparse
from datetime import date
from decimal import Decimal

from claimsense.agents import PolicyInfo, Team, make_stub_services
from claimsense.agents import clauses as C

from .build import build_graph, memory_checkpointer, resume, start


def example_packet() -> dict:
    s = {"document": "bill.txt", "start": 0, "end": 3, "text": "row"}
    lines = [("L1", "Private room", "room", "21000.00", 3), ("L2", "Surgeon fees", "doctor_fees", "15000.00", None),
             ("L3", "OT charges", "ot", "30000.00", None), ("L4", "Pharmacy", "medicines", "8000.00", None),
             ("L5", "Gloves and masks", "consumables", "2000.00", None)]
    return {"claim_id": "CLM-DEMO-1", "documents": {}, "claim": {
        "claim_id": "CLM-DEMO-1", "policy_number": "POL-001", "patient_pseudonym": "PT-7731",
        "admission_date": "2026-05-10", "discharge_date": "2026-05-13", "diagnosis": "appendicitis",
        "procedure": "Appendectomy", "room_category": "single_private", "sum_insured": "200000.00",
        "bill_total": "76000.00",
        "bill_lines": [{"line_id": i, "description": d, "category": c, "amount": a, "days": n, "source": s}
                       for i, d, c, a, n in lines]}}


def show(payload: dict):
    print(f"\n⏸  {payload['level'].upper()} REVIEW  {payload['plan']}")
    ws = payload.get("worksheet")
    if ws:
        for l in ws["lines"]:
            ded = "; ".join(f"-{d['amount']} {d['reason']} [{d['clause_id']}]" for d in l["deductions"])
            print(f"   {l['line_id']}: {l['claimed']:>10} → {l['payable']:>10}  {ded}")
        print(f"   co-pay {ws['co_pay']['amount'] if ws['co_pay'] else 0};  PAYABLE {ws['total_payable']}"
              f"   hash {payload['worksheet_hash'][:12]}")
    for k in ("fraud_flags", "critic", "escalation"):
        if payload.get(k):
            print(f"   {k}: {payload[k]}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--edit", action="store_true", help="senior edits L3 after the first approval")
    a = ap.parse_args(argv)
    svc = make_stub_services(policies={"POL-001": PolicyInfo(
        policy_number="POL-001", period_start=date(2026, 1, 1), period_end=date(2026, 12, 31),
        first_inception=date(2024, 1, 1), sum_insured=Decimal("200000"), insured_pseudonym="PT-7731")})
    if a.edit:
        svc.senior_threshold = Decimal("10000")
    app = build_graph(Team(svc), checkpointer=memory_checkpointer())
    out, cfg = start(app, example_packet())
    edited = False
    while out.get("__interrupt__"):
        p = out["__interrupt__"][0].value
        show(p)
        if a.edit and p["level"] == "senior" and not edited:
            edited = True
            print("   → senior EDITS L3 to non-payable")
            decision = {"decision": "edit", "approver_id": "senior-1", "edits": [
                {"line_id": "L3", "clause_id": C.NON_PAYABLE_ITEMS, "reason": "demo edit"}]}
        else:
            print("   → APPROVE")
            decision = {"decision": "approve", "approver_id": f"{p['level']}-1"}
        out = resume(app, cfg, decision)
    final = app.get_state(cfg).values
    print("\nTRACE\n  " + "\n  ".join(final["trace"]))
    print("\nLETTER\n" + final.get("letter", ""))


if __name__ == "__main__":
    main()
