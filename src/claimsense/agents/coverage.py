"""Coverage analyst: admissibility (code) and one clause per bill line (model). Never rupees.

The model's only job is judgement: which clause governs this line. Retrieval happens in code
first (ReWOO-style, L10: plan the lookups, then one decision call), so there is a single LLM call
per attempt and the candidate set is auditable.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, timedelta

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


# Clause 7.15(a) (Code Excl18): treatment traceable to childbirth, incl. caesarean, is excluded;
# ectopic pregnancy is carved out. 7.15(b) (miscarriage / MTP) is left out on purpose: its accident
# exception needs an accident tag the claim does not carry yet (see the 30-day-wait TODO below).
CHILDBIRTH_TERMS = ("caesarean", "cesarean", "c-section", "lscs", "childbirth", "delivery")
MATERNITY_CARVE_OUTS = ("ectopic",)

# Clause 6.2 (Code Excl02), specific waiting period: (list item, months from the first policy's
# inception, trigger terms). Items and months follow the wording, 6.2.1-6.2.20 at 24 months and
# 6.2.21-6.2.22 at 36. The trigger terms are OURS, not the wording's: the Domain lead extends them.
# Matched as whole words (an "s"/"es" plural allowed) in the diagnosis and procedure. ADR-0011.
SPECIFIC_WAITS: tuple[tuple[str, int, tuple[str, ...]], ...] = (
    ("6.2.1 benign ENT disorders", 24, ("benign ent", "septoplasty", "deviated nasal septum")),
    ("6.2.2 tonsillectomy", 24, ("tonsillectomy",)),
    ("6.2.3 adenoidectomy", 24, ("adenoidectomy",)),
    ("6.2.4 mastoidectomy", 24, ("mastoidectomy",)),
    ("6.2.5 tympanoplasty", 24, ("tympanoplasty",)),
    ("6.2.6 hysterectomy", 24, ("hysterectomy",)),
    (
        "6.2.7 benign tumours, cysts, polyps, benign breast lumps",
        24,
        ("benign tumour", "benign tumor", "cyst", "polyp", "fibroid", "fibroadenoma", "lipoma"),
    ),
    ("6.2.8 benign prostate hypertrophy", 24, ("bph", "benign prostat", "turp")),
    ("6.2.9 cataract and age related eye ailments", 24, ("cataract", "phacoemulsification")),
    ("6.2.10 gastric / duodenal ulcer", 24, ("gastric ulcer", "duodenal ulcer", "peptic ulcer")),
    ("6.2.11 gout and rheumatism", 24, ("gout", "rheumatism")),
    ("6.2.12 hernia of all types", 24, ("hernia", "herniorrhaphy", "hernioplasty")),
    ("6.2.13 hydrocele", 24, ("hydrocele",)),
    ("6.2.14 non infective arthritis", 24, ("non infective arthritis", "rheumatoid arthritis")),
    (
        "6.2.15 piles, fissures and fistula in anus",
        24,
        ("piles", "haemorrhoid", "hemorrhoid", "fissure", "fistula", "fistulectomy"),
    ),
    ("6.2.16 pilonidal sinus, sinusitis", 24, ("pilonidal", "sinusitis")),
    (
        "6.2.17 prolapsed intervertebral disc and spinal diseases",
        24,
        ("pivd", "disc prolapse", "prolapsed intervertebral disc", "discectomy", "laminectomy"),
    ),
    (
        "6.2.18 calculi in urinary system, gall bladder and bile duct",
        24,
        (
            "calculus",
            "calculi",
            "stone",
            "gallstone",
            "ureteroscopy",
            "lithotripsy",
            "pcnl",
            "cholecystectomy",
            "cholelithiasis",
            "choledocholithiasis",
        ),
    ),
    ("6.2.19 varicose veins and varicose ulcers", 24, ("varicose",)),
    ("6.2.20 internal congenital anomalies", 24, ("internal congenital",)),
    (
        "6.2.21 joint replacement",
        36,
        ("joint replacement", "knee replacement", "hip replacement", "arthroplasty"),
    ),
    ("6.2.22 age-related osteoarthritis and osteoporosis", 36, ("osteoarthritis", "osteoporosis")),
)
#: 6.2.18 says "excluding malignancy".
MALIGNANCY_TERMS = ("malignan", "cancer", "carcinoma")


def _mentions(text: str, terms: tuple[str, ...]) -> bool:
    return any(re.search(rf"\b{re.escape(t)}(?:s|es)?\b", text) for t in terms)


def specific_wait(text: str) -> tuple[str, int] | None:
    """The first 6.2 list item the diagnosis/procedure text names, with its months, or None."""
    for item, months, terms in SPECIFIC_WAITS:
        if item.startswith("6.2.18") and any(m in text for m in MALIGNANCY_TERMS):
            continue
        if _mentions(text, terms):
            return item, months
    return None


def _add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


# Bill-line wording -> policy wording (query rewriting, L6). Extend from the dev claims.
REWRITE = {
    "ot charges": "operation theatre charges",
    "rmo": "medical practitioner fees",
    "pharmacy": "medicines and drugs",
    "consumables": "excluded items consumables non-payable",
}

#: How much of each candidate clause the model is shown (and the judge checks rationales against).
CANDIDATE_CHARS = 400

SYSTEM = f"""You are the coverage analyst for Arogya Sanjeevani reimbursement claims.
For EVERY bill line choose exactly one clause_id from that line's CANDIDATES that governs how the
line is paid or deducted. Do not compute any amounts: a calculator does that.
{DATA_RULE}
If PLAYBOOK LESSONS are given, apply each one only when its 'applies when' condition holds.
If CRITIC FEEDBACK is given, fix exactly the problems it names and keep other choices."""


class CoverageAgent:
    name = AgentName.COVERAGE

    def __init__(self, services: Services, playbook=None, lesson_k: int = 3, chooser=None):
        self.svc = services
        self.belt = ToolBelt(self.name, services.registry(), services.tool_log)
        self.llm = get_llm("coverage")
        self.playbook = playbook  # reflexion.Playbook | None; only APPROVED lessons come out
        self.lesson_k = lesson_k
        # Optional replacement for the clause-selection call only (L12 §6-7: a compiled DSPy
        # program, see reflexion/dspy_coverage.py). Same inputs as _ask_model, same validation
        # below; admissibility, candidates and the calculator are untouched.
        self.chooser = chooser
        # From the latest choose_clauses call, for the eval judge (RAGAS faithfulness): the model's
        # one-sentence rationale per line it decided (never for a fallback or a human override),
        # and the candidate wording it was shown for each line. Nothing in the graph reads these.
        self.rationales: dict[str, str] = {}
        #: The clause each rationale argues for. An adjudicator edit (apply_edits) can later lock
        #: another clause without a new choose_clauses call; a reader must then drop the reason.
        self.rationale_clauses: dict[str, str] = {}
        self.shown: dict[str, list[str]] = {}

    # ---------------- admissibility (deterministic) ----------------
    def check_admissibility(self, claim: Claim) -> Admissibility:
        pol = self.belt.call("get_policy", policy_number=claim.policy_number)
        if pol is None:
            return Admissibility(
                admissible=False, needs_review=True, reasons=["policy not found in claims-db"]
            )
        reasons, ids = [], []
        diag = claim.diagnosis.lower()
        if not (pol.period_start <= claim.admission_date <= pol.period_end):
            reasons.append("admission date outside the policy period")
            ids.append(C.POLICY_PERIOD)  # clause 2: cover only "during the policy period"
        else:
            # Waiting periods only apply to a stay inside cover. An admission outside the period
            # cites clause 2 alone (Domain lead ruling 2026-11-12, ADR-0011; gold CLM-0013).
            if claim.admission_date < pol.first_inception + timedelta(days=30):
                # TODO: accident cases are exempt from the 30-day wait; add once extraction tags
                # them
                reasons.append("within the 30-day initial waiting period")
                ids.append(C.INITIAL_WAITING_PERIOD)
            if any(
                p.lower() in diag for p in pol.declared_peds
            ) and claim.admission_date < pol.first_inception + timedelta(days=36 * 30):
                # TODO: use exact month arithmetic and the wording's PED period (CIS says 36
                # months, table of benefits says 4 years: resolve with the domain lead)
                reasons.append("pre-existing disease within its waiting period")
                ids.append(C.PED_WAITING_PERIOD)
            listed = specific_wait(f"{diag} {(claim.procedure or '').lower()}")
            if listed and claim.admission_date < _add_months(pol.first_inception, listed[1]):
                # TODO: accidents are exempt (6.2(a)); add once the claim carries an accident
                # indicator. Until then a person decides (Domain lead ruling, ADR-0011).
                reasons.append(
                    f"specific waiting period: {listed[0]}, {listed[1]} months from first inception"
                )
                ids.append(C.SPECIFIC_WAITING_PERIOD)
        if any(t in diag for t in CHILDBIRTH_TERMS) and not any(
            t in diag for t in MATERNITY_CARVE_OUTS
        ):
            reasons.append("childbirth / caesarean is excluded (maternity exclusion)")
            ids.append(C.MATERNITY_EXCLUSION)
        needs_review = pol.insured_pseudonym != claim.patient_pseudonym
        if needs_review:
            reasons.append("patient on the bill does not match the insured person")
        return Admissibility(
            admissible=not reasons, needs_review=needs_review, reasons=reasons, clause_ids=ids
        )

    # ---------------- clause selection (model) ----------------
    def candidates(self, claim: Claim) -> dict[str, list]:
        out = {}
        for line in claim.bill_lines:
            q = line.description.lower()
            for k, v in REWRITE.items():
                q = q.replace(k, v)
            out[line.line_id] = self.belt.call(
                "policy_search", query=q, category=line.category.value
            )
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
        model_rationales: dict[str, str] = {}
        self.shown = {
            lid: [p.clause.text[:CANDIDATE_CHARS] for p in ps] for lid, ps in cands.items()
        }

        if self.chooser is not None:
            choices = self.chooser(claim, cands, lessons, critic_feedback, previous)
        elif self.llm is None:
            # Stub: top-ranked candidate; a lesson whose 'applies when' names the line category
            # re-points it to the lesson's first clause. Crude, but it lets the Reflexion harness
            # show a before/after effect offline. The real model reads lessons from the prompt.
            choices = {}
            for line in claim.bill_lines:
                ps = cands[line.line_id]
                pick = (previous or {}).get(line.line_id) or ps[0].clause.clause_id
                for l in lessons:
                    if (
                        line.category.value in l.applies_when.lower().split()
                        and l.clause_ids
                        and l.clause_ids[0] in {p.clause.clause_id for p in ps}
                    ):
                        pick = l.clause_ids[0]
                choices[line.line_id] = pick
        else:
            choices = self._ask_model(
                claim, cands, lessons, critic_feedback, previous, rationales=model_rationales
            )
        picked = dict(choices)

        for lid, ps in cands.items():  # validate: the model may only pick a retrieved clause
            # ...and never a claim-level ruling (clause 2, waiting periods, maternity): those
            # deduct a line in full and only the admissibility gate applies them (ADR-0010).
            line_ids = [p.clause.clause_id for p in ps if p.clause.clause_id not in C.CLAIM_LEVEL]
            if choices.get(lid) not in line_ids:
                fallback = line_ids[0] if line_ids else C.HOSPITALISATION
                notes.append(
                    f"{lid}: model chose {choices.get(lid)!r} outside the line-level candidates; "
                    f"fell back to {fallback}"
                )
                choices[lid] = fallback
        choices.update(locked)  # a human decision always wins
        self.rationales = {
            lid: why
            for lid, why in model_rationales.items()
            if lid not in locked and choices.get(lid) == picked.get(lid) and why.strip()
        }
        self.rationale_clauses = {lid: choices[lid] for lid in self.rationales}
        return choices, [l.lesson_id for l in lessons], notes

    def _ask_model(
        self, claim, cands, lessons, critic_feedback, previous, rationales=None
    ) -> dict[str, str]:
        """{line_id: clause_id}. Pass a dict as `rationales` to receive the model's reasons."""
        lines = []
        for line in claim.bill_lines:
            cand = "\n".join(
                f"    - {p.clause.clause_id}: {p.clause.text[:CANDIDATE_CHARS]}"
                for p in cands[line.line_id]
            )
            lines.append(
                f"{line.line_id} | {line.category.value} | {line.description} | "
                f"Rs {line.amount} | days={line.days}\n  CANDIDATES:\n{cand}"
            )
        parts = [
            f"Room category: {claim.room_category.value}; nights: {claim.nights}; "
            f"diagnosis: {claim.diagnosis}; procedure: {claim.procedure}",
            "BILL LINES:\n" + "\n".join(lines),
        ]
        if lessons:
            parts.append(
                "PLAYBOOK LESSONS:\n"
                + "\n".join(
                    f"- [{l.lesson_id}] {l.text} (applies when: {l.applies_when})" for l in lessons
                )
            )
        if critic_feedback:
            parts.append("PREVIOUS CHOICES: " + str(previous))
            parts.append("CRITIC FEEDBACK:\n" + "\n".join(f"- {f}" for f in critic_feedback))
        out = self.llm.with_structured_output(CoverageDecision).invoke(
            [("system", SYSTEM), ("human", "\n\n".join(parts))]
        )
        if rationales is not None:
            rationales.update({c.line_id: c.rationale for c in out.choices})
        return {c.line_id: c.clause_id for c in out.choices}

    # ---------------- rupees: always the calculator ----------------
    def adjudicate(
        self,
        claim: Claim,
        choices: dict[str, str],
        version: int = 1,
        fraud_flags: list[str] | None = None,
    ) -> Worksheet:
        return self.belt.call(
            "calculate",
            claim=claim,
            clause_choices=choices,
            version=version,
            fraud_flags=fraud_flags or [],
        )
