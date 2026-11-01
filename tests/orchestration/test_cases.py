"""`reflexion.cases`: the dev golden set loads into DevCase objects that the pipeline can run.

These are the day-1 "dry run" checks from the plan, kept as tests so they run on every commit.
Everything here is stub mode: no model, no network.
"""

import importlib.util
import json
from decimal import Decimal
from pathlib import Path

import pytest

from claimsense.agents import clauses as C
from claimsense.contracts import Claim, Worksheet
from claimsense.reflexion import Playbook, evaluate, local_run_fn, summarize
from claimsense.reflexion.cases import (
    gold_from_fixture,
    load_cases,
    packet_from_fixture,
    policy_from_fixture,
    stub_services_factory,
)

DEV = "eval/golden_dev"


@pytest.fixture(scope="module")
def cases():
    return load_cases(DEV)


@pytest.fixture(scope="module")
def raw():
    claims = [json.loads(line) for line in open(f"{DEV}/claims.jsonl", encoding="utf-8")]
    golds = {
        g["claim_id"]: g
        for g in (
            json.loads(line) for line in open(f"{DEV}/gold_worksheets.jsonl", encoding="utf-8")
        )
    }
    return claims, golds


def test_loads_every_dev_claim_once(cases):
    assert len(cases) == 20
    assert len({c.case_id for c in cases}) == 20
    assert all(c.split == "dev" for c in cases)


def test_every_packet_is_a_valid_claim_whose_lines_add_up(cases):
    for c in cases:
        claim = Claim.model_validate(c.packet["claim"])
        assert claim.total_matches_lines(), c.case_id
        assert claim.nights >= 1, c.case_id
        assert c.packet["documents"] == {}
        assert "scenario_label" not in json.dumps(c.packet), (
            "evaluation-only field leaked into the packet"
        )
        assert "fixture_notes" not in json.dumps(c.packet)


def test_gold_worksheet_matches_the_gold_file(cases, raw):
    _, golds = raw
    for c in cases:
        g = golds[c.case_id]
        ws = c.gold_worksheet
        assert isinstance(ws, Worksheet)
        assert ws.total_payable == Decimal(g["expected_settlement_inr"]), c.case_id
        assert sum(line.payable for line in ws.lines) == Decimal(g["payable_before_copay_inr"]), (
            c.case_id
        )
        assert (ws.co_pay.amount if ws.co_pay else Decimal(0)) == Decimal(g["copay_amount_inr"]), (
            c.case_id
        )
        assert c.gold_admissible == (g["expected_admissibility"] == "admissible"), c.case_id


def test_gold_clause_choices_follow_the_reason_codes(cases, raw):
    claims, golds = raw
    by_id = {x["claim_id"]: x for x in claims}
    for c in cases:
        if not c.gold_admissible:
            continue
        codes = {li["line_id"]: li["reason_codes"] for li in golds[c.case_id]["line_items"]}
        cats = {b["line_id"]: b["category"] for b in by_id[c.case_id]["bill_lines"]}
        for line_id, want in c.gold_choices().items():
            if "non_payable_item_demo_rule" in codes[line_id]:
                assert want == C.NON_PAYABLE_ITEMS
            elif "room_rent_daily_cap" in codes[line_id]:
                assert want == C.ROOM_RENT_LIMIT and cats[line_id] == "room_rent"
            elif "room_rent_proportional_reduction" in codes[line_id]:
                assert want == C.OTHER_EXPENSES
            else:
                assert want == C.HOSPITALISATION
        # a duplicate line is a fraud finding, not a clause choice
        for line_id, cs in codes.items():
            if "duplicate_line" in cs:
                assert line_id not in c.gold_choices()


def test_policy_record_comes_from_the_fixture(raw):
    claims, _ = raw
    fx = claims[0]
    pol = policy_from_fixture(fx)
    assert pol.policy_number == fx["policy"]["policy_id"]
    assert pol.sum_insured == Decimal(fx["policy"]["sum_insured_inr"])
    assert pol.insured_pseudonym == fx["policyholder"]["synthetic_person_id"]
    assert str(pol.period_start) == fx["policy"]["policy_start_date"]
    assert packet_from_fixture(fx)["fixture_policy"]["policy_number"] == pol.policy_number


def test_unknown_reason_code_or_category_raises(raw):
    claims, golds = raw
    fx, g = json.loads(json.dumps(claims[3])), json.loads(json.dumps(golds[claims[3]["claim_id"]]))
    g["line_items"][0]["deduction_before_copay_inr"] = 1
    g["line_items"][0]["allowed_before_copay_inr"] -= 1
    g["line_items"][0]["reason_codes"] = ["some_new_rule"]
    with pytest.raises(ValueError, match="unmapped gold reason code"):
        gold_from_fixture(fx, g)
    fx["bill_lines"][0]["category"] = "robotics"
    with pytest.raises(ValueError, match="unmapped bill-line category"):
        packet_from_fixture(fx)


def test_stub_dry_run_of_all_dev_claims_completes(cases):
    """The plan's day-1 dry run: every case ends settled or repudiated, nothing crashes, and the
    not-admissible cases come out at Rs 0 like their gold."""
    results = evaluate(local_run_fn(stub_services_factory()), cases, None)
    assert len(results) == 20
    assert {r.status for r in results} <= {"settled", "repudiated"}
    for r, c in zip(results, cases, strict=True):
        if not c.gold_admissible:
            assert r.abs_error == 0, (c.case_id, r.proposed_total, r.gold_total)
    s = summarize(results)
    assert s["cases"] == 20
    assert 0 <= s["exact_match_rate"] <= 1


# ---------------------------------------------------------------- the two scripts, end to end
SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _script(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_day4_experiment_script_runs_end_to_end_and_freezes(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAIMSENSE_LLM", "stub")
    exp = _script("run_reflexion_experiment")
    out = tmp_path / "run"
    exp.main(["baseline", "--out", str(out)])
    assert (out / "baseline.md").exists() and (out / "baseline.json").exists()
    exp.main(
        [
            "experiment",
            "--approve",
            "auto",
            "--reviewer",
            "test",
            "--out",
            str(out),
            "--after-runs",
            "2",
        ]
    )
    report = (out / "report.md").read_text()
    assert "HARNESS CHECK ONLY" in report  # auto-approve is stamped, never silent
    assert "Frozen playbook hash" in report and "Spread across the 2" in report
    pb = Playbook.load(out / "playbook.json")
    assert pb.frozen and pb.content_hash() == pb.frozen_hash
    with pytest.raises(SystemExit):  # a frozen playbook ends the experiment
        exp.main(["experiment", "--approve", "auto", "--out", str(out)])
    with pytest.raises(SystemExit):  # never learn from anything called held-out
        exp.main(["baseline", "--cases", "../claimsense-heldout", "--out", str(out)])


def _renamed_copy(src: str, dst: Path, old: str, new: str) -> None:
    dst.mkdir(parents=True)
    for name in ("claims.jsonl", "gold_worksheets.jsonl"):
        text = (Path(src) / name).read_text(encoding="utf-8")
        (dst / name).write_text(text.replace(old, new), encoding="utf-8")


def test_day5_heldout_script_guards_and_runs(tmp_path, monkeypatch):
    """Uses a renamed copy of the dev set as a stand-in for the held-out format. The real held-out
    set lives outside the repo and is never read here."""
    monkeypatch.setenv("CLAIMSENSE_LLM", "stub")
    ho = _script("run_reflexion_heldout")
    _renamed_copy(DEV, tmp_path / "ho", "CLM-", "HO-")
    pb_path = tmp_path / "pb.json"
    pb = Playbook(path=pb_path)
    pb.save()
    args = [
        "--playbook",
        str(pb_path),
        "--heldout",
        str(tmp_path / "ho"),
        "--out",
        str(tmp_path / "res"),
    ]
    with pytest.raises(SystemExit, match="not frozen"):
        ho.main(args)
    pb.freeze()
    with pytest.raises(SystemExit, match="outside the repository"):
        ho.main(["--playbook", str(pb_path), "--heldout", DEV, "--out", str(tmp_path / "res")])
    ho.main(args + ["--repeat", "2"])
    report = (tmp_path / "res" / "heldout_report.md").read_text()
    assert "held-out cases: 20" in report and "Spread across 2" in report
    data = json.loads((tmp_path / "res" / "heldout_report.json").read_text())
    assert data["playbook_hash"] == pb.frozen_hash and len(data["after_runs"]) == 2
    # a lesson learned from a held-out case must be refused
    leaky = Playbook(path=tmp_path / "leak.json")
    lesson = leaky.propose("x lesson text", "room line", [C.ROOM_RENT_LIMIT], "HO-0001")
    leaky.approve(lesson.lesson_id, "t")
    leaky.freeze()
    with pytest.raises(AssertionError, match="held-out"):
        ho.main(
            [
                "--playbook",
                str(tmp_path / "leak.json"),
                "--heldout",
                str(tmp_path / "ho"),
                "--out",
                str(tmp_path / "res2"),
            ]
        )
