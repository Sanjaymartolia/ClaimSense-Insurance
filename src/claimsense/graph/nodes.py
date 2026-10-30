"""Graph nodes and routers. Each node: state -> partial update (L8). The supervisor is this code.

Pipeline (brief, step 2):
  plan → extract → admissibility ─┬─ coverage → fraud → critic ─┬─ human_review ─┬─ settle → memory
                                  │                ▲  (fail, r<1)│                │  (senior needed)
                                  │                └── revise ◄──┤                ├─ senior_review → settle
                                  │                              └ escalate → human_review
                                  └─ (not admissible) → human_review → repudiate → memory
  human/senior "edit" → apply_edits → critic → human_review   (old approvals are void)
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable

from claimsense.agents import Team
from claimsense.contracts import AgentName, ApprovalDecision, ApprovalLevel, ApprovalToken, Handoff

from . import planner
from .state import ClaimState, ReviewDecision, Status


def _default_interrupt(payload: dict) -> Any:
    from langgraph.types import interrupt  # lazy: unit tests inject their own

    return interrupt(payload)


def _handoff(state: ClaimState, to: AgentName, step: str, summary: str, refs: list[str]) -> Handoff:
    return Handoff(sender=AgentName.SUPERVISOR, recipient=to, claim_id=state["claim_id"],
                   step=step, summary=summary, artifact_refs=refs)


class Nodes:
    def __init__(self, team: Team, interrupt_fn: Callable[[dict], Any] | None = None):
        self.team = team
        self.interrupt = interrupt_fn or _default_interrupt

    # ------------------------------------------------------------------ nodes
    def plan(self, s: ClaimState) -> dict:
        p = planner.make_plan(s["claim_id"])
        return {"plan": p, "trace": [planner.render(p)]}

    def extract(self, s: ClaimState) -> dict:
        claim, issues = self.team.extraction.run(s["packet"])
        return {
            "claim": claim, "extraction_issues": issues,
            "plan": planner.mark(s["plan"], "extract", "done"),
            "handoffs": [_handoff(s, AgentName.EXTRACTION, "extract",
                                  "Extract typed fields and every bill line with spans.", ["packet"])],
            "trace": [f"extract: {len(claim.bill_lines)} lines, {len(issues)} issues"],
        }

    def admissibility(self, s: ClaimState) -> dict:
        adm = self.team.coverage.check_admissibility(s["claim"])
        plan = planner.mark(s["plan"], "admissibility", "done" if adm.admissible else "failed")
        plan = planner.monitor_after_admissibility(plan, adm.admissible)
        return {"admissibility": adm, "plan": plan,
                "handoffs": [_handoff(s, AgentName.COVERAGE, "admissibility",
                                      "Policy active, waiting periods served, no exclusion?", ["claim"])],
                "trace": [f"admissibility: {'ok' if adm.admissible else 'NOT admissible'} "
                          f"{adm.clause_ids}", planner.render(plan)]}

    def coverage(self, s: ClaimState) -> dict:
        revising = s.get("revisions", 0) > 0 and s.get("critic_report") is not None
        feedback = s["critic_report"].feedback() if revising else None
        choices, lesson_ids, notes = self.team.coverage.choose_clauses(
            s["claim"], critic_feedback=feedback, locked=s.get("locked_choices"),
            previous=s.get("clause_choices"))
        prev = s.get("worksheet")
        ws = self.team.coverage.adjudicate(s["claim"], choices,
                                           version=(prev.version + 1) if prev else 1,
                                           fraud_flags=s.get("fraud_flags", []))
        return {"clause_choices": choices, "lessons_used": lesson_ids, "coverage_notes": notes,
                "worksheet": ws, "approvals": [],
                "plan": planner.mark(s["plan"], "adjudicate_lines", "done"),
                "handoffs": [_handoff(s, AgentName.COVERAGE, "adjudicate_lines",
                                      "Pick a clause per line; calculator computes rupees."
                                      + (" Fix the critic's issues." if revising else ""),
                                      ["claim", "critic_report"] if revising else ["claim"])],
                "trace": [f"coverage{' (revision)' if revising else ''}: worksheet v{ws.version} "
                          f"payable Rs {ws.total_payable}; lessons {lesson_ids}"]}

    def fraud(self, s: ClaimState) -> dict:
        flags = self.team.fraud.run(s["claim"], s.get("extraction_issues"))
        # Worksheet is immutable once hashed; rebuild it through the calculator with the flags.
        ws = self.team.coverage.adjudicate(s["claim"], s["clause_choices"],
                                           version=s["worksheet"].version, fraud_flags=flags)
        return {"fraud_flags": flags, "worksheet": ws,
                "plan": planner.mark(s["plan"], "fraud_screen", "done"),
                "handoffs": [_handoff(s, AgentName.FRAUD, "fraud_screen",
                                      "Duplicates, used sub-limits, tariff outliers, dates.", ["claim"])],
                "trace": [f"fraud: {len(flags)} flag(s)"]}

    def critic(self, s: ClaimState) -> dict:
        rep = self.team.critic.review(s["claim"], s["clause_choices"], s["worksheet"])
        return {"critic_report": rep, "critic_history": [rep],
                "plan": planner.mark(s["plan"], "review", "done" if rep.passed else "failed"),
                "handoffs": [_handoff(s, AgentName.CRITIC, "review",
                                      "Rerun calculator; check each deduction's clause.",
                                      ["worksheet", "clause_choices"])],
                "trace": [f"critic: {'pass' if rep.passed else 'FAIL ' + str(len(rep.issues))}"]}

    def revise(self, s: ClaimState) -> dict:
        return {"revisions": s.get("revisions", 0) + 1,
                "trace": [f"critic → coverage, revision {s.get('revisions', 0) + 1}/{s['max_revisions']}"]}

    def escalate(self, s: ClaimState) -> dict:
        why = "critic still fails after the allowed revision: " + "; ".join(s["critic_report"].feedback())
        return {"escalation": why, "trace": ["escalate: revision limit reached"]}

    def _review(self, s: ClaimState, level: ApprovalLevel) -> dict:
        ws, adm = s.get("worksheet"), s["admissibility"]
        kind = "worksheet" if adm.admissible else "repudiation"
        subject_hash = ws.content_hash() if kind == "worksheet" else \
            hashlib.sha256(adm.model_dump_json().encode()).hexdigest()
        payload = {
            "claim_id": s["claim_id"], "kind": kind, "level": level.value,
            "worksheet": ws.model_dump(mode="json") if ws and kind == "worksheet" else None,
            "worksheet_hash": subject_hash, "admissibility": adm.model_dump(mode="json"),
            "fraud_flags": s.get("fraud_flags", []),
            "critic": s["critic_report"].feedback() if s.get("critic_report") else [],
            "escalation": s.get("escalation"), "plan": planner.render(s["plan"]),
        }
        d = ReviewDecision.model_validate(self.interrupt(payload))  # ⏸ graph pauses here
        base = {"review_decision": d.decision.value}
        if d.decision == ApprovalDecision.APPROVE:
            tok = ApprovalToken(claim_id=s["claim_id"], worksheet_hash=subject_hash, level=level,
                                approver_id=d.approver_id, decided_at=datetime.now(timezone.utc))
            return {**base, "approvals": [*s.get("approvals", []), tok],
                    "plan": planner.mark(s["plan"], "approve", "done"),
                    "trace": [f"{level.value} approved v{ws.version if ws else '-'}"]}
        if d.decision == ApprovalDecision.EDIT:
            log = [{"claim_id": s["claim_id"], "level": level.value, "line_id": e.line_id,
                    "old_clause": (s.get("clause_choices") or {}).get(e.line_id),
                    "new_clause": e.clause_id, "new_amount": str(e.amount) if e.amount else None,
                    "reason": e.reason} for e in d.edits]
            return {**base, "pending_edits": d.edits, "edit_log": log,
                    "trace": [f"{level.value} edited {len(d.edits)} line(s)"]}
        return {**base, "status": Status.REJECTED, "trace": [f"{level.value} rejected"]}

    def human_review(self, s: ClaimState) -> dict:
        return self._review(s, ApprovalLevel.ADJUDICATOR)

    def senior_review(self, s: ClaimState) -> dict:
        return self._review(s, ApprovalLevel.SENIOR)

    def apply_edits(self, s: ClaimState) -> dict:
        """Re-entry point: an edit changes the worksheet, so every earlier approval is void."""
        adm = s["admissibility"]
        if not adm.admissible:  # adjudicator overrides the inadmissibility finding
            adm = adm.model_copy(update={"admissible": True,
                                         "reasons": adm.reasons + ["overridden by adjudicator"]})
        claim, locked = s["claim"], dict(s.get("locked_choices") or {})
        lines = []
        for line in claim.bill_lines:
            e = next((e for e in s.get("pending_edits", []) if e.line_id == line.line_id), None)
            if e and e.amount is not None:
                line = line.model_copy(update={"amount": Decimal(e.amount)})
            if e and e.clause_id:
                locked[line.line_id] = e.clause_id
            lines.append(line)
        delta = sum((l.amount for l in lines), Decimal(0)) - claim.lines_total()
        claim = claim.model_copy(update={"bill_lines": lines, "bill_total": claim.bill_total + delta})
        choices = {**(s.get("clause_choices") or {}), **locked}
        if not s.get("clause_choices"):  # came from the repudiation path: run coverage first
            choices, _, _ = self.team.coverage.choose_clauses(claim, locked=locked)
        prev = s.get("worksheet")
        ws = self.team.coverage.adjudicate(claim, choices, version=(prev.version + 1) if prev else 1,
                                           fraud_flags=s.get("fraud_flags", []))
        return {"claim": claim, "admissibility": adm, "locked_choices": locked,
                "clause_choices": choices, "worksheet": ws, "approvals": [], "pending_edits": [],
                "human_edited": True,
                "trace": [f"edit → worksheet v{ws.version}, payable Rs {ws.total_payable}; "
                          f"earlier approvals void"]}

    def settle(self, s: ClaimState) -> dict:
        receipt, letter = self.team.settlement.settle(
            s["claim"], s["worksheet"], s.get("approvals", []), needs_senior=needs_senior(s, self.team))
        return {"settlement": receipt, "letter": letter, "status": Status.SETTLED,
                "plan": planner.mark(s["plan"], "settle", "done"),
                "handoffs": [_handoff(s, AgentName.SETTLEMENT, "settle",
                                      "Settle with the approval token; letter with a reason per deduction.",
                                      ["worksheet", "approvals"])],
                "trace": [f"settled Rs {s['worksheet'].total_payable}"]}

    def repudiate(self, s: ClaimState) -> dict:
        adm = s["admissibility"]
        receipt, letter = self.team.settlement.repudiate(s["claim"], adm.reasons, adm.clause_ids,
                                                         s.get("approvals", []))
        return {"settlement": receipt, "letter": letter, "status": Status.REPUDIATED,
                "plan": planner.mark(s["plan"], "repudiate", "done"), "trace": ["repudiated"]}

    def memory_update(self, s: ClaimState) -> dict:
        # Claim history (used sub-limits, bills seen). Edits stay in edit_log for Reflexion; they
        # become lessons only after review (reflexion/), never automatically.
        self.team.services.record_history(s["claim"], s.get("worksheet"))
        return {"plan": planner.mark(s["plan"], "update_memory", "done"),
                "trace": ["memory: claim history updated"]}

    def table(self) -> dict[str, Callable]:
        return {n: getattr(self, n) for n in NODE_NAMES}


NODE_NAMES = ["plan", "extract", "admissibility", "coverage", "fraud", "critic", "revise",
              "escalate", "human_review", "senior_review", "apply_edits", "settle", "repudiate",
              "memory_update"]


# ---------------------------------------------------------------------- routers
def needs_senior(s: ClaimState, team: Team) -> bool:
    ws = s.get("worksheet")
    if ws is None or not s["admissibility"].admissible:
        return False
    return ws.total_payable > team.services.senior_threshold or bool(s.get("fraud_flags"))


def after_admissibility(s: ClaimState) -> str:
    return "coverage" if s["admissibility"].admissible else "human_review"


def after_critic(s: ClaimState) -> str:
    if s["critic_report"].passed:
        return "human_review"
    if s.get("human_edited"):
        return "human_review"  # never let an agent overrule a human edit; show the issues instead
    if s.get("revisions", 0) < s["max_revisions"]:
        return "revise"
    return "escalate"


def make_after_review(team: Team) -> Callable[[ClaimState], str]:
    def route(s: ClaimState) -> str:
        d = s.get("review_decision")
        if d == ApprovalDecision.EDIT:
            return "apply_edits"
        if d == ApprovalDecision.REJECT:
            return "end"
        if not s["admissibility"].admissible:
            return "repudiate"
        has_senior = any(a.level == ApprovalLevel.SENIOR and a.is_valid_for(s["worksheet"])
                         for a in s.get("approvals", []))
        if needs_senior(s, team) and not has_senior:
            return "senior_review"
        return "settle"
    return route
