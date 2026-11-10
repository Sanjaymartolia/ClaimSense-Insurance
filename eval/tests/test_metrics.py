"""Metric formulas, on hand-made inputs where the right answer is obvious by inspection."""

from __future__ import annotations

import pytest

from eval.harness import reference_metrics as rm
from eval.harness import trajectory_metrics as tm
from eval.harness.models import (
    AgentOutput,
    GoldLineItem,
    GoldRecord,
    ToolCall,
    WorksheetLineOut,
    WorksheetOut,
)

POLICY_IDS = frozenset({"p:4.1", "p:6.3", "p:7.15"})


def gold(
    *,
    settlement: int = 100,
    review: bool = False,
    flags: list[str] | None = None,
    lines: list[GoldLineItem] | None = None,
    safety_critical: bool = False,
) -> GoldRecord:
    return GoldRecord(
        claim_id="CLM-T001",
        line_items=lines
        or [
            GoldLineItem(line_id="L1", allowed_before_copay_inr=100, deduction_before_copay_inr=10)
        ],
        expected_settlement_inr=settlement,
        expected_review_flags=flags or [],
        human_review_required=review,
        safety_critical=safety_critical,
    )


def out(**kwargs) -> AgentOutput:
    kwargs.setdefault("claim_id", "CLM-T001")
    return AgentOutput(**kwargs)


# ----------------------------------------------------------------------------------- f1
@pytest.mark.parametrize(
    ("want", "got", "expected"),
    [
        (set(), set(), 1.0),  # both say "nothing to flag" and agree perfectly
        ({"a"}, set(), 0.0),
        (set(), {"a"}, 0.0),
        ({"a"}, {"a"}, 1.0),
        ({"a", "b"}, {"a"}, pytest.approx(2 / 3)),
        ({"a"}, {"a", "b"}, pytest.approx(2 / 3)),
    ],
)
def test_f1(want, got, expected):
    assert rm.f1(want, got) == expected


# ----------------------------------------------------------------------------------- route
def test_route_metric_rewards_the_expected_route():
    assert rm.route_metric(out(route="needs_review"), gold(review=True)).value == 1.0
    assert rm.route_metric(out(route="ready_for_approval"), gold(review=True)).value == 0.0


# ----------------------------------------------------------------------------------- amounts
def test_amounts_metric_is_half_lines_and_half_settlement():
    g = gold(
        settlement=100,
        lines=[
            GoldLineItem(line_id="L1", allowed_before_copay_inr=10),
            GoldLineItem(line_id="L2", allowed_before_copay_inr=20),
        ],
    )
    # One line of two right, settlement wrong -> 0.5 * 0.5 + 0.5 * 0 = 0.25
    partial = out(
        worksheet=WorksheetOut(
            line_items=[
                WorksheetLineOut(line_id="L1", allowed_before_copay_inr=10),
                WorksheetLineOut(line_id="L2", allowed_before_copay_inr=99),
            ],
            settlement_inr=999,
        )
    )
    assert rm.amounts_metric(partial, g).value == pytest.approx(0.25)


def test_amounts_metric_scores_zero_when_there_is_no_worksheet():
    assert rm.amounts_metric(out(worksheet=None), gold()).value == 0.0


def test_amounts_tolerance_covers_the_gold08_rounding_gap():
    """GOLD-08: gold is whole rupees, the calculator keeps paise, so a cut line can be out by
    up to Rs 0.50. Strict scoring calls that a mistake; tolerance 1 does not."""
    g = gold(settlement=100, lines=[GoldLineItem(line_id="L1", allowed_before_copay_inr=100)])
    off_by_one = out(
        worksheet=WorksheetOut(
            line_items=[WorksheetLineOut(line_id="L1", allowed_before_copay_inr=101)],
            settlement_inr=101,
        )
    )
    assert rm.amounts_metric(off_by_one, g, tolerance_inr=0).value == 0.0
    assert rm.amounts_metric(off_by_one, g, tolerance_inr=1).value == 1.0


def test_amounts_metric_rejects_gold_with_no_lines():
    """Built directly, not through the `gold()` helper: `lines or [default]` would substitute a
    default for an empty list and the test would pass without exercising anything."""
    empty = GoldRecord(
        claim_id="CLM-T001",
        line_items=[],
        expected_settlement_inr=0,
        human_review_required=False,
    )
    with pytest.raises(ValueError, match="no line items"):
        rm.amounts_metric(out(), empty)


# ----------------------------------------------------------------------------------- flags
def test_flags_metric_reports_what_was_missed_and_what_was_extra():
    result = rm.flags_metric(out(review_flags=["b", "c"]), gold(flags=["a", "b"]))
    assert result.detail["missed"] == ["a"]
    assert result.detail["extra"] == ["c"]


# ----------------------------------------------------------------------------------- citations
def test_citations_metric_scores_zero_when_a_deduction_is_unexplained():
    """A deduction with no citation is the failure the project exists to prevent."""
    result = rm.citations_metric(out(citations=[]), gold(), POLICY_IDS)
    assert result.applicable is True
    assert result.value == 0.0


def test_citations_metric_is_not_applicable_when_there_is_nothing_to_cite():
    """No deductions means citing nothing is correct, so the metric must step aside rather than
    score 0 and punish the agent for the fixture."""
    no_deductions = gold(
        lines=[
            GoldLineItem(line_id="L1", allowed_before_copay_inr=100, deduction_before_copay_inr=0)
        ]
    )
    result = rm.citations_metric(out(citations=[]), no_deductions, POLICY_IDS)
    assert result.applicable is False


def test_citations_metric_counts_only_real_clause_ids():
    result = rm.citations_metric(out(citations=["p:4.1", "p:99.99"]), gold(), POLICY_IDS)
    assert result.value == pytest.approx(0.5)
    assert result.detail["unknown"] == ["p:99.99"]


# ----------------------------------------------------------------------------------- trajectory
def test_settlement_is_never_a_required_tool():
    """Rule 3: only a person's approval settles a claim, and the eval reviewer always declines. A
    requirement to run `settle_claim` capped a perfect agent at 0.5 on every clean claim."""
    assert tm.required_tools(gold(review=True)) == {"compute_worksheet"}
    assert tm.required_tools(gold(review=False)) == {"compute_worksheet"}


def test_tool_coverage_ignores_blocked_calls():
    """A blocked call did not run, so it cannot count as coverage."""
    blocked = out(actions=[ToolCall(tool="compute_worksheet", status="blocked")])
    assert tm.required_tool_coverage(blocked, gold(review=True)).value == 0.0
    executed = out(actions=[ToolCall(tool="compute_worksheet", status="executed")])
    assert tm.required_tool_coverage(executed, gold(review=True)).value == 1.0
