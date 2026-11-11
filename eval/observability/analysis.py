"""Reading spans: the tree of one trace, the RED table, what a claim did after an error, the gate.

Every function here takes `SpanRow`s, so the same code reads spans from the in-memory exporter
(the simple way) and spans read back from Jaeger (the production way). Notebook sections:

    show(trace_id)          -> tree()          3: one trace as an indented tree
    red(df)                 -> red()           6.1: rate, errors and duration per span name
    steps(df, trace_id)     -> error_paths()   6.2: what the claim did after a tool failed
    watching the gate       -> gate()          8: share sent to a person, decisions, time
    wrap-up (cost)          -> usage()         9: model calls, tokens and cost from the spans
"""

from __future__ import annotations

import base64
import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from eval.harness.efficiency_metrics import percentile

#: Span names that the RED table and the chart report. Library-internal steps (LangChain's
#: `*.workflow` and `*.task` spans) are left out, as the notebook leaves them out.
_REPORTED_PREFIXES = ("invoke_agent", "node ", "execute_tool", "guardrail", "human_review")


@dataclass(frozen=True)
class SpanRow:
    """One finished span, reduced to what the analysis needs."""

    trace_id: str  # 32 hex digits
    span_id: str  # 16 hex digits
    parent_id: str | None
    name: str
    start_ns: int
    end_ns: int
    error: bool
    attrs: dict[str, Any] = field(default_factory=dict)

    @property
    def ms(self) -> float:
        return (self.end_ns - self.start_ns) / 1e6


# ----------------------------------------------------------------------------- building rows
def from_readable(span: Any) -> SpanRow:
    """An OpenTelemetry SDK `ReadableSpan` (what an exporter receives)."""
    from opentelemetry.trace import StatusCode

    parent = span.parent
    return SpanRow(
        trace_id=f"{span.context.trace_id:032x}",
        span_id=f"{span.context.span_id:016x}",
        parent_id=f"{parent.span_id:016x}" if parent is not None else None,
        name=span.name,
        start_ns=int(span.start_time or 0),
        end_ns=int(span.end_time or 0),
        error=span.status.status_code == StatusCode.ERROR,
        attrs=dict(span.attributes or {}),
    )


def _otlp_id(value: str | None, size: int) -> str | None:
    """OTLP JSON ids are hex in Jaeger's API v3 and base64 in some other exporters."""
    if not value:
        return None
    text = value.lower()
    if len(text) == size and all(c in "0123456789abcdef" for c in text):
        return text
    return base64.b64decode(value).hex()


def _otlp_value(value: dict) -> Any:
    if "arrayValue" in value:
        return [_otlp_value(v) for v in (value["arrayValue"].get("values") or [])]
    for key in ("stringValue", "boolValue", "doubleValue"):
        if key in value:
            return value[key]
    if "intValue" in value:
        return int(value["intValue"])  # int64 is a string in OTLP JSON
    return None


def from_otlp(body: dict) -> list[SpanRow]:
    """Every span in an OTLP JSON body (`{"resourceSpans": [...]}`, as Jaeger returns it)."""
    rows: list[SpanRow] = []
    for resource in body.get("resourceSpans") or []:
        for scope in resource.get("scopeSpans") or []:
            for s in scope.get("spans") or []:
                status = (s.get("status") or {}).get("code")
                rows.append(
                    SpanRow(
                        trace_id=_otlp_id(s.get("traceId"), 32) or "",
                        span_id=_otlp_id(s.get("spanId"), 16) or "",
                        parent_id=_otlp_id(s.get("parentSpanId"), 16),
                        name=s.get("name", ""),
                        start_ns=int(s.get("startTimeUnixNano") or 0),
                        end_ns=int(s.get("endTimeUnixNano") or 0),
                        error=status in (2, "STATUS_CODE_ERROR"),
                        attrs={
                            a["key"]: _otlp_value(a.get("value") or {})
                            for a in s.get("attributes") or []
                        },
                    )
                )
    return rows


def by_trace(rows: Iterable[SpanRow]) -> dict[str, list[SpanRow]]:
    out: dict[str, list[SpanRow]] = defaultdict(list)
    for r in rows:
        out[r.trace_id].append(r)
    return dict(out)


def roots(rows: Iterable[SpanRow]) -> list[SpanRow]:
    """The `invoke_agent claimsense` span of each claim, in start order."""
    return sorted(
        (r for r in rows if r.parent_id is None and r.name.startswith("invoke_agent")),
        key=lambda r: r.start_ns,
    )


# ------------------------------------------------------------------------------------- tree
def _note(a: dict[str, Any]) -> str:
    """A short, content-free note for one line of the tree."""
    if "claim.route" in a:
        money = a.get("claim.settlement_inr")
        paid = "-" if money is None else f"Rs {money:,}"
        return f"route={a['claim.route']} {paid} status={a.get('claim.status', '')}"
    if "hitl.decision" in a:
        return f"decision={a['hitl.decision']} proposed=Rs {a.get('hitl.proposed_inr', '-')}"
    if "claimsense.tool.result" in a:
        who = f"{a['claimsense.agent']}: " if a.get("claimsense.agent") else ""
        return f"{who}{a.get('claimsense.tool.args', '')} -> {a['claimsense.tool.result']}"
    if "gen_ai.usage.input_tokens" in a:
        return (
            f"{a.get('gen_ai.request.model', '')} {a['gen_ai.usage.input_tokens']} in / "
            f"{a.get('gen_ai.usage.output_tokens', '?')} out"
        )
    if "claimsense.guardrail.findings" in a:
        return f"findings={a['claimsense.guardrail.findings']}"
    return ""


def tree(rows: Sequence[SpanRow], width: int = 40) -> str:
    """One trace as an indented tree, children in start order (notebook `show`)."""
    ids = {r.span_id for r in rows}
    kids: dict[str | None, list[SpanRow]] = defaultdict(list)
    for r in rows:
        kids[r.parent_id if r.parent_id in ids else None].append(r)
    lines: list[str] = []

    def walk(parent: str | None, depth: int) -> None:
        for r in sorted(kids[parent], key=lambda r: r.start_ns):
            flag = " ERROR" if r.error else ""
            name = f"{'  ' * depth}{r.name}"
            lines.append(f"{name:<{width}} {r.ms:8.1f} ms{flag:<6}  {_note(r.attrs)[:80]}")
            walk(r.span_id, depth + 1)

    walk(None, 0)
    return "\n".join(lines)


# -------------------------------------------------------------------------------------- RED
def reported(r: SpanRow) -> bool:
    """A span the RED table counts: ours, plus the model-call spans of the instrumentation."""
    return r.name.startswith(_REPORTED_PREFIXES) or r.attrs.get("gen_ai.operation.name") == "chat"


def red(rows: Iterable[SpanRow]) -> dict[str, dict[str, float]]:
    """Rate, errors and duration per span name (the first table of any incident)."""
    groups: dict[str, list[SpanRow]] = defaultdict(list)
    for r in rows:
        if reported(r):
            groups[r.name].append(r)
    out: dict[str, dict[str, float]] = {}
    for name, spans in sorted(groups.items()):
        times = sorted(s.ms for s in spans)
        errors = sum(s.error for s in spans)
        out[name] = {
            "spans": len(spans),
            "errors": errors,
            "error_pct": round(100 * errors / len(spans), 1),
            "p50_ms": round(percentile(times, 0.50), 1),
            "p95_ms": round(percentile(times, 0.95), 1),
        }
    return out


def red_table(columns: dict[str, dict[str, dict[str, float]]]) -> str:
    """Several RED tables side by side, one column group per phase."""
    names = sorted({n for table in columns.values() for n in table})
    head = f"{'span':<34}" + "".join(f"| {phase:^28}" for phase in columns)
    sub = f"{'':<34}" + "".join(f"| {'spans':>6} {'err %':>6} {'p95 ms':>12} " for _ in columns)
    lines = [head, sub, "-" * len(sub)]
    for n in names:
        cells = ""
        for table in columns.values():
            row = table.get(n)
            cells += (
                f"| {row['spans']:>6} {row['error_pct']:>6.1f} {row['p95_ms']:>12.1f} "
                if row
                else f"| {'-':>6} {'-':>6} {'-':>12} "
            )
        lines.append(f"{n[:34]:<34}{cells}")
    return "\n".join(lines)


# ----------------------------------------------------------------- what happened after an error
#: Tools left out of a path: they run on every claim and say nothing about the reaction.
_QUIET_TOOLS = frozenset({"policy_search", "get_clause", "record_history"})


def error_paths(rows: Iterable[SpanRow]) -> list[dict[str, Any]]:
    """For each claim with a failed tool call: its tool calls in order and how the claim ended."""
    out = []
    for trace_id, spans in by_trace(rows).items():
        tools = sorted(
            (s for s in spans if s.name.startswith("execute_tool")), key=lambda s: s.start_ns
        )
        if not any(s.error for s in tools):
            continue
        root = next((s for s in spans if s.parent_id is None), None)
        a = root.attrs if root else {}
        steps = []
        for s in tools:
            tool = s.name.split(" ", 1)[-1]
            if tool in _QUIET_TOOLS and not s.error:
                continue
            steps.append(f"{tool}[FAILED]" if s.error else tool)
        out.append(
            {
                "trace_id": trace_id,
                "claim_id": a.get("claim.id", "?"),
                "status": a.get("claim.status", "?"),
                "route": a.get("claim.route", ""),
                "error_type": a.get("error.type", ""),
                "path": " -> ".join(steps),
            }
        )
    return sorted(out, key=lambda r: r["claim_id"])


# ------------------------------------------------------------------------------------ the gate
def gate(rows: Iterable[SpanRow]) -> dict[str, Any]:
    """L14 section 8, 'watching the gate': who was sent to a person, what they decided, how fast."""
    rows = list(rows)
    claims = {r.trace_id for r in roots(rows)}
    reviews = [r for r in rows if r.name == "human_review"]
    reviewed = {r.trace_id for r in reviews}
    waits = [float(r.attrs.get("hitl.wait_s", r.ms / 1000)) for r in reviews]
    return {
        "claims": len(claims),
        "sent_to_person": len(reviewed & claims),
        "share_sent_to_person": round(len(reviewed & claims) / len(claims), 3) if claims else None,
        "reviews": len(reviews),
        "decisions": dict(Counter(str(r.attrs.get("hitl.decision", "?")) for r in reviews)),
        "levels": dict(Counter(str(r.attrs.get("hitl.level", "?")) for r in reviews)),
        "median_wait_s": round(statistics.median(waits), 4) if waits else None,
    }


# ----------------------------------------------------------------------------------- the cost
def usage(rows: Iterable[SpanRow]) -> dict[str, Any]:
    """Model calls and tokens from the model-call spans, cost from the claims' own totals."""
    rows = list(rows)
    chats = [r.attrs for r in rows if r.attrs.get("gen_ai.operation.name") == "chat"]
    return {
        "model_call_spans": len(chats),
        "input_tokens": sum(int(a.get("gen_ai.usage.input_tokens") or 0) for a in chats),
        "output_tokens": sum(int(a.get("gen_ai.usage.output_tokens") or 0) for a in chats),
        "cost_usd": round(sum(float(r.attrs.get("claim.cost_usd") or 0) for r in roots(rows)), 6),
    }


# ------------------------------------------------------------------------------------ the chart
def _short_label(name: str) -> str:
    """Bar labels that stay distinct: the review *node* and the person's review span differ."""
    if name.startswith("invoke_agent"):
        return "whole claim"
    if name == "human_review":
        return "person's review"
    if name.startswith("node "):
        return f"node {name[5:]}"
    return name.split(" ", 1)[-1]


def plot_red(
    tables: dict[str, dict[str, dict[str, float]]], path: Path, title: str, top: int = 10
) -> bool:
    """Error share and p95 time per span name, one bar per phase. False if matplotlib is missing."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    names = sorted(
        {n for t in tables.values() for n in t},
        key=lambda n: -max(t.get(n, {}).get("p95_ms", 0) for t in tables.values()),
    )
    tools = [n for n in names if n.startswith("execute_tool")][:top]
    others = [n for n in names if not n.startswith("execute_tool")][:top]
    colors = ["#2a6fdb", "#e0672b", "#2e9d5b", "#8a5cc7"]
    fig, axes = plt.subplots(2, 2, figsize=(13, 8.5), constrained_layout=True)
    for col, (group, label) in enumerate(((tools, "tool calls"), (others, "agent steps"))):
        for row, (metric, unit) in enumerate((("error_pct", "errors (%)"), ("p95_ms", "p95 (ms)"))):
            ax = axes[row][col]
            n = len(tables) or 1
            width = 0.8 / n
            for i, (phase, table) in enumerate(tables.items()):
                xs = [j + (i - (n - 1) / 2) * width for j in range(len(group))]
                ys = [table.get(g, {}).get(metric, 0) for g in group]
                ax.bar(xs, ys, width * 0.92, label=phase, color=colors[i % len(colors)])
            ax.set_xticks(range(len(group)))
            ax.set_xticklabels(
                [_short_label(g) for g in group], rotation=30, ha="right", fontsize=8
            )
            ax.set_ylabel(unit)
            note = " (log scale; under 0.1 ms not drawn)" if metric == "p95_ms" else ""
            ax.set_title(f"{label}: {unit}{note}", fontsize=10, loc="left")
            ax.grid(axis="y", alpha=0.3)
            ax.spines[["top", "right"]].set_visible(False)
            if metric == "p95_ms" and any(
                table.get(g, {}).get(metric, 0) > 0 for table in tables.values() for g in group
            ):
                ax.set_yscale("log")
    axes[0][0].legend(title="phase", fontsize=8)
    fig.suptitle(title, fontsize=11)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return True
