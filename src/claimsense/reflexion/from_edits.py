"""Adjudicator edits from live claim runs become PROPOSED lessons (brief, step 9).

"Adjudicator corrections become candidate lessons, used only after review." The graph never writes
a lesson (ADR-0005 memory ownership, T46): it only leaves the edits in the claim state's
`edit_log`. This module is the offline hand-off:

    1. a claim run (`scripts/run_one.py --edits-out edits.jsonl`) appends its edits as records;
    2. `python -m claimsense.reflexion.review_cli propose-from-edits <playbook> --edits <file>`
       turns each record into a Mistake, triages it, reflects, and files a PROPOSED lesson;
    3. `... review <playbook> --reviewer <name>` is the human gate, as for the dev loop.

Nothing here approves anything. A record holds ids, clauses, the line category and the reason the
adjudicator typed: no patient text, no amounts beyond what the adjudicator wrote (rule 4).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from claimsense.contracts import Lesson

from .evaluator import Mistake
from .playbook import Playbook
from .reflector import reflect
from .triage import NO_LESSON, backlog_entry, is_clause_choice

FIELDS = ("claim_id", "level", "line_id", "category", "old_clause", "new_clause", "reason")


def edits_from_state(final_state: dict) -> list[dict]:
    """The edit records of one finished run: `edit_log` entries plus each line's category."""
    claim = final_state.get("claim")
    cat = {ln.line_id: ln.category.value for ln in claim.bill_lines} if claim else {}
    out = []
    for e in final_state.get("edit_log", []):
        rec = {k: e.get(k) for k in FIELDS if k != "category"}
        rec["category"] = cat.get(e.get("line_id"))
        out.append(rec)
    return out


def write_edits(path: str | Path, records: list[dict]) -> int:
    """Append records as JSON lines. Returns how many were written."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps({k: r.get(k) for k in FIELDS}, default=str) + "\n")
    return len(records)


def read_edits(path: str | Path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def mistake_from_edit(rec: dict) -> Mistake:
    return Mistake(
        case_id=str(rec.get("claim_id") or "?"),
        source="adjudicator_edit",
        line_id=rec.get("line_id"),
        category=rec.get("category"),
        got_clause=rec.get("old_clause"),
        expected_clause=rec.get("new_clause"),
        detail=str(rec.get("reason") or ""),
    )


def propose_from_edits(
    playbook: Playbook,
    records: list[dict],
    get_clause_text: Callable[[str], str] = lambda cid: "",
    known_clause_ids: set[str] | None = None,
) -> tuple[list[Lesson], list[dict]]:
    """Each edit → triage → reflect → PROPOSED lesson. Returns (proposed, backlog).
    Never approves; never touches a frozen playbook (Playbook.propose raises)."""
    proposed: list[Lesson] = []
    backlog: list[dict] = []
    for rec in records:
        m = mistake_from_edit(rec)
        ok, why = is_clause_choice(m)
        if not ok:
            backlog.append(backlog_entry(m, why))
            continue
        text = get_clause_text(m.expected_clause or "")
        draft = reflect(m, text, known_clause_ids=known_clause_ids)
        if draft is None:
            backlog.append(backlog_entry(m, NO_LESSON))
            continue
        dup = playbook.duplicate_of(draft.lesson, draft.applies_when, draft.clause_ids)
        if dup is not None:
            backlog.append(backlog_entry(m, f"near-duplicate of {dup.lesson_id} ({dup.status})"))
            continue
        lesson = playbook.propose(draft.lesson, draft.applies_when, draft.clause_ids, m.case_id)
        if lesson is not None:
            proposed.append(lesson)
    playbook.save()
    return proposed, backlog
