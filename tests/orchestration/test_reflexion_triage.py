"""Triage, dedupe against refused lessons, and the reflector's clause-id guard (run-03 noise)."""

import pytest

from claimsense.agents import clauses as C
from claimsense.reflexion import (
    Mistake,
    Playbook,
    is_clause_choice,
    known_clause_ids,
    learn,
    local_run_fn,
    reflect,
)

from .test_reflexion import kit_case, services_factory


@pytest.fixture(autouse=True)
def _stub_mode(monkeypatch):
    monkeypatch.setenv("CLAIMSENSE_LLM", "stub")


def mistake(**over):
    base = {
        "case_id": "CLM-X",
        "source": "gold_diff",
        "line_id": "L1",
        "category": "room",
        "got_clause": C.HOSPITALISATION,
        "expected_clause": C.OTHER_EXPENSES,
    }
    return Mistake(**{**base, **over})


def test_a_clause_choice_mistake_goes_to_the_reflector():
    ok, why = is_clause_choice(mistake())
    assert ok and why == ""
    ok, _ = is_clause_choice(mistake(source="adjudicator_edit"))
    assert ok
    ok, _ = is_clause_choice(
        mistake(source="critic_rejection", detail="missing_clause: no clause cited")
    )
    assert ok


def test_everything_else_goes_to_the_backlog_with_a_reason():
    # claim-level: the admissibility finding of a claim the gold calls not admissible
    ok, why = is_clause_choice(mistake(line_id=None, got_clause=None, expected_clause=None))
    assert not ok and "claim-level" in why
    # gold wants a waiting-period or exclusion clause: the gate applies those, not the analyst
    ok, why = is_clause_choice(mistake(expected_clause=C.SPECIFIC_WAITING_PERIOD))
    assert not ok and "admissibility gate" in why
    # same clause as the gold: the rupee difference is a calculator or gold gap (REF-01)
    ok, why = is_clause_choice(mistake(expected_clause=C.HOSPITALISATION))
    assert not ok and "calculator or gold gap" in why
    # critic arithmetic/total issues are not clause choices
    ok, why = is_clause_choice(mistake(source="critic_rejection", detail="arithmetic: off by 1"))
    assert not ok and "arithmetic" in why
    # REF-17: the critic refusing the duplicate-line deduction under clause 2
    ok, why = is_clause_choice(
        mistake(
            source="critic_rejection",
            got_clause=C.OPERATIVE,
            detail="unsupported_clause: reason other not supported by clause 2",
        )
    )
    assert not ok and "critic item" in why
    ok, why = is_clause_choice(mistake(got_clause=None, expected_clause=None))
    assert not ok and "no clause" in why


def test_known_clause_ids_is_the_agents_registry():
    ids = known_clause_ids()
    assert {C.HOSPITALISATION, C.OTHER_EXPENSES, C.NON_PAYABLE_ITEMS, C.OPERATIVE} <= ids
    assert all(i.startswith(C.P) and i != C.P for i in ids)
    assert "new_india_arogya_sanjeevani:99.9" not in ids


def test_reflector_drops_unknown_clause_ids():
    m = mistake(got_clause="new_india_arogya_sanjeevani:99.9", expected_clause=C.OTHER_EXPENSES)
    draft = reflect(m, "", known_clause_ids=known_clause_ids())
    assert draft is not None and draft.clause_ids == [C.OTHER_EXPENSES]  # invented id removed
    only_invented = mistake(got_clause=None, expected_clause="new_india_arogya_sanjeevani:99.9")
    assert reflect(only_invented, "", known_clause_ids=known_clause_ids()) is None
    assert reflect(m, "") is not None  # no registry given: unchanged behaviour


def test_a_refused_lesson_is_not_proposed_again():
    pb = Playbook()
    text = "Check the room cap per day first."
    les = pb.propose(text, "room line", [C.ROOM_RENT_LIMIT], "D1")
    pb.reject(les.lesson_id, "adj", "wrong: the calculator applies the cap")
    dup = pb.duplicate_of(text, "room line", [C.ROOM_RENT_LIMIT])
    assert dup is not None and dup.lesson_id == les.lesson_id and dup.status == "rejected"
    assert pb.propose(text.rstrip("."), "room line", [C.ROOM_RENT_LIMIT], "D2") is None
    # a different clause set is a different lesson
    assert pb.propose(text, "room line", [C.ICU_LIMIT], "D2") is not None


def reject_all(lesson):
    """Tests only: a reviewer who refuses every lesson, as in run-03."""
    return False, "adj-test", "test: refused"


def test_learn_records_the_backlog(tmp_path):
    dev = [kit_case("DEV-0"), kit_case("DEV-1")]
    pb = Playbook(path=tmp_path / "pb.json")
    triage: list[dict] = []
    proposed = learn(
        local_run_fn(services_factory),
        dev,
        pb,
        reject_all,
        known_clause_ids=known_clause_ids(),
        triage=triage,
    )
    assert proposed, "the surgical-kit edit is a clause choice and must reach the gate"
    assert all(les.status == "rejected" for les in pb.lessons.values())
    # the second case repeats the first case's mistake: a duplicate of a REFUSED lesson is not
    # shown to the reviewer again, it goes to the backlog with the refused lesson's id
    dups = [t for t in triage if t["case_id"] == "DEV-1" and "near-duplicate" in t["reason"]]
    assert dups and "(rejected)" in dups[0]["reason"]
    assert all({"case_id", "line_id", "source", "reason"} <= set(t) for t in triage)
