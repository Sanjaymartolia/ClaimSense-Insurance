"""The Reflexion experiment: baseline → learn on dev → ablate → freeze → held-out.

    actor      = the whole pipeline (the coverage analyst reads the playbook)
    evaluator  = simulated adjudicator + critic + gold diff  (evaluator.py)
    reflector  = reflect()                                    (reflector.py)
    memory     = Playbook, APPROVED lessons only               (playbook.py)

`run_fn(case, playbook, reviewer) -> final_state` hides which executor you use:
`local_run_fn` (no LangGraph, fast, for dry runs) or `langgraph_run_fn` (the real graph).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable

from claimsense.agents import Services, Team
from claimsense.contracts import Lesson

from .evaluator import DevCase, Mistake, SimulatedAdjudicator, mistakes_from_run
from .metrics import CaseResult, compare_table, summarize
from .playbook import Playbook
from .reflector import reflect

RunFn = Callable[[DevCase, Playbook | None, Callable[[dict], dict]], dict]
ServicesFactory = Callable[[DevCase], Services]
# A human gate: (lesson) -> (approved?, reviewer_id, note). In the real run this is the review
# CLI (review_cli.py) or the case UI. Never auto-approve in the reported experiment.
ApproveFn = Callable[[Lesson], tuple[bool, str, str | None]]


def local_run_fn(services_factory: ServicesFactory) -> RunFn:
    from claimsense.graph import LocalRunner

    def run(case, playbook, reviewer):
        return LocalRunner(Team(services_factory(case), playbook=playbook)).run(case.packet, reviewer)
    return run


def langgraph_run_fn(services_factory: ServicesFactory) -> RunFn:
    from claimsense.graph import build_graph, memory_checkpointer, run_claim

    def run(case, playbook, reviewer):
        app = build_graph(Team(services_factory(case), playbook=playbook),
                          checkpointer=memory_checkpointer())
        return run_claim(app, case.packet, reviewer, thread_id=f"{case.case_id}-{id(playbook)}")
    return run


# ------------------------------------------------------------------------------ one pass
def run_case(run_fn: RunFn, case: DevCase, playbook: Playbook | None) -> tuple[CaseResult, list[Mistake]]:
    adj = SimulatedAdjudicator(case)
    final = run_fn(case, playbook, adj)
    first = adj.first_payload or {}
    proposed = Decimal(first["worksheet"]["total_payable"]) if first.get("worksheet") else None
    gold = case.gold_worksheet.total_payable if case.gold_worksheet else None
    if not case.gold_admissible:
        gold = Decimal(0)
    if first.get("kind") == "repudiation":
        proposed = Decimal(0)
    err = abs(proposed - gold) if proposed is not None and gold is not None else Decimal(0)
    result = CaseResult(
        case_id=case.case_id, proposed_total=proposed, gold_total=gold, abs_error=err,
        edited=adj.edited,
        lines_edited=len(final.get("edit_log", [])),
        critic_rejections=sum(not r.passed for r in final.get("critic_history", [])),
        lessons_used=final.get("lessons_used", []), status=final.get("status", "?"))
    return result, mistakes_from_run(case, final, adj)


def evaluate(run_fn: RunFn, cases: list[DevCase], playbook: Playbook | None) -> list[CaseResult]:
    return [run_case(run_fn, c, playbook)[0] for c in cases]


# ------------------------------------------------------------------------------ learning
def learn(run_fn: RunFn, cases: list[DevCase], playbook: Playbook, approve_fn: ApproveFn,
          get_clause_text: Callable[[str], str] = lambda cid: "") -> list[Lesson]:
    """One pass over dev cases in order. Each mistake → reflect → PROPOSED → human gate.
    Later cases read lessons approved on earlier ones (L12 notebook §5)."""
    assert all(c.split == "dev" for c in cases), "Reflexion may only learn from development cases"
    proposed: list[Lesson] = []
    for case in cases:
        _, mistakes = run_case(run_fn, case, playbook)
        for m in mistakes:
            draft = reflect(m, get_clause_text(m.expected_clause or ""))
            if draft is None:
                continue
            lesson = playbook.propose(draft.lesson, draft.applies_when, draft.clause_ids, case.case_id)
            if lesson is None:  # duplicate
                continue
            proposed.append(lesson)
            ok, reviewer, note = approve_fn(lesson)
            if ok:
                playbook.approve(lesson.lesson_id, reviewer, note)
            else:
                playbook.reject(lesson.lesson_id, reviewer, note or "rejected by reviewer")
        playbook.save()
    return proposed


def ablate(run_fn: RunFn, cases: list[DevCase], playbook: Playbook) -> list[dict]:
    """Leave-one-lesson-out. A lesson is harmful if removing it lowers error or edit rate."""
    full = summarize(evaluate(run_fn, cases, playbook))
    rows = []
    for lesson in playbook.by_status("approved"):
        s = summarize(evaluate(run_fn, cases, playbook.without(lesson.lesson_id)))
        d_err = full["settlement_error_total_rs"] - s["settlement_error_total_rs"]
        d_edit = full["edit_rate"] - s["edit_rate"]
        rows.append({"lesson_id": lesson.lesson_id, "text": lesson.text,
                     "error_increase_rs": d_err, "edit_rate_increase": round(d_edit, 3),
                     "harmful": d_err > 0 or d_edit > 0})
    return rows


@dataclass
class Report:
    baseline: dict
    after: dict
    ablation: list[dict]
    withdrawn: list[str]
    frozen_hash: str
    heldout_baseline: dict | None = None
    heldout_after: dict | None = None
    per_case: dict = field(default_factory=dict)

    def markdown(self) -> str:
        parts = ["## Development claims", compare_table(self.baseline, self.after),
                 "", "## Lessons that made results worse (withdrawn)"]
        parts += [f"- {r['lesson_id']}: {r['text']} (+Rs {r['error_increase_rs']}, "
                  f"+{r['edit_rate_increase']} edit rate)" for r in self.ablation if r["harmful"]] or ["- none"]
        parts.append(f"\nFrozen playbook hash: `{self.frozen_hash}`")
        if self.heldout_after:
            parts += ["", "## Held-out claims (frozen playbook)",
                      compare_table(self.heldout_baseline, self.heldout_after)]
        return "\n".join(parts)


def experiment(run_fn: RunFn, dev: list[DevCase], playbook: Playbook, approve_fn: ApproveFn,
               heldout: list[DevCase] | None = None, reviewer_id: str = "lead-adjudicator",
               get_clause_text=lambda cid: "") -> Report:
    baseline = summarize(evaluate(run_fn, dev, None))
    learn(run_fn, dev, playbook, approve_fn, get_clause_text)
    ablation = ablate(run_fn, dev, playbook)
    withdrawn = []
    for r in ablation:
        if r["harmful"]:
            playbook.withdraw(r["lesson_id"], reviewer_id, "made dev results worse in ablation")
            withdrawn.append(r["lesson_id"])
    after = summarize(evaluate(run_fn, dev, playbook))
    frozen = playbook.freeze()
    report = Report(baseline, after, ablation, withdrawn, frozen)
    if heldout:
        report.heldout_baseline, report.heldout_after = run_heldout(run_fn, heldout, playbook, dev)
    return report


def run_heldout(run_fn: RunFn, heldout: list[DevCase], playbook: Playbook,
                dev: list[DevCase]) -> tuple[dict, dict]:
    """No reflection, no proposals: the playbook must be frozen, and must not contain a lesson
    learned from any held-out case."""
    if not playbook.frozen:
        raise RuntimeError("freeze the playbook before the held-out run")
    held_ids = {c.case_id for c in heldout}
    assert not held_ids & {c.case_id for c in dev}, "dev and held-out overlap"
    leaked = [l.lesson_id for l in playbook.lessons.values() if l.source_case_id in held_ids]
    assert not leaked, f"lessons learned from held-out cases: {leaked}"
    assert playbook.content_hash() == playbook.frozen_hash, "playbook changed after freezing"
    return summarize(evaluate(run_fn, heldout, None)), summarize(evaluate(run_fn, heldout, playbook))
