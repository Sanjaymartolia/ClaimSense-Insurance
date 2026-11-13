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

    def settle(
        self, claim: Claim, worksheet: Worksheet, approvals: list[ApprovalToken], needs_senior: bool
    ) -> tuple[dict, str]:
        """Fail-closed order (L15 notebook section 7): the payment ceiling, then the letter guard,
        and only then the tool that moves money. Any failure raises OutputGuardError: nothing is
        paid, nothing is sent, and the claim goes back to a person."""
        self.payment_guard(claim, worksheet)
        letter = self.output_guard(claim, worksheet, self.draft_letter(claim, worksheet))
        receipt = self.belt.call(
            "settle_claim",
            claim_id=claim.claim_id,
            worksheet=worksheet,
            approvals=approvals,
            needs_senior=needs_senior,
        )
        return receipt, letter

    def repudiate(
        self,
        claim: Claim,
        reasons: list[str],
        clause_ids: list[str],
        approvals: list[ApprovalToken],
    ) -> tuple[dict, str]:
        # Every reason gets a line: the old padding (`clause_ids + [""] * 9`) silently dropped
        # reasons beyond len(clause_ids) + 9.
        padded = clause_ids + [""] * max(0, len(reasons) - len(clause_ids))
        body = "\n".join(f"- {r} (clause {c})" for r, c in zip(reasons, padded, strict=False))
        letter = (
            f"Policy {claim.policy_number}, claim {claim.claim_id}, insured "
            f"{claim.patient_pseudonym}.\nYour claim is not admissible:\n{body}"
        )
        # The letter is checked before the repudiation is recorded, so a blocked letter leaves
        # nothing half done.
        from claimsense.guardrails.output_guardrails import process_output_pipeline

        checked = process_output_pipeline(letter, verify_grounding=False, min_citations=0)
        if checked.blocked:
            raise OutputGuardError(f"repudiation letter blocked: {checked.block_reason}")
        receipt = self.belt.call(
            "record_repudiation", claim_id=claim.claim_id, reasons=reasons, approvals=approvals
        )
        return receipt, checked.sanitized_output

    def draft_letter(self, claim: Claim, ws: Worksheet) -> str:
        rows = []
        for line in ws.lines:
            for d in line.deductions:
                rows.append((line.line_id, d.reason.value, d.amount, d.clause_id, d.explanation))
        if ws.co_pay:
            rows.append(
                (
                    "claim",
                    ws.co_pay.reason.value,
                    ws.co_pay.amount,
                    ws.co_pay.clause_id,
                    ws.co_pay.explanation,
                )
            )
        reasons = self._plain_reasons(rows)
        table = "\n".join(
            f"- {lid}: Rs {amt} deducted ({reason}, clause {cid}). {why}"
            for (lid, reason, amt, cid, _), why in zip(rows, reasons, strict=True)
        )
        return (
            f"Policy number: {claim.policy_number}\nClaim: {claim.claim_id}\n"
            f"Insured: {claim.patient_pseudonym}\n\n"
            f"Amount claimed: Rs {ws.total_claimed}\nAmount payable: Rs {ws.total_payable}\n\n"
            f"Deductions:\n{table or '- none'}\n"
        )

    def _plain_reasons(self, rows) -> list[str]:
        if self.llm is None or not rows:
            return [r[4] for r in rows]
        prompt = "\n".join(
            f"{i}. {r[1]} under clause {r[3]}: {r[4]}" for i, r in enumerate(rows, 1)
        )
        out = (
            self.llm.invoke(
                [
                    (
                        "system",
                        "Rewrite each numbered deduction reason as one short sentence a "
                        "patient can understand. Do not mention or change any amount. "
                        "Return one line per item.",
                    ),
                    ("human", prompt),
                ]
            )
            .content.strip()
            .splitlines()
        )
        out = [
            o.split(".", 1)[-1].strip() if o[:1].isdigit() else o.strip() for o in out if o.strip()
        ]
        return out if len(out) == len(rows) else [r[4] for r in rows]

    @staticmethod
    def output_guard(claim: Claim, ws: Worksheet, letter: str) -> str:
        """L15 output guard: `output_guardrails.check_letter_safe` (secret and prompt leaks,
        internal ids, links, then the right claim, policy number, insured person and total).
        Returns the letter as it may be sent; raises OutputGuardError if it is blocked."""
        from claimsense.guardrails.output_guardrails import check_letter_safe

        result = check_letter_safe(claim, ws, letter)
        if result.blocked:
            raise OutputGuardError(f"letter blocked: {result.block_reason}")
        return result.sanitized_output

    def payment_guard(self, claim: Claim, ws: Worksheet) -> None:
        """L15 notebook section 7, a guardrail on the action, from trusted inputs: the worksheet
        reconciles, pays nothing above what was claimed, and stays within the sum insured on the
        policy record. No policy record means no payment (fail closed)."""
        from claimsense.guardrails.guardrails import check_payment_ceiling

        policy = self.belt.call("get_policy", policy_number=claim.policy_number)
        if policy is None:
            raise OutputGuardError("no policy record: the payment cannot be checked")
        problems = check_payment_ceiling(ws, sum_insured=policy.sum_insured)
        if problems:
            raise OutputGuardError("payment blocked: " + "; ".join(p.message for p in problems))
