"""AAI-13 LLM-as-a-judge, written with DeepEval. Opt-in: it needs a key and costs money.

    CLAIMSENSE_DEEPEVAL_JUDGE=1   turns these tests on (they skip otherwise)

The judge is the `judge` model in config/models.yaml, a different family from the agents. It reads
what an adjudicator reads (the review payload) and the policy text the agents were shown; neither
holds claim text. Two metrics:

- `GEval` with the agent suite's payload checklist (`eval.agent_suite.judge.CHECKLIST`): do the
  cited clauses support the deductions, do the numbers match, is no instruction from the claim
  documents followed, can a person tell why the claim is routed where it is.
- `FaithfulnessMetric`: is each deduction's explanation supported by the clause text it cites?

Both judges are uncalibrated (no Cohen's kappa against people yet), so a score here is an opinion
to read, not a gate. The threshold is DeepEval's default, 0.5.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("deepeval", reason='needs pip install -e ".[deepeval]"')
pytest.importorskip("langgraph", reason='needs pip install -e ".[agents]"')

pytestmark = pytest.mark.skipif(
    os.environ.get("CLAIMSENSE_DEEPEVAL_JUDGE") != "1",
    reason="the LLM judge is opt-in (it costs money): set CLAIMSENSE_DEEPEVAL_JUDGE=1",
)

from deepeval import assert_test  # noqa: E402
from deepeval.metrics import FaithfulnessMetric, GEval  # noqa: E402
from deepeval.test_case import LLMTestCase, SingleTurnParams  # noqa: E402

from eval.agent_suite.judge import CHECKLIST, evidence_from_trace  # noqa: E402
from eval.deepeval_suite.support import cases, judge_model, run_all  # noqa: E402

DEV = cases(("dev",))
THRESHOLD = 0.5


@pytest.fixture(scope="module")
def judge():
    model = judge_model()
    if model is None:
        pytest.skip("no OPENROUTER_API_KEY in the environment or in .env")
    return model


@pytest.fixture(scope="module")
def traced():
    return run_all(DEV)


def deductions(t) -> tuple[list[str], list[str]]:
    """Each deduction the adjudicator was shown, and the policy text of the clauses it cites."""
    if not t.review_payloads:
        return [], []
    ws = t.review_payloads[-1].get("worksheet") or {}
    deds = [d for line in ws.get("lines") or [] for d in line.get("deductions") or []]
    if ws.get("co_pay"):
        deds.append(ws["co_pay"])
    lines = [
        f"Rs {d.get('amount')} deducted ({d.get('reason')}) under clause {d.get('clause_id')}: "
        f"{d.get('explanation', '')}"
        for d in deds
    ]
    cited = sorted({d.get("clause_id") for d in deds if d.get("clause_id")})
    return lines, [t.clause_texts[c] for c in cited if c in t.clause_texts]


@pytest.mark.parametrize("claim_id", [c.claim_id for c in DEV])
def test_the_review_payload_meets_the_checklist(claim_id, traced, judge):
    _, t = traced[claim_id]
    evidence = evidence_from_trace(t)
    if not evidence:
        pytest.skip("no review payload: the claim never reached a person")
    case = LLMTestCase(
        input="Grade this review payload, which a claims adjudicator will read before deciding.",
        actual_output=evidence,
        name=claim_id,
    )
    metric = GEval(
        name="Review payload checklist",
        criteria=CHECKLIST,
        evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT],
        model=judge,
        threshold=THRESHOLD,
        async_mode=False,
    )
    assert_test(case, [metric], run_async=False)


@pytest.mark.parametrize("claim_id", [c.claim_id for c in DEV])
def test_each_deduction_is_faithful_to_the_clause_it_cites(claim_id, traced, judge):
    _, t = traced[claim_id]
    lines, contexts = deductions(t)
    if not lines or not contexts:
        pytest.skip("no deduction with a retrieved clause on this claim")
    case = LLMTestCase(
        input=f"Why was money deducted on claim {claim_id}?",
        actual_output="\n".join(lines),
        retrieval_context=contexts,
        name=claim_id,
    )
    metric = FaithfulnessMetric(threshold=THRESHOLD, model=judge, async_mode=False)
    assert_test(case, [metric], run_async=False)
