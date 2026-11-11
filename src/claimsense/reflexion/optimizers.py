"""L12 notebook §6-9 on ClaimSense: every lever on the clause choice, one table.

| notebook row                  | here                                             | lever     |
|-------------------------------|--------------------------------------------------|-----------|
| Baseline (think first)        | the shipped coverage prompt, no playbook         | nothing   |
| Reflexion playbook            | shipped prompt + the frozen run-02 playbook      | memory    |
| DSPy Predict / ChainOfThought | `ChooseClauses` as Predict / ChainOfThought      | module    |
| BootstrapFewShot              | demos the student solved on the training half    | prompt    |
| BootstrapFewShot + coach      | demos from the reflector model                   | prompt    |
| GEPA                          | instruction rewritten from the metric's feedback | prompt    |
| (eval harness) gold replay    | ceiling: gold choice wherever it was retrievable | retrieval |

The notebook's one rule holds: a method may learn from the training half only, the test half is
only ever scored. Both halves are development claims; the held-out set never comes near this file.

Two numbers per row, from the same evaluator for every row:
- clause accuracy on reachable lines (`dspy_coverage.score_choices`), what the prompt controls;
- settlement error / exact match / edit rate through the whole pipeline (`loop.evaluate`), what
  the adjudicator sees. The money is a guard, not the target: rule 1 keeps it in the calculator.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from pathlib import Path

import dspy

from claimsense.agents import CoverageAgent
from claimsense.contracts import Claim

from .dspy_coverage import (
    ChooseClauses,
    Models,
    ServicesFactory,
    gold_chooser,
    make_metric,
    program_chooser,
    score_choices,
)
from .evaluator import DevCase
from .loop import evaluate, local_run_fn
from .metrics import summarize
from .playbook import Playbook

OPTIMIZED = (
    "DSPy Predict",
    "DSPy ChainOfThought",
    "BootstrapFewShot",
    "BootstrapFewShot + coach",
    "GEPA",
)
LEVER = {
    "Agent prompt (as shipped)": "nothing: the prompt we wrote",
    "Agent prompt + Reflexion playbook": "memory: approved lessons the analyst reads",
    "DSPy Predict": "nothing: DSPy wrote the prompt",
    "DSPy ChainOfThought": "the module: reason before answering",
    "BootstrapFewShot": "prompt: worked examples it already solved",
    "BootstrapFewShot + coach": "prompt: worked examples from the reflector model",
    "GEPA": "prompt: a rewritten instruction",
    "Ceiling: gold replay within candidates": "retrieval: what the candidates allow",
}


# ------------------------------------------------------------------------------ the split
def split_cases(cases: list[DevCase]) -> tuple[list[DevCase], list[DevCase]]:
    """Admissible development cases only, sorted by id, alternating train / test. Deterministic,
    disjoint, and the same for every method so the rows are comparable."""
    adm = sorted((c for c in cases if c.gold_admissible), key=lambda c: c.case_id)
    return adm[0::2], adm[1::2]


# ------------------------------------------------------------------------------ one row
@dataclass
class MethodResult:
    name: str
    lever: str
    train_accuracy: float | None
    test_accuracy: float
    per_case: list[dict]  # test half: case_id, accuracy, wrong, unreachable
    settlement_error_total_rs: str
    exact_match_rate: float
    edit_rate: float
    prompt_chars: int
    demos: int  # labelled + bootstrapped demos in the prompt
    bootstrapped: int  # demos that came from a trace the metric accepted
    compile_seconds: float
    lm_calls: int
    instruction: str = ""
    notes: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return asdict(self)


def clause_accuracy(
    cases: list[DevCase], services_factory: ServicesFactory, chooser=None, playbook=None
) -> tuple[float, list[dict]]:
    """Mean clause accuracy over cases, through `CoverageAgent.choose_clauses` (so the agent's own
    candidate validation applies to every row, DSPy or not)."""
    rows = []
    for case in cases:
        svc = services_factory(case)
        agent = CoverageAgent(svc, playbook=playbook, chooser=chooser)
        claim = Claim.model_validate(case.packet["claim"])
        choices, _, _ = agent.choose_clauses(claim)
        cands = {
            lid: [p.clause.clause_id for p in ps] for lid, ps in agent.candidates(claim).items()
        }
        s = score_choices(case, cands, choices, svc.calculate)
        rows.append(
            {
                "case_id": case.case_id,
                "accuracy": round(s.accuracy, 3),
                "wrong": [list(w) for w in s.wrong],
                "unreachable": s.unreachable,
                "settlement_error_rs": str(s.settlement_error),
            }
        )
    mean = sum(r["accuracy"] for r in rows) / len(rows) if rows else 0.0
    return round(mean, 3), rows


def first_predictor(program: dspy.Module) -> dspy.Predict:
    return next(iter(program.named_predictors()))[1]


def instruction_of(program: dspy.Module) -> str:
    return first_predictor(program).signature.instructions


def prompt_chars(program: dspy.Module) -> int:
    """What every call pays for: instruction plus demos (the notebook's §7.3 warning)."""
    p = first_predictor(program)
    demos = sum(len(json.dumps(d.toDict(), default=str)) for d in p.demos)
    return len(p.signature.instructions) + demos


def measure(
    name: str,
    train: list[DevCase],
    test: list[DevCase],
    services_factory: ServicesFactory,
    tolerance_rs: Decimal,
    *,
    chooser=None,
    playbook: Playbook | None = None,
    program: dspy.Module | None = None,
    compile_seconds: float = 0.0,
    lm_calls: int = 0,
    notes: list[str] | None = None,
) -> MethodResult:
    train_acc, _ = clause_accuracy(train, services_factory, chooser, playbook)
    test_acc, per_case = clause_accuracy(test, services_factory, chooser, playbook)
    pipe = summarize(
        evaluate(local_run_fn(services_factory, chooser=chooser), test, playbook, tolerance_rs)
    )
    return MethodResult(
        name=name,
        lever=LEVER.get(name, ""),
        train_accuracy=train_acc,
        test_accuracy=test_acc,
        per_case=per_case,
        settlement_error_total_rs=str(pipe["settlement_error_total_rs"]),
        exact_match_rate=pipe["exact_match_rate"],
        edit_rate=pipe["edit_rate"],
        prompt_chars=prompt_chars(program) if program is not None else 0,
        demos=len(first_predictor(program).demos) if program is not None else 0,
        bootstrapped=(
            sum(bool(d.get("augmented")) for d in first_predictor(program).demos)
            if program is not None
            else 0
        ),
        compile_seconds=round(compile_seconds, 1),
        lm_calls=lm_calls,
        instruction=instruction_of(program) if program is not None else "",
        notes=list(notes or []),
    )


# ------------------------------------------------------------------------------ optimizers
def compile_bootstrap(
    trainset: list[dspy.Example], metric, teacher_lm: dspy.BaseLM | None = None, demos: int = 4
) -> tuple[dspy.Module, float]:
    """§7.1 / §7.2: keep worked examples that pass the metric; with `teacher_lm` the stronger
    model produces them. Returns (program, seconds)."""
    t0 = time.time()
    kw = {"teacher_settings": {"lm": teacher_lm}} if teacher_lm is not None else {}
    bfs = dspy.BootstrapFewShot(
        metric=metric, max_bootstrapped_demos=demos, max_labeled_demos=demos, **kw
    )
    program = bfs.compile(dspy.ChainOfThought(ChooseClauses), trainset=trainset)
    return program, time.time() - t0


def compile_gepa(
    trainset: list[dspy.Example],
    metric,
    reflection_lm: dspy.BaseLM,
    max_metric_calls: int = 100,
    seed: int = 0,
    num_threads: int = 1,
    valset: list[dspy.Example] | None = None,
) -> tuple[dspy.Module, float]:
    """§7.3: reflect on failures with the metric's feedback, rewrite the instruction. With only a
    handful of training claims the validation set defaults to the training set (the notebook split
    12/12 of 24); the test half is still never seen."""
    t0 = time.time()
    gepa = dspy.GEPA(
        metric=metric,
        max_metric_calls=max_metric_calls,
        num_threads=num_threads,
        seed=seed,
        reflection_lm=reflection_lm,
        warn_on_score_mismatch=False,
    )
    program = gepa.compile(
        dspy.ChainOfThought(ChooseClauses), trainset=trainset, valset=valset or trainset
    )
    return program, time.time() - t0


# ------------------------------------------------------------------------------ the table
def choose_winner(results: list[MethodResult]) -> tuple[str, str]:
    """Among the optimizable rows: highest test clause accuracy; ties go to the lower settlement
    error, then to the shorter prompt (every extra character is read on every claim). Returns
    (name, reason)."""
    rows = [r for r in results if r.name in OPTIMIZED]
    if not rows:
        return "", "no optimizable rows"
    best = sorted(
        rows,
        key=lambda r: (-r.test_accuracy, Decimal(r.settlement_error_total_rs), r.prompt_chars),
    )[0]
    tied = [r.name for r in rows if r.test_accuracy == best.test_accuracy and r is not best]
    reason = f"highest test clause accuracy ({best.test_accuracy})"
    if tied:
        reason += (
            f"; tied with {', '.join(tied)} on accuracy, chosen on settlement error then prompt "
            f"length ({best.prompt_chars} chars)"
        )
    return best.name, reason


def comparison_md(results: list[MethodResult], winner: tuple[str, str]) -> str:
    rows = [
        "| method | train acc | test acc | test settlement error Rs | exact | edit rate | "
        "prompt chars | demos (bootstrapped) | compile s | LM calls | what changed |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        mark = " **(chosen)**" if r.name == winner[0] else ""
        rows.append(
            f"| {r.name}{mark} | {'-' if r.train_accuracy is None else r.train_accuracy} | "
            f"{r.test_accuracy} | {r.settlement_error_total_rs} | {r.exact_match_rate} | "
            f"{r.edit_rate} | {r.prompt_chars} | {r.demos} ({r.bootstrapped}) | "
            f"{r.compile_seconds} | {r.lm_calls} | "
            f"{r.lever} |"
        )
    return "\n".join(rows)


def plot(results: list[MethodResult], path: str | Path) -> bool:
    """Bar chart of test clause accuracy and settlement error per method. False if matplotlib is
    not installed (the docs extra); the report then says so instead of failing."""
    import os
    import tempfile

    os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "claimsense-mpl"))
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    names = [r.name.replace(": ", ":\n").replace(" + ", "\n+ ") for r in results]
    fig, (a, b) = plt.subplots(1, 2, figsize=(14, 5))
    a.bar(names, [r.test_accuracy for r in results], color="#4c72b0")
    a.set_ylim(0, 1.05)
    a.set_title("Clause accuracy on reachable lines (test half)")
    a.tick_params(axis="x", labelrotation=60, labelsize=7)
    b.bar(names, [float(r.settlement_error_total_rs) for r in results], color="#dd8452")
    b.set_title("Settlement error, test half (Rs, through the pipeline)")
    b.tick_params(axis="x", labelrotation=60, labelsize=7)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return True


def save_program(program: dspy.Module, path: str | Path) -> None:
    """§7.5: the improvement is a file (instruction + demos), reviewable and revertible."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    program.save(str(path))


def load_program(path: str | Path, chain_of_thought: bool = True) -> dspy.Module:
    program = (
        dspy.ChainOfThought(ChooseClauses) if chain_of_thought else dspy.Predict(ChooseClauses)
    )
    program.load(str(path))
    return program


def lm_calls_since(models: Models, before: int) -> int:
    return models.calls() - before


__all__ = [
    "LEVER",
    "OPTIMIZED",
    "MethodResult",
    "choose_winner",
    "clause_accuracy",
    "comparison_md",
    "compile_bootstrap",
    "compile_gepa",
    "gold_chooser",
    "instruction_of",
    "lm_calls_since",
    "load_program",
    "make_metric",
    "measure",
    "plot",
    "program_chooser",
    "prompt_chars",
    "save_program",
    "split_cases",
]
