"""Adjudicator review of proposed lessons, withdrawal of approved ones, and the hand-off from
live adjudicator edits to proposed lessons.

    python -m claimsense.reflexion.review_cli review   playbook.json --reviewer adj-07
    python -m claimsense.reflexion.review_cli withdraw playbook.json LSN-1a2b3c4d \
        --reviewer adj-07 --note "made sub-limit claims worse"
    python -m claimsense.reflexion.review_cli list     playbook.json
    python -m claimsense.reflexion.review_cli propose-from-edits playbook.json --edits edits.jsonl

`propose-from-edits` reads the edit records a claim run wrote (`scripts/run_one.py --edits-out`),
files one PROPOSED lesson per clause-choice edit, and prints the rest as a backlog. It approves
nothing: run `review` afterwards. A frozen playbook is refused; start a new playbook file.
"""

from __future__ import annotations

import argparse
import sys

from claimsense.contracts import Lesson, LessonStatus

from .playbook import FrozenPlaybookError, Playbook


def console_approver(reviewer_id: str):
    """An ApproveFn for loop.learn(): asks a person at the terminal."""

    def ask(lesson: Lesson):
        print(
            f"\n[{lesson.lesson_id}] from {lesson.source_case_id}\n  LESSON: {lesson.text}\n"
            f"  APPLIES WHEN: {lesson.applies_when}\n  CLAUSES: {', '.join(lesson.clause_ids)}"
        )
        ans = input("approve? [y/n] ").strip().lower()
        note = None if ans == "y" else input("reason for rejecting: ").strip() or "rejected"
        return ans == "y", reviewer_id, note

    return ask


def _propose_from_edits(pb: Playbook, edits_path: str) -> None:
    from claimsense.agents import make_stub_services

    from .from_edits import propose_from_edits, read_edits
    from .triage import backlog_md, known_clause_ids

    records = read_edits(edits_path)
    if not records:
        sys.exit(f"no edit records in {edits_path}")
    clause = make_stub_services().get_clause

    def clause_text(cid: str) -> str:
        c = clause(cid) if cid else None
        return c.text if c else ""

    try:
        proposed, backlog = propose_from_edits(pb, records, clause_text, known_clause_ids())
    except FrozenPlaybookError:
        sys.exit("refusing: this playbook is frozen; propose into a new playbook file")
    print(
        f"{len(records)} edit record(s): {len(proposed)} lesson(s) PROPOSED, "
        f"{len(backlog)} to backlog"
    )
    for les in proposed:
        print(f"  proposed  {les.lesson_id}  {les.text}")
    print("backlog (no lesson):")
    print(backlog_md(backlog))
    print(f"\nnext: python -m claimsense.reflexion.review_cli review {pb.path} --reviewer <name>")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["list", "review", "withdraw", "propose-from-edits"])
    ap.add_argument("path")
    ap.add_argument("lesson_id", nargs="?")
    ap.add_argument("--reviewer", default="adjudicator")
    ap.add_argument("--note", default="")
    ap.add_argument("--edits", default="", help="edits.jsonl from `run_one.py --edits-out`")
    a = ap.parse_args(argv)
    pb = Playbook.load(a.path)
    if a.cmd == "list":
        for les in pb.lessons.values():
            print(f"{les.status.value:9} {les.lesson_id}  {les.text}")
    elif a.cmd == "review":
        ask = console_approver(a.reviewer)
        for les in pb.by_status(LessonStatus.PROPOSED):
            ok, who, note = ask(les)
            if ok:
                pb.approve(les.lesson_id, who, note)
            else:
                pb.reject(les.lesson_id, who, note)
        pb.save()
    elif a.cmd == "propose-from-edits":
        if not a.edits:
            ap.error("propose-from-edits needs --edits <edits.jsonl>")
        _propose_from_edits(pb, a.edits)
    else:
        pb.withdraw(a.lesson_id, a.reviewer, a.note or "withdrawn by reviewer")
        pb.save()


if __name__ == "__main__":
    main()
