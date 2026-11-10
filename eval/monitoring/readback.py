"""L13 sections 8.7 and 8.8: read the dashboard back through PromQL, and list the alerts.

Grafana shows the incident while it happens. For a report, the same queries are run against
Prometheus afterwards (`collect_panels`), saved as numbers (`panels.json`) and drawn as one chart
(`panels.png`). Every expression comes from `dashboard.QUERIES`, so the chart and the dashboard
cannot drift apart.

8.8 asks Prometheus which alerts fired and when (`alerts_fired`), and `drill_check` compares that
with what the scenario was built to raise: an alert that stays silent in a drill is the most
useful thing a drill can find.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .dashboard import QUERIES, thresholds
from .live import Phase

#: prom(expr, start=None, end=None, step=5) -> the `result` list of a Prometheus query.
Prom = Callable[..., list[dict]]
Series = dict[str, tuple[list[float], list[float]]]
PhaseLog = Sequence[tuple[str, float, float]]


@dataclass(frozen=True)
class PanelSpec:
    key: str
    title: str
    unit: str  # share | seconds | usd | per_min
    #: (key in QUERIES, label key in the result or None, fixed legend for a single series)
    queries: tuple[tuple[str, str | None, str], ...]
    #: Alert whose threshold is drawn on the panel, if any; `below` = it fires under the limit.
    alert: str = ""
    below: bool = False


#: The line an alert on the whole stream watches, next to the per-variant lines.
ALL_CLAIMS = "all claims"

PANELS: tuple[PanelSpec, ...] = (
    PanelSpec(
        "handled_correctly",
        "Handled correctly, by variant",
        "share",
        (("handled_correctly_by_variant", "variant", ""), ("handled_correctly", None, ALL_CLAIMS)),
        alert="HandledCorrectlyDrop",
        below=True,
    ),
    PanelSpec(
        "latency",
        "Latency per claim",
        "seconds",
        (("latency_p50", None, "P50"), ("latency_p95", None, "P95")),
        alert="LatencyP95High",
    ),
    PanelSpec(
        "tool_errors",
        "Tool error rate, by tool",
        "share",
        (("tool_error_rate_by_tool", "tool", ""),),
        alert="ToolErrorRateHigh",
    ),
    PanelSpec(
        "pipeline_errors",
        "Claims ending in a pipeline error",
        "share",
        (("pipeline_error_share", None, ALL_CLAIMS),),
        alert="PipelineErrorRateHigh",
    ),
    PanelSpec(
        "guardrail",
        "Guardrail trips, as a share of claims",
        "share",
        (("guardrail_trip_share", None, ALL_CLAIMS),),
        alert="GuardrailBurst",
    ),
    PanelSpec(
        "outcomes",
        "Outcomes per minute",
        "per_min",
        (("outcomes_per_minute", "outcome", ""),),
    ),
    PanelSpec(
        "cost",
        "Cost per claim, by variant",
        "usd",
        (("cost_per_claim_by_variant", "variant", ""),),
        alert="CostPerClaimHigh",
    ),
    PanelSpec(
        "payload_checks",
        "Review payload code checks passed, by variant",
        "share",
        (("payload_check_pass_rate_by_variant", "variant", ""),),
    ),
)


# --------------------------------------------------------------------------------- 8.7 read
def _number(text: str) -> float:
    """Prometheus sends numbers as strings; "NaN" and the infinities become NaN (a gap)."""
    value = float(text)
    return value if math.isfinite(value) else math.nan


def series(
    prom: Prom,
    expr: str,
    legend_key: str | None = None,
    start: float | None = None,
    end: float | None = None,
    step: int = 5,
    legend: str = "",
) -> Series:
    """Run a range query. Returns {label: (unix times, values)}, one entry per series."""
    out: Series = {}
    for result in prom(expr, start=start, end=end, step=step):
        label = result["metric"].get(legend_key, "") if legend_key else legend
        times = [float(t) for t, _ in result["values"]]
        values = [_number(v) for _, v in result["values"]]
        out[label or "value"] = (times, values)
    return out


def collect_panels(prom: Prom, start: float, end: float, step: int = 5) -> dict[str, Series]:
    """Every panel of the chart: {panel key: {label: (times, values)}}."""
    panels: dict[str, Series] = {}
    for spec in PANELS:
        merged: Series = {}
        for query, legend_key, legend in spec.queries:
            merged.update(series(prom, QUERIES[query], legend_key, start, end, step, legend))
        panels[spec.key] = merged
    return panels


def panels_to_json(panels: dict[str, Series]) -> dict:
    """The table view of the chart: every point, NaN written as null."""
    spec = {s.key: s for s in PANELS}
    return {
        key: {
            "title": spec[key].title,
            "unit": spec[key].unit,
            "queries": [QUERIES[q] for q, _, _ in spec[key].queries],
            "series": {
                label: {"t": ts, "v": [None if math.isnan(v) else round(v, 6) for v in vs]}
                for label, (ts, vs) in sorted(data.items())
            },
        }
        for key, data in panels.items()
    }


def phase_at(ts: float, phase_log: PhaseLog) -> str:
    """The phase a moment falls in; "before" the first one starts, "after" the last one ends."""
    if not phase_log or ts < phase_log[0][1]:
        return "before"
    if ts > phase_log[-1][2]:
        return "after"
    return [name for name, start, _ in phase_log if start <= ts][-1]


def phase_means(panels: dict[str, Series], phase_log: PhaseLog) -> dict[str, dict]:
    """{panel: {label: {phase: mean of the points in that phase}}}. None where there is no data.

    Rates are computed over one or two minutes, so a phase's mean still carries some of the phase
    before it. Use it to compare phases, not as an exact level.
    """
    out: dict[str, dict] = {}
    for key, data in panels.items():
        out[key] = {}
        for label, (ts, vs) in sorted(data.items()):
            per_phase: dict[str, float | None] = {}
            for name, start, end in phase_log:
                points = [v for t, v in zip(ts, vs, strict=True) if start <= t <= end]
                finite = [v for v in points if not math.isnan(v)]
                per_phase[name] = round(sum(finite) / len(finite), 6) if finite else None
            out[key][label] = per_phase
    return out


# ------------------------------------------------------------------------------- 8.8 alerts
def _intervals(times: list[float], step: int) -> list[tuple[float, float]]:
    """Group sample times into unbroken stretches (a gap of more than two steps ends one)."""
    out: list[tuple[float, float]] = []
    for t in times:
        if out and t - out[-1][1] <= 2 * step:
            out[-1] = (out[-1][0], t)
        else:
            out.append((t, t))
    return out


def alerts_fired(
    prom: Prom,
    phase_log: PhaseLog,
    rules: Sequence[dict] = (),
    start: float | None = None,
    end: float | None = None,
    step: int = 5,
) -> list[dict]:
    """Every alert that fired between `start` and `end`, oldest first.

    rules: what `Stack.rules()` returns; the runbook line of each alert is taken from it.
    """
    runbook = {r["name"]: (r.get("annotations") or {}).get("runbook", "") for r in rules}
    order = {name: i for i, (name, _, _) in enumerate(phase_log)}
    out: list[dict] = []
    for result in prom(QUERIES["alerts_firing"], start=start, end=end, step=step):
        times = [float(t) for t, _ in result["values"]]
        if not times:
            continue
        name = result["metric"].get("alertname", "?")
        phases = {phase_at(t, phase_log) for t in times}
        out.append(
            {
                "alert": name,
                "tool": result["metric"].get("tool", ""),
                "first": times[0],
                "last": times[-1],
                "intervals": _intervals(times, step),
                "phases": sorted(phases, key=lambda p: order.get(p, -1 if p == "before" else 99)),
                "runbook": runbook.get(name, ""),
            }
        )
    return sorted(out, key=lambda a: (a["first"], a["alert"]))


def drill_check(scenario: Sequence[Phase], phase_log: PhaseLog, alerts: Sequence[dict]) -> dict:
    """Did the alerts do what the scenario was built to show?

    Two checks, both robust to the lag of a rate window:
    - every alert a phase expects first fired after that phase began;
    - nothing fired before the first phase that expects an alert (no false alarm in normal traffic).
    Alerts that fired without being expected are listed, not failed: a slower, broader alert (such
    as `HandledCorrectlyDrop`) may or may not cross its limit in a short incident.
    """
    began = {name: start for name, start, _ in phase_log}
    expecting = [p for p in scenario if p.expect and p.name in began]
    first_incident = min((began[p.name] for p in expecting), default=None)
    expected = []
    for phase in expecting:
        for alert in phase.expect:
            hits = [a for a in alerts if a["alert"] == alert and a["first"] >= began[phase.name]]
            expected.append(
                {
                    "phase": phase.name,
                    "alert": alert,
                    "fired": bool(hits),
                    "after_s": round(hits[0]["first"] - began[phase.name], 1) if hits else None,
                }
            )
    wanted = {alert for phase in expecting for alert in phase.expect}
    false_alarms = sorted(
        {a["alert"] for a in alerts if first_incident is not None and a["first"] < first_incident}
    )
    return {
        "expected": expected,
        "false_alarms": false_alarms,
        "also_fired": sorted({a["alert"] for a in alerts} - wanted - set(false_alarms)),
        "ok": all(row["fired"] for row in expected) and not false_alarms,
    }


def format_alerts(alerts: Sequence[dict], t0: float) -> str:
    """The 8.8 printout: what fired, from when to when (seconds into the run), and the runbook."""
    if not alerts:
        return "no alert fired"
    lines = []
    for a in alerts:
        name = f"{a['alert']}{{tool={a['tool']}}}" if a["tool"] else a["alert"]
        lines.append(
            f"{name:<38} fired {a['first'] - t0:>4.0f} s to {a['last'] - t0:>4.0f} s  "
            f"during: {', '.join(a['phases'])}"
        )
        if a["runbook"]:
            lines.append(f"    runbook: {a['runbook']}")
    return "\n".join(lines)


# --------------------------------------------------------------------------------- the chart
INK, INK_2, SURFACE, GRID, SPINE = "#0b0b0b", "#52514e", "#fcfcfb", "#e4e3df", "#c3c2b7"
BAND = "#f1f0ec"  # incident phases, a shade under the surface
CRITICAL = "#d03b3b"  # status colour: alerts only

#: Colour follows the entity. A and B keep their colour in every panel.
VARIANT_COLOURS = {"A": "#2a78d6", "B": "#eb6834"}
#: The outcome palette is local to the outcomes panel (validated with dataviz validate_palette).
OUTCOME_COLOURS = {
    "ready_for_approval": "#1baf7a",
    "needs_review": "#eda100",
    "blocked": "#6250d6",
    "error": "#e34948",
}
_UNIT_LABEL = {
    "share": "share",
    "seconds": "seconds",
    "usd": "US dollars",
    "per_min": "claims per minute",
}


def _finite(values: Sequence[float]) -> list[float]:
    return [v for v in values if not math.isnan(v)]


#: (series label, legend text, colour, line style, line width)
Style = tuple[str, str, str, Any, float]


def _styles(spec: PanelSpec, data: Series, arms: dict[str, str]) -> list[Style]:
    """How each line of a panel is drawn, in a stable order.

    Series that never left zero are dropped from the tool panel (nine flat lines say nothing).
    """
    if spec.key == "outcomes":
        return [(k, k, c, "-", 2.0) for k, c in OUTCOME_COLOURS.items() if k in data]
    if spec.key in ("handled_correctly", "cost", "payload_checks"):
        out: list[Style] = [
            (k, f"{k} ({arms.get(k, '?')})", c, "-", 2.0)
            for k, c in VARIANT_COLOURS.items()
            if k in data
        ]
        if ALL_CLAIMS in data:  # the line the alert watches
            out.append((ALL_CLAIMS, ALL_CLAIMS, INK, (0, (2, 2)), 1.5))
        return out
    if spec.key == "tool_errors":
        failing = sorted(k for k, (_, vs) in data.items() if max(_finite(vs), default=0) > 0)
        return [
            (k, k, INK if i == 0 else INK_2, ("-", "--", ":")[min(i, 2)], 2.0)
            for i, k in enumerate(failing)
        ]
    if spec.key == "latency":
        return [(k, k, c, "-", 2.0) for k, c in (("P95", INK), ("P50", INK_2)) if k in data]
    return [(k, k, INK, "-", 2.0) for k in sorted(data)]


def _limit_text(spec: PanelSpec, limit: float) -> str:
    value = {"seconds": f"{limit:g} s", "usd": f"${limit:g}"}.get(spec.unit, f"{limit:g}")
    return f"{spec.alert} fires {'below' if spec.below else 'above'} {value}"


def _end_labels(ax: Any, items: list[tuple[float, str]]) -> None:
    """Name each line at its right end, in ink, nudged apart so two labels never overlap."""
    lo, hi = ax.get_ylim()
    span = (hi - lo) or 1.0
    placed: list[tuple[float, str]] = []
    for y, text in sorted(items):
        frac = min(max((y - lo) / span, 0.02), 0.98)
        if placed and frac - placed[-1][0] < 0.09:
            frac = placed[-1][0] + 0.09
        placed.append((frac, text))
    for frac, text in placed:
        ax.annotate(
            text,
            xy=(1.0, frac),
            xycoords="axes fraction",
            xytext=(5, 0),
            textcoords="offset points",
            va="center",
            ha="left",
            fontsize=8,
            color=INK_2,
            annotation_clip=False,
        )


def plot_panels(
    panels: dict[str, Series],
    phase_log: PhaseLog,
    alerts: Sequence[dict],
    path: Path,
    title: str = "",
    arms: dict[str, str] | None = None,
    limits: dict[str, float] | None = None,
) -> bool:
    """8.7: the dashboard as one picture, phases shaded, alerts underneath. False if matplotlib
    is not installed (it is in the `docs` and `course` extras, not in the base install)."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False

    arms = arms or {}
    limits = thresholds() if limits is None else limits
    t0 = phase_log[0][1] if phase_log else 0.0
    t_end = max(
        [end for _, _, end in phase_log]
        + [t for data in panels.values() for ts, _ in data.values() for t in ts[-1:]]
        + [t0 + 1]
    )
    rows = math.ceil(len(PANELS) / 2)
    strip_h = max(0.62, 0.24 * len(alerts) + 0.3)
    fig = plt.figure(figsize=(14, 3.1 * rows + 1.4 + 2.0 * strip_h), facecolor=SURFACE)
    # Row 0 names the phases once per column; the last row is the alert strip.
    grid = fig.add_gridspec(
        rows + 2,
        2,
        height_ratios=[0.12] + [1.0] * rows + [strip_h],
        hspace=0.75,
        wspace=0.3,
    )
    headers = [fig.add_subplot(grid[0, col]) for col in range(2)]
    axes = [fig.add_subplot(grid[1 + i // 2, i % 2]) for i in range(len(PANELS))]
    strip = fig.add_subplot(grid[rows + 1, :])

    def dress(ax: Any) -> None:
        ax.set_facecolor(SURFACE)
        for i, (_, start, end) in enumerate(phase_log):
            if i % 2 == 1:
                ax.axvspan(start - t0, end - t0, color=BAND, lw=0, zorder=0)
        ax.set_xlim(0, t_end - t0)
        ax.grid(axis="y", color=GRID, lw=0.8)
        ax.set_axisbelow(True)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(SPINE)
        ax.tick_params(colors=INK_2, labelsize=8, length=0)

    def name_phases(ax: Any, y: float, va: str, dy: float) -> None:
        for name, start, end in phase_log:
            ax.annotate(
                name,
                xy=((start + end) / 2 - t0, y),
                xycoords=("data", "axes fraction"),
                xytext=(0, dy),
                textcoords="offset points",
                ha="center",
                va=va,
                fontsize=8.5,
                color=INK,
            )

    for header in headers:
        dress(header)
        header.grid(False)
        header.set_xticks([])
        header.set_yticks([])
        header.spines["bottom"].set_visible(False)
        name_phases(header, 0.5, "center", 0)

    for ax, spec in zip(axes, PANELS, strict=True):
        dress(ax)
        data = panels.get(spec.key, {})
        styles = _styles(spec, data, arms)
        ends: list[tuple[float, str]] = []
        for label, legend, colour, dash, width in styles:
            ts, vs = data[label]
            ax.plot([t - t0 for t in ts], vs, color=colour, lw=width, ls=dash, label=legend)
            if _finite(vs):
                ends.append((_finite(vs)[-1], legend))
        top = data_top = max(
            [v for label, *_ in styles for v in _finite(data[label][1])], default=0.0
        )
        if spec.alert and spec.alert in limits:
            limit = limits[spec.alert]
            if top > 0 and limit > 3 * top:
                # A line at 30 s would flatten a 2 s curve; say where the limit is instead.
                ax.text(
                    0.01,
                    0.97,
                    f"{_limit_text(spec, limit)} (off this scale)",
                    transform=ax.transAxes,
                    ha="left",
                    va="top",
                    fontsize=7.5,
                    color=INK_2,
                )
            else:
                top = max(top, limit)
                ax.axhline(limit, color=INK_2, lw=1, ls=(0, (4, 3)))
                ax.annotate(  # on the side of the line where the alert is quiet
                    _limit_text(spec, limit),
                    xy=(0.0, limit),
                    xycoords=("axes fraction", "data"),
                    xytext=(4, -3 if spec.below else 3),
                    textcoords="offset points",
                    va="top" if spec.below else "bottom",
                    fontsize=7.5,
                    color=INK_2,
                )
        if spec.unit == "share":
            ax.set_ylim(0, 1.0 if top > 0.5 else max(0.1, top * 1.35))
        else:
            ax.set_ylim(0, top * 1.2 if top > 0 else 1.0)
        if data_top == 0:
            note = "no failing tool" if spec.key == "tool_errors" else "zero throughout"
            if spec.unit == "usd":
                note = "zero: stub agents call no model"
            ax.text(
                0.5,
                0.5,
                note,
                transform=ax.transAxes,
                ha="center",
                va="center",
                fontsize=9,
                color=INK_2,
            )
        ax.set_title(
            f"{spec.title}  ({_UNIT_LABEL[spec.unit]})", loc="left", fontsize=10, color=INK, pad=20
        )
        if len(styles) >= 2:
            ax.legend(
                loc="lower right",
                bbox_to_anchor=(1.0, 1.0),
                ncol=len(styles),
                frameon=False,
                fontsize=7.5,
                labelcolor=INK_2,
                handlelength=1.6,
                columnspacing=1.0,
                borderaxespad=0.1,
            )
        if 1 <= len(styles) <= 4:
            _end_labels(ax, ends)
    for ax in axes[-2:]:
        ax.set_xlabel("seconds since the run started", fontsize=8, color=INK_2)

    # ---- the alerts, one row each, on the same time axis; the name sits above its bar
    dress(strip)
    strip.grid(False)
    strip.set_yticks([])
    for row, alert in enumerate(alerts):
        name = f"{alert['alert']} ({alert['tool']})" if alert["tool"] else alert["alert"]
        for start, end in alert["intervals"]:
            strip.barh(
                row, max(end - start, 2.5), left=start - t0, height=0.36, color=CRITICAL, lw=0
            )
        strip.annotate(
            f"{name}   firing {alert['first'] - t0:.0f} to {alert['last'] - t0:.0f} s",
            xy=(0.0, row - 0.2),
            xycoords=("axes fraction", "data"),
            xytext=(4, 1),
            textcoords="offset points",
            ha="left",
            va="bottom",
            fontsize=8,
            color=INK,
        )
    strip.set_ylim(max(len(alerts), 1) - 0.5, -0.9)
    if not alerts:
        strip.text(
            0.5,
            0.5,
            "no alert fired",
            transform=strip.transAxes,
            ha="center",
            va="center",
            fontsize=9,
            color=INK_2,
        )
    strip.set_title("Alerts firing", loc="left", fontsize=10, color=INK, pad=20)
    strip.set_xlabel("seconds since the run started", fontsize=8, color=INK_2)
    name_phases(strip, 1.0, "bottom", 3)

    if title:
        fig.suptitle(title, x=0.05, y=0.99, ha="left", fontsize=12, color=INK)
    fig.subplots_adjust(left=0.05, right=0.9, top=0.95, bottom=0.04)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=130, facecolor=SURFACE)
    plt.close(fig)
    return True


def write_panels_json(panels: dict[str, Series], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(panels_to_json(panels), indent=1), encoding="utf-8")
