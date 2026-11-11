"""DSPy / GEPA on the clause choice (L12 §6-7), offline: stub LMs, the real dev cases.

`dspy` is the `reflexion` extra, not `dev`, so CI (`.[dev]` only) skips this file.
"""

import importlib.util
import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

dspy = pytest.importorskip("dspy")

from claimsense.agents import CoverageAgent, Team, make_stub_services  # noqa: E402
from claimsense.agents import clauses as C  # noqa: E402
from claimsense.contracts import Claim  # noqa: E402
from claimsense.graph import LocalRunner  # noqa: E402
from claimsense.reflexion import evaluate, local_run_fn, summarize  # noqa: E402
from claimsense.reflexion.cases import load_cases, stub_services_factory  # noqa: E402
from claimsense.reflexion.dspy_coverage import (  # noqa: E402
    INPUT_FIELDS,
    ChooseClauses,
    OracleStubLM,
    StubLM,
    configure_dspy,
    coverage_examples,
    gold_chooser,
    make_metric,
    parse_candidates,
    program_chooser,
    render_inputs,
    score_choices,
)
from claimsense.reflexion.optimizers import (  # noqa: E402
    MethodResult,
    choose_winner,
    clause_accuracy,
    compile_bootstrap,
    compile_gepa,
    load_program,
    save_program,
    split_cases,
)

from .conftest import POLICY, approve, room_breach_packet  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def cases():
    return load_cases(ROOT / "eval" / "golden_dev")


@pytest.fixture(scope="module")
def factory():
    return stub_services_factory()


@pytest.fixture(autouse=True)
def stub(monkeypatch):
    monkeypatch.setenv("CLAIMSENSE_LLM", "stub")


# ------------------------------------------------------------------------------ data
def test_examples_cover_admissible_cases_only_and_leak_nothing(cases, factory):
    exs = coverage_examples(cases, factory)
    adm = [c for c in cases if c.gold_admissible]
    assert [e.case_id for e in exs] == [c.case_id for c in adm] and len(exs) >= 10
    for e in exs:
        assert set(e.inputs().keys()) == set(INPUT_FIELDS)
        text = " ".join(e[k] for k in INPUT_FIELDS).lower()
        for secret in ("scenario_label", "fixture_notes", "room_rent_breach", "gold"):
            assert secret not in text
        assert parse_candidates(e.bill_lines) == e.candidates  # the stub reads what we rendered
        for lid, clause in e.choices.items():  # a demo never shows a non-candidate id
            assert clause in e.candidates[lid]


def test_split_is_deterministic_disjoint_and_dev_only(cases):
    train, test = split_cases(cases)
    train2, test2 = split_cases(list(reversed(cases)))
    assert [c.case_id for c in train] == [c.case_id for c in train2]
    assert [c.case_id for c in test] == [c.case_id for c in test2]
    assert train and test and not {c.case_id for c in train} & {c.case_id for c in test}
    assert all(c.gold_admissible and c.split == "dev" for c in train + test)


# ------------------------------------------------------------------------------ metric
def test_metric_scores_reachable_lines_and_names_the_expected_clause(cases, factory):
    exs = coverage_examples(cases, factory)
    ex = next(e for e in exs if e.case_id == "CLM-0004")
    case = next(c for c in cases if c.case_id == "CLM-0004")
    metric = make_metric(cases, factory)
    perfect = metric(ex, dspy.Prediction(choices=ex.choices))
    assert (
        perfect.score == 1.0 and metric(ex, dspy.Prediction(choices=ex.choices), trace=[]) is True
    )
    # the stub rule: top candidate everywhere -> procedure and diagnostics cite 4.1 not 4.1.1
    top = {lid: ids[0] for lid, ids in ex.candidates.items()}
    got = metric(ex, dspy.Prediction(choices=top))
    assert 0 < got.score < 1 and C.OTHER_EXPENSES in got.feedback and "proportional" in got.feedback
    assert metric(ex, dspy.Prediction(choices=top), trace=[]) is False
    s = score_choices(case, ex.candidates, top)
    assert "CLM-0004-L03" in s.unreachable  # nursing's gold clause 12.1 is not a stub candidate
    assert all(lid not in s.unreachable for lid, _, _ in s.wrong)
    # garbage from the model is validated the way the agent validates it, never a crash
    assert metric(ex, dspy.Prediction(choices={"CLM-0004-L01": "made-up"})).score == got.score
    assert metric(ex, dspy.Prediction(choices="not a dict")).score == got.score


def test_score_never_touches_the_money_rule(cases, factory):
    """Rule 1: the choices go through the calculator; the metric reads its total, nothing else."""
    case = next(c for c in cases if c.case_id == "CLM-0006")
    ex = next(e for e in coverage_examples([case], factory))
    s = score_choices(case, ex.candidates, ex.choices)
    assert s.gold_total == case.gold_worksheet.total_payable
    assert s.settlement_error <= Decimal("1")  # gold is whole rupees, calculator keeps paise


# ------------------------------------------------------------------------------ offline LMs
def test_stub_lm_matches_the_stub_analyst_through_the_whole_pipeline(cases, factory):
    """A DSPy program answering with the top candidate must give exactly the stub baseline:
    same choices, same rupees, same edits. Otherwise the comparison rows are not comparable."""
    configure_dspy(cases)
    adm = [c for c in cases if c.gold_admissible]
    program = dspy.ChainOfThought(ChooseClauses)
    base = summarize(evaluate(local_run_fn(factory), adm, None, Decimal(1)))
    prog = summarize(
        evaluate(local_run_fn(factory, chooser=program_chooser(program)), adm, None, Decimal(1))
    )
    assert base == prog
    acc_base, rows_base = clause_accuracy(adm, factory)
    acc_prog, rows_prog = clause_accuracy(adm, factory, chooser=program_chooser(program))
    assert acc_base == acc_prog and rows_base == rows_prog
    acc_gold, _ = clause_accuracy(adm, factory, chooser=gold_chooser(adm))
    assert acc_gold == 1.0 > acc_base


def test_oracle_coach_bootstraps_demos_and_the_program_is_a_file(cases, factory, tmp_path):
    train, _ = split_cases(cases)
    configure_dspy(train)
    trainset = coverage_examples(train, factory)
    metric = make_metric(train, factory)
    student_only, _ = compile_bootstrap(trainset, metric, demos=3)
    coached, secs = compile_bootstrap(trainset, metric, teacher_lm=OracleStubLM(train), demos=3)
    assert sum(bool(d.get("augmented")) for d in student_only.predict.demos) == 0
    assert sum(bool(d.get("augmented")) for d in coached.predict.demos) == 3 and secs >= 0
    path = tmp_path / "programs" / "coached.json"
    save_program(coached, path)
    saved = json.loads(path.read_text())
    assert "predict" in saved and len(saved["predict"]["demos"]) == 3
    again = load_program(path)
    assert [d["choices"] for d in again.predict.demos] == [
        d["choices"] for d in coached.predict.demos
    ]
    assert again.predict.signature.instructions == ChooseClauses.instructions


def test_gepa_runs_offline_and_keeps_or_improves_the_instruction(cases, factory):
    train, _ = split_cases(cases)
    models = configure_dspy(train)
    trainset = coverage_examples(train, factory)
    program, _ = compile_gepa(
        trainset, make_metric(train, factory), models.reflection, max_metric_calls=15
    )
    assert isinstance(program.predict.signature.instructions, str)
    assert models.reflection.calls >= 1  # the reflector was asked
    assert models.student.calls >= len(trainset)


# ------------------------------------------------------------------------------ the seam
def test_chooser_seam_is_validated_like_the_model(services):
    """A chooser may only pick retrieved clauses; anything else falls back with a note, and a
    human override still wins (same contract as the model path)."""
    packet = room_breach_packet()
    claim = Claim.model_validate(packet["claim"])

    def bad(claim, cands, lessons, feedback, previous):
        return {"L1": "nowhere:9.9", "L5": C.HOSPITALISATION}

    agent = CoverageAgent(services, chooser=bad)
    choices, _, notes = agent.choose_clauses(claim, locked={"L5": C.NON_PAYABLE_ITEMS})
    assert choices["L1"] == C.ROOM_RENT_LIMIT and any("L1" in n for n in notes)
    assert choices["L5"] == C.NON_PAYABLE_ITEMS
    out = LocalRunner(Team(services, chooser=bad)).run(packet, approve())
    assert out["status"] == "settled"


def test_render_inputs_mirror_the_agent_prompt(services):
    claim = Claim.model_validate(room_breach_packet()["claim"])
    agent = CoverageAgent(services)
    cands = agent.candidates(claim)
    r = render_inputs(claim, cands, critic_feedback=["L1: unsupported_clause: x"], previous={})
    assert "Room category: single_private" in r["claim_context"]
    assert "L1 | room | Private room | Rs 21000.00 | days=3" in r["bill_lines"]
    assert r["lessons"] == "none" and "unsupported_clause" in r["critic_feedback"]
    assert parse_candidates(r["bill_lines"])["L1"][0] == C.ROOM_RENT_LIMIT


def test_stub_lm_answers_every_output_field_as_json():
    lm = StubLM()
    system = (
        "Your output fields are:\n1. `plan` (str): x\n2. `choices` (dict[str, str]): y\n"
        "All interactions"
    )
    out = json.loads(
        lm.answer(system, "L1 | room | r | Rs 1 | days=1\n  CANDIDATES:\n    - a: t\n    - b: t\n")
    )
    assert out == {"plan": "Top-ranked candidate for every line.", "choices": {"L1": "a"}}
    out = json.loads(
        lm.answer("Your output fields are:\n1. `new_instruction` (str): z\nAll interactions", "")
    )
    assert "clause" in out["new_instruction"].lower() and lm.calls == 2


# ------------------------------------------------------------------------------ the table
def _row(name, acc, err="0", chars=10):
    return MethodResult(name, "", acc, acc, [], err, 1.0, 0.0, chars, 0, 0, 0.0, 0)


def test_winner_is_accuracy_then_money_then_prompt_length():
    rows = [
        _row("Agent prompt (as shipped)", 0.9),  # never a candidate: not an optimizer
        _row("GEPA", 0.8, "5", 900),
        _row("BootstrapFewShot", 0.8, "5", 300),
        _row("DSPy Predict", 0.7),
    ]
    name, reason = choose_winner(rows)
    assert name == "BootstrapFewShot" and "tied with GEPA" in reason
    rows[1] = _row("GEPA", 0.8, "4", 900)
    assert choose_winner(rows)[0] == "GEPA"


def _script(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_dspy_script_runs_end_to_end_in_stub_mode(tmp_path):
    mod = _script("run_reflexion_dspy")
    out = tmp_path / "dspy"
    mod.main(
        [
            "--out",
            str(out),
            "--tolerance-rs",
            "1",
            "--gepa-metric-calls",
            "12",
            "--bootstrap-demos",
            "2",
            "--playbook",
            str(ROOT / "docs/experiments/reflexion/run-02/playbook.json"),
        ]
    )
    report = (out / "report.md").read_text()
    assert "HARNESS CHECK ONLY" in report and "**Chosen:" in report
    assert "tolerance: Rs 1" in report and "Ceiling: gold replay" in report
    data = json.loads((out / "results.json").read_text())
    assert data["harness_check_only"] is True and len(data["rows"]) == 8
    assert not set(data["train"]) & set(data["test"])
    for name in ("dspy-predict", "bootstrapfewshot-coach", "gepa"):
        assert (out / "programs" / f"{name}.json").exists()
    ceiling = next(r for r in data["rows"] if r["name"].startswith("Ceiling"))
    assert ceiling["test_accuracy"] == 1.0
    with pytest.raises(SystemExit):  # never learn from anything called held-out
        mod.main(["--cases", "../claimsense-heldout", "--out", str(out)])
    with pytest.raises(SystemExit):
        mod.main(["--out", str(out), "--tolerance-rs", "-1"])


def test_make_stub_services_is_enough_for_examples():
    """The kit example from conftest also renders; nothing in the DSPy path needs the dev files."""
    svc = make_stub_services(policies={"POL-001": POLICY})
    claim = Claim.model_validate(room_breach_packet()["claim"])
    cands = CoverageAgent(svc).candidates(claim)
    assert set(parse_candidates(render_inputs(claim, cands)["bill_lines"])) == {
        ln.line_id for ln in claim.bill_lines
    }
