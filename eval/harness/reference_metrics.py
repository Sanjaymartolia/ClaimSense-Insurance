"""Reference metrics: the agent's answer against the human gold answer.

The four formulas come from `course/evalkit/metrics.py`, the team's own teaching scorer, so a
course-kit score and a product score mean the same thing. RET-03 in
`docs/CLAIMS_AND_GOLD_SET_FIXES.md` records what happens when two tools quietly use one metric
name for two different formulas, so they are reused here rather than re-derived.

    route      the routing decision: ready_for_approval vs needs_review
    amounts    half the per-line allowed amounts, half the exact settlement
    flags      F1 of review flags against the gold flags
    citations  the share of cited ids that are real, searchable policy clauses

Read the gold caveat before trusting any of this. `eval/README.md` records that GOLD-02, GOLD-03,
GOLD-05, GOLD-06 and GOLD-08 are still open, so the gold itself is wrong in places. A high score
here means "agrees with today's gold", not "correct under the policy".
"""

from __future__ import annotations

from .models import AgentOutput, GoldRecord, MetricResult


def f1(gold: set[str], pred: set[str]) -> float:
    """F1 over two label sets. Two empty sets agree perfectly, which is the useful convention."""
    if not gold and not pred:
        return 1.0
    true_positives = len(gold & pred)
    if true_positives == 0:
        return 0.0
    return 2 * true_positives / (len(gold) + len(pred))


def route_metric(out: AgentOutput, gold: GoldRecord) -> MetricResult:
    correct = out.route == gold.expected_route
    return MetricResult(
        name="route",
        family="reference",
        value=float(correct),
        passed=correct,
        severity="high",
        detail={"predicted": out.route, "expected": gold.expected_route},
    )


def amounts_metric(out: AgentOutput, gold: GoldRecord, tolerance_inr: int = 0) -> MetricResult:
    """Half the per-line allowed amounts, half the exact settlement.

    `tolerance_inr` exists for GOLD-08: the gold is in whole rupees and the calculator keeps paise,
    so a cut line can differ by up to Rs 0.50 through rounding alone. Default 0 keeps the strict
    reading; pass 1 to stop rounding counting as a mistake. Report which you used.
    """
    want = {li.line_id: li.allowed_before_copay_inr for li in gold.line_items}
    got = out.allowed_by_line()
    if not want:
        raise ValueError(f"{gold.claim_id}: gold has no line items")

    def close(a: int | None, b: int) -> bool:
        return a is not None and abs(a - b) <= tolerance_inr

    matched = [line_id for line_id, amount in want.items() if close(got.get(line_id), amount)]
    line_share = len(matched) / len(want)
    settlement = out.worksheet.settlement_inr if out.worksheet else None
    settlement_exact = close(settlement, gold.expected_settlement_inr)

    value = 0.5 * line_share + 0.5 * float(settlement_exact)
    return MetricResult(
        name="amounts",
        family="reference",
        value=value,
        passed=value == 1.0,
        severity="high",
        detail={
            "line_match_share": round(line_share, 4),
            "lines_matched": len(matched),
            "lines_total": len(want),
            "settlement_predicted": settlement,
            "settlement_expected": gold.expected_settlement_inr,
            "settlement_exact": settlement_exact,
            "tolerance_inr": tolerance_inr,
        },
    )


def flags_metric(out: AgentOutput, gold: GoldRecord) -> MetricResult:
    """F1 of review flags.

    GOLD-06 is open: the gold flags name only the claim's headline scenario, not every rule that
    fired, so a thorough agent is punished for extra correct flags. Treat a mid-range value as a
    question about the gold, not proof the agent is wrong.
    """
    want, got = set(gold.expected_review_flags), set(out.review_flags)
    value = f1(want, got)
    return MetricResult(
        name="flags",
        family="reference",
        value=value,
        passed=value == 1.0,
        severity="medium",
        detail={
            "expected": sorted(want),
            "predicted": sorted(got),
            "missed": sorted(want - got),
            "extra": sorted(got - want),
        },
    )


def citations_metric(
    out: AgentOutput, gold: GoldRecord, policy_ids: frozenset[str]
) -> MetricResult:
    """The share of cited ids that are real, searchable clauses.

    Three cases, and the distinction is the whole value of this metric:

    - The gold has no deductions, so there is nothing to justify. Citing nothing is **correct**,
      and the metric is marked not applicable rather than scored.
    - The gold has deductions and the agent cited nothing: 0.0. An unexplained deduction is the
      exact failure this project exists to prevent, so this is never excused.
    - Otherwise: the share of cited ids that exist. Row 12.5 is absent from `policy_ids` by
      ADR-0004, so citing it earns nothing even though it is real text.
    """
    cited = set(out.citations)
    deductions = sum(1 for li in gold.line_items if li.deduction_before_copay_inr > 0)
    if deductions == 0:
        return MetricResult(
            name="citations",
            family="reference",
            value=1.0,
            passed=None,
            applicable=False,
            severity="medium",
            detail={
                "reason": "gold has no deductions, so there is nothing to cite",
                "cited": sorted(cited),
            },
        )
    value = len(cited & policy_ids) / len(cited) if cited else 0.0
    return MetricResult(
        name="citations",
        family="reference",
        value=value,
        passed=bool(cited) and value == 1.0,
        severity="medium",
        detail={
            "cited": sorted(cited),
            "unknown": sorted(cited - policy_ids),
            "cited_count": len(cited),
            "gold_deduction_lines": deductions,
            "gold_lines_without_clause_id": sorted(
                li.line_id
                for li in gold.line_items
                if li.deduction_before_copay_inr > 0 and not li.clause_id
            ),
        },
    )


def score_case(
    out: AgentOutput,
    gold: GoldRecord,
    policy_ids: frozenset[str],
    tolerance_inr: int = 0,
) -> dict[str, MetricResult]:
    results = [
        route_metric(out, gold),
        amounts_metric(out, gold, tolerance_inr),
        flags_metric(out, gold),
        citations_metric(out, gold, policy_ids),
    ]
    return {r.name: r for r in results}
