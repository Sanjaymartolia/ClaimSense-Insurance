"""The ClaimSense evaluation harness (L13, L15). Owner: Eval & Red-Team.

Modelled on the KYC evaluation harness in `Building-AI-Agents-for-Finance/Chapter 11`: metric
families, a weighted scorecard, and catastrophic gates that are never averaged away.

    loader               reads the eval sets and strips every answer-revealing field
    adapters             how the harness talks to a thing under test (+ three fixtures)
    claimsense_adapter   runs the real agent pipeline (no LangGraph, no API key)
    reference_metrics    route, amounts, flags, citations, against the human gold
    trajectory_metrics   did the agent call the tools the claim needed
    safety_metrics       the six catastrophic gates
    efficiency_metrics   latency, tokens, cost (reported, never gated)
    llm_judge_metrics    RAGAS faithfulness of each rationale (opt-in, needs a key)
    scorecard            weighted composite + gates -> pass or fail
    run                  the CLI for one run
    suite                the CLI for every run at once, each with its expected outcome

Start with `python -m eval.harness.suite`: it runs everything and checks each row against the
outcome `docs/EVAL_HARNESS_REPORT.md` records.

To debug one piece, `python -m eval.harness.run --adapter gold-replay --split dev` replays the
gold answer. It must score 0.975 with no gate failures. It is 0.975 and not 1.000 for a measured
reason: five dev claims carry a deduction that no clause explains, so no agent can cite them
correctly. Treat any drop below that as a harness or fixture regression.
"""

from .models import AgentOutput, CaseScore, ClaimRecord, EvalCase, GoldRecord, MetricResult

__all__ = [
    "AgentOutput",
    "CaseScore",
    "ClaimRecord",
    "EvalCase",
    "GoldRecord",
    "MetricResult",
]
