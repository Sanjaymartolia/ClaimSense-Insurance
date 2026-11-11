"""What the DeepEval tests share: traced claims, the expected tools, two models, one custom metric.

Rule 4 (no health details): a DeepEval test case is kept in DeepEval's local cache (`.deepeval/`)
and printed on failure, so it never holds claim text. `input` is a claim id, `actual_output` is
the route and the amount, tools are names only, and the judge reads the review payload and the
policy text, which hold no health details by construction (`eval.agent_suite.judge`).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from functools import cache
from typing import Any

import yaml
from deepeval.metrics import BaseMetric
from deepeval.models import DeepEvalBaseLLM
from deepeval.test_case import LLMTestCase, ToolCall

from eval.agent_suite.dataset import Case, load_dataset
from eval.agent_suite.trace import FORBIDDEN_TOOLS, Trace, run_traced
from eval.harness.loader import REPO_ROOT


def mode() -> str:
    from claimsense.agents.llm import stub_mode

    return "stub" if stub_mode() else "real"


@cache
def cases(splits: tuple[str, ...] = ("dev",)) -> tuple[Case, ...]:
    return tuple(load_dataset(splits))


def run_all(selected: tuple[Case, ...], workers: int = 4) -> dict[str, tuple[Case, Trace]]:
    """Run each claim once through the real pipeline (variant v1). Real mode costs money."""
    with ThreadPoolExecutor(workers) as pool:
        traces = list(pool.map(lambda c: run_traced(c.eval_case), selected))
    return {c.claim_id: (c, t) for c, t in zip(selected, traces, strict=True)}


# --------------------------------------------------------------------------- the tools
def _went_on(t: Trace) -> bool:
    """Past admissibility and not blocked: `went_on` in `eval/agent_suite/process.py`."""
    return t.admissible is True and t.status != "blocked"


def expected_tools(case: Case, t: Trace) -> list[str]:
    """The (node:tool) calls the pipeline's design requires for this claim: the agent suite's
    path checks (`eval/agent_suite/process.py`), from the design and the claim's own bill, never
    from gold. The per-line search count is in `TrajectoryRulesMetric` (ToolCorrectness cannot
    count), and a crash fails both tests (it would leave `admissible` unset).

    Every claim the graph runs: admissibility reads the policy. A claim that went on: coverage
    searches the policy and computes the rupees in code (rule 1), the fraud agent reads the claim
    history, and for a procedure checks the tariff range. A claim blocked before the graph: [].
    """
    if not t.path:
        return []
    tools = ["admissibility:get_policy"]
    if _went_on(t):
        tools += ["coverage:policy_search", "coverage:calculate", "fraud:claim_history"]
        if case.has_procedure:
            tools.append("fraud:tariff_range")
    return tools


def tools_called(t: Trace) -> list[ToolCall]:
    """Tools that ran (an ACL refusal is not a call), as node:tool. No arguments: they can hold
    claim text."""
    return [ToolCall(name=f"{s.node}:{s.name}") for s in t.tool_spans if s.status != "blocked"]


def min_policy_searches(case: Case, t: Trace) -> int:
    """`retrieval_per_line`: one policy search per bill line, on every coverage attempt."""
    return case.n_lines * t.path.count("coverage") if _went_on(t) else 0


def make_test_case(case: Case, t: Trace, **extra: Any) -> LLMTestCase:
    money = "-" if t.settlement_inr is None else f"Rs {t.settlement_inr}"
    return LLMTestCase(
        input=f"Adjudicate claim {case.claim_id}",
        actual_output=f"route {t.route}; settlement {money}; status {t.status}",
        tools_called=tools_called(t),
        expected_tools=[ToolCall(name=n) for n in expected_tools(case, t)],
        name=case.claim_id,
        additional_metadata={
            "status": t.status,
            # the exception type only: its message can quote claim text (rule 4)
            "error_type": (t.error or "").split(":", 1)[0] if t.status == "error" else "",
            "min_policy_searches": min_policy_searches(case, t),
        },
        **extra,
    )


@cache
def tool_budget() -> int:
    """`budgets.max_tool_calls_per_claim` in config/models.yaml (the hooks' ceiling)."""
    config = yaml.safe_load((REPO_ROOT / "config" / "models.yaml").read_text(encoding="utf-8"))
    return int(config["budgets"]["max_tool_calls_per_claim"])


# ------------------------------------------------------------------------------ models
class OfflineModel(DeepEvalBaseLLM):
    """DeepEval 4.3 builds a model for every metric, even one that never asks it anything (tool
    correctness without `available_tools`). This one refuses every call, so a test that passes
    with it is proof that no model was used and nothing left the machine."""

    def __init__(self) -> None:
        super().__init__("offline")

    def load_model(self) -> None:
        return None

    def generate(self, *args: Any, **kwargs: Any) -> str:
        raise AssertionError("this metric must not call a model")

    async def a_generate(self, *args: Any, **kwargs: Any) -> str:
        raise AssertionError("this metric must not call a model")

    def get_model_name(self) -> str:
        return "offline (no model)"


class TrajectoryRulesMetric(BaseMetric):
    """AAI-13 'unit tests for agents', as a DeepEval metric computed by code (no judge): the
    pipeline did not crash, no forbidden tool ran (rule 3: nothing settles during evaluation),
    coverage searched the policy once per bill line, and the claim stayed within its tool budget
    (no loop)."""

    def __init__(self, budget: int | None = None) -> None:
        self.threshold = 1.0
        self.budget = budget or tool_budget()
        self.async_mode = False
        self.include_reason = True
        self.evaluation_model = "code (no model)"

    def measure(self, test_case: LLMTestCase, *args: Any, **kwargs: Any) -> float:
        meta = test_case.additional_metadata or {}
        called = [t.name.rsplit(":", 1)[-1] for t in test_case.tools_called or []]
        problems = []
        if meta.get("status") == "error":
            problems.append(f"pipeline crashed: {meta.get('error_type') or 'error'}")
        problems += [f"forbidden tool ran: {n}" for n in called if n in FORBIDDEN_TOOLS]
        searches = sum(t.name == "coverage:policy_search" for t in test_case.tools_called or [])
        if searches < meta.get("min_policy_searches", 0):
            problems.append(
                f"{searches} policy searches in coverage, needs {meta['min_policy_searches']}"
            )
        if len(called) > self.budget:
            problems.append(f"{len(called)} tool calls, budget {self.budget}")
        self.score = 0.0 if problems else 1.0
        self.reason = "; ".join(problems) or (
            f"no crash, no forbidden tool ran, a policy search per line; {len(called)} tool "
            f"calls within the budget of {self.budget}"
        )
        self.success = self.score >= self.threshold
        return self.score

    async def a_measure(self, test_case: LLMTestCase, *args: Any, **kwargs: Any) -> float:
        return self.measure(test_case)

    def is_successful(self) -> bool:
        return bool(self.success)

    @property
    def __name__(self) -> str:  # DeepEval reads the metric's name from here
        return "Trajectory rules"


def judge_model() -> DeepEvalBaseLLM | None:
    """The `judge` model from config/models.yaml through OpenRouter (a different model family
    from the agents, as AAI-13 asks). None if no key is available."""
    from deepeval.models import OpenRouterModel

    from eval.harness.llm_judge_metrics import OPENROUTER_BASE_URL, load_key_from_dotenv

    if not load_key_from_dotenv():
        return None
    import os

    config = yaml.safe_load((REPO_ROOT / "config" / "models.yaml").read_text(encoding="utf-8"))
    return OpenRouterModel(
        model=config["models"]["judge"],
        api_key=os.environ["OPENROUTER_API_KEY"],
        base_url=OPENROUTER_BASE_URL,
        temperature=0,
    )
