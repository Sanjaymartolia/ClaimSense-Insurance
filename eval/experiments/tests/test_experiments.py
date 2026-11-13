"""E1 configs and the one harness, offline: config rules, the three adapters in stub mode, the
single agent's budget stop and pick validation (scripted fake model), and the comparison maths."""

import dataclasses
import shutil
from types import SimpleNamespace

import pytest
import yaml

from eval.experiments import adapters as A
from eval.experiments import config as K
from eval.experiments import run as R
from eval.harness.loader import load_cases


@pytest.fixture(autouse=True)
def _stub(monkeypatch):
    monkeypatch.setenv("CLAIMSENSE_LLM", "stub")


@pytest.fixture(scope="module")
def e1():
    return K.load_experiment("E1")


@pytest.fixture(scope="module")
def two_cases():
    return load_cases(["dev"])[:2]


def test_e1_has_three_comparable_conditions(e1):
    assert [(c.condition, c.architecture) for c in e1] == [
        ("C0", "fixed"),
        ("C1", "single_agent"),
        ("C2", "team"),
    ]
    models = yaml.safe_load(K.MODELS_YAML.read_text(encoding="utf-8"))["models"]
    assert {c.model for c in e1} == {models["coverage"]}
    assert len({tuple(sorted(c.shared().items(), key=str)) for c in e1}) == 1


def _copy(tmp_path, change=None, name="E1_C1_single_agent.yaml"):
    for src in K.CONFIG_DIR.glob("E1_*.yaml"):
        shutil.copy(src, tmp_path / src.name)
    if change:
        path = tmp_path / name
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        change(raw)
        path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize(
    "change",
    [
        lambda r: r["budget"].update(max_tool_calls_per_claim=99),
        lambda r: r.update(model_role="critic"),
        lambda r: r.update(tools=["policy_search"]),
        lambda r: r["data"].update(splits=["dev"]),
    ],
)
def test_a_condition_that_differs_in_more_than_architecture_is_refused(tmp_path, change):
    with pytest.raises(K.ConfigError, match="may change between conditions"):
        K.load_experiment("E1", _copy(tmp_path, change))


def test_a_model_id_in_a_config_is_refused(tmp_path):
    folder = _copy(tmp_path, lambda r: r.update(model="openai/gpt-4o-mini"))
    with pytest.raises(K.ConfigError, match="model_role"):
        K.load_experiment("E1", folder)


def test_an_unknown_model_role_is_refused(tmp_path):
    folder = _copy(tmp_path)
    for path in folder.glob("*.yaml"):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        raw["model_role"] = "nope"
        path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(K.ConfigError, match="not in"):
        K.load_experiment("E1", folder)


@pytest.mark.parametrize("condition", ["C0", "C1", "C2"])
def test_each_architecture_runs_and_the_calculator_makes_the_money(e1, two_cases, condition):
    cfg = next(c for c in e1 if c.condition == condition)
    with R.same_model(cfg.model):
        adapter = A.build(cfg)
        outs = [adapter.run(case.claim) for case in two_cases]
    for case, out in zip(two_cases, outs, strict=True):
        assert out.claim_id == case.claim_id and out.error is None
        assert out.route in ("needs_review", "ready_for_approval")
        if out.worksheet is not None:
            assert "calculate" in {a.tool for a in out.actions if a.status == "executed"}


def test_same_model_sets_every_role_and_restores(e1):
    from claimsense.agents import llm

    before = dict(llm.MODELS)
    with R.same_model("x/model"):
        assert set(llm.MODELS.values()) == {"x/model"}
    assert llm.MODELS == before


class _ToolHappyModel:
    """Always asks for another search; answers only when made to."""

    def __init__(self, final):
        self.final, self.rounds = final, 0

    def bind_tools(self, tools):
        self.tool_names = [t.name for t in tools]
        return self

    def invoke(self, messages):
        from langchain_core.messages import AIMessage

        self.rounds += 1
        return AIMessage(
            content="",
            tool_calls=[
                {"name": "policy_search", "args": {"query": "room"}, "id": f"a{self.rounds}"},
                {"name": "policy_search", "args": {"query": "icu"}, "id": f"b{self.rounds}"},
            ],
        )

    def with_structured_output(self, _schema):
        return SimpleNamespace(invoke=lambda _messages: self.final)


def _parsed(adapter, case):
    from claimsense.contracts import Claim

    return Claim.model_validate(adapter._packet(case.claim)["claim"])


def test_single_agent_stops_at_the_tool_budget(e1, two_cases):
    cfg = dataclasses.replace(next(c for c in e1 if c.condition == "C1"), budget=K.Budget(3, 0.20))
    adapter = A.SingleAgentAdapter(cfg)
    case = two_cases[0]
    final = A.FinalDecision(choices=[], admissible=True, needs_review=False)
    model = _ToolHappyModel(final)
    got, seen, executed, stop = adapter.decide(
        model, _parsed(adapter, case), {}, adapter._services(case.claim)
    )
    assert got is final and stop == "tool budget"
    assert executed == ["policy_search"] * 3
    assert set(model.tool_names) == set(cfg.tools)
    assert seen  # the searches it did run returned clauses


def test_single_agent_picks_must_be_line_level_clauses_it_was_shown(two_cases, e1):
    from claimsense.agents import clauses as C

    adapter = A.SingleAgentAdapter(next(c for c in e1 if c.condition == "C1"))
    claim = _parsed(adapter, two_cases[0])
    first, second, *rest = [line.line_id for line in claim.bill_lines]
    shown = "kb:shown"
    final = A.FinalDecision(
        choices=[
            A.LinePick(line_id=first, clause_id=shown, rationale="because"),
            A.LinePick(line_id=second, clause_id=C.MATERNITY_EXCLUSION, rationale="x"),
        ],
        admissible=True,
        needs_review=False,
    )
    seen = {shown: "text", C.MATERNITY_EXCLUSION: "excluded"}
    choices, rationales, contexts = A.validate(final, claim, seen, C)
    assert choices[first] == shown and rationales == {first: "because"}
    assert contexts == {first: ["text"]}
    assert choices[second] == C.HOSPITALISATION  # claim-level clause: not a line pick
    assert all(choices[lid] == C.HOSPITALISATION for lid in rest)  # never picked


def test_compare_gives_quality_per_extra_dollar():
    rows = [
        {"condition": "C0", "composite": 0.80, "cost_usd_per_claim": 0.001},
        {"condition": "C1", "composite": 0.85, "cost_usd_per_claim": 0.011},
        {"condition": "C2", "composite": 0.70, "cost_usd_per_claim": 0.001},
    ]
    out = {r["condition"]: r for r in R.compare(rows)}
    assert out["C0"]["quality_per_extra_usd"] is None  # the cheapest (ties go to C0)
    assert out["C1"]["quality_per_extra_usd"] == 5.0  # +0.05 for +$0.01
    assert out["C2"]["quality_per_extra_usd"] is None  # no extra cost
    assert {r["vs"] for r in out.values()} == {"C0"}


def test_existing_label_and_missing_key_are_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "RUNS_DIR", tmp_path)
    (tmp_path / "taken").mkdir()
    assert R.main(["--experiment", "E1", "--label", "taken", "--stub"]) == 2
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert R.main(["--experiment", "E1", "--label", "fresh"]) == 2
    assert not (tmp_path / "fresh").exists()
