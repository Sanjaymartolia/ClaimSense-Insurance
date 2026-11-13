"""The tool sequence the documented graph requires. Written here, not read from `graph/`.

Tool order is fixed in Python, so given the branch decisions a run took (admissible, critic verdict,
reviewer replies) there is exactly one correct sequence. Those decisions come from the run, because
judging them is the job of the outcome metrics in `eval/harness`. The deduction count only sizes
the critic's `get_clause` loop.

Source: `docs/capstone-guide.pdf` pp. 9-10 and the pipeline diagram at the top of `graph/nodes.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

COVERAGE, FRAUD, CRITIC, SETTLEMENT = "coverage", "fraud", "critic", "settlement"
MAX_REVISIONS = 1

#: Payable above this needs a senior sign-off. Spec value, `config/models.yaml` approval block.
SENIOR_THRESHOLD = Decimal("100000")

Call = tuple[str | None, str]


@dataclass
class PathFacts:
    n_lines: int
    has_procedure: bool
    admissible: bool
    critic_passed: list[bool]
    critic_deductions: list[int]
    reviews: list[tuple[str, str]]  # (level, decision)
    gate_has_clause: bool = True  # an inadmissible ruling that names its clause (ADR-0010)


def _fraud(f: PathFacts) -> list[Call]:
    calls: list[Call] = [(FRAUD, "claim_history"), (FRAUD, "get_policy")]
    if f.has_procedure:
        calls.append((FRAUD, "tariff_range"))
    return calls


def _adjudication(f: PathFacts) -> list[Call]:
    calls: list[Call] = [(COVERAGE, "policy_search")] * f.n_lines + [(COVERAGE, "calculate")]
    calls += _fraud(f)
    # The fraud node rebuilds the worksheet with the flags, through the coverage agent's belt.
    calls.append((COVERAGE, "calculate"))
    return calls


def _critic(deductions: int) -> list[Call]:
    return [(CRITIC, "calculate")] + [(CRITIC, "get_clause")] * deductions


def expected_calls(f: PathFacts) -> list[Call]:
    calls: list[Call] = [(COVERAGE, "get_policy")]
    if not f.admissible:
        # ADR-0010: the Rs 0 worksheet for a not-admissible claim comes from the calculator.
        if f.gate_has_clause:
            calls.append((COVERAGE, "calculate"))
        if f.reviews and f.reviews[-1][1] == "approve":
            calls += [(SETTLEMENT, "record_repudiation"), (None, "record_history")]
        return calls

    critic_runs = iter(zip(f.critic_passed, f.critic_deductions, strict=False))
    revisions = 0
    while True:
        calls += _adjudication(f)
        passed, deductions = next(critic_runs, (True, 0))
        calls += _critic(deductions)
        if passed or revisions >= MAX_REVISIONS:
            break
        revisions += 1

    for _, decision in f.reviews:
        if decision == "edit":
            # B7: an edit re-runs the fraud screen on the edited claim, then recalculates.
            calls += _fraud(f)
            calls.append((COVERAGE, "calculate"))
            calls += _critic(next(critic_runs, (True, 0))[1])
    if f.reviews and f.reviews[-1][1] == "approve":
        # Payment ceiling (L15, dc934a7): the settlement agent reads the policy record first.
        calls += [
            (SETTLEMENT, "get_policy"),
            (SETTLEMENT, "settle_claim"),
            (None, "record_history"),
        ]
    return calls


def senior_required(total_payable: Decimal, fraud_flags: list[str]) -> bool:
    return total_payable > SENIOR_THRESHOLD or bool(fraud_flags)
