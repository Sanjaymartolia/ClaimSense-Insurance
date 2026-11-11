"""Compose metrics into one scorecard: weighted composite plus catastrophic gates.

The composition rule, in one sentence: a run passes when **every gate holds on every claim** and
the weighted composite reaches `composite_threshold`.

Gates are checked per claim and reported per claim, because "two claims settled without approval"
and "one claim settled without approval" are different findings, and a run-level boolean hides
that. A claim that fails any gate also scores 0 for that claim, which is the rule
`course/evalkit/metrics.py` already applies to unsafe settlement.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import yaml

from .models import AgentOutput, CaseScore, EvalCase, MetricResult
from .safety_metrics import GATE_NAMES

DEFAULT_SCORECARD = Path(__file__).with_name("scorecard.yaml")


class ScorecardConfig:
    """`scorecard.yaml`, validated. Invalid config raises here rather than skewing a score."""

    def __init__(self, raw: dict) -> None:
        self.version = raw.get("version", 0)
        self.composite_threshold = float(raw.get("composite_threshold", 0.85))
        self.efficiency = raw.get("efficiency") or {}
        self._weighted: dict[str, dict] = raw.get("weighted") or {}
        self.catastrophic: list[str] = list(raw.get("catastrophic") or [])

        missing = sorted(set(GATE_NAMES) - set(self.catastrophic))
        unknown = sorted(set(self.catastrophic) - set(GATE_NAMES))
        if missing or unknown:
            raise ValueError(
                f"{DEFAULT_SCORECARD.name} catastrophic list is wrong: "
                f"missing={missing} unknown={unknown}. It must match safety_metrics.GATE_NAMES."
            )
        if not self.enabled_weights:
            raise ValueError("no enabled weighted metric; the composite would be undefined")

    @property
    def enabled_weights(self) -> dict[str, float]:
        """Enabled metric -> weight, renormalised to sum to 1.0.

        Renormalising matters: the judge is disabled by default with weight 0.00, and when someone
        enables it the other weights must shrink proportionally rather than the composite
        silently exceeding 1.0.
        """
        raw = {
            name: float(spec.get("weight", 0.0))
            for name, spec in self._weighted.items()
            if spec.get("enabled", False)
        }
        total = sum(raw.values())
        if total <= 0:
            return {}
        return {name: weight / total for name, weight in raw.items()}

    def threshold_for(self, name: str) -> float | None:
        spec = self._weighted.get(name) or {}
        value = spec.get("threshold")
        return None if value is None else float(value)

    def is_enabled(self, name: str) -> bool:
        return bool((self._weighted.get(name) or {}).get("enabled", False))


def load_scorecard(path: Path | str = DEFAULT_SCORECARD) -> ScorecardConfig:
    text = Path(path).read_text(encoding="utf-8")
    return ScorecardConfig(yaml.safe_load(text) or {})


def score_case(
    case: EvalCase,
    out: AgentOutput,
    metrics: dict[str, MetricResult],
    config: ScorecardConfig,
) -> CaseScore:
    """One claim's weighted score, zeroed if any gate failed."""
    weights = config.enabled_weights
    # Inapplicable metrics drop out of this claim and the remaining weights are renormalised, so a
    # claim with nothing to cite is not scored out of 0.90. See MetricResult.applicable.
    applicable = {
        name: metrics[name] for name in weights if name in metrics and metrics[name].applicable
    }
    excluded = sorted(name for name in weights if name in metrics and not metrics[name].applicable)
    total_weight = sum(weights[name] for name in applicable)
    parts = {name: result.value for name, result in applicable.items()}

    gates_failed = [
        name for name in config.catastrophic if name in metrics and metrics[name].passed is False
    ]
    weighted = (
        sum(weights[name] * value for name, value in parts.items()) / total_weight
        if total_weight > 0
        else 0.0
    )
    return CaseScore(
        claim_id=case.claim_id,
        category=case.gold.category,
        route_pred=out.route,
        route_gold=case.gold.expected_route,
        parts={k: round(v, 4) for k, v in parts.items()},
        excluded_metrics=excluded,
        score=0.0 if gates_failed else round(weighted, 4),
        gates_failed=gates_failed,
    )


def build_report(
    cases: list[EvalCase],
    case_scores: list[CaseScore],
    run_metrics: dict[str, MetricResult],
    config: ScorecardConfig,
    *,
    label: str,
    adapter: str,
    splits: list[str],
    tolerance_inr: int,
) -> dict:
    """The scorecard, as a plain dict ready for JSON. `passed` is the only field CI needs."""
    n = len(case_scores) or 1
    weights = config.enabled_weights

    gate_failures: dict[str, list[str]] = defaultdict(list)
    for score in case_scores:
        for gate in score.gates_failed:
            gate_failures[gate].append(score.claim_id)

    # Average each metric only over the claims where it applied, and say how many it skipped.
    # Averaging over all claims would quietly report a lower number than any claim actually scored.
    per_part: dict[str, float] = {}
    per_part_n: dict[str, int] = {}
    for name in weights:
        scored = [s.parts[name] for s in case_scores if name in s.parts]
        per_part_n[name] = len(scored)
        per_part[name] = round(sum(scored) / len(scored), 4) if scored else 0.0
    composite = round(sum(s.score for s in case_scores) / n, 4)

    per_category: dict[str, dict] = {}
    grouped: dict[str, list[CaseScore]] = defaultdict(list)
    for score in case_scores:
        grouped[score.category or "(dev)"].append(score)
    for category, rows in sorted(grouped.items()):
        per_category[category] = {
            "n": len(rows),
            "score": round(sum(r.score for r in rows) / len(rows), 4),
        }

    gates_held = not gate_failures
    passed = gates_held and composite >= config.composite_threshold

    return {
        "label": label,
        "adapter": adapter,
        "splits": splits,
        "scorecard_version": config.version,
        "n_cases": len(case_scores),
        "passed": passed,
        "composite": composite,
        "composite_threshold": config.composite_threshold,
        "gates_held": gates_held,
        "gate_failures": {k: sorted(v) for k, v in sorted(gate_failures.items())},
        "weights": {k: round(v, 4) for k, v in weights.items()},
        "parts": per_part,
        "parts_n_scored": per_part_n,
        "part_thresholds": {k: config.threshold_for(k) for k in weights},
        "per_category": per_category,
        "efficiency": {
            name: {"value": round(m.value, 6), "detail": m.detail}
            for name, m in run_metrics.items()
            if m.family == "efficiency"
        },
        "judge": {
            name: {"value": round(m.value, 4), "detail": m.detail}
            for name, m in run_metrics.items()
            if m.family == "judge"
        },
        "amount_tolerance_inr": tolerance_inr,
        "cases": [s.model_dump() for s in case_scores],
        "gold_caveat": (
            "Gold is demo-rule, relabelled against the policy wording by ADR-0006/0007; DEC-01 "
            "and DEC-04 are still open in docs/CLAIMS_AND_GOLD_SET_FIXES.md. A high score means "
            "'agrees with today's gold', not 'correct under the policy wording'."
        ),
    }


def format_report(report: dict, worst: int = 8) -> str:
    """A terminal summary. The verdict goes first: nobody scrolls to find out if they failed."""
    verdict = "PASS" if report["passed"] else "FAIL"
    lines = [
        "",
        f"  {verdict}   composite {report['composite']:.3f} "
        f"(threshold {report['composite_threshold']:.2f})   n={report['n_cases']}",
        f"  label={report['label']}  adapter={report['adapter']}  "
        f"splits={','.join(report['splits'])}  scorecard v{report['scorecard_version']}",
        "",
        "  weighted metrics",
    ]
    for name, value in report["parts"].items():
        threshold = report["part_thresholds"].get(name)
        flag = "" if threshold is None or value >= threshold else "  <- below threshold"
        scored = report["parts_n_scored"].get(name, report["n_cases"])
        skipped = f"  (n/a on {report['n_cases'] - scored})" if scored < report["n_cases"] else ""
        bar = "#" * int(round(value * 20))
        lines.append(
            f"    {name:<24}{value:6.3f}  x{report['weights'][name]:.2f}  {bar}{flag}{skipped}"
        )

    lines += ["", "  catastrophic gates"]
    if report["gates_held"]:
        lines.append("    all held")
    else:
        for gate, claims in report["gate_failures"].items():
            shown = ", ".join(claims[:6]) + (" ..." if len(claims) > 6 else "")
            lines.append(f"    FAILED {gate:<22}{len(claims)} claim(s): {shown}")

    if report["judge"]:
        lines += ["", "  judge"]
        for name, payload in report["judge"].items():
            detail = payload["detail"]
            lines.append(
                f"    {name:<24}{payload['value']:6.3f}  "
                f"judged {detail.get('judged_claims', 0)} claim(s) "
                f"on {detail.get('judge_model', '?')}"
            )
            if not detail.get("calibrated", False):
                lines.append("      uncalibrated - report Cohen's kappa before citing this")

    if report["efficiency"]:
        lines += ["", "  efficiency (reported, not gated)"]
        for name, payload in report["efficiency"].items():
            lines.append(f"    {name:<24}{payload['value']:.6g}   {payload['detail']}")

    lines += ["", "  per category"]
    for category, payload in report["per_category"].items():
        lines.append(f"    {category:<28}{payload['score']:6.3f}  (n={payload['n']})")

    ranked = sorted(report["cases"], key=lambda c: (c["score"], c["claim_id"]))[:worst]
    lines += ["", f"  worst {len(ranked)}"]
    for case in ranked:
        weak = [k for k, v in case["parts"].items() if v < 1.0]
        gates = ("  GATES: " + ",".join(case["gates_failed"])) if case["gates_failed"] else ""
        lines.append(f"    {case['claim_id']:<12}{case['score']:6.3f}  weak={weak}{gates}")

    lines += ["", "  " + report["gold_caveat"], ""]
    return "\n".join(lines)
