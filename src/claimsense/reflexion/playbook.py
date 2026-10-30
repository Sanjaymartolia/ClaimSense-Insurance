"""The playbook: reviewed lessons the coverage analyst reads (Signature B, L12).

Rules from the brief and the L12 deck ("treat every lesson like code"):
- a lesson enters as PROPOSED and is used only after an adjudicator APPROVES it;
- retrieval returns only relevant APPROVED lessons, capped at k (L12: keep 1-3);
- any lesson can be WITHDRAWN, with a note, at any time;
- freeze() before the held-out run: no more proposals or status changes, and the hash is recorded
  in the report so anyone can check the held-out run used exactly this playbook.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from claimsense.contracts import Lesson, LessonStatus

_WORD = re.compile(r"[a-z]{3,}")


class FrozenPlaybookError(RuntimeError):
    pass


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


class Playbook:
    def __init__(self, lessons: list[Lesson] | None = None, frozen_hash: str | None = None,
                 path: str | Path | None = None, exclude: set[str] | None = None):
        self.lessons: dict[str, Lesson] = {l.lesson_id: l for l in lessons or []}
        self.frozen_hash = frozen_hash
        self.path = Path(path) if path else None
        self.exclude = set(exclude or ())  # for ablation views

    # ---------------------------------------------------------------- lifecycle
    def _check_open(self):
        if self.frozen_hash:
            raise FrozenPlaybookError("playbook is frozen for the held-out run")

    def propose(self, text: str, applies_when: str, clause_ids: list[str],
                source_case_id: str) -> Lesson | None:
        """Returns None for a near-duplicate of an existing lesson (L12: memory piles up)."""
        self._check_open()
        new = _tokens(text + " " + applies_when)
        for l in self.lessons.values():
            if l.status in (LessonStatus.REJECTED, LessonStatus.WITHDRAWN):
                continue
            old = _tokens(l.text + " " + l.applies_when)
            if set(clause_ids) == set(l.clause_ids) and len(new & old) / max(len(new | old), 1) > 0.6:
                return None
        lesson = Lesson(lesson_id="LSN-" + uuid.uuid4().hex[:8], text=text.strip(),
                        applies_when=applies_when.strip(), clause_ids=list(clause_ids),
                        source_case_id=source_case_id, created_at=datetime.now(timezone.utc))
        self.lessons[lesson.lesson_id] = lesson
        return lesson

    def _set(self, lesson_id: str, status: LessonStatus, reviewer_id: str, note: str | None):
        self._check_open()
        self.lessons[lesson_id] = self.lessons[lesson_id].model_copy(
            update={"status": status, "reviewer_id": reviewer_id, "review_note": note})

    def approve(self, lesson_id: str, reviewer_id: str, note: str | None = None):
        self._set(lesson_id, LessonStatus.APPROVED, reviewer_id, note)

    def reject(self, lesson_id: str, reviewer_id: str, note: str):
        if not note:
            raise ValueError("a rejection needs a note")
        self._set(lesson_id, LessonStatus.REJECTED, reviewer_id, note)

    def withdraw(self, lesson_id: str, reviewer_id: str, note: str):
        if not note:
            raise ValueError("a withdrawal needs a note (e.g. 'made results worse in ablation')")
        self._set(lesson_id, LessonStatus.WITHDRAWN, reviewer_id, note)

    def by_status(self, status: LessonStatus) -> list[Lesson]:
        return [l for l in self.lessons.values() if l.status == status]

    # ---------------------------------------------------------------- retrieval
    def retrieve(self, clause_ids: set[str], text: str, k: int = 3) -> list[Lesson]:
        """Only APPROVED lessons; a lesson must share a clause or wording with the claim.
        TODO(day 4): ask the Knowledge role whether to swap this for the shared hybrid retriever."""
        words = _tokens(text)
        scored = []
        for l in self.lessons.values():
            if l.status != LessonStatus.APPROVED or l.lesson_id in self.exclude:
                continue
            score = 2 * len(set(l.clause_ids) & set(clause_ids)) + \
                len(_tokens(l.applies_when) & words) / max(len(_tokens(l.applies_when)), 1)
            if score > 0.34:
                scored.append((score, l.lesson_id, l))
        return [l for _, _, l in sorted(scored, key=lambda t: (-t[0], t[1]))[:k]]

    def without(self, lesson_id: str) -> "Playbook":
        """A read-only view with one lesson removed: leave-one-out ablation."""
        return Playbook(list(self.lessons.values()), self.frozen_hash or "ablation-view",
                        exclude=self.exclude | {lesson_id})

    # ---------------------------------------------------------------- freeze + persistence
    def content_hash(self) -> str:
        approved = sorted((l.model_dump(mode="json") for l in self.by_status(LessonStatus.APPROVED)),
                          key=lambda d: d["lesson_id"])
        return hashlib.sha256(json.dumps(approved, sort_keys=True).encode()).hexdigest()

    def freeze(self) -> str:
        self.frozen_hash = self.content_hash()
        self.save()
        return self.frozen_hash

    @property
    def frozen(self) -> bool:
        return bool(self.frozen_hash)

    def save(self, path: str | Path | None = None):
        p = Path(path) if path else self.path
        if p is None:
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"frozen_hash": self.frozen_hash,
                                 "lessons": [l.model_dump(mode="json") for l in self.lessons.values()]},
                                indent=2))

    @classmethod
    def load(cls, path: str | Path) -> "Playbook":
        p = Path(path)
        if not p.exists():
            return cls(path=p)
        d = json.loads(p.read_text())
        return cls([Lesson.model_validate(x) for x in d["lessons"]], d.get("frozen_hash"), path=p)
