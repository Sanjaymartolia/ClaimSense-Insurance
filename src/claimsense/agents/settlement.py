"""Settlement agent: the ONLY agent with settle_claim. Writes the settlement, drafts the letter.

The letter's numbers are copied from the worksheet by code; the model (if any) only writes the
plain-language reason sentences. The output guard checks name, policy number and totals before
anything leaves.
"""

from __future__ import annotations

from claimsense.contracts import AgentName, ApprovalToken, Claim, Worksheet

from .llm import get_llm
from .permissions import ToolBelt
from .services import Services


class OutputGuardError(ValueError):
    pass


class SettlementAgent:
    name = AgentName.SETTLEMENT

    def __init__(self, services: Services):
        self.belt = ToolBelt(self.name, services.registry(), services.tool_log)
        self.llm = get_llm("settlement")

    def settle(self, claim: Claim, worksheet: Worksheet, approvals: list[ApprovalToken],
               needs_senior: bool) -> tuple[dict, str]:
        letter = self.draft_letter(claim, worksheet)
        self.output_guard(claim, worksheet, letter)
        receipt = self.belt.call("settle_claim", claim_id=claim.claim_id, worksheet=worksheet,
                                 approvals=approvals, needs_senior=needs_senior)
        return receipt, letter

    def repudiate(self, claim: Claim, reasons: list[str], clause_ids: list[str],
                  approvals: list[ApprovalToken]) -> tuple[dict, str]:
        receipt = self.belt.call("record_repudiation", claim_id=claim.claim_id,
                                 reasons=reasons, approvals=approvals)
        body = "\n".join(f"- {r} (clause {c})" for r, c in zip(reasons, clause_ids + [""] * 9))
        letter = (f"Policy {claim.policy_number}, claim {claim.claim_id}, insured "
                  f"{claim.patient_pseudonym}.\nYour claim is not admissible:\n{body}")
        return receipt, letter

    def draft_letter(self, claim: Claim, ws: Worksheet) -> str:
        rows = []
        for line in ws.lines:
            for d in line.deductions:
                rows.append((line.line_id, d.reason.value, d.amount, d.clause_id, d.explanation))
        if ws.co_pay:
            rows.append(("claim", ws.co_pay.reason.value, ws.co_pay.amount, ws.co_pay.clause_id,
                         ws.co_pay.explanation))
        reasons = self._plain_reasons(rows)
        table = "\n".join(f"- {lid}: Rs {amt} deducted ({reason}, clause {cid}). {why}"
                          for (lid, reason, amt, cid, _), why in zip(rows, reasons))
        return (f"Policy number: {claim.policy_number}\nClaim: {claim.claim_id}\n"
                f"Insured: {claim.patient_pseudonym}\n\n"
                f"Amount claimed: Rs {ws.total_claimed}\nAmount payable: Rs {ws.total_payable}\n\n"
                f"Deductions:\n{table or '- none'}\n")

    def _plain_reasons(self, rows) -> list[str]:
        if self.llm is None or not rows:
            return [r[4] for r in rows]
        prompt = "\n".join(f"{i}. {r[1]} under clause {r[3]}: {r[4]}" for i, r in enumerate(rows, 1))
        out = self.llm.invoke([
            ("system", "Rewrite each numbered deduction reason as one short sentence a patient can "
                       "understand. Do not mention or change any amount. Return one line per item."),
            ("human", prompt)]).content.strip().splitlines()
        out = [o.split(".", 1)[-1].strip() if o[:1].isdigit() else o.strip() for o in out if o.strip()]
        return out if len(out) == len(rows) else [r[4] for r in rows]

    @staticmethod
    def output_guard(claim: Claim, ws: Worksheet, letter: str) -> None:
        """L15 output guard. Tools & Security may replace this; keep the call."""
        if claim.claim_id != ws.claim_id:
            raise OutputGuardError("worksheet belongs to a different claim")
        if claim.policy_number not in letter or claim.patient_pseudonym not in letter:
            raise OutputGuardError("letter does not name the right policy and insured person")
        if f"Rs {ws.total_payable}" not in letter:
            raise OutputGuardError("letter total does not match the worksheet")
