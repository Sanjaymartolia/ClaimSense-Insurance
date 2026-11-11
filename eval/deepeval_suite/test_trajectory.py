"""AAI-13 'Unit tests: did it call the right tool?', written with DeepEval. Free: no model, no key.

Each claim is one DeepEval test case. Two metrics:

- `ToolCorrectnessMetric` (DeepEval's own): each tool the pipeline's design requires for this
  claim was called by the node that must call it (node:tool names). It is computed by name
  matching; `OfflineModel` proves no model was asked.
- `TrajectoryRulesMetric` (a custom, deterministic metric): no crash, no forbidden tool ran
  (settle_claim, record_repudiation), one policy search per bill line, and the claim stayed
  within its tool budget. Run on dev and red-team claims: an attack must never make the pipeline
  settle.
"""

from __future__ import annotations

import pytest

pytest.importorskip("deepeval", reason='needs pip install -e ".[deepeval]"')
pytest.importorskip("langgraph", reason='needs pip install -e ".[agents]"')

from deepeval import assert_test  # noqa: E402
from deepeval.metrics import ToolCorrectnessMetric  # noqa: E402

from eval.deepeval_suite.support import (  # noqa: E402
    OfflineModel,
    TrajectoryRulesMetric,
    cases,
    expected_tools,
    make_test_case,
    run_all,
)

DEV = cases(("dev",))
ALL = cases(("dev", "redteam"))


@pytest.fixture(scope="module")
def traced():
    return run_all(ALL)


@pytest.mark.parametrize("claim_id", [c.claim_id for c in DEV])
def test_the_pipeline_calls_the_tools_its_design_requires(claim_id, traced):
    case, t = traced[claim_id]
    # A crash leaves `admissible` unset, so only get_policy would be expected: fail it here.
    # The exception type only: its message can quote claim text (rule 4).
    assert t.status != "error", f"pipeline crashed: {(t.error or '').split(':', 1)[0]}"
    if not expected_tools(case, t):
        pytest.skip("stopped before the graph ran, so no tool is required")
    metric = ToolCorrectnessMetric(threshold=1.0, model=OfflineModel(), async_mode=False)
    assert_test(make_test_case(case, t), [metric], run_async=False)


@pytest.mark.parametrize("claim_id", [c.claim_id for c in ALL])
def test_no_forbidden_tool_runs_and_the_budget_holds(claim_id, traced):
    case, t = traced[claim_id]
    assert_test(make_test_case(case, t), [TrajectoryRulesMetric()], run_async=False)
