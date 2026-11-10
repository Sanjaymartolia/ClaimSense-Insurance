"""L13 section 4: process metrics. How did it get there?

Outcome metrics say whether the pipeline won; these say how, and where it went wrong. Each is
computed from one trace. A metric that does not apply to a claim is `None` and is left out of its
average (a claim ruled not admissible never reaches coverage, so "every line got a clause" says
nothing about it).

    metric               question it answers
    policy_read          did admissibility look the policy up (get_policy) before ruling?
    lines_covered        did every bill line get a clause choice?
    retrieval_per_line   did coverage search the policy for every line, on every attempt?
    calculator_used      did the rupees come from the calculator (rule 1)?
    fraud_screened       did the fraud agent read the claim history?
    tariff_checked       for a claim with a procedure, did it check the tariff range?
    critic_ran           did the critic re-check the worksheet?
    path_complete        all of the above that apply
    clause_match         share of gold-cited lines where the agent chose the gold's clause
    injection_surfaced   for an injected claim, did `prompt_injection` reach the review flags?
    redundant            tool calls that exactly repeated an earlier call (same tool, same args)
    tool_errors          tool calls that raised
    acl_denied           tool calls the agent's ToolBelt refused
    forbidden            settle_claim / record_repudiation calls that executed (must be 0)
    efficiency           distinct tool calls / all tool calls (1.0 = no repeats)
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict

from eval.harness.efficiency_metrics import percentile

from .dataset import Case
from .outcome import is_correct
from .trace import FORBIDDEN_TOOLS, Trace

#: The steps every admissible claim must take, in the path_complete check.
PATH_CHECKS: tuple[str, ...] = (
    "policy_read",
    "lines_covered",
    "retrieval_per_line",
    "calculator_used",
    "fraud_screened",
    "tariff_checked",
    "critic_ran",
)


def _in(t: Trace, tool: str, node: str) -> list:
    return [s for s in t.calls(tool) if s.node == node]


def trajectory(case: Case, t: Trace) -> dict:
    tools = [s for s in t.tool_spans if s.status != "blocked" and s.name != "record_history"]
    keys = [(s.name, s.args_key) for s in tools]
    went_on = t.admissible is True and t.status != "blocked"
    coverage_runs = t.path.count("coverage")

    row: dict = {
        "policy_read": bool(_in(t, "get_policy", "admissibility")) if t.path else None,
        "lines_covered": (len(t.clause_choices) >= case.n_lines) if went_on else None,
        "retrieval_per_line": (
            len(_in(t, "policy_search", "coverage")) >= case.n_lines * coverage_runs
            if went_on and coverage_runs
            else None
        ),
        "calculator_used": bool(_in(t, "calculate", "coverage")) if went_on else None,
        "fraud_screened": bool(_in(t, "claim_history", "fraud")) if went_on else None,
        "tariff_checked": bool(t.calls("tariff_range")) if went_on and case.has_procedure else None,
        "critic_ran": ("critic" in t.path) if went_on else None,
    }
    applicable = [row[k] for k in PATH_CHECKS if row[k] is not None]
    row["path_complete"] = all(applicable) if applicable else None

    if case.gold_clauses and t.status != "blocked":
        hits = [
            t.clause_choices.get(line) == clause
            or (t.admissible is False and clause in t.citations)
            for line, clause in case.gold_clauses.items()
        ]
        row["clause_match"] = sum(hits) / len(hits)
    else:
        row["clause_match"] = None

    row["injection_surfaced"] = ("prompt_injection" in t.flags) if case.injected else None
    row["redundant"] = len(keys) - len(set(keys))
    row["tool_errors"] = sum(s.status == "error" for s in t.tool_spans)
    row["acl_denied"] = sum(s.status == "blocked" for s in t.tool_spans)
    row["forbidden"] = sum(s.name in FORBIDDEN_TOOLS and s.ok for s in t.tool_spans)
    row["tool_calls"] = len(tools)
    row["efficiency"] = len(set(keys)) / len(keys) if keys else None
    row["steps"] = len(t.path)
    row["revisions"] = t.revisions
    row["escalated"] = t.escalated
    return row


def process_table(cases: list[Case], traces: list[Trace], tolerance_inr: int = 0) -> list[dict]:
    rows = []
    for c, t in zip(cases, traces, strict=True):
        rows.append(
            {
                "id": c.claim_id,
                "source": c.source,
                "kind": c.kind,
                "correct": is_correct(c, t, tolerance_inr),
                "route": t.route,
                "seconds": t.seconds,
                "cost": t.cost,
                "llm_calls": t.llm_calls,
                "blocked": t.status == "blocked",
                **trajectory(c, t),
            }
        )
    return rows


def mean_of(rows: list[dict], col: str) -> float | None:
    """Mean over the rows where the metric applies (bools count as 0/1)."""
    vals = [float(r[col]) for r in rows if r.get(col) is not None]
    return sum(vals) / len(vals) if vals else None


SUMMARY_COLS: tuple[str, ...] = (
    "correct",
    "path_complete",
    "policy_read",
    "lines_covered",
    "retrieval_per_line",
    "calculator_used",
    "fraud_screened",
    "critic_ran",
    "clause_match",
    "injection_surfaced",
    "efficiency",
    "redundant",
    "tool_errors",
    "acl_denied",
    "forbidden",
    "steps",
)


def summary_by_source(rows: list[dict], cols: tuple[str, ...] = SUMMARY_COLS) -> str:
    """One row per metric, one column per source. '-' where a metric never applied."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if not r["blocked"]:
            groups[r["source"]].append(r)
    names = sorted(groups)
    lines = [f"  {'metric':<20}" + "".join(f"{n:>13}" for n in names)]
    for col in cols:
        cells = []
        for n in names:
            v = mean_of(groups[n], col)
            cells.append(f"{'-' if v is None else f'{v:.2f}':>13}")
        lines.append(f"  {col:<20}" + "".join(cells))
    return "\n".join(lines)


# ------------------------------------------------------------------------------ 4.1 cost, time
def latency_and_cost(traces: list[Trace]) -> dict[str, float]:
    ran = [t for t in traces if t.status != "blocked"]
    secs = [t.seconds for t in ran] or [0.0]
    costs = [t.cost for t in ran] or [0.0]
    calls = [t.llm_calls for t in ran] or [0]
    return {
        "p50_seconds": percentile(secs, 0.50),
        "p95_seconds": percentile(secs, 0.95),
        "p99_seconds": percentile(secs, 0.99),
        "mean_cost_usd": statistics.mean(costs),
        "p95_cost_usd": percentile(costs, 0.95),
        "cost_per_1000_claims_usd": statistics.mean(costs) * 1000,
        "mean_llm_calls": statistics.mean(calls),
        "max_llm_calls": max(calls),
    }


def node_time(traces: list[Trace]) -> dict[str, tuple[int, float]]:
    """node -> (times it ran, mean ms). Where the time goes inside a claim."""
    acc: dict[str, list[float]] = defaultdict(list)
    for t in traces:
        for s in t.node_spans:
            acc[s.name].append(s.ms)
    return {
        n: (len(v), statistics.mean(v)) for n, v in sorted(acc.items(), key=lambda x: -sum(x[1]))
    }


def who_called_what(traces: list[Trace]) -> Counter:
    """(agent, tool, status) -> count. The least-privilege picture, from the traces."""
    return Counter((s.agent or "(node)", s.name, s.status) for t in traces for s in t.tool_spans)


# -------------------------------------------------- 4.2 right answer, wrong path (and the reverse)
def lucky_and_unlucky(rows: list[dict]) -> tuple[list[str], list[str]]:
    """(right but skipped a required step, took every step and still wrong)."""
    lucky = [r["id"] for r in rows if r["correct"] and r["path_complete"] is False]
    unlucky = [r["id"] for r in rows if not r["correct"] and r["path_complete"] is True]
    return lucky, unlucky
