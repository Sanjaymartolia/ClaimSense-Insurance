"""Markdown and JSON rendering shared by the Reflexion scripts (day 4 experiment, day 5 held-out).

Kept out of the scripts so both render results the same way and so a test can call them.
Nothing here decides anything: it only formats `CaseResult`s, summaries and the playbook.
"""

from __future__ import annotations

import json
from decimal import Decimal

from claimsense.agents.llm import stub_mode
from claimsense.contracts import LessonStatus

from .metrics import CaseResult, summarize
from .playbook import Playbook


def to_json(obj) -> str:
    return json.dumps(obj, indent=2, default=str)


def mode_label() -> str:
    return "STUB (deterministic, no model)" if stub_mode() else "REAL MODEL via OpenRouter"


def case_table(results: list[CaseResult]) -> str:
    rows = [
        "| case | status | proposed Rs | gold Rs | abs error Rs | edited | lines edited | "
        "critic rejections | lessons used |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        rows.append(
            f"| {r.case_id} | {r.status} | {r.proposed_total} | {r.gold_total} | {r.abs_error} | "
            f"{'yes' if r.edited else 'no'} | {r.lines_edited} | {r.critic_rejections} | "
            f"{', '.join(r.lessons_used) or '-'} |"
        )
    return "\n".join(rows)


def error_breakdown(results: list[CaseResult]) -> dict[str, list[str]]:
    """Separates rounding noise (under Rs 1) from real disagreements; an aggregate hides it."""
    return {
        "exact": [r.case_id for r in results if r.abs_error == 0],
        "rounding_only_under_1_rs": [r.case_id for r in results if 0 < r.abs_error < 1],
        "real_disagreement": [r.case_id for r in results if r.abs_error >= 1],
    }


def breakdown_md(results: list[CaseResult]) -> str:
    b = error_breakdown(results)
    return "\n".join(
        [
            f"- exact match: {len(b['exact'])} cases",
            f"- rounding only (error under Rs 1): {len(b['rounding_only_under_1_rs'])} cases "
            f"({', '.join(b['rounding_only_under_1_rs']) or '-'})",
            f"- real disagreement (Rs 1 or more): {len(b['real_disagreement'])} cases "
            f"({', '.join(b['real_disagreement']) or '-'})",
        ]
    )


def summary_table(summary: dict) -> str:
    return "\n".join(
        ["| metric | value |", "|---|---|", *[f"| {k} | {v} |" for k, v in summary.items()]]
    )


def lessons_md(pb: Playbook) -> str:
    if not pb.lessons:
        return "- none"
    rows = [
        "| lesson | status | reviewer | note | text | applies when | clauses | from case |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for lesson in pb.lessons.values():
        rows.append(
            f"| {lesson.lesson_id} | {lesson.status.value} | {lesson.reviewer_id or '-'} | "
            f"{lesson.review_note or '-'} | {lesson.text} | {lesson.applies_when} | "
            f"{', '.join(lesson.clause_ids)} | {lesson.source_case_id} |"
        )
    return "\n".join(rows)


def ablation_md(rows: list[dict]) -> str:
    out = [
        "| lesson | harmful | error increase Rs | edit-rate increase | text |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        out.append(
            f"| {r['lesson_id']} | {'yes' if r['harmful'] else 'no'} | {r['error_increase_rs']} | "
            f"{r['edit_rate_increase']} | {r['text']} |"
        )
    return "\n".join(out)


def playbook_counts(pb: Playbook) -> dict[str, int]:
    return {s.value: len(pb.by_status(s)) for s in LessonStatus}


def spread(runs: list[list[CaseResult]]) -> dict[str, tuple[Decimal | float, Decimal | float]]:
    """Min and max of each summary metric across repeated runs (the brief asks for the spread)."""
    summaries = [summarize(r) for r in runs]
    keys = [k for k in summaries[0] if k != "cases"] if summaries else []
    return {k: (min(s[k] for s in summaries), max(s[k] for s in summaries)) for k in keys}


def spread_md(runs: list[list[CaseResult]]) -> str:
    if not runs:
        return "- no runs"
    rows = ["| metric | min | max |", "|---|---|---|"]
    for k, (lo, hi) in spread(runs).items():
        rows.append(f"| {k} | {lo} | {hi} |")
    return "\n".join(rows)
