"""Critic: re-runs the calculator and checks that every deduction cites a clause that supports it.

Checks 1-3 are code and decide pass/fail on their own. Check 4 (does the clause text support the
deduction reason?) uses a model when one is configured, a keyword table otherwise.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from claimsense.contracts import AgentName, Claim, DeductionReason, Worksheet

from .llm import get_llm
from .permissions import ToolBelt
from .services import Services


class CriticIssue(BaseModel):
    line_id: str | None
    kind: str  # arithmetic | missing_clause | unknown_clause | unsupported_clause | total
    message: str


class CriticReport(BaseModel):
    passed: bool
    issues: list[CriticIssue] = Field(default_factory=list)

    def feedback(self) -> list[str]:
        return [f"{i.line_id or 'claim'}: {i.kind}: {i.message}" for i in self.issues]


REASON_KEYWORDS = {
    DeductionReason.ROOM_RENT_CAP: ("room",),
    DeductionReason.ICU_CAP: ("icu",),
    DeductionReason.PROPORTIONAL_CUT: ("proportion",),
    DeductionReason.SUB_LIMIT: ("sub limit", "sub-limit", "cataract", "whichever is lower"),
    DeductionReason.NON_PAYABLE: ("excluded", "not payable", "non-payable", "consumable"),
    DeductionReason.WAITING_PERIOD: ("waiting period",),
    DeductionReason.EXCLUSION: ("exclu",),
    DeductionReason.CO_PAY: ("co-pay", "co pay", "copay", "co-payment"),
}


class SupportVerdict(BaseModel):
    supported: bool
    why: str


class CriticAgent:
    name = AgentName.CRITIC

    def __init__(self, services: Services):
        self.belt = ToolBelt(self.name, services.registry(), services.tool_log)
        self.llm = get_llm("critic")

    def review(self, claim: Claim, clause_choices: dict[str, str], worksheet: Worksheet) -> CriticReport:
        issues: list[CriticIssue] = []

        # 1. arithmetic: recompute from the same inputs and compare line by line
        redo = self.belt.call("calculate", claim=claim, clause_choices=clause_choices,
                              version=worksheet.version, fraud_flags=worksheet.fraud_flags)
        mine = {l.line_id: l for l in worksheet.lines}
        for l in redo.lines:
            got = mine.get(l.line_id)
            if got is None:
                issues.append(CriticIssue(line_id=l.line_id, kind="arithmetic", message="line missing"))
            elif got.payable != l.payable:
                issues.append(CriticIssue(line_id=l.line_id, kind="arithmetic",
                                          message=f"payable {got.payable} but calculator gives {l.payable}"))
        if redo.total_payable != worksheet.total_payable:
            issues.append(CriticIssue(line_id=None, kind="total",
                                      message=f"total {worksheet.total_payable} != {redo.total_payable}"))

        # 2-4. every deduction cites a real clause that supports it
        deductions = [(l.line_id, d) for l in worksheet.lines for d in l.deductions]
        if worksheet.co_pay:
            deductions.append((None, worksheet.co_pay))
        for line_id, d in deductions:
            if not d.clause_id:
                issues.append(CriticIssue(line_id=line_id, kind="missing_clause",
                                          message=f"{d.reason} deduction cites no clause"))
                continue
            clause = self.belt.call("get_clause", clause_id=d.clause_id)
            if clause is None:
                issues.append(CriticIssue(line_id=line_id, kind="unknown_clause",
                                          message=f"{d.clause_id} not in policy-kb"))
                continue
            ok, why = self._supports(d.reason, clause.text)
            if not ok:
                issues.append(CriticIssue(line_id=line_id, kind="unsupported_clause",
                                          message=f"{d.clause_id} does not support {d.reason}: {why}"))
        return CriticReport(passed=not issues, issues=issues)

    def _supports(self, reason: DeductionReason, clause_text: str) -> tuple[bool, str]:
        if self.llm is None:
            kws = REASON_KEYWORDS.get(reason, ())
            ok = not kws or any(k in clause_text.lower() for k in kws)
            return ok, "keyword check"
        v = self.llm.with_structured_output(SupportVerdict).invoke([
            ("system", "Answer whether the policy clause text, read literally, supports a "
                       "deduction of the given type. Be strict."),
            ("human", f"DEDUCTION TYPE: {reason}\nCLAUSE TEXT:\n{clause_text}"),
        ])
        return v.supported, v.why
