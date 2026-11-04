"""The judge's inputs. No API call is made here, so these tests are free and run offline.

The judge's *output* is not tested: it is a model's opinion, and an assertion on it would be a
test of OpenRouter. What is tested is everything that decides what the judge sees, because that is
where the measurement error was.
"""

from __future__ import annotations

import os

import pytest

from eval.harness import llm_judge_metrics as judge
from eval.harness.loader import load_split
from eval.harness.models import AgentOutput


@pytest.fixture(scope="module")
def dev_cases():
    return load_split("dev")


# ------------------------------------------------------------------ claim facts
def test_claim_facts_carry_the_facts_a_rationale_relies_on(dev_cases):
    """Measured: a correct rationale scores 0.200 against clause text alone and 0.800 once these
    facts are added. The claim-derived half of a rationale is unverifiable without them."""
    case = next(c for c in dev_cases if c.claim_id == "CLM-0018")
    text = judge.claim_facts(case.claim)
    assert "CLM-0018" in text
    assert "Caesarean" in text, "the diagnosis must reach the judge"
    assert "2026-05-06" in text, "the admission date must reach the judge"


def test_claim_facts_state_no_conclusion(dev_cases):
    """If the context said whether a line is payable, the judge could read the answer off it and
    would stop measuring the rationale."""
    for case in dev_cases:
        text = judge.claim_facts(case.claim).lower()
        for leak in ("payable", "not payable", "excluded", "admissible", "settlement"):
            assert leak not in text, f"{case.claim_id}: claim facts leak a conclusion ({leak!r})"


def test_claim_facts_say_that_absent_conditions_are_absent(dev_cases):
    """Clause 7.15 excepts ectopic pregnancy. A rationale must be able to say the claim does not
    record one. That is only verifiable if the context says so."""
    text = judge.claim_facts(dev_cases[0].claim)
    assert "not recorded on this claim" in text


# ------------------------------------------------------------------ context assembly
def test_attach_adds_both_the_clause_text_and_the_claim_facts(dev_cases):
    case = next(c for c in dev_cases if c.claim_id == "CLM-0018")
    out = AgentOutput(
        claim_id=case.claim_id,
        citations=["new_india_arogya_sanjeevani:7.15"],
        rationales={"CLM-0018-L01": "Not payable under 7.15."},
    )
    filled = judge.attach_clause_contexts([out], [case])
    assert filled == 1
    contexts = out.retrieved_contexts["CLM-0018-L01"]
    assert len(contexts) == 2, "expected the clause text and the claim facts"
    assert any("Maternity" in c for c in contexts)
    assert any("CLM-0018 facts" in c for c in contexts)


def test_attach_without_cases_still_adds_the_clause_text(dev_cases):
    """`cases` is optional so an adapter that records its own full context is left alone."""
    out = AgentOutput(
        claim_id="CLM-0018",
        citations=["new_india_arogya_sanjeevani:7.15"],
        rationales={"L1": "r"},
    )
    assert judge.attach_clause_contexts([out]) == 1
    assert len(out.retrieved_contexts["L1"]) == 1


def test_attach_never_overwrites_context_an_adapter_already_recorded():
    """What the agent was really shown beats anything reconstructed here."""
    out = AgentOutput(
        claim_id="X", rationales={"L1": "r"}, retrieved_contexts={"L1": ["the real context"]}
    )
    assert judge.attach_clause_contexts([out]) == 0
    assert out.retrieved_contexts == {"L1": ["the real context"]}


def test_attach_skips_an_output_with_no_rationale_to_judge():
    out = AgentOutput(claim_id="X", citations=["new_india_arogya_sanjeevani:4.1"], rationales={})
    assert judge.attach_clause_contexts([out]) == 0


def test_attach_skips_a_citation_that_is_not_a_real_clause():
    out = AgentOutput(claim_id="X", citations=["made:up"], rationales={"L1": "r"})
    assert judge.attach_clause_contexts([out]) == 0, "no real clause means nothing to judge against"


# ------------------------------------------------------------------ clause text
def test_the_clause_index_uses_the_text_with_headings():
    """A list item such as 6.2.6 is just "6. Hysterectomy" without its parent heading (AGT-13).
    Judging against the bare item would mark correct rationales unfaithful."""
    index = judge.clause_text_index()
    item = index["new_india_arogya_sanjeevani:6.2.6"]
    assert "Hysterectomy" in item
    assert "Specific Waiting Period" in item, "the parent heading must be included"


# ------------------------------------------------------------------ the key
def test_the_dotenv_loader_reports_presence_and_never_returns_the_value(monkeypatch):
    """Rule 4: the key is never printed, logged or returned. Only presence is reported."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-not-a-real-key")
    result = judge.load_key_from_dotenv()
    assert result is True
    assert isinstance(result, bool), "a bool, never the key itself"


def test_the_dotenv_loader_is_a_no_op_when_the_key_is_already_set(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-already-here")
    judge.load_key_from_dotenv()
    assert os.environ["OPENROUTER_API_KEY"] == "sk-or-already-here"


def test_the_judge_refuses_clearly_when_no_key_is_available(monkeypatch, tmp_path):
    """The rest of the harness runs without a key. The judge must say so, not fail obscurely."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(judge, "REPO_ROOT", tmp_path)  # a root with no .env
    pytest.importorskip("ragas")
    with pytest.raises(judge.JudgeUnavailableError, match="needs a key"):
        judge._build_scorer()
