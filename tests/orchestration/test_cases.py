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
from claimsense.contracts import Claim, DeductionReason, Worksheet
from claimsense.reflexion import Playbook, evaluate, local_run_fn, run_case, summarize
from claimsense.reflexion.cases import (
    MATERNITY_EXCLUSION,
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
            elif "icu_daily_cap" in codes[line_id]:
                assert want == C.ICU_LIMIT and cats[line_id] == "icu"
            elif "room_rent_proportional_reduction" in codes[line_id]:
                assert want == C.OTHER_EXPENSES
            else:
                assert want == C.HOSPITALISATION
        # a duplicate line is a fraud finding, not a clause choice
        for line_id, cs in codes.items():
            if "duplicate_line" in cs:
                assert line_id not in c.gold_choices()


def test_gold_audit_relabels_are_mapped(cases, raw):
    """The 2026-11-04 gold audit (docs/CLAIMS_AND_GOLD_SET_FIXES.md): CLM-0018 is a caesarean
    excluded under clause 7.15 (GOLD-01); CLM-0016's ICU day is capped (GOLD-04)."""
    _, golds = raw
    by_id = {c.case_id: c for c in cases}

    c18 = by_id["CLM-0018"]
    assert golds["CLM-0018"]["reason_codes"] == ["maternity_childbirth_exclusion"]
    assert not c18.gold_admissible
    assert c18.gold_worksheet.total_payable == 0
    assert MATERNITY_EXCLUSION == "new_india_arogya_sanjeevani:7.15"
    for line in c18.gold_worksheet.lines:
        assert line.payable == 0
        assert line.deductions[0].reason == DeductionReason.EXCLUSION
        assert line.deductions[0].clause_id == MATERNITY_EXCLUSION
        # the gold file now carries the clause too; the mapping must agree with it
        assert MATERNITY_EXCLUSION == next(
            li["clause_id"]
            for li in golds["CLM-0018"]["line_items"]
            if li["line_id"] == line.line_id
        )

    c16 = by_id["CLM-0016"]
    icu = next(line for line in c16.gold_worksheet.lines if line.line_id == "CLM-0016-L01")
    assert icu.payable == Decimal("10000") and icu.deductions[0].reason == DeductionReason.ICU_CAP
    assert c16.gold_choices()["CLM-0016-L01"] == C.ICU_LIMIT
    assert c16.gold_worksheet.total_payable == Decimal("59346")


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


#: Gold repudiates these under an exclusion the coverage analyst's admissibility check does not
#: implement yet (CLM-0018: caesarean, clause 7.15; GOLD-01 / AGT-02 in the gold audit). The
#: pipeline pays them, so they are a known baseline miss. Remove an id here once the check exists:
#: the test below then fails loudly if the id is still listed but no longer missed.
KNOWN_UNIMPLEMENTED_EXCLUSIONS = {"CLM-0018"}


def test_stub_dry_run_of_all_dev_claims_completes(cases):
    """The plan's day-1 dry run: every case ends settled or repudiated, nothing crashes, and the
    not-admissible cases come out at Rs 0 like their gold, except the documented exclusion gap."""
    results = evaluate(local_run_fn(stub_services_factory()), cases, None)
    assert len(results) == 20
    assert {r.status for r in results} <= {"settled", "repudiated"}
    for r, c in zip(results, cases, strict=True):
        if c.case_id in KNOWN_UNIMPLEMENTED_EXCLUSIONS:
            assert not c.gold_admissible and r.abs_error > 0, (
                f"{c.case_id} is no longer missed: drop it from KNOWN_UNIMPLEMENTED_EXCLUSIONS"
            )
        elif not c.gold_admissible:
            assert r.abs_error == 0, (c.case_id, r.proposed_total, r.gold_total)
    s = summarize(results)
    assert s["cases"] == 20
    assert 0 <= s["exact_match_rate"] <= 1


def test_rounding_tolerance_changes_what_counts_as_a_mistake_not_the_rupees(cases):
    """Gold is whole rupees, the calculator keeps paise. With a Rs 1 tolerance a line that is
    off by paise is not edited and raises no gold_diff mistake; the rupee error stays exact."""
    run_fn = local_run_fn(stub_services_factory())
    strict = evaluate(run_fn, cases, None)
    loose = evaluate(run_fn, cases, None, Decimal("1"))
    for a, b in zip(strict, loose, strict=True):
        assert a.abs_error == b.abs_error, a.case_id  # rupee error never tolerated away
        assert b.tolerance_rs == 1 and a.tolerance_rs == 0
    s_strict, s_loose = summarize(strict), summarize(loose)
    assert s_strict["settlement_error_total_rs"] == s_loose["settlement_error_total_rs"]
    assert any(0 < r.abs_error < 1 for r in strict), "dev set should hold paise-only totals"
    assert s_loose["exact_match_rate"] > s_strict["exact_match_rate"]
    # line level: strict mode raises gold_diff mistakes for paise differences (these produced the
    # "do not round prematurely" lessons in run-01); tolerant mode drops exactly those and keeps
    # every real disagreement.
    paise, kept = 0, 0
    for case in cases:
        _, strict_m = run_case(run_fn, case, None)
        _, loose_m = run_case(run_fn, case, None, Decimal("1"))
        strict_g = {(m.line_id, m.rupee_error) for m in strict_m if m.source == "gold_diff"}
        loose_g = {(m.line_id, m.rupee_error) for m in loose_m if m.source == "gold_diff"}
        assert loose_g <= strict_g, case.case_id
        assert loose_g == {m for m in strict_g if not 0 < m[1] <= 1}, case.case_id
        paise += len(strict_g - loose_g)
        kept += len(loose_g)
    assert paise > 0 and kept > 0


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
    assert "tolerance: Rs 0" in (out / "baseline.md").read_text()
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
            "--tolerance-rs",
            "1",
        ]
    )
    report = (out / "report.md").read_text()
    assert "HARNESS CHECK ONLY" in report  # auto-approve is stamped, never silent
    assert "Frozen playbook hash" in report and "Spread across the 2" in report
    assert "tolerance: Rs 1" in report  # the tolerance used is always visible
    assert json.loads((out / "report.json").read_text())["tolerance_rs"] == "1"
    pb = Playbook.load(out / "playbook.json")
    assert pb.frozen and pb.content_hash() == pb.frozen_hash
    with pytest.raises(SystemExit):  # a frozen playbook ends the experiment
        exp.main(["experiment", "--approve", "auto", "--out", str(out)])
    with pytest.raises(SystemExit):  # never learn from anything called held-out
        exp.main(["baseline", "--cases", "../claimsense-heldout", "--out", str(out)])
    with pytest.raises(SystemExit):  # a negative tolerance makes no sense
        exp.main(["baseline", "--out", str(out), "--tolerance-rs", "-1"])


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
    ho.main(args + ["--repeat", "2", "--tolerance-rs", "1"])
    report = (tmp_path / "res" / "heldout_report.md").read_text()
    assert "held-out cases: 20" in report and "Spread across 2" in report
    assert "tolerance: Rs 1" in report
    data = json.loads((tmp_path / "res" / "heldout_report.json").read_text())
    assert data["playbook_hash"] == pb.frozen_hash and len(data["after_runs"]) == 2
    assert data["tolerance_rs"] == "1"
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
