"""Adjudicator review of proposed lessons, and withdrawal of approved ones.

    python -m claimsense.reflexion.review_cli review   playbook.json --reviewer adj-07
    python -m claimsense.reflexion.review_cli withdraw playbook.json LSN-1a2b3c4d --reviewer adj-07 \
        --note "made sub-limit claims worse"
    python -m claimsense.reflexion.review_cli list     playbook.json
"""

from __future__ import annotations

import argparse

from claimsense.contracts import Lesson, LessonStatus

from .playbook import Playbook


def console_approver(reviewer_id: str):
    """An ApproveFn for loop.learn(): asks a person at the terminal."""
    def ask(lesson: Lesson):
        print(f"\n[{lesson.lesson_id}] from {lesson.source_case_id}\n  LESSON: {lesson.text}\n"
              f"  APPLIES WHEN: {lesson.applies_when}\n  CLAUSES: {', '.join(lesson.clause_ids)}")
        ans = input("approve? [y/n] ").strip().lower()
        note = None if ans == "y" else input("reason for rejecting: ").strip() or "rejected"
        return ans == "y", reviewer_id, note
    return ask


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["list", "review", "withdraw"])
    ap.add_argument("path")
    ap.add_argument("lesson_id", nargs="?")
    ap.add_argument("--reviewer", default="adjudicator")
    ap.add_argument("--note", default="")
    a = ap.parse_args(argv)
    pb = Playbook.load(a.path)
    if a.cmd == "list":
        for l in pb.lessons.values():
            print(f"{l.status.value:9} {l.lesson_id}  {l.text}")
    elif a.cmd == "review":
        ask = console_approver(a.reviewer)
        for l in pb.by_status(LessonStatus.PROPOSED):
            ok, who, note = ask(l)
            pb.approve(l.lesson_id, who, note) if ok else pb.reject(l.lesson_id, who, note)
        pb.save()
    else:
        pb.withdraw(a.lesson_id, a.reviewer, a.note or "withdrawn by reviewer")
        pb.save()


if __name__ == "__main__":
    main()
