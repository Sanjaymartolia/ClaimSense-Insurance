"""Reflexion harness end to end in stub mode: learn → approve → improve → ablate → freeze."""

import pytest

from claimsense.agents import make_stub_services, reference_calculate
from claimsense.agents.services import stub_clause
from claimsense.agents import clauses as C
from claimsense.contracts import Claim, RetrievedPassage
from claimsense.reflexion import (DevCase, FrozenPlaybookError, Playbook, experiment,
                                  local_run_fn, run_heldout, too_specific)

from .conftest import POLICY, room_breach_packet, span


def services_factory(case):
    svc = make_stub_services(policies={"POL-001": POLICY})
    base = svc.policy_search

    def search(query, category=None, k=5):  # make NON_PAYABLE a lower-ranked candidate everywhere
        res = base(query, category, k)
        if C.NON_PAYABLE_ITEMS not in {r.clause.clause_id for r in res}:
            res.append(RetrievedPassage(clause=stub_clause(C.NON_PAYABLE_ITEMS, "excluded items"),
                                        score=0.1, rank=len(res) + 1))
        return res
    svc.policy_search = search
    return svc


def kit_case(case_id, split="dev"):
    p = room_breach_packet(case_id)
    p["claim"]["bill_lines"].append({"line_id": "L6", "description": "Surgical kit", "category": "other",
                                     "amount": "3000.00", "source": span()})
    p["claim"]["bill_total"] = "79000.00"
    claim = Claim.model_validate(p["claim"])
    gold_choices = {"L5": C.NON_PAYABLE_ITEMS, "L6": C.NON_PAYABLE_ITEMS}
    gold = reference_calculate(claim, {l.line_id: gold_choices.get(l.line_id, C.HOSPITALISATION)
                                       for l in claim.bill_lines})
    return DevCase(case_id=case_id, packet=p, gold_worksheet=gold,
                   gold_clause_choices=gold_choices, split=split)


def test_reflexion_improves_dev_and_freezes(tmp_path):
    dev = [kit_case(f"DEV-{i}") for i in range(3)]
    held = [kit_case(f"HO-{i}", split="heldout") for i in range(2)]
    pb = Playbook(path=tmp_path / "playbook.json")
    approve_all = lambda lesson: (True, "adj-test", None)  # tests only; the real gate is a human

    rep = experiment(local_run_fn(services_factory), dev, pb, approve_all, heldout=held)

    assert rep.baseline["edit_rate"] == 1.0
    assert rep.after["settlement_error_total_rs"] < rep.baseline["settlement_error_total_rs"]
    assert rep.after["edit_rate"] < rep.baseline["edit_rate"]
    assert rep.heldout_after["settlement_error_total_rs"] <= rep.heldout_baseline["settlement_error_total_rs"]
    assert pb.frozen and (tmp_path / "playbook.json").exists()
    with pytest.raises(FrozenPlaybookError):
        pb.propose("x", "y", [], "DEV-0")
    print(rep.markdown())


def test_ablation_finds_and_withdraws_a_harmful_lesson(tmp_path):
    dev = [kit_case(f"DEV-{i}") for i in range(2)]
    pb = Playbook(path=tmp_path / "pb.json")
    bad = pb.propose("Treat surgeon fees as excluded items.", "doctor_fees line on the bill",
                     [C.NON_PAYABLE_ITEMS], "DEV-0")
    pb.approve(bad.lesson_id, "adj-test")
    rep = experiment(local_run_fn(services_factory), dev, pb, lambda l: (True, "adj-test", None))
    assert bad.lesson_id in rep.withdrawn
    assert pb.lessons[bad.lesson_id].status == "withdrawn"


def test_heldout_refuses_unfrozen_or_leaky_playbook():
    dev, held = [kit_case("DEV-0")], [kit_case("HO-0", split="heldout")]
    pb = Playbook()
    with pytest.raises(RuntimeError):
        run_heldout(local_run_fn(services_factory), held, pb, dev)
    leak = pb.propose("x lesson", "room line", [C.ROOM_RENT_LIMIT], "HO-0")
    pb.approve(leak.lesson_id, "a")
    pb.freeze()
    with pytest.raises(AssertionError):
        run_heldout(local_run_fn(services_factory), held, pb, dev)


def test_only_approved_lessons_are_retrieved():
    pb = Playbook()
    a = pb.propose("Check room cap per day.", "room line", [C.ROOM_RENT_LIMIT], "DEV-1")
    b = pb.propose("Check ICU cap per day.", "icu line", [C.ICU_LIMIT], "DEV-2")
    pb.approve(a.lesson_id, "r")
    got = pb.retrieve({C.ROOM_RENT_LIMIT, C.ICU_LIMIT}, "room icu", k=3)
    assert [l.lesson_id for l in got] == [a.lesson_id]
    pb.withdraw(a.lesson_id, "r", "test")
    assert pb.retrieve({C.ROOM_RENT_LIMIT}, "room", k=3) == []
    assert b.status == "proposed"


def test_specific_lessons_blocked():
    assert too_specific("Kabir's dinner was Rs 7,500")
    assert not too_specific("Check the policy year before applying a sub-limit (clause 4.1.1).")
