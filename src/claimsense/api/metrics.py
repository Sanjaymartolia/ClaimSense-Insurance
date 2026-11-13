"""Product metrics for the case API (L13, L16), served on ``/metrics/``.

Two groups. The first uses the names and labels that ``eval/monitoring/metrics.py`` defines for
"when the API starts recording what the agents did", so the alert rules in
``eval/monitoring/alert_rules.yml`` apply to live traffic unchanged: claims by route, latency,
tokens, cost, tool calls, guardrail trips and claims in flight. The second is the operations
dashboard the brief asks for: final outcomes, reviewer decisions (the edit rate), rupees deducted
by reason, fraud flags and turnaround.

Labels are few and fixed. No claim id, approver id or claim text is ever a label (rule 4), and
every series starts at zero, so a rate or a ratio has data from the first scrape.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from typing import Any

from prometheus_client import Counter, Gauge, Histogram

from claimsense.contracts import DeductionReason

#: The agents' route at the first review, as `eval/monitoring` names it.
ROUTES = ("ready_for_approval", "needs_review", "blocked", "error")
#: How a claim ends. `escalated` = a guard blocked the payment and a person must take over.
OUTCOMES = ("settled", "repudiated", "rejected", "escalated", "error")
LEVELS = ("adjudicator", "senior")
DECISIONS = ("approve", "edit", "reject")
FLAG_KINDS = ("duplicate", "tariff", "sub_limit", "bill_total", "dates", "injection", "other")
TOOL_STATUSES = ("ok", "error", "blocked")
RULES = ("prompt_injection", "tool_acl")

#: Seconds, as `eval/monitoring`: the gate's P95 limit (30 s) is a bucket edge.
LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 15.0, 30.0, 60.0)
#: Seconds from receipt to the final decision: a person is in the loop, so minutes to days.
TURNAROUND_BUCKETS = (1, 10, 60, 300, 900, 1800, 3600, 4 * 3600, 24 * 3600, 3 * 24 * 3600)

# ------------------------------------------------------------------ eval/monitoring names
CLAIMS = Counter("claimsense_claims", "Claims handled by the agents, by route", ["outcome"])
LATENCY = Histogram(
    "claimsense_latency_seconds",
    "Seconds from receipt to the first review",
    buckets=LATENCY_BUCKETS,
)
TOKENS = Counter("claimsense_tokens", "Model tokens, by direction", ["kind"])
COST = Counter("claimsense_cost_usd", "Model spend in US dollars")
TOOL_CALLS = Counter("claimsense_tool_calls", "Tool calls, by tool and result", ["tool", "status"])
GUARDRAIL_TRIPS = Counter(
    "claimsense_guardrail_trips", "Times a guardrail stopped something", ["rule"]
)
IN_FLIGHT = Gauge("claimsense_in_flight", "Claim runs executing right now")

# ------------------------------------------------------------------ the brief's dashboard
PROCESSED = Counter(
    "claimsense_claims_processed", "Claims that reached a final outcome", ["outcome"]
)
REVIEW_DECISIONS = Counter(
    "claimsense_review_decisions",
    "Reviewer decisions; edit rate = edit / all",
    ["level", "decision"],
)
RUPEES_DEDUCTED = Counter(
    "claimsense_rupees_deducted", "Rupees deducted on decided claims, by reason", ["reason"]
)
FRAUD_FLAGS = Counter("claimsense_fraud_flags", "Flags on decided claims, by kind", ["kind"])
TURNAROUND = Histogram(
    "claimsense_turnaround_seconds",
    "Seconds from receipt to the final outcome",
    buckets=TURNAROUND_BUCKETS,
)

for _route in ROUTES:
    CLAIMS.labels(_route)
for _kind in ("prompt", "completion"):
    TOKENS.labels(_kind)
for _rule in RULES:
    GUARDRAIL_TRIPS.labels(_rule)
for _outcome in OUTCOMES:
    PROCESSED.labels(_outcome)
for _level in LEVELS:
    for _decision in DECISIONS:
        REVIEW_DECISIONS.labels(_level, _decision)
for _reason in DeductionReason:
    RUPEES_DEDUCTED.labels(_reason.value)
for _flag in FLAG_KINDS:
    FRAUD_FLAGS.labels(_flag)


def flag_kind(flag: str) -> str:
    """One of `FLAG_KINDS`, from the wording `agents/fraud.py` and extraction use."""
    text = flag.lower()
    if "prompt injection" in text:
        return "injection"
    for needle, kind in (
        ("duplicate", "duplicate"),
        ("tariff", "tariff"),
        ("sub-limit", "sub_limit"),
        ("bill total", "bill_total"),
    ):
        if needle in text:
            return kind
    if any(needle in text for needle in ("date", "policy period", "night stay")):
        return "dates"
    return "other"


def route_of(values: dict[str, Any]) -> str:
    """The agents' route at the first review: `needs_review` if they found anything a person must
    look at beyond the normal approval. Mirrors the eval harness, so the numbers agree."""
    admissibility = values.get("admissibility")
    if admissibility is not None and not getattr(admissibility, "admissible", True):
        return "needs_review"
    if values.get("fraud_flags") or values.get("escalation") or values.get("extraction_issues"):
        return "needs_review"
    critic = values.get("critic_report")
    if critic is not None and not getattr(critic, "passed", True):
        return "needs_review"
    return "ready_for_approval"


def record_first_segment(values: dict[str, Any], seconds: float, failed: bool) -> None:
    """The run from receipt to the first review (or to an error)."""
    CLAIMS.labels("error" if failed else route_of(values)).inc()
    LATENCY.observe(seconds)
    issues = values.get("extraction_issues") or []
    if any("prompt injection" in issue.lower() for issue in issues):
        GUARDRAIL_TRIPS.labels("prompt_injection").inc()


def record_decision(level: str, decision: str) -> None:
    REVIEW_DECISIONS.labels(level, decision).inc()


def record_outcome(values: dict[str, Any], outcome: str, received_at: str | None) -> None:
    """A claim reached its final outcome: count it, time it, and add up what it deducted."""
    outcome = outcome if outcome in OUTCOMES else "error"
    PROCESSED.labels(outcome).inc()
    if received_at:
        received = datetime.fromisoformat(received_at)
        TURNAROUND.observe(max(0.0, (datetime.now(UTC) - received).total_seconds()))
    for flag in values.get("fraud_flags") or []:
        FRAUD_FLAGS.labels(flag_kind(flag)).inc()
    worksheet = values.get("worksheet")
    if outcome not in ("settled", "repudiated") or worksheet is None:
        return
    deductions = [d for line in worksheet.lines for d in line.deductions]
    if worksheet.co_pay is not None:
        deductions.append(worksheet.co_pay)
    for deduction in deductions:
        RUPEES_DEDUCTED.labels(deduction.reason.value).inc(float(deduction.amount))


def record_tool_calls(records: Iterable[Any]) -> None:
    """Hook audit records -> tool calls. A permission denial is the ACL working (`blocked`)."""
    for record in records:
        status = {"ok": "ok", "denied": "blocked"}.get(record.status, "error")
        TOOL_CALLS.labels(record.tool, status).inc()
        if status == "blocked":
            GUARDRAIL_TRIPS.labels("tool_acl").inc()


def _walk(run: Any) -> Iterator[Any]:
    yield run
    for child in getattr(run, "child_runs", None) or []:
        yield from _walk(child)


def _usage(run: Any) -> tuple[int, int, float]:
    """(prompt tokens, completion tokens, USD) of one model run. OpenRouter reports the cost in
    `token_usage`; other providers may report tokens only."""
    outputs = getattr(run, "outputs", None) or {}
    usage = dict((outputs.get("llm_output") or {}).get("token_usage") or {})
    if not usage:
        try:
            message = outputs["generations"][0][0]["message"]["kwargs"]
        except (KeyError, IndexError, TypeError):
            message = {}
        meta = message.get("usage_metadata") or {}
        usage = {
            "prompt_tokens": meta.get("input_tokens", 0),
            "completion_tokens": meta.get("output_tokens", 0),
            **((message.get("response_metadata") or {}).get("token_usage") or {}),
        }
    return (
        int(usage.get("prompt_tokens") or 0),
        int(usage.get("completion_tokens") or 0),
        float(usage.get("cost") or 0.0),
    )


@contextlib.contextmanager
def llm_usage(enabled: bool) -> Iterator[None]:
    """Count the tokens and dollars of every model call made inside the block."""
    if not enabled:
        yield
        return
    try:
        from langchain_core.tracers.context import collect_runs
    except ImportError:  # no LangChain installed: no model can have been called
        yield
        return
    with collect_runs() as collector:
        try:
            yield
        finally:
            for root in collector.traced_runs:
                for run in _walk(root):
                    if run.run_type in ("llm", "chat_model"):
                        prompt, completion, cost = _usage(run)
                        TOKENS.labels("prompt").inc(prompt)
                        TOKENS.labels("completion").inc(completion)
                        COST.inc(cost)
