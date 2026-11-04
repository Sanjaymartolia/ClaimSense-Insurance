"""Efficiency metrics: latency, tokens and cost per claim.

These report, they do not grade. A slow run is a planning problem, not a wrong answer, so folding
latency into a correctness score would hide both. The budgets in `config/models.yaml`
(`max_cost_usd_per_claim`, `max_tool_calls_per_claim`) are the comparison, and a breach is a
`warn`, not a gate.

p95 is reported next to p50 because the mean hides the slow tail that a human actually waits for.
"""

from __future__ import annotations

from .models import AgentOutput, MetricResult


def percentile(values: list[float], fraction: float) -> float:
    """Nearest-rank percentile. No numpy: the harness core stays dependency-light so it runs
    anywhere, including a machine with no `retrieval` extra installed."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = max(0, min(len(ordered) - 1, round(fraction * (len(ordered) - 1))))
    return ordered[rank]


def summarise(
    outputs: list[AgentOutput], cost_budget_usd: float | None = None
) -> dict[str, MetricResult]:
    """Run-level efficiency. Per-claim values are not scored, only aggregated."""
    latencies = [o.latency_s for o in outputs]
    costs = [o.cost_usd for o in outputs]
    tokens = [float(o.prompt_tokens + o.completion_tokens) for o in outputs]
    n = len(outputs) or 1

    results = [
        MetricResult(
            name="latency_seconds",
            family="efficiency",
            value=percentile(latencies, 0.5),
            severity="warn",
            detail={
                "p50": round(percentile(latencies, 0.5), 4),
                "p95": round(percentile(latencies, 0.95), 4),
                "max": round(max(latencies), 4) if latencies else 0.0,
            },
        ),
        MetricResult(
            name="tokens_per_claim",
            family="efficiency",
            value=sum(tokens) / n,
            severity="warn",
            detail={"mean": round(sum(tokens) / n, 1), "total": int(sum(tokens))},
        ),
    ]

    mean_cost = sum(costs) / n
    cost_detail = {"mean_usd": round(mean_cost, 6), "total_usd": round(sum(costs), 6)}
    passed = None
    if cost_budget_usd is not None:
        passed = mean_cost <= cost_budget_usd
        cost_detail["budget_usd_per_claim"] = cost_budget_usd
    results.append(
        MetricResult(
            name="cost_usd_per_claim",
            family="efficiency",
            value=mean_cost,
            passed=passed,
            threshold=cost_budget_usd,
            severity="warn",
            detail=cost_detail,
        )
    )
    return {r.name: r for r in results}
