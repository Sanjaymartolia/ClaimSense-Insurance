"""The evaluator: turns a run into concrete mistakes (L12: 'the evaluator does the real work').

Three feedback sources, as the brief asks:
1. adjudicator edits (on dev claims, a simulated adjudicator who knows the gold worksheet);
2. critic rejections recorded in critic_history;
3. the difference between the first worksheet shown to the adjudicator and the gold worksheet.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field

from claimsense.contracts import ApprovalDecision, Worksheet


class DevCase(BaseModel):
    """One development or held-out case. TODO(day 4): write load_cases() for eval/'s format."""

    case_id: str
    packet: dict
    gold_worksheet: Worksheet | None = None
    gold_clause_choices: dict[str, str] = Field(default_factory=dict)
    gold_admissible: bool = True
    split: str = "dev"  # dev | heldout

    def gold_choices(self) -> dict[str, str]:
        """Prefer explicit gold choices; otherwise infer from the gold deductions' clauses."""
        if self.gold_clause_choices or self.gold_worksheet is None:
            return dict(self.gold_clause_choices)
        return {l.line_id: l.deductions[0].clause_id for l in self.gold_worksheet.lines if l.deductions}


class Mistake(BaseModel):
    case_id: str
    source: str  # adjudicator_edit | critic_rejection | gold_diff
    line_id: str | None = None
    category: str | None = None
    got_clause: str | None = None
    expected_clause: str | None = None
    rupee_error: Decimal = Decimal("0")
    detail: str = ""


class SimulatedAdjudicator:
    """Plays the adjudicator on dev claims: corrects lines whose clause differs from gold, once,
    then approves. Records the FIRST worksheet it was shown: that is what we score."""

    def __init__(self, case: DevCase, reviewer_id: str = "sim-adjudicator"):
        self.case, self.reviewer_id = case, reviewer_id
        self.first_payload: dict | None = None
        self.edits_made: list[dict] = []
        self.edited = False
        self.rounds = 0

    def __call__(self, payload: dict) -> dict:
        self.rounds += 1
        if self.first_payload is None:
            self.first_payload = payload
        me = {"approver_id": f"{self.reviewer_id}-{payload['level']}"}
        if payload["kind"] == "repudiation":
            ok = not self.case.gold_admissible
            self.edited = self.edited or not ok
            return {**me, "decision": ApprovalDecision.APPROVE if ok else ApprovalDecision.EDIT,
                    "edits": [], "note": None if ok else "claim is admissible"}
        if self.edits_made or self.case.gold_worksheet is None:
            return {**me, "decision": ApprovalDecision.APPROVE}
        gold = self.case.gold_choices()
        ws = Worksheet.model_validate(payload["worksheet"])
        gold_lines = {l.line_id: l for l in self.case.gold_worksheet.lines}
        edits = []
        for line in ws.lines:
            g = gold_lines.get(line.line_id)
            if g is None or g.payable == line.payable:
                continue
            got = line.deductions[0].clause_id if line.deductions else None
            want = gold.get(line.line_id)
            if want and want != got:
                edits.append({"line_id": line.line_id, "clause_id": want,
                              "reason": f"should be governed by {want}, not {got}"})
        if not edits:
            return {**me, "decision": ApprovalDecision.APPROVE}
        self.edits_made, self.edited = edits, True
        return {**me, "decision": ApprovalDecision.EDIT, "edits": edits}


def mistakes_from_run(case: DevCase, final_state: dict, adjudicator: SimulatedAdjudicator) -> list[Mistake]:
    out: list[Mistake] = []
    claim = final_state.get("claim")
    cat = {l.line_id: l.category.value for l in claim.bill_lines} if claim else {}
    first = adjudicator.first_payload or {}
    proposed = Worksheet.model_validate(first["worksheet"]) if first.get("worksheet") else None

    for e in final_state.get("edit_log", []):
        out.append(Mistake(case_id=case.case_id, source="adjudicator_edit", line_id=e["line_id"],
                           category=cat.get(e["line_id"]), got_clause=e.get("old_clause"),
                           expected_clause=e.get("new_clause"), detail=e.get("reason", "")))
    for rep in final_state.get("critic_history", []):
        for i in rep.issues:
            out.append(Mistake(case_id=case.case_id, source="critic_rejection", line_id=i.line_id,
                               category=cat.get(i.line_id or ""), detail=f"{i.kind}: {i.message}"))
    if proposed is not None and case.gold_worksheet is not None:
        gold = {l.line_id: l for l in case.gold_worksheet.lines}
        edited = {e["line_id"] for e in final_state.get("edit_log", [])}
        for l in proposed.lines:
            g = gold.get(l.line_id)
            if g and g.payable != l.payable and l.line_id not in edited:
                out.append(Mistake(case_id=case.case_id, source="gold_diff", line_id=l.line_id,
                                   category=cat.get(l.line_id), rupee_error=abs(g.payable - l.payable),
                                   got_clause=l.deductions[0].clause_id if l.deductions else None,
                                   expected_clause=case.gold_choices().get(l.line_id),
                                   detail=f"payable {l.payable} vs gold {g.payable}"))
    if not case.gold_admissible and final_state.get("admissibility") and \
            final_state["admissibility"].admissible:
        out.append(Mistake(case_id=case.case_id, source="gold_diff",
                           detail="claim should have been found not admissible"))
    return out
