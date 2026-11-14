"""L16: the operations dashboard and the edit-rate alert, on the case API's own metrics.

`dashboard.py` builds the live dashboard for the monitoring drill, which simulates its traffic.
This module builds the one the capstone brief asks for in production: claims processed, the
adjudicator edit rate, rupees deducted by reason, fraud flags, turnaround and cost per claim, from
the metric names in `src/claimsense/api/metrics.py`, with the same `panel` helper. The alert is in
`ops_alert_rules.yml` (promtool unit test: `ops_alert_rules.test.yml`).

`python -m eval.monitoring export` writes both for Deploy & Ops to adopt; nothing here touches
`monitoring/`. Panels count over the dashboard's time range (`$__range`), so the numbers survive a
restart of the API only as far as Prometheus kept the samples.
"""

from __future__ import annotations

from pathlib import Path

from . import dashboard as d

OPS_RULES_FILE = Path(__file__).with_name("ops_alert_rules.yml")
OPS_RULES_TEST = Path(__file__).with_name("ops_alert_rules.test.yml")
OPS_UID = "claimsense-ops"
OPS_TITLE = "ClaimSense operations"
EDIT_ALERT = "AdjudicatorEditRateRising"


def _edit_rate(window: str) -> str:
    edits = f'claimsense_review_decisions_total{{decision="edit"}}[{window}]'
    return f"sum(increase({edits})) / sum(increase(claimsense_review_decisions_total[{window}]))"


def _over_range(metric: str, by: str = "") -> str:
    agg = f"sum by ({by})" if by else "sum"
    return f"{agg} (increase({metric}[$__range]))"


OPS_QUERIES: dict[str, str] = {
    "claims_processed": _over_range("claimsense_claims_processed_total"),
    "claims_by_outcome": _over_range("claimsense_claims_processed_total", by="outcome"),
    "edit_rate": _edit_rate("$__range"),
    "edit_rate_last_hour": _edit_rate("1h"),
    "edit_rate_last_day": _edit_rate("1d"),
    "decisions_by_level": _over_range("claimsense_review_decisions_total", by="level, decision"),
    "rupees_deducted": _over_range("claimsense_rupees_deducted_total"),
    "rupees_deducted_by_reason": _over_range("claimsense_rupees_deducted_total", by="reason"),
    "fraud_flags": _over_range("claimsense_fraud_flags_total"),
    "fraud_flags_by_kind": _over_range("claimsense_fraud_flags_total", by="kind"),
    "turnaround_p95": (
        "histogram_quantile(0.95, sum by (le) "
        "(increase(claimsense_turnaround_seconds_bucket[$__range])))"
    ),
    "cost_per_claim": (
        f"{_over_range('claimsense_cost_usd_total')} / {_over_range('claimsense_claims_total')}"
    ),
    "tool_calls_per_minute": "sum by (status) (rate(claimsense_tool_calls_total[5m])) * 60",
    "alerts_firing": 'ALERTS{alertstate="firing"}',
}


def api_metric_names() -> set[str]:
    """Every sample name the case API exposes: counters end in `_total`, histograms add `_bucket`,
    `_sum` and `_count`."""
    from prometheus_client import REGISTRY

    import claimsense.api.metrics  # noqa: F401 - registers the API's metrics

    names: set[str] = set()
    for family in REGISTRY.collect():
        if not family.name.startswith("claimsense_"):
            continue
        if family.type == "counter":
            names.add(f"{family.name}_total")
        elif family.type == "histogram":
            names |= {f"{family.name}_{part}" for part in ("bucket", "sum", "count")}
        else:
            names.add(family.name)
    return names


def _bars(panel: dict) -> dict:
    """A horizontal bar per label value: for breakdowns such as rupees by reason."""
    panel["options"] = {
        "reduceOptions": {"calcs": ["lastNotNull"], "values": False},
        "orientation": "horizontal",
        "displayMode": "gradient",
        "showUnfilled": True,
    }
    return panel


def build_ops_dashboard(rules_path: Path = OPS_RULES_FILE) -> dict:
    """Six numbers to read from across the room, then the breakdowns behind them."""
    limit = d.thresholds(rules_path)[EDIT_ALERT]  # the tile turns red where the alert fires
    q = OPS_QUERIES
    panels = [
        d.panel("Claims processed", [(q["claims_processed"], "")], 0, 0, 4, 4, kind="stat"),
        d.panel(
            "Adjudicator edit rate",
            [(q["edit_rate"], "")],
            4,
            0,
            4,
            4,
            kind="stat",
            unit="percentunit",
            decimals=0,
            thresholds=d.green_red(limit),
            description="Edits as a share of all review decisions in the time range.",
        ),
        d.panel(
            "Rupees deducted",
            [(q["rupees_deducted"], "")],
            8,
            0,
            4,
            4,
            kind="stat",
            unit="currencyINR",
            decimals=0,
            description="On settled and repudiated claims, co-pay included.",
        ),
        d.panel("Fraud flags", [(q["fraud_flags"], "")], 12, 0, 4, 4, kind="stat", decimals=0),
        d.panel(
            "Turnaround P95",
            [(q["turnaround_p95"], "")],
            16,
            0,
            4,
            4,
            kind="stat",
            unit="s",
            decimals=0,
            description="From receipt to the final decision, reviewers' time included.",
        ),
        d.panel(
            "Cost per claim",
            [(q["cost_per_claim"], "")],
            20,
            0,
            4,
            4,
            kind="stat",
            unit="currencyUSD",
            decimals=4,
            description="Model spend over claims run. Zero while the agents run in stub mode.",
        ),
        d.panel(
            "Edit rate: last hour against last day",
            [(q["edit_rate_last_hour"], "last hour"), (q["edit_rate_last_day"], "last day")],
            0,
            4,
            12,
            8,
            unit="percentunit",
            lo=0,
            hi=1,
            thresholds=d.green_red(limit),
            description=f"{EDIT_ALERT} fires when the last hour is above 1.5 times the last day, "
            "over at least 10 decisions, and above the red line.",
        ),
        _bars(
            d.panel(
                "Rupees deducted by reason",
                [(q["rupees_deducted_by_reason"], "{{reason}}")],
                12,
                4,
                12,
                8,
                kind="bargauge",
                unit="currencyINR",
                decimals=0,
            )
        ),
        _bars(
            d.panel(
                "Claims by outcome",
                [(q["claims_by_outcome"], "{{outcome}}")],
                0,
                12,
                8,
                8,
                kind="bargauge",
            )
        ),
        _bars(
            d.panel(
                "Fraud flags by kind",
                [(q["fraud_flags_by_kind"], "{{kind}}")],
                8,
                12,
                8,
                8,
                kind="bargauge",
            )
        ),
        _bars(
            d.panel(
                "Review decisions",
                [(q["decisions_by_level"], "{{level}} {{decision}}")],
                16,
                12,
                8,
                8,
                kind="bargauge",
            )
        ),
        d.panel(
            "Tool calls per minute",
            [(q["tool_calls_per_minute"], "{{status}}")],
            0,
            20,
            12,
            8,
            stack=True,
        ),
        d.panel(
            "Alerts firing",
            [(q["alerts_firing"], "{{alertname}}")],
            12,
            20,
            12,
            8,
            kind="state-timeline",
        ),  # fmt: skip
    ]
    for number, panel in enumerate(panels, start=1):
        panel["id"] = number
    return {
        "uid": OPS_UID,
        "title": OPS_TITLE,
        "description": "ClaimSense in production (L16): the numbers the capstone brief asks for.",
        "tags": ["claimsense", "L16"],
        "refresh": "30s",
        "schemaVersion": 39,
        "time": {"from": "now-24h", "to": "now"},
        "panels": panels,
    }
