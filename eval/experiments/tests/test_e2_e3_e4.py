"""E2 (defences), E3 (lessons) and E4 (who computes the rupees), offline."""

import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

from eval.experiments import adapters as A
from eval.experiments import config as K
from eval.experiments import e3
from eval.experiments import run as R
from eval.harness.loader import load_cases


@pytest.fixture(autouse=True)
def _stub(monkeypatch):
    monkeypatch.setenv("CLAIMSENSE_LLM", "stub")


# ------------------------------------------------------------------------------ configs
def test_e2_and_e4_vary_only_their_own_field():
    e2, e4 = K.load_experiment("E2"), K.load_experiment("E4")
    assert [c.defence for c in e2] == ["none", "input", "input+scan", "input+guard_model"]
    assert {c.measure for c in e2} == {"security"} and {c.varies for c in e2} == {("defence",)}
    assert [c.arithmetic for c in e4] == ["calculator", "llm"]
    assert {c.varies for c in e4} == {("arithmetic",)}


@pytest.mark.parametrize(
    "overrides",
    [
        {"architecture": "fixed", "defence": "none"},  # defences apply to the team only
        {"arithmetic": "llm", "calculator": "reference"},  # llm replaces the real calculator
        {"defence": "everything"},
        {"varies": ["model_role"]},
    ],
)
def test_impossible_conditions_are_refused(tmp_path, overrides):
    import yaml

    raw = yaml.safe_load((K.CONFIG_DIR / "E4_A0_calculator.yaml").read_text(encoding="utf-8"))
    raw.update(overrides)
    path = tmp_path / "E9_X.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(K.ConfigError):
        K.load(path)


# ------------------------------------------------------------------------------ E2
@pytest.fixture(scope="module")
def e2_rows():
    with R.llm_mode(True):
        return {
            c.defence: R.security_row(c, ("dev", "redteam"), True) for c in K.load_experiment("E2")
        }


def test_defences_on_stop_attacks_without_blocking_more_clean_claims(e2_rows):
    off, on = e2_rows["none"], e2_rows["input"]
    assert off["n_attacked"] == 30 and off["n_clean"] > 0
    assert on["attack_success_rate"] < off["attack_success_rate"]
    assert on["injections_shown"] == 1.0 and off["injections_shown"] == 0.0
    assert on["false_block_rate"] <= off["false_block_rate"]


def test_guard_model_is_skipped_in_stub_mode(e2_rows):
    assert e2_rows["input+guard_model"]["skipped"] == "real mode only"


# ------------------------------------------------------------------------------ E4
@pytest.fixture(scope="module")
def claim():
    from claimsense.contracts import Claim
    from eval.harness.claimsense_adapter import ClaimSenseAdapter

    adapter = ClaimSenseAdapter(calculator="real")
    case = load_cases(["dev"])[3]
    return Claim.model_validate(adapter._packet(case.claim)["claim"])


def _calc():
    from claimsense.agents.services import real_calculate

    return real_calculate


def test_stub_llm_arithmetic_returns_the_calculator_and_logs_zero_error(claim):
    fn = A.LlmArithmetic(_calc())
    ws = fn(claim, {})
    assert ws.total_payable == _calc()(claim, {}).total_payable
    assert fn.log[claim.claim_id] == {
        "total_error_rs": 0.0,
        "line_error_rs": 0.0,
        "reconciles": True,
    }


def test_model_numbers_are_kept_as_given_and_their_error_measured(claim, monkeypatch):
    truth = _calc()(claim, {})
    wrong = A.LlmWorksheet(
        lines=[A.LlmLine(line_id=b.line_id, payable=float(b.amount)) for b in claim.bill_lines],
        co_pay=0.0,
        total_payable=float(truth.total_payable) + 1000,
    )
    fake = SimpleNamespace(
        with_structured_output=lambda _s: SimpleNamespace(invoke=lambda _m: wrong)
    )
    monkeypatch.setattr("claimsense.agents.llm.get_llm", lambda _role: fake)
    fn = A.LlmArithmetic(_calc())
    ws = fn(claim, {})
    assert ws.total_payable == Decimal(str(round(float(truth.total_payable) + 1000, 2)))
    log = fn.log[claim.claim_id]
    assert log["total_error_rs"] == pytest.approx(1000, abs=0.01)
    assert log["reconciles"] is False  # lines claim no deductions, the total says otherwise


def test_rules_in_words_carry_the_calculator_caps(claim):
    from claimsense.calc.adjudication import PolicyRules

    text = A.rules_in_words(claim)
    room = min(claim.sum_insured * PolicyRules().room_rent_pct, PolicyRules().room_rent_max_per_day)
    assert f"Rs {room}" in text and "proportional" in text and "Co-payment" in text


def test_arithmetic_summary():
    log = {
        "a": {"total_error_rs": 0.0, "line_error_rs": 0.0, "reconciles": True},
        "b": {"total_error_rs": 120.5, "line_error_rs": 300.0, "reconciles": False},
    }
    assert R.arithmetic_summary(log) == {
        "arithmetic_error_rs_mean": 60.25,
        "arithmetic_error_rs_max": 120.5,
        "claims_with_error": 1,
        "worksheets_not_reconciling": 1,
    }


def test_e4_llm_condition_swaps_only_the_calculator():
    a0, a1 = K.load_experiment("E4")
    plain, swapped = A.build(a0), A.build(a1)
    assert not hasattr(plain, "arithmetic")
    assert swapped._imports["real_calculate"] is swapped.arithmetic


# ------------------------------------------------------------------------------ E3
def test_e3_config_needs_three_repeats(tmp_path):
    import yaml

    raw = yaml.safe_load(e3.CONFIG.read_text(encoding="utf-8"))
    assert e3.load_e3()["repeat"] >= 3
    raw["repeat"] = 1
    path = tmp_path / "E3.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(K.ConfigError, match="3"):
        e3.load_e3(path)


def test_lesson_meter_counts_calls_and_lessons():
    drafts = iter([object(), None, object()])
    meter = e3.LessonMeter(lambda *a, **k: next(drafts), metered=False)
    for _ in range(3):
        meter("mistake")
    s = meter.summary()
    assert (s["reflect_calls"], s["lessons_drafted"], s["cost_usd"]) == (3, 2, 0.0)


def test_harmful_lessons_come_from_the_ablation(tmp_path):
    report = {
        "ablation": [
            {"lesson_id": "L1", "harmful": True, "error_increase_rs": "12.00"},
            {"lesson_id": "L2", "harmful": False, "error_increase_rs": "-3.00"},
        ]
    }
    (tmp_path / "report.json").write_text(json.dumps(report), encoding="utf-8")
    assert e3.harmful_lessons(tmp_path / "report.json") == [
        {"lesson_id": "L1", "error_increase_rs": "12.00", "harmful": True}
    ]
    assert e3.harmful_lessons(tmp_path / "missing.json") == []


def test_heldout_passes_the_config_through_and_reads_nothing(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        e3,
        "_script",
        lambda name: SimpleNamespace(main=lambda argv: seen.update(name=name, argv=argv)),
    )
    assert e3.main(["heldout", "--heldout", "../h", "--out", "../o"]) == 0
    argv = seen["argv"]
    assert seen["name"] == "run_reflexion_heldout"
    assert argv[argv.index("--repeat") + 1] == "3"
    assert argv[argv.index("--heldout") + 1] == "../h"
    assert argv[argv.index("--playbook") + 1].endswith("run-03/playbook.json")


def test_run_py_refuses_e3():
    with pytest.raises(K.ConfigError, match="e3"):
        K.load_experiment("E3")
