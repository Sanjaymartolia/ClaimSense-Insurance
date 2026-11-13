"""Triage before reflection: only a clause-choice mistake can become a lesson.

L12's point: when a lesson cannot fix something, change something else. The coverage analyst's one
decision is which retrieved clause governs a bill line, so a lesson can only ever move that choice.
Every other kind of mistake (an admissibility ruling, a calculator or gold gap, a critic arithmetic
issue) goes to an engineering backlog with a reason, instead of to the reflector and the reviewer.
In `run-03` the reviewer rejected 16 of 16 proposals, and 14 of them fail these rules.

Also here: the registry of clause ids the agents know (`known_clause_ids`). The reflector drops any
other id from a draft (REF-08: invented ids), and never invents one itself.
"""

from __future__ import annotations

from claimsense.agents import clauses as C

from .evaluator import Mistake

# Critic issue kinds that are about the clause cited on a line; the rest are arithmetic/totals.
_CITATION_KINDS = ("missing_clause", "unknown_clause", "unsupported_clause")
# Backlog reason when the reflector's guard dropped the draft (too specific, or no known clause).
NO_LESSON = "reflector drew no usable lesson (specific text or unknown clause id)"


def known_clause_ids() -> set[str]:
    """Every clause id the agents refer to by name (agents/clauses.py)."""
    return {v for v in vars(C).values() if isinstance(v, str) and v.startswith(C.P) and v != C.P}


def is_clause_choice(m: Mistake) -> tuple[bool, str]:
    """(True, "") when a lesson could have prevented this mistake; otherwise (False, reason)."""
    if not m.line_id:
        return False, "claim-level finding (admissibility), not a per-line clause choice"
    if m.source == "critic_rejection":
        kind = m.detail.split(":", 1)[0].strip()
        if kind not in _CITATION_KINDS:
            return False, f"critic '{kind}' issue is arithmetic or totals, not a clause choice"
        if m.got_clause in C.CLAIM_LEVEL:
            return (
                False,
                "deduction under a claim-level clause is made by the gate or the calculator, "
                "not chosen by the analyst; a critic item",
            )
        return True, ""
    if m.expected_clause in C.CLAIM_LEVEL:
        return (
            False,
            "expected clause is a claim-level ruling applied by the admissibility gate (ADR-0010)",
        )
    if not m.expected_clause and not m.got_clause:
        return False, "no clause named on either side"
    if m.expected_clause and m.got_clause and m.expected_clause == m.got_clause:
        return (
            False,
            "same clause as the gold; the amount difference is a calculator or gold gap "
            "(RULE_DISAGREEMENTS), not a clause choice",
        )
    return True, ""


def backlog_entry(m: Mistake, reason: str) -> dict:
    return {
        "case_id": m.case_id,
        "line_id": m.line_id,
        "source": m.source,
        "got_clause": m.got_clause,
        "expected_clause": m.expected_clause,
        "reason": reason,
        "detail": m.detail[:160],
    }


def backlog_md(rows: list[dict]) -> str:
    if not rows:
        return "- none"
    return "\n".join(
        f"- {r['case_id']} {r['line_id'] or '(claim)'} [{r['source']}]: {r['reason']}" for r in rows
    )
