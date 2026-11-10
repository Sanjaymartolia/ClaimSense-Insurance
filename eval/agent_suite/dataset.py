"""L13 section 2: the eval dataset.

The lecture's recipe is roughly 50 / 30 / 20: production traffic, hand-written golden cases,
adversarial cases. ClaimSense has no production traffic yet, so the suite runs on what exists:

    source       split     cases  where it comes from
    golden       dev       20     eval/golden_dev: starter-pack claims with human gold
    adversarial  redteam   30     eval/redteam: a dev claim plus one attack (build_cases.py)
    production   -         0      none until the product runs on real (synthetic) traffic

The held-out set is never read (CLAUDE.md rule 5): every case comes through `eval.harness.loader`,
which refuses held-out paths and strips the answer-revealing fields before anything runs.

Each `Case` carries what the metrics need and the agent never sees: the right route, the right
settlement, the clause the gold cites per line, and for an attack, its id and the door it used.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from eval.harness.loader import load_cases
from eval.harness.models import EvalCase

SOURCES: dict[str, str] = {"dev": "golden", "redteam": "adversarial"}

#: Red-team categories that plant an instruction in the documents (RT-001, 007, 009-012).
INJECTION_CATEGORIES: frozenset[str] = frozenset({"prompt_injection", "hidden_text_instruction"})


@dataclass
class Case:
    eval_case: EvalCase
    claim_id: str
    split: str
    source: str  # golden | adversarial
    kind: str  # dev: "clean" or the gold's first review flag; red-team: the attack category
    #: True when a person must look at this claim. Sending it to review is then the right answer.
    escalation_ok: bool
    due: int  # gold settlement, whole rupees
    gold_clauses: dict[str, str] = field(default_factory=dict)  # line_id -> clause the gold cites
    n_lines: int = 0
    has_procedure: bool = False
    attack_id: str | None = None
    door: str | None = None

    @property
    def injected(self) -> bool:
        """An instruction was planted in a document or bill line."""
        return self.source == "adversarial" and self.kind in INJECTION_CATEGORIES


def to_case(ec: EvalCase) -> Case:
    gold = ec.gold
    source = SOURCES.get(ec.split, ec.split)
    if source == "adversarial":
        kind = gold.category or "attack"
    else:
        kind = (
            (gold.expected_review_flags or ["review"])[0] if gold.human_review_required else "clean"
        )
    return Case(
        eval_case=ec,
        claim_id=ec.claim_id,
        split=ec.split,
        source=source,
        kind=kind,
        escalation_ok=gold.human_review_required,
        due=gold.expected_settlement_inr,
        gold_clauses={li.line_id: li.clause_id for li in gold.line_items if li.clause_id},
        n_lines=len(ec.claim.bill_lines),
        has_procedure=any(b.category == "procedure" for b in ec.claim.bill_lines),
        attack_id=gold.attack_id,
        door=gold.door,
    )


def load_dataset(splits: tuple[str, ...] | list[str] = ("dev", "redteam")) -> list[Case]:
    return [to_case(ec) for ec in load_cases(list(splits))]


def composition(cases: list[Case]) -> str:
    by_source = Counter(c.source for c in cases)
    by_kind = Counter((c.source, c.kind) for c in cases)
    total = len(cases) or 1
    lines = [f"{len(cases)} cases"]
    for source in ("production", "golden", "adversarial"):
        n = by_source.get(source, 0)
        lines.append(f"  {source:<12} {n:>3}  ({n / total:.0%})")
    lines.append("by kind:")
    for (source, kind), n in sorted(by_kind.items()):
        lines.append(f"  {source:<12} {kind:<32} {n:>3}")
    review = sum(c.escalation_ok for c in cases)
    lines.append(f"{review} of {len(cases)} need a person; {len(cases) - review} may be cleared")
    return "\n".join(lines)
