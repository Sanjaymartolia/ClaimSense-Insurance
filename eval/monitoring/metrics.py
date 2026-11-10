"""L13 section 8.1: metrics. Every trace becomes counters, histograms and a gauge.

A trace answers "what happened on this claim". A metric answers "what is happening across all
claims, right now". `Metrics.export_trace` is the bridge: it reads one finished `Trace` from
`eval.agent_suite` and adds it to the running totals. Prometheus scrapes those totals from a
`/metrics` page every few seconds and does the arithmetic (rates, ratios, percentiles) itself.

Three metric types are enough, as in the notebook:

    counter    only goes up: claims handled, tool calls, dollars spent. Always read with rate()
    histogram  counts per bucket: latency, model calls per claim. Read with histogram_quantile()
    gauge      goes up and down: claims in flight

Labels are kept few and small on purpose: the arm of the A/B test (`variant`), the outcome, the
tool name and its status, the guardrail rule. **No claim id, member id or any claim text is ever a
label** (rule 4, and each distinct label value is a new time series).

The product's API already exports one counter, `claimsense_claims_processed_total{outcome}`
(`src/claimsense/api/main.py`, Deploy & Ops). The names here do not clash with it. When the API
starts recording what the agents did, these are the names and labels to add.
"""

from __future__ import annotations

from collections.abc import Iterable
from threading import Thread
from typing import Any

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, start_http_server

from eval.agent_suite.trace import TOOL_NAMES, Trace

#: How a claim can end. `blocked` = the input guardrail sent it to a person before any agent ran.
#: `error` = the pipeline crashed, so the claim has no route at all.
OUTCOMES: tuple[str, ...] = ("ready_for_approval", "needs_review", "blocked", "error")
TOOL_STATUSES: tuple[str, ...] = ("ok", "error", "blocked")

#: Guardrail rules. `prompt_injection` is the input guardrail; `tool_acl` is an agent asking for a
#: tool its ACL does not allow (the ToolBelt refuses, and the trace records a `blocked` tool span).
RULES: tuple[str, ...] = ("prompt_injection", "tool_acl")

#: Seconds. The stub agents answer in milliseconds, real models in seconds, so the buckets cover
#: both. The gate's P95 limit (30 s) is a bucket edge, so the alert on it is exact.
LATENCY_BUCKETS: tuple[float, ...] = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    15.0,
    30.0,
    60.0,
)
LLM_CALL_BUCKETS: tuple[float, ...] = (0, 1, 2, 3, 4, 5, 6, 8, 10, 15, 20)


def outcome_of(t: Trace) -> str:
    """One of `OUTCOMES`."""
    if t.status == "blocked":
        return "blocked"
    if t.status == "error" or t.route is None:
        return "error"
    return t.route


class Metrics:
    """The metric set on a registry of its own, so tests and reruns never collide."""

    def __init__(self, variants: Iterable[str] = ("A", "B")) -> None:
        self.registry = CollectorRegistry()
        r = self.registry
        self.claims = Counter(
            "claimsense_claims",
            "Claims handled, by how they ended",
            ["variant", "outcome"],
            registry=r,
        )
        self.scored = Counter(
            "claimsense_scored", "Claims whose right answer is known", ["variant"], registry=r
        )
        self.correct = Counter(
            "claimsense_correct",
            "Scored claims handled correctly (right route, and the right amount when cleared)",
            ["variant"],
            registry=r,
        )
        self.latency = Histogram(
            "claimsense_latency_seconds",
            "Seconds per claim that reached the agents",
            ["variant"],
            buckets=LATENCY_BUCKETS,
            registry=r,
        )
        self.llm_calls = Histogram(
            "claimsense_llm_calls",
            "Model calls per claim that reached the agents",
            ["variant"],
            buckets=LLM_CALL_BUCKETS,
            registry=r,
        )
        self.tokens = Counter(
            "claimsense_tokens", "Model tokens, by direction", ["variant", "kind"], registry=r
        )
        self.cost = Counter(
            "claimsense_cost_usd", "Model spend in US dollars", ["variant"], registry=r
        )
        self.tool_calls = Counter(
            "claimsense_tool_calls",
            "Tool calls, by tool and result",
            ["tool", "status"],
            registry=r,
        )
        self.guardrail_trips = Counter(
            "claimsense_guardrail_trips",
            "Times a guardrail stopped something",
            ["rule"],
            registry=r,
        )
        self.payload_checked = Counter(
            "claimsense_payload_checked",
            "Review payloads checked by code before a person reads them",
            ["variant"],
            registry=r,
        )
        self.payload_check_pass = Counter(
            "claimsense_payload_check_pass",
            "Review payloads that passed every code check",
            ["variant"],
            registry=r,
        )
        self.judged = Counter(
            "claimsense_judged",
            "Review payloads sampled for the LLM judge",
            ["variant"],
            registry=r,
        )
        self.judge_pass = Counter(
            "claimsense_judge_pass",
            "Sampled payloads the LLM judge passed",
            ["variant"],
            registry=r,
        )
        self.in_flight = Gauge("claimsense_in_flight", "Claims being handled right now", registry=r)

        # Create every series at zero, so a rate() or a ratio has data from the first scrape and a
        # panel shows 0 instead of "No data" (in stub mode cost and tokens never move).
        for v in variants:
            for outcome in OUTCOMES:
                self.claims.labels(v, outcome)
            for kind in ("in", "out"):
                self.tokens.labels(v, kind)
            for per_variant in (
                self.scored,
                self.correct,
                self.cost,
                self.payload_checked,
                self.payload_check_pass,
                self.judged,
                self.judge_pass,
                self.latency,
                self.llm_calls,
            ):
                per_variant.labels(v)
        for tool in TOOL_NAMES:
            for status in ("ok", "error"):
                self.tool_calls.labels(tool, status)
        for rule in RULES:
            self.guardrail_trips.labels(rule)

    # ------------------------------------------------------------------------------ export
    def export_trace(self, t: Trace, correct: bool | None = None) -> None:
        """Add one finished trace to the totals.

        `correct` is None when the right answer is not known (real traffic has no gold). A claim
        the guardrail blocked is scored like any other: here the guardrail is what the A/B test
        compares, so leaving its claims out would hide the effect being measured.
        """
        v = t.variant
        self.claims.labels(v, outcome_of(t)).inc()
        if correct is not None:
            self.scored.labels(v).inc()
            if correct:
                self.correct.labels(v).inc()
        for span in t.tool_spans:
            self.tool_calls.labels(span.name, span.status).inc()
            if span.status == "blocked":
                self.guardrail_trips.labels("tool_acl").inc()
        if t.status == "blocked":
            for rule in t.flags or ["prompt_injection"]:
                self.guardrail_trips.labels(rule).inc()
            return  # no agent ran: no latency, model calls or cost to report
        self.latency.labels(v).observe(t.seconds)
        self.llm_calls.labels(v).observe(t.llm_calls)
        self.tokens.labels(v, "in").inc(sum(s.tokens_in for s in t.llm_spans))
        self.tokens.labels(v, "out").inc(sum(s.tokens_out for s in t.llm_spans))
        self.cost.labels(v).inc(t.cost)

    def record_payload_check(self, variant: str, passed: bool) -> None:
        self.payload_checked.labels(variant).inc()
        if passed:
            self.payload_check_pass.labels(variant).inc()

    def record_judge(self, variant: str, passed: bool) -> None:
        self.judged.labels(variant).inc()
        if passed:
            self.judge_pass.labels(variant).inc()

    # ------------------------------------------------------------------------------- serve
    def serve(self, port: int, host: str = "127.0.0.1") -> tuple[Any, Thread]:
        """Serve `/metrics` for Prometheus to scrape. Returns (server, thread); stop with
        `server.shutdown()`. Bound to this machine only."""
        return start_http_server(port, addr=host, registry=self.registry)

    def names(self) -> set[str]:
        """Every sample name on the `/metrics` page (for the tests that check rules and panels)."""
        return {s.name for family in self.registry.collect() for s in family.samples}
