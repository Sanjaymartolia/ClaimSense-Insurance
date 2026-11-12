"""Retrieval and the RAGAS judge in the pipeline runs (12 Nov 2026).

Before: every eval run used the stub clause table (it ignores the query), and the judge scored a
placeholder sentence the adapter wrote, not the coverage model's rationale. No API key is used.
"""

from __future__ import annotations

import pytest

from eval.harness import llm_judge_metrics as judge
from eval.harness.loader import REPO_ROOT, load_split
from eval.harness.models import AgentOutput

pytest.importorskip("claimsense.agents", reason="needs pip install -e '.[dev]'")


@pytest.fixture(scope="module")
def dev_cases():
    return load_split("dev")


def _fake_model_choices(monkeypatch):
    """Make the coverage agent 'ask a model' that picks the top candidate with a reason."""
    from claimsense.agents import coverage

    monkeypatch.setattr(coverage, "get_llm", lambda role: object())

    def ask(self, claim, cands, lessons, feedback, previous, rationales=None):
        picks = {lid: ps[0].clause.clause_id for lid, ps in cands.items() if ps}
        if rationales is not None:
            rationales.update(
                {lid: f"Line {lid} is governed by the wording shown." for lid in picks}
            )
        return picks

    monkeypatch.setattr(coverage.CoverageAgent, "_ask_model", ask)


def test_the_adapter_hands_the_judge_the_model_rationale_and_what_it_saw(monkeypatch, dev_cases):
    from eval.harness.claimsense_adapter import ClaimSenseAdapter

    _fake_model_choices(monkeypatch)
    case = next(c for c in dev_cases if c.claim_id == "CLM-0004")
    out = ClaimSenseAdapter().run(case.claim)

    judged = set(out.retrieved_contexts)
    assert judged, "lines with a model rationale carry the wording the model was shown"
    for line_id in judged:
        assert out.rationales[line_id] == f"Line {line_id} is governed by the wording shown."
        assert all(text.strip() for text in out.retrieved_contexts[line_id])


def test_stub_agents_give_the_judge_nothing_to_score(dev_cases):
    """No model, no rationale: the placeholder sentence is never judged, even after `run.py`
    calls attach_clause_contexts (review finding: it used to rebuild context for placeholders)."""
    from eval.harness.claimsense_adapter import ClaimSenseAdapter

    case = next(c for c in dev_cases if c.claim_id == "CLM-0004")
    out = ClaimSenseAdapter().run(case.claim)
    assert out.retrieved_contexts == {}
    assert all(judge.is_placeholder(r) for r in out.rationales.values())
    assert judge.attach_clause_contexts([out], [case]) == 0
    assert out.retrieved_contexts == {}, "nothing for the judge to score"


def test_the_placeholder_check_does_not_catch_real_text():
    assert judge.is_placeholder(
        "Line L1 was adjudicated under clause new_india_arogya_sanjeevani:4.1."
    )
    assert not judge.is_placeholder("Line L1 is allowed Rs 500 under clause 4.1.")  # gold-replay
    assert not judge.is_placeholder("Room rent is capped at 2% of the sum insured per day.")


def test_a_traced_run_hands_the_scorer_the_same_rationales_as_the_adapter(monkeypatch, dev_cases):
    """trace.py promises `output` is field for field what the adapter returns (review finding)."""
    from eval.agent_suite.trace import run_traced
    from eval.harness.claimsense_adapter import ClaimSenseAdapter

    _fake_model_choices(monkeypatch)
    case = next(c for c in dev_cases if c.claim_id == "CLM-0004")
    adapter_out = ClaimSenseAdapter().run(case.claim)
    traced_out = run_traced(case).output
    assert traced_out.rationales == adapter_out.rationales
    assert traced_out.retrieved_contexts == adapter_out.retrieved_contexts
    assert traced_out.retrieved_contexts, "the fake model gave reasons, so there is context"


def test_a_reason_for_another_clause_is_not_kept_after_an_edit():
    """apply_edits can lock a new clause without a new choose_clauses call (review finding)."""
    from types import SimpleNamespace

    from eval.harness.claimsense_adapter import coverage_rationales

    coverage = SimpleNamespace(
        rationales={"L1": "Room capped.", "L2": "OT covered."},
        rationale_clauses={"L1": "c:12.1", "L2": "c:4.1"},
        shown={"L1": ["room text"], "L2": ["ot text"]},
    )
    rationales, contexts = coverage_rationales(
        SimpleNamespace(coverage=coverage), {"L1": "c:12.1", "L2": "c:annexure"}
    )
    assert rationales["L1"] == "Room capped." and contexts == {"L1": ["room text"]}
    assert judge.is_placeholder(rationales["L2"]), "the edited line's old reason is dropped"


def _fake_chat(cost: float, tokens_in: int = 120, tokens_out: int = 30):
    pytest.importorskip("langchain_core", reason='needs pip install -e ".[agents]"')
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
    from langchain_core.messages import AIMessage

    usage = {"prompt_tokens": tokens_in, "completion_tokens": tokens_out, "cost": cost}
    meta = {"input_tokens": tokens_in, "output_tokens": tokens_out, "total_tokens": 150}
    reply = AIMessage(content="ok", usage_metadata=meta, response_metadata={"token_usage": usage})
    return GenericFakeChatModel(messages=iter([reply]))


def test_model_calls_are_counted_in_tokens_and_cost():
    """`eval.harness.run` used to report tokens_per_claim 0 and cost_usd_per_claim 0 in real
    mode: the adapter never counted the agents' model calls (only run_traced did)."""
    from eval.harness.claimsense_adapter import count_llm_usage

    model = _fake_chat(cost=0.0004)
    with count_llm_usage() as usage:
        model.invoke("hi")
    assert usage == {"prompt_tokens": 120, "completion_tokens": 30, "cost_usd": 0.0004}
    with count_llm_usage(enabled=False) as off:
        _fake_chat(cost=0.0004).invoke("hi")
    assert off == {"prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0}


def test_the_adapter_reports_what_the_models_cost(monkeypatch, dev_cases):
    from contextlib import contextmanager

    from eval.harness import claimsense_adapter
    from eval.harness.efficiency_metrics import summarise

    @contextmanager
    def spent(_enabled=True):
        yield {"prompt_tokens": 1500, "completion_tokens": 200, "cost_usd": 0.0013}

    monkeypatch.setattr(claimsense_adapter, "count_llm_usage", spent)
    case = next(c for c in dev_cases if c.claim_id == "CLM-0004")
    out = claimsense_adapter.ClaimSenseAdapter().run(case.claim)
    assert (out.prompt_tokens, out.completion_tokens, out.cost_usd) == (1500, 200, 0.0013)
    metrics = summarise([out])
    assert metrics["tokens_per_claim"].value == 1700
    assert metrics["cost_usd_per_claim"].value == pytest.approx(0.0013)


def test_variants_without_real_retrieval_need_no_retriever():
    from eval.agent_suite.suite import retrieval_problem

    assert retrieval_problem(["v1", "guarded"]) is None


def test_a_changed_tool_definition_stops_the_run_cleanly(monkeypatch):
    """A ToolPinError used to escape as a traceback (review finding)."""
    from claimsense.hooks import pins
    from claimsense.mcp_servers import policy_kb
    from eval.harness.real_retrieval import RetrievalUnavailableError, open_real_retrieval

    monkeypatch.setattr(policy_kb, "warm_up", lambda: None)

    def refuse(_registry, _pins=None):
        raise pins.ToolPinError("policy_search changed since review.")

    monkeypatch.setattr(pins, "check_pins", refuse)
    with pytest.raises(RetrievalUnavailableError, match="pins --update"):
        open_real_retrieval()


def test_the_python_314_eval_extra_covers_what_ragas_needs():
    """On 3.14 ragas goes in with --no-deps, so the extra must list its dependencies itself
    (review finding: pillow was missing, and `from ragas.metrics.collections` needs it)."""
    import re
    import tomllib
    from importlib.metadata import PackageNotFoundError, requires

    try:
        needed = requires("ragas") or []
    except PackageNotFoundError:
        pytest.skip("ragas is not installed")
    norm = lambda name: re.sub(r"[-_.]+", "-", name).lower()  # noqa: E731
    needed = {
        norm(re.split(r"[ <>=!;\[(~]", r, maxsplit=1)[0]) for r in needed if "extra ==" not in r
    }
    extra = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    listed = extra["project"]["optional-dependencies"]["eval"] + extra["project"]["dependencies"]
    have = {norm(re.split(r"[ <>=!;\[(~]", d, maxsplit=1)[0]) for d in listed}
    missing = needed - have - {"scikit-network", "pydantic"}  # pydantic: a core dependency
    assert not missing, f"add to the eval extra (and requirements.txt): {sorted(missing)}"


def test_attach_adds_the_claim_facts_to_context_an_adapter_recorded(dev_cases):
    case = next(c for c in dev_cases if c.claim_id == "CLM-0018")
    out = AgentOutput(
        claim_id=case.claim_id, rationales={"L1": "r"}, retrieved_contexts={"L1": ["shown"]}
    )
    assert judge.attach_clause_contexts([out], [case]) == 0, "nothing reconstructed"
    assert out.retrieved_contexts["L1"] == ["shown", judge.claim_facts(case.claim)]
    judge.attach_clause_contexts([out], [case])
    assert len(out.retrieved_contexts["L1"]) == 2, "the facts are added once"


def test_an_unknown_retrieval_mode_is_refused(dev_cases):
    from eval.agent_suite.trace import run_traced

    with pytest.raises(ValueError, match="retrieval"):
        run_traced(dev_cases[0], retrieval="magic")


def test_the_real_retrieval_adapter_searches_the_real_index(dev_cases):
    pytest.importorskip("chromadb", reason='needs pip install -e ".[retrieval]"')
    if not (REPO_ROOT / "chroma-data").exists():
        pytest.skip("no index: python -m claimsense.retrieval.index")
    from claimsense.mcp_servers import policy_kb
    from eval.harness.adapters import build_adapter

    adapter = build_adapter("claimsense-real-retrieval", dev_cases)
    case = next(c for c in dev_cases if c.claim_id == "CLM-0004")
    out = adapter.run(case.claim)
    assert out.error is None
    assert any(a.tool == "policy_search" and a.status == "executed" for a in out.actions)
    assert out.citations and all(
        c.startswith("new_india_arogya_sanjeevani:") for c in out.citations
    )
    assert policy_kb._ENGINE is not None, "the hybrid retriever answered the searches"
