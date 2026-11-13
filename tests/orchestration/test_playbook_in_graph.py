"""T46: a frozen playbook in a normal claim run, and the edit → proposed-lesson hand-off.

Stub mode only: no key, no money. The graph only reads lessons; it never writes one.
"""

import json

import pytest

from claimsense.agents import Team
from claimsense.agents import clauses as C
from claimsense.contracts import ApprovalDecision, LessonStatus
from claimsense.graph import LocalRunner
from claimsense.reflexion import (
    Playbook,
    edits_from_state,
    known_clause_ids,
    propose_from_edits,
    read_edits,
    write_edits,
)
from claimsense.reflexion.review_cli import main as review_main

from .conftest import approve
from .test_reflexion import kit_case, services_factory

LESSON = (
    "Treat a surgical kit as an excluded item.",
    "other line on the bill",
    [C.NON_PAYABLE_ITEMS],
)


@pytest.fixture(autouse=True)
def _stub_mode(monkeypatch):
    """A key in the shell must never turn these tests into paid model calls."""
    monkeypatch.setenv("CLAIMSENSE_LLM", "stub")


def frozen_playbook(tmp_path, approve_lesson=True, extra_status=None):
    pb = Playbook(path=tmp_path / "playbook.json")
    les = pb.propose(*LESSON, "DEV-0")
    if approve_lesson:
        pb.approve(les.lesson_id, "adj-test")
    elif extra_status == LessonStatus.REJECTED:
        pb.reject(les.lesson_id, "adj-test", "test: refused")
    pb.freeze()
    return pb, les


def run_claim(case, playbook, reviewer=None):
    team = Team(services_factory(case), playbook=playbook)
    return LocalRunner(team).run(case.packet, reviewer or approve())


def test_load_frozen_refuses_a_playbook_that_was_never_frozen(tmp_path):
    pb = Playbook(path=tmp_path / "pb.json")
    les = pb.propose(*LESSON, "DEV-0")
    pb.approve(les.lesson_id, "adj-test")
    pb.save()
    with pytest.raises(ValueError, match="not frozen"):
        Playbook.load_frozen(tmp_path / "pb.json")
    with pytest.raises(ValueError, match="not found"):
        Playbook.load_frozen(tmp_path / "missing.json")


def test_load_frozen_refuses_a_playbook_edited_after_freezing(tmp_path):
    pb, les = frozen_playbook(tmp_path)
    assert Playbook.load_frozen(pb.path).frozen_hash == pb.frozen_hash  # unchanged: accepted
    raw = json.loads(pb.path.read_text())
    raw["lessons"][0]["text"] = "Treat every item as excluded."  # someone edited the approved text
    pb.path.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="changed after"):
        Playbook.load_frozen(pb.path)


def test_frozen_playbook_lesson_is_used_in_a_normal_run(tmp_path):
    pb, les = frozen_playbook(tmp_path)
    final = run_claim(kit_case("DEV-1"), Playbook.load_frozen(pb.path))
    assert final["lessons_used"] == [les.lesson_id]
    # the lesson re-pointed the surgical-kit line to the non-payable clause
    assert final["clause_choices"]["L6"] == C.NON_PAYABLE_ITEMS


def test_no_playbook_means_no_lessons_used(tmp_path):
    final = run_claim(kit_case("DEV-1"), None)
    assert final["lessons_used"] == []
    assert final["clause_choices"]["L6"] == C.HOSPITALISATION


@pytest.mark.parametrize("status", [LessonStatus.PROPOSED, LessonStatus.REJECTED])
def test_unapproved_lessons_never_reach_the_run(tmp_path, status):
    pb, les = frozen_playbook(tmp_path, approve_lesson=False, extra_status=status)
    assert pb.lessons[les.lesson_id].status == status
    final = run_claim(kit_case("DEV-1"), Playbook.load_frozen(pb.path))
    assert final["lessons_used"] == []
    assert final["clause_choices"]["L6"] == C.HOSPITALISATION


# ---------------------------------------------------------------- edits → proposed lessons
def editing_reviewer():
    """Plays an adjudicator who re-points the surgical-kit line once, then approves."""
    state = {"edited": False}

    def reviewer(payload):
        me = {"approver_id": f"{payload['level']}-1"}
        if payload["kind"] == "worksheet" and not state["edited"]:
            state["edited"] = True
            return {
                **me,
                "decision": ApprovalDecision.EDIT,
                "edits": [
                    {
                        "line_id": "L6",
                        "clause_id": C.NON_PAYABLE_ITEMS,
                        "reason": "a surgical kit is a consumable, not a hospitalisation expense",
                    }
                ],
            }
        return {**me, "decision": ApprovalDecision.APPROVE}

    return reviewer


def test_edits_become_proposed_lessons_only_after_the_offline_step(tmp_path):
    final = run_claim(kit_case("CLM-T46"), None, editing_reviewer())
    records = edits_from_state(final)
    assert len(records) == 1
    rec = records[0]
    assert rec["claim_id"] == "CLM-T46" and rec["line_id"] == "L6" and rec["category"] == "other"
    assert rec["old_clause"] == C.HOSPITALISATION and rec["new_clause"] == C.NON_PAYABLE_ITEMS
    assert set(rec) == {
        "claim_id", "level", "line_id", "category", "old_clause", "new_clause", "reason"
    }  # fmt: skip

    edits = tmp_path / "edits.jsonl"
    assert write_edits(edits, records) == 1
    assert read_edits(edits) == [json.loads(edits.read_text().splitlines()[0])]

    # the graph wrote no lesson; the offline step files exactly one, PROPOSED, never approved
    pb = Playbook(path=tmp_path / "live.json")
    proposed, backlog = propose_from_edits(
        pb, read_edits(edits), known_clause_ids=known_clause_ids()
    )
    assert len(proposed) == 1 and backlog == []
    assert proposed[0].status == LessonStatus.PROPOSED
    assert proposed[0].source_case_id == "CLM-T46"
    assert C.NON_PAYABLE_ITEMS in proposed[0].clause_ids
    assert pb.by_status(LessonStatus.APPROVED) == []
    # it is not retrieved until a person approves it
    assert pb.retrieve({C.NON_PAYABLE_ITEMS}, "surgical kit other", k=3) == []
    # a second run of the same edits proposes nothing new (duplicate of the pending one)
    again, backlog = propose_from_edits(pb, read_edits(edits))
    assert again == [] and "near-duplicate" in backlog[0]["reason"]


def test_review_cli_propose_from_edits(tmp_path, capsys):
    final = run_claim(kit_case("CLM-T46"), None, editing_reviewer())
    edits = tmp_path / "edits.jsonl"
    write_edits(edits, edits_from_state(final))
    pb_path = tmp_path / "live.json"
    review_main(["propose-from-edits", str(pb_path), "--edits", str(edits)])
    out = capsys.readouterr().out
    assert "1 lesson(s) PROPOSED" in out and "next:" in out
    pb = Playbook.load(pb_path)
    assert len(pb.by_status(LessonStatus.PROPOSED)) == 1
    # a frozen playbook is never written to
    frozen, _ = frozen_playbook(tmp_path / "f")
    with pytest.raises(SystemExit, match="frozen"):
        review_main(["propose-from-edits", str(frozen.path), "--edits", str(edits)])
    with pytest.raises(SystemExit, match="no edit records"):
        review_main(["propose-from-edits", str(pb_path), "--edits", str(tmp_path / "none.jsonl")])
