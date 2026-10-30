"""Coverage analyst: admissibility (code) and one clause per bill line (model). Never rupees.

The model's only job is judgement: which clause governs this line. Retrieval happens in code
first (ReWOO-style, L10: plan the lookups, then one decision call), so there is a single LLM call
per attempt and the candidate set is auditable.
"""

from __future__ import annotations

from datetime import timedelta

from pydantic import BaseModel, Field

from claimsense.contracts import AgentName, Claim, Worksheet

from . import clauses as C
from .llm import DATA_RULE, get_llm
from .permissions import ToolBelt
from .services import Services


class Admissibility(BaseModel):
    admissible: bool
    needs_review: bool = False
    reasons: list[str] = Field(default_factory=list)
    clause_ids: list[str] = Field(default_factory=list)


class LineChoice(BaseModel):
    line_id: str
    clause_id: str
    rationale: str = Field(description="one sentence, cite the clause wording")


class CoverageDecision(BaseModel):
    choices: list[LineChoice]


# Bill-line wording -> policy wording (query rewriting, L6). Extend from the dev claims.
REWRITE = {
    "ot charges": "operation theatre charges",
    "rmo": "medical practitioner fees",
    "pharmacy": "medicines and drugs",
    "consumables": "excluded items consumables non-payable",
}

SYSTEM = f"""You are the coverage analyst for Arogya Sanjeevani reimbursement claims.
For EVERY bill line choose exactly one clause_id from that line's CANDIDATES that governs how the
line is paid or deducted. Do not compute any amounts: a calculator does that.
{DATA_RULE}
If PLAYBOOK LESSONS are given, apply each one only when its 'applies when' condition holds.
If CRITIC FEEDBACK is given, fix exactly the problems it names and keep other choices."""


class CoverageAgent:
    name = AgentName.COVERAGE

    def __init__(self, services: Services, playbook=None, lesson_k: int = 3):
        self.svc = services
        self.belt = ToolBelt(self.name, services.registry(), services.tool_log)
        self.llm = get_llm("coverage")
        self.playbook = playbook  # reflexion.Playbook | None; only APPROVED lessons come out
        self.lesson_k = lesson_k

    # ---------------- admissibility (deterministic) ----------------
    def check_admissibility(self, claim: Claim) -> Admissibility:
        pol = self.belt.call("get_policy", policy_number=claim.policy_number)
        if pol is None:
            return Admissibility(admissible=False, needs_review=True,
                                 reasons=["policy not found in claims-db"])
        reasons, ids = [], []
        if not (pol.period_start <= claim.admission_date <= pol.period_end):
            reasons.append("admission date outside the policy period")
            ids.append("policy_schedule:period")  # TODO: cite the schedule/condition clause
        if claim.admission_date < pol.first_inception + timedelta(days=30):
            # TODO: accident cases are exempt from the 30-day wait; add once extraction tags them
            reasons.append("within the 30-day initial waiting period")
            ids.append(C.INITIAL_WAITING_PERIOD)
        diag = claim.diagnosis.lower()
        if any(p.lower() in diag for p in pol.declared_peds) and \
                claim.admission_date < pol.first_inception + timedelta(days=36 * 30):
            # TODO: use exact month arithmetic and the wording's PED period (CIS says 36 months,
            # table of benefits says 4 years: resolve with the domain lead)
            reasons.append("pre-existing disease within its waiting period")
            ids.append(C.PED_WAITING_PERIOD)
        needs_review = pol.insured_pseudonym != claim.patient_pseudonym
        if needs_review:
            reasons.append("patient on the bill does not match the insured person")
        return Admissibility(admissible=not reasons, needs_review=needs_review,
                             reasons=reasons, clause_ids=ids)

    # ---------------- clause selection (model) ----------------
    def candidates(self, claim: Claim) -> dict[str, list]:
        out = {}
        for line in claim.bill_lines:
            q = line.description.lower()
            for k, v in REWRITE.items():
                q = q.replace(k, v)
            out[line.line_id] = self.belt.call("policy_search", query=q, category=line.category.value)
        return out

    def lessons_for(self, claim: Claim, cands: dict[str, list]) -> list:
        if self.playbook is None:
            return []
        clause_ids = {p.clause.clause_id for ps in cands.values() for p in ps}
        text = " ".join(l.description for l in claim.bill_lines) + " " + claim.diagnosis
        return self.playbook.retrieve(clause_ids=clause_ids, text=text, k=self.lesson_k)

    def choose_clauses(
        self,
        claim: Claim,
        critic_feedback: list[str] | None = None,
        locked: dict[str, str] | None = None,
        previous: dict[str, str] | None = None,
    ) -> tuple[dict[str, str], list[str], list[str]]:
        """Returns (clause_choices, lesson_ids_used, notes). `locked` = adjudicator overrides."""
        locked = locked or {}
        cands = self.candidates(claim)
        lessons = self.lessons_for(claim, cands)
        notes: list[str] = []

        if self.llm is None:
            # Stub: top-ranked candidate; a lesson whose 'applies when' names the line category
            # re-points it to the lesson's first clause. Crude, but it lets the Reflexion harness
            # show a before/after effect offline. The real model reads lessons from the prompt.
            choices = {}
            for line in claim.bill_lines:
                ps = cands[line.line_id]
                pick = (previous or {}).get(line.line_id) or ps[0].clause.clause_id
                for l in lessons:
                    if line.category.value in l.applies_when.lower().split() and l.clause_ids and \
                            l.clause_ids[0] in {p.clause.clause_id for p in ps}:
                        pick = l.clause_ids[0]
                choices[line.line_id] = pick
        else:
            choices = self._ask_model(claim, cands, lessons, critic_feedback, previous)

        for lid, ps in cands.items():  # validate: the model may only pick a retrieved clause
            allowed = {p.clause.clause_id for p in ps}
            if choices.get(lid) not in allowed:
                notes.append(f"{lid}: model chose {choices.get(lid)!r} outside candidates; "
                             f"fell back to {ps[0].clause.clause_id}")
                choices[lid] = ps[0].clause.clause_id
        choices.update(locked)  # a human decision always wins
        return choices, [l.lesson_id for l in lessons], notes

    def _ask_model(self, claim, cands, lessons, critic_feedback, previous) -> dict[str, str]:
        lines = []
        for line in claim.bill_lines:
            cand = "\n".join(f"    - {p.clause.clause_id}: {p.clause.text[:400]}" for p in cands[line.line_id])
            lines.append(f"{line.line_id} | {line.category.value} | {line.description} | "
                         f"Rs {line.amount} | days={line.days}\n  CANDIDATES:\n{cand}")
        parts = [f"Room category: {claim.room_category.value}; nights: {claim.nights}; "
                 f"diagnosis: {claim.diagnosis}; procedure: {claim.procedure}",
                 "BILL LINES:\n" + "\n".join(lines)]
        if lessons:
            parts.append("PLAYBOOK LESSONS:\n" + "\n".join(
                f"- [{l.lesson_id}] {l.text} (applies when: {l.applies_when})" for l in lessons))
        if critic_feedback:
            parts.append("PREVIOUS CHOICES: " + str(previous))
            parts.append("CRITIC FEEDBACK:\n" + "\n".join(f"- {f}" for f in critic_feedback))
        out = self.llm.with_structured_output(CoverageDecision).invoke(
            [("system", SYSTEM), ("human", "\n\n".join(parts))])
        return {c.line_id: c.clause_id for c in out.choices}

    # ---------------- rupees: always the calculator ----------------
    def adjudicate(self, claim: Claim, choices: dict[str, str], version: int = 1,
                   fraud_flags: list[str] | None = None) -> Worksheet:
        return self.belt.call("calculate", claim=claim, clause_choices=choices,
                              version=version, fraud_flags=fraud_flags or [])
