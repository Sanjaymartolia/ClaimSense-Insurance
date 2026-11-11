"""DSPy on the coverage analyst's clause choice (L12 notebook §6-7, replicated on ClaimSense).

The notebook's assistant pays rupees. ClaimSense never lets a model do that (rule 1): the coverage
analyst only picks one clause per bill line and the calculator pays. So on ClaimSense

- the **signature** is the clause choice (`ChooseClauses`), fed exactly what the shipped prompt
  feeds the model (`render_inputs` mirrors `CoverageAgent._ask_model`);
- the **metric** is clause accuracy against the gold, counted only on *reachable* lines: lines whose
  gold clause is among the candidates the policy search returned. A line whose gold clause was
  never retrieved is a retrieval gap, not a choice the model could have made, so it is excluded
  from the score and reported as unreachable. The feedback text GEPA reads names, per wrong line,
  the clause the adjudicator cites and why (the gold deduction reason);
- the **money** is never in the score: it is reported beside it, through the ordinary pipeline
  (`loop.evaluate` with `chooser=`), so every lever is judged by the same evaluator.

Offline (stub mode, CI, tests) `StubLM` answers every DSPy prompt with the top-ranked candidate per
line, the same rule as the stub coverage analyst, and `OracleStubLM` plays the notebook's "coach"
so the BootstrapFewShot-with-teacher path is exercised. Their numbers are a harness check, never a
result; `scripts/run_reflexion_dspy.py` stamps the report accordingly.

Model ids come from `agents.llm.MODELS` (student = coverage, coach/reflection = reflector), so the
DSPy run uses the same models as the agents and the same `CLAIMSENSE_MODEL_*` overrides.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from decimal import Decimal

import dspy
from dspy.clients.engines.base import validate_request
from dspy.lm15 import Message, Response, TextPart, Usage

from claimsense.agents import CoverageAgent, Services, reference_calculate
from claimsense.agents.coverage import SYSTEM
from claimsense.agents.llm import MODELS, stub_mode
from claimsense.contracts import Claim, Lesson

from .evaluator import DevCase

INPUT_FIELDS = ("claim_context", "bill_lines", "lessons", "critic_feedback")


# ------------------------------------------------------------------------------ signature
class ChooseClauses(dspy.Signature):
    """Placeholder: replaced below by the shipped coverage prompt, so 'DSPy Predict' starts from
    the same instruction the agent uses and GEPA rewrites that text, not a new one."""

    claim_context: str = dspy.InputField(desc="room category, nights, diagnosis, procedure")
    bill_lines: str = dspy.InputField(
        desc="one block per bill line: id | category | description | amount | days, then its "
        "CANDIDATES as 'clause_id: wording'"
    )
    lessons: str = dspy.InputField(desc="approved playbook lessons with 'applies when', or 'none'")
    critic_feedback: str = dspy.InputField(
        desc="previous choices and the problems the critic found in them, or 'none'"
    )
    choices: dict[str, str] = dspy.OutputField(
        desc="line_id -> clause_id; every line, each clause_id one of that line's CANDIDATES"
    )


ChooseClauses = ChooseClauses.with_instructions(SYSTEM)  # type: ignore[misc]


# ------------------------------------------------------------------------------ rendering
def render_inputs(
    claim: Claim,
    cands: dict[str, list],
    lessons: Iterable[Lesson] = (),
    critic_feedback: list[str] | None = None,
    previous: dict[str, str] | None = None,
) -> dict[str, str]:
    """The same facts, in the same order, as `CoverageAgent._ask_model` puts in its prompt."""
    blocks = []
    for line in claim.bill_lines:
        cand = "\n".join(
            f"    - {p.clause.clause_id}: {p.clause.text[:400]}" for p in cands[line.line_id]
        )
        blocks.append(
            f"{line.line_id} | {line.category.value} | {line.description} | "
            f"Rs {line.amount} | days={line.days}\n  CANDIDATES:\n{cand}"
        )
    lesson_text = "\n".join(
        f"- [{les.lesson_id}] {les.text} (applies when: {les.applies_when})" for les in lessons
    )
    feedback = "none"
    if critic_feedback:
        feedback = f"PREVIOUS CHOICES: {previous}\n" + "\n".join(f"- {f}" for f in critic_feedback)
    return {
        "claim_context": (
            f"Room category: {claim.room_category.value}; nights: {claim.nights}; "
            f"diagnosis: {claim.diagnosis}; procedure: {claim.procedure}"
        ),
        "bill_lines": "\n".join(blocks),
        "lessons": lesson_text or "none",
        "critic_feedback": feedback,
    }


_CANDIDATE_BLOCK = re.compile(r"^(\S+) \|.*?\n  CANDIDATES:\n((?:    - .*(?:\n|$))+)", re.M)


def parse_candidates(bill_lines: str) -> dict[str, list[str]]:
    """Inverse of `render_inputs` for the candidate ids; the stub LMs read the prompt with it."""
    return {
        lid: re.findall(r"^    - (\S+):", block, re.M)
        for lid, block in _CANDIDATE_BLOCK.findall(bill_lines)
    }


# ------------------------------------------------------------------------------ examples
ServicesFactory = Callable[[DevCase], Services]


def candidate_ids(cands: dict[str, list]) -> dict[str, list[str]]:
    return {lid: [p.clause.clause_id for p in ps] for lid, ps in cands.items()}


def label_within_candidates(gold: dict[str, str], candidates: dict[str, list[str]]) -> dict:
    """The gold choice where it was retrievable, else the top candidate (the agent's own fallback).
    Used as the labelled demo, so a demo never shows an id the model is not allowed to pick."""
    return {
        lid: gold[lid] if gold.get(lid) in ids else ids[0] for lid, ids in candidates.items() if ids
    }


def coverage_examples(
    cases: list[DevCase], services_factory: ServicesFactory, playbook=None
) -> list[dspy.Example]:
    """One `dspy.Example` per admissible case. Non-admissible claims are decided by code
    (`CoverageAgent.check_admissibility`) before any clause is chosen, so there is nothing for a
    prompt to learn on them. Labels: `case_id`, `candidates` (ids per line) and `choices` (gold
    within candidates). `scenario_label` and `fixture_notes` never enter the packet (cases.py)."""
    out = []
    for case in cases:
        if not case.gold_admissible or case.gold_worksheet is None:
            continue
        claim = Claim.model_validate(case.packet["claim"])
        agent = CoverageAgent(services_factory(case), playbook=playbook)
        cands = agent.candidates(claim)
        ids = candidate_ids(cands)
        ex = dspy.Example(
            **render_inputs(claim, cands, agent.lessons_for(claim, cands)),
            case_id=case.case_id,
            candidates=ids,
            choices=label_within_candidates(case.gold_choices(), ids),
        )
        out.append(ex.with_inputs(*INPUT_FIELDS))
    return out


# ------------------------------------------------------------------------------ scoring
def validate_choices(choices: dict, candidates: dict[str, list[str]]) -> dict[str, str]:
    """Same rule as `CoverageAgent.choose_clauses`: a choice outside the line's candidates falls
    back to the top-ranked one; a missing line gets the top-ranked one."""
    return {
        lid: choices.get(lid) if choices.get(lid) in ids else ids[0]
        for lid, ids in candidates.items()
        if ids
    }


@dataclass
class ChoiceScore:
    case_id: str
    reachable: list[str]
    unreachable: list[str]  # gold clause not among the candidates: a retrieval gap
    wrong: list[tuple[str, str, str]]  # (line_id, chosen, expected) on reachable lines
    proposed_total: Decimal
    gold_total: Decimal
    feedback: str
    chosen: dict[str, str] = field(default_factory=dict)

    @property
    def accuracy(self) -> float:
        if not self.reachable:
            return 1.0
        return (len(self.reachable) - len(self.wrong)) / len(self.reachable)

    @property
    def settlement_error(self) -> Decimal:
        return abs(self.proposed_total - self.gold_total)


def score_choices(
    case: DevCase,
    candidates: dict[str, list[str]],
    choices: dict,
    calculate: Callable[..., object] = reference_calculate,
) -> ChoiceScore:
    """Clause accuracy on reachable lines, plus the rupee effect of exactly these choices."""
    assert case.gold_worksheet is not None, "score_choices needs a gold worksheet"
    gold = case.gold_choices()
    claim = Claim.model_validate(case.packet["claim"])
    chosen = validate_choices(choices, candidates)
    reachable = [lid for lid, ids in candidates.items() if gold.get(lid) in ids]
    unreachable = [lid for lid in candidates if lid in gold and lid not in reachable]
    wrong = [(lid, chosen[lid], gold[lid]) for lid in reachable if chosen[lid] != gold[lid]]
    ws = calculate(claim, chosen)
    reasons = {
        ln.line_id: ln.deductions[0].reason.value
        for ln in case.gold_worksheet.lines
        if ln.deductions
    }
    notes = [
        f"{lid}: chose {got}; the adjudicator cites {want}"
        + (f" ({reasons[lid].replace('_', ' ')})" if lid in reasons else " (payable in full)")
        for lid, got, want in wrong
    ] or ["Every reachable line cites the clause the adjudicator cites."]
    if unreachable:
        notes.append(
            f"Not scored (gold clause not among the candidates): {', '.join(unreachable)}."
        )
    notes.append(
        f"Settlement with these choices Rs {ws.total_payable} vs gold Rs "
        f"{case.gold_worksheet.total_payable}."
    )
    return ChoiceScore(
        case_id=case.case_id,
        reachable=reachable,
        unreachable=unreachable,
        wrong=wrong,
        proposed_total=ws.total_payable,
        gold_total=case.gold_worksheet.total_payable,
        feedback=" ".join(notes),
        chosen=chosen,
    )


def make_metric(cases: list[DevCase], services_factory: ServicesFactory):
    """A DSPy metric in the GEPA form: `(example, pred, trace, pred_name, pred_trace)`.
    - with `trace` (BootstrapFewShot deciding whether to keep a demo): True only when every
      reachable line is right;
    - otherwise `dspy.Prediction(score, feedback)`: score in [0, 1], feedback for the reflector."""
    by_id = {c.case_id: c for c in cases}

    def metric(example, pred, trace=None, pred_name=None, pred_trace=None):
        case = by_id[example.case_id]
        choices = getattr(pred, "choices", None)
        s = score_choices(
            case,
            example.candidates,
            choices if isinstance(choices, dict) else {},
            services_factory(case).calculate,
        )
        if trace is not None:
            return s.accuracy == 1.0
        return dspy.Prediction(score=s.accuracy, feedback=s.feedback)

    return metric


# ------------------------------------------------------------------------------ into the agent
def program_chooser(program: dspy.Module):
    """A `CoverageAgent.chooser`: the compiled program answers, the agent still validates."""

    def choose(claim, cands, lessons, critic_feedback, previous) -> dict[str, str]:
        pred = program(**render_inputs(claim, cands, lessons, critic_feedback, previous))
        out = getattr(pred, "choices", None)
        return dict(out) if isinstance(out, dict) else {}

    return choose


def gold_chooser(cases: list[DevCase]):
    """The ceiling: replay the gold choice wherever it was retrievable (eval 'gold-replay' idea).
    Anything above this needs better retrieval, not a better prompt."""
    gold = {}
    for c in cases:
        gold.update(c.gold_choices())

    def choose(claim, cands, lessons, critic_feedback, previous) -> dict[str, str]:
        return {lid: gold[lid] for lid in cands if lid in gold}

    return choose


# ------------------------------------------------------------------------------ offline LMs
STUB_INSTRUCTION = (
    "Choose, for every bill line, the one CANDIDATE clause that governs how it is paid or "
    "deducted; when the room or ICU rate is above its limit, cite the proportional-deduction "
    "note for the other expenses except medicines."
)

_OUTPUT_FIELDS = re.compile(r"Your output fields are:(.*?)(?:All interactions|Output format)", re.S)


def output_field_names(system_prompt: str) -> list[str]:
    m = _OUTPUT_FIELDS.search(system_prompt)
    return re.findall(r"^\d+\. `(\w+)`", m.group(1), re.M) if m else []


def _text(parts) -> str:
    return "".join(p.text for p in parts if isinstance(p, TextPart))


class _StubEngine:
    def __init__(self, owner: StubLM):
        self.owner = owner

    def complete(self, request):
        validate_request(request)
        system = request.system if isinstance(request.system, str) else _text(request.system or [])
        user = _text(request.messages[-1].parts) if request.messages else ""
        return Response(
            id=None,
            model=self.owner.model,
            message=Message.assistant([TextPart(self.owner.answer(system, user))]),
            finish_reason="stop",
            usage=Usage(input_tokens=0, output_tokens=0, total_tokens=0),
        )

    def close(self):
        pass


class StubLM(dspy.BaseLM):
    """Offline DSPy model: the top-ranked candidate per line, the stub analyst's rule. Any other
    output field gets fixed text, and a field named *instruction* (GEPA's reflector) gets
    `STUB_INSTRUCTION`, so the optimizer loops run without a key. Harness check only."""

    def __init__(self, name: str = "stub-student"):
        super().__init__(name, "chat", 0.0, 2000, False, engine=_StubEngine(self))
        self.calls = 0

    def pick(self, candidates: dict[str, list[str]]) -> dict[str, str]:
        return {lid: ids[0] for lid, ids in candidates.items() if ids}

    def answer(self, system: str, user: str) -> str:
        self.calls += 1
        cands = parse_candidates(user)
        out = {}
        for name in output_field_names(system):
            if name == "choices":
                out[name] = self.pick(cands)
            elif "instruction" in name:
                out[name] = STUB_INSTRUCTION
            else:
                out[name] = "Top-ranked candidate for every line."
        return json.dumps(out)


class OracleStubLM(StubLM):
    """Stub-mode stand-in for the notebook's *coach*: answers with the gold clause where it is a
    candidate. Only ever a BootstrapFewShot teacher on development cases, so the demos it produces
    are exactly what a stronger model's correct answers would be. Never a student."""

    def __init__(self, cases: list[DevCase], name: str = "stub-coach"):
        super().__init__(name)
        self.gold: dict[str, str] = {}
        for c in cases:
            self.gold.update(c.gold_choices())

    def pick(self, candidates: dict[str, list[str]]) -> dict[str, str]:
        return label_within_candidates(self.gold, candidates)


# ------------------------------------------------------------------------------ models
@dataclass
class Models:
    student: dspy.BaseLM
    coach: dspy.BaseLM
    reflection: dspy.BaseLM
    mode: str  # "stub" | "real"
    ids: dict[str, str]

    def calls(self) -> int:
        return sum(len(lm.history) for lm in (self.student, self.coach, self.reflection))


def configure_dspy(cases: list[DevCase] | None = None, cache: bool = True) -> Models:
    """Student = the coverage model, coach and reflector = the reflector model, as the agents use
    them (`agents.llm.MODELS`, overridable with `CLAIMSENSE_MODEL_COVERAGE` / `_REFLECTOR`). Stub
    mode (no key, or `CLAIMSENSE_LLM=stub`) gives the offline LMs above. The JSON adapter is used
    so the `choices` dict round-trips the same way for every model."""
    if stub_mode():
        models = Models(StubLM(), OracleStubLM(cases or []), StubLM("stub-reflection"), "stub", {})
    else:
        key = os.environ["OPENROUTER_API_KEY"]
        base = "https://openrouter.ai/api/v1"
        student_id, coach_id = MODELS["coverage"], MODELS["reflector"]
        models = Models(
            dspy.LM(
                "openrouter/" + student_id,
                api_key=key,
                api_base=base,
                temperature=0,
                max_tokens=2000,
                cache=cache,
            ),
            dspy.LM(
                "openrouter/" + coach_id,
                api_key=key,
                api_base=base,
                temperature=0,
                max_tokens=2000,
                cache=cache,
            ),
            dspy.LM(
                "openrouter/" + coach_id,
                api_key=key,
                api_base=base,
                temperature=1.0,
                max_tokens=4000,
                cache=cache,
            ),
            "real",
            {"student": student_id, "coach": coach_id, "reflection": coach_id},
        )
    dspy.configure(lm=models.student, adapter=dspy.JSONAdapter())
    return models


__all__ = [
    "INPUT_FIELDS",
    "ChoiceScore",
    "ChooseClauses",
    "Models",
    "OracleStubLM",
    "StubLM",
    "candidate_ids",
    "configure_dspy",
    "coverage_examples",
    "gold_chooser",
    "label_within_candidates",
    "make_metric",
    "parse_candidates",
    "program_chooser",
    "render_inputs",
    "score_choices",
    "validate_choices",
]
