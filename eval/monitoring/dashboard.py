"""L13 section 8.3: the dashboard as code.

A dashboard clicked together in a browser cannot be reviewed, diffed or rebuilt. This one is a
Python function that returns Grafana's dashboard JSON, so it lives in git next to the alert rules
and the metrics it reads.

`QUERIES` is the single list of PromQL used anywhere in this package: the dashboard panels, the
read-back chart (`readback.py`) and the tests all take their expressions from it. The three
patterns from the notebook cover every panel:

    rate(counter[1m])                                       how fast a counter is growing
    rate(a[1m]) / rate(b[1m])                               a ratio of two rates (a share)
    histogram_quantile(0.95, sum by (le) (rate(h_bucket[2m])))   a percentile from a histogram

The red/green limits on the stat tiles are read from `alert_rules.yml`, so a tile turns red at the
same value at which its alert fires.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

RULES_FILE = Path(__file__).with_name("alert_rules.yml")
DASHBOARD_UID = "claimsense-live"
DASHBOARD_TITLE = "ClaimSense live"
DS = {"type": "prometheus", "uid": "prom"}


def _share(numerator: str, denominator: str, by: str = "", window: str = "1m") -> str:
    """A ratio of two rates, optionally split by one label."""
    agg = f"sum by ({by})" if by else "sum"
    return f"{agg}(rate({numerator}[{window}])) / {agg}(rate({denominator}[{window}]))"


def _quantile(q: float) -> str:
    return f"histogram_quantile({q}, sum by (le) (rate(claimsense_latency_seconds_bucket[2m])))"


_TOOL_ERRORS = _share(
    'claimsense_tool_calls_total{status="error"}', "claimsense_tool_calls_total", by="tool"
)

QUERIES: dict[str, str] = {
    "claims_per_minute": "sum(rate(claimsense_claims_total[1m])) * 60",
    "handled_correctly": _share("claimsense_correct_total", "claimsense_scored_total"),
    "handled_correctly_by_variant": _share(
        "claimsense_correct_total", "claimsense_scored_total", by="variant"
    ),
    "latency_p50": _quantile(0.5),
    "latency_p95": _quantile(0.95),
    "latency_p99": _quantile(0.99),
    "cost_per_claim": _share("claimsense_cost_usd_total", "claimsense_claims_total", window="2m"),
    "cost_per_claim_by_variant": _share(
        "claimsense_cost_usd_total", "claimsense_claims_total", by="variant", window="2m"
    ),
    "tool_error_rate_by_tool": _TOOL_ERRORS,
    # The worst single tool, not the average over all tools: one dead tool among nine is an
    # incident, and an average would hide it.
    "tool_error_rate_worst": f"max({_TOOL_ERRORS})",
    "pipeline_error_share": _share(
        'claimsense_claims_total{outcome="error"}', "claimsense_claims_total"
    ),
    "outcomes_per_minute": "sum by (outcome) (rate(claimsense_claims_total[1m])) * 60",
    "guardrail_trips_per_minute": (
        "sum by (rule) (rate(claimsense_guardrail_trips_total[1m])) * 60"
    ),
    "guardrail_trip_share": _share("claimsense_guardrail_trips_total", "claimsense_claims_total"),
    "judge_pass_rate_by_variant": _share(
        "claimsense_judge_pass_total", "claimsense_judged_total", by="variant", window="3m"
    ),
    "llm_calls_per_claim_by_variant": _share(
        "claimsense_llm_calls_sum", "claimsense_llm_calls_count", by="variant", window="2m"
    ),
    "payload_check_pass_rate_by_variant": _share(
        "claimsense_payload_check_pass_total", "claimsense_payload_checked_total", by="variant"
    ),
    "alerts_firing_count": 'count(ALERTS{alertstate="firing"}) or vector(0)',
    "alerts_firing": 'ALERTS{alertstate="firing"}',
}


# ------------------------------------------------------------------------------ alert rules
def load_rules(path: Path = RULES_FILE) -> list[dict]:
    groups = yaml.safe_load(path.read_text(encoding="utf-8"))["groups"]
    return [rule for group in groups for rule in group["rules"]]


def thresholds(path: Path = RULES_FILE) -> dict[str, float]:
    """alert name -> the number its expression compares against."""
    out: dict[str, float] = {}
    for rule in load_rules(path):
        match = re.search(r"[<>]=?\s*([0-9.]+)\s*$", rule["expr"].strip())
        if not match:
            raise ValueError(f"{rule['alert']}: the expression must end with a comparison")
        out[rule["alert"]] = float(match.group(1))
    return out


def metric_names(expr: str) -> set[str]:
    """Every `claimsense_*` metric an expression reads."""
    return set(re.findall(r"claimsense_[a-z0-9_]+", expr))


# ----------------------------------------------------------------------------------- panels
def green_red(red_at: float) -> list[tuple[str, float | None]]:
    """Green below the limit, red at and above it."""
    return [("green", None), ("red", red_at)]


def red_green(green_at: float) -> list[tuple[str, float | None]]:
    """Red below the limit, green at and above it."""
    return [("red", None), ("green", green_at)]


def panel(
    title: str,
    queries: list[tuple[str, str]],
    x: int,
    y: int,
    w: int,
    h: int,
    kind: str = "timeseries",
    unit: str | None = None,
    decimals: int | None = None,
    lo: float | None = None,
    hi: float | None = None,
    thresholds: list[tuple[str, float | None]] | None = None,
    stack: bool = False,
    description: str = "",
) -> dict:
    """One Grafana panel. queries: list of (PromQL, legend)."""
    defaults: dict = {
        "custom": {
            "lineWidth": 2,
            "fillOpacity": 12,
            "showPoints": "never",
            "stacking": {"mode": "normal" if stack else "none"},
        }
    }
    if unit:
        defaults["unit"] = unit
    if decimals is not None:
        defaults["decimals"] = decimals
    if lo is not None:
        defaults["min"] = lo
    if hi is not None:
        defaults["max"] = hi
    if thresholds:
        defaults["thresholds"] = {
            "mode": "absolute",
            "steps": [{"color": color, "value": value} for color, value in thresholds],
        }
    p: dict = {
        "type": kind,
        "title": title,
        "description": description,
        "datasource": DS,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": [
            {"refId": chr(65 + i), "expr": q, "legendFormat": legend, "datasource": DS}
            for i, (q, legend) in enumerate(queries)
        ],
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "options": {
            "legend": {"displayMode": "list", "placement": "bottom"},
            "tooltip": {"mode": "multi"},
        },
    }
    if kind == "stat":
        p["options"] = {
            "reduceOptions": {"calcs": ["lastNotNull"]},
            "colorMode": "background",
            "graphMode": "area",
            "textMode": "value",
        }
    if kind == "state-timeline":
        p["options"] = {"showValue": "never", "mergeValues": True, "rowHeight": 0.8}
        p["fieldConfig"]["defaults"]["color"] = {"mode": "fixed", "fixedColor": "red"}
        p["fieldConfig"]["defaults"]["mappings"] = [
            {"type": "value", "options": {"1": {"text": "firing", "color": "red"}}}
        ]
    return p


def build_dashboard(arms: dict[str, str] | None = None, rules_path: Path = RULES_FILE) -> dict:
    """The whole dashboard: six stat tiles, ten time series, and the alert timeline.

    arms: A/B label -> the agent-suite variant behind it, shown in the panel descriptions.
    """
    arms = arms or {"A": "v1", "B": "guarded"}
    limit = thresholds(rules_path)
    who = ", ".join(f"{label} = {variant}" for label, variant in sorted(arms.items()))
    q = QUERIES
    by_variant = "{{variant}}"

    panels = [
        # ---- row 1: six numbers to read from across the room
        panel(
            "Claims per minute", [(q["claims_per_minute"], "")], 0, 0, 4, 4, kind="stat", decimals=0
        ),
        panel(
            "Handled correctly (1 min)",
            [(q["handled_correctly"], "")],
            4,
            0,
            4,
            4,
            kind="stat",
            unit="percentunit",
            decimals=0,
            thresholds=red_green(limit["HandledCorrectlyDrop"]),
            description="Right route, and the gold settlement when cleared. Scored claims only.",
        ),
        panel(
            "P95 latency",
            [(q["latency_p95"], "")],
            8,
            0,
            4,
            4,
            kind="stat",
            unit="s",
            decimals=2,
            thresholds=green_red(limit["LatencyP95High"]),
        ),
        panel(
            "Cost per claim",
            [(q["cost_per_claim"], "")],
            12,
            0,
            4,
            4,
            kind="stat",
            unit="currencyUSD",
            decimals=4,
            thresholds=green_red(limit["CostPerClaimHigh"]),
            description="Model spend over all claims. Zero in stub mode: no model is called.",
        ),
        panel(
            "Worst tool error rate",
            [(q["tool_error_rate_worst"], "")],
            16,
            0,
            4,
            4,
            kind="stat",
            unit="percentunit",
            decimals=0,
            thresholds=green_red(limit["ToolErrorRateHigh"]),
            description="The tool that fails most often, as a share of its own calls.",
        ),
        panel(
            "Alerts firing",
            [(q["alerts_firing_count"], "")],
            20,
            0,
            4,
            4,
            kind="stat",
            decimals=0,
            thresholds=green_red(1),
        ),
        # ---- quality and speed
        panel(
            "Handled correctly, by variant",
            [(q["handled_correctly_by_variant"], by_variant)],
            0,
            4,
            12,
            8,
            unit="percentunit",
            lo=0,
            hi=1,
            description=f"A/B test, routed by member: {who}.",
        ),
        panel(
            "Latency P50 / P95 / P99",
            [(q["latency_p50"], "P50"), (q["latency_p95"], "P95"), (q["latency_p99"], "P99")],
            12,
            4,
            12,
            8,
            unit="s",
            description="Claims that reached the agents. Blocked claims are left out.",
        ),
        # ---- money and tools
        panel(
            "Cost per claim, by variant",
            [(q["cost_per_claim_by_variant"], by_variant)],
            0,
            12,
            12,
            8,
            unit="currencyUSD",
            decimals=4,
            description=f"{who}. Zero in stub mode.",
        ),
        panel(
            "Tool error rate, by tool",
            [(q["tool_error_rate_by_tool"], "{{tool}}")],
            12,
            12,
            12,
            8,
            unit="percentunit",
            lo=0,
            hi=1,
        ),
        # ---- what happened to the claims
        panel(
            "Outcomes per minute",
            [(q["outcomes_per_minute"], "{{outcome}}")],
            0,
            20,
            12,
            8,
            stack=True,
            description="blocked = the input guardrail sent it to a person. error = a crash.",
        ),
        panel(
            "Guardrail trips per minute, by rule",
            [(q["guardrail_trips_per_minute"], "{{rule}}")],
            12,
            20,
            12,
            8,
            stack=True,
        ),
        # ---- online quality checks
        panel(
            "Online judge pass rate, by variant",
            [(q["judge_pass_rate_by_variant"], by_variant)],
            0,
            28,
            12,
            8,
            unit="percentunit",
            lo=0,
            hi=1,
            description="A sample of review payloads graded by the LLM judge. Needs --judge.",
        ),
        panel(
            "Model calls per claim, by variant",
            [(q["llm_calls_per_claim_by_variant"], by_variant)],
            12,
            28,
            12,
            8,
            decimals=1,
            description="Zero in stub mode. A jump here usually explains a jump in cost.",
        ),
        panel(
            "Review payload code checks passed, by variant",
            [(q["payload_check_pass_rate_by_variant"], by_variant)],
            0,
            36,
            12,
            8,
            unit="percentunit",
            lo=0,
            hi=1,
            description=(
                "Exact checks on what the adjudicator is shown: every deduction cites a clause, "
                "the clause exists, the totals add up, the route matches the findings. "
                "No gold needed."
            ),
        ),
        panel(
            "Claims ending in a pipeline error",
            [(q["pipeline_error_share"], "share of claims")],
            12,
            36,
            12,
            8,
            unit="percentunit",
            lo=0,
            hi=1,
        ),
        # ---- alerts
        panel(
            "Alerts",
            [(q["alerts_firing"], "{{alertname}}")],
            0,
            44,
            24,
            5,
            kind="state-timeline",
        ),
    ]
    return {
        "uid": DASHBOARD_UID,
        "title": DASHBOARD_TITLE,
        "description": f"ClaimSense pipeline, live. A/B arms: {who}.",
        "refresh": "5s",
        "schemaVersion": 39,
        "time": {"from": "now-10m", "to": "now"},
        "panels": panels,
        "annotations": {
            "list": [
                {
                    "builtIn": 1,
                    "datasource": {"type": "grafana", "uid": "-- Grafana --"},
                    "enable": True,
                    "hide": False,
                    "iconColor": "rgba(255, 96, 96, 1)",
                    "name": "Annotations & Alerts",
                    "type": "dashboard",
                }
            ]
        },
    }
