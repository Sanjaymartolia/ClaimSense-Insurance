"""What the case UI shows and sends, as plain functions (no Streamlit needed)."""

from decimal import Decimal

import pytest

from claimsense.ui import views

# CLM-0004 as the case API streams it (stub agents): the room-rent scene of the demo.
WORKSHEET = {
    "claim_id": "CLM-0004",
    "version": 1,
    "lines": [
        {
            "line_id": "CLM-0004-L01",
            "claimed": "74726",
            "deductions": [
                {
                    "reason": "proportional_cut",
                    "amount": "37747.58",
                    "clause_id": "new_india_arogya_sanjeevani:4.1.1",
                    "explanation": "Proportional cut after room/ICU breach, factor 0.494854.",
                }
            ],
            "payable": "36978.42",
        },
        {
            "line_id": "CLM-0004-L02",
            "claimed": "24000",
            "deductions": [
                {
                    "reason": "room_rent_cap",
                    "amount": "12123.52",
                    "clause_id": "new_india_arogya_sanjeevani:12.1",
                    "explanation": "Room share Rs 5000.00/day x 3 ward day(s); factor 0.494854.",
                }
            ],
            "payable": "11876.48",
        },
        {
            "line_id": "CLM-0004-L03",
            "claimed": "6312",
            "deductions": [
                {
                    "reason": "room_rent_cap",
                    "amount": "3188.48",
                    "clause_id": "new_india_arogya_sanjeevani:12.1",
                    "explanation": "Room share Rs 5000.00/day x 3 ward day(s); factor 0.494854.",
                }
            ],
            "payable": "3123.52",
        },
        {"line_id": "CLM-0004-L04", "claimed": "14871", "deductions": [], "payable": "14871"},
        {
            "line_id": "CLM-0004-L05",
            "claimed": "7573",
            "deductions": [
                {
                    "reason": "proportional_cut",
                    "amount": "3825.47",
                    "clause_id": "new_india_arogya_sanjeevani:4.1.1",
                    "explanation": "Proportional cut after room/ICU breach, factor 0.494854.",
                }
            ],
            "payable": "3747.53",
        },
    ],
    "co_pay": {
        "reason": "co_pay",
        "amount": "3529.85",
        "clause_id": "new_india_arogya_sanjeevani:9.5",
        "explanation": "5% co-pay on admissible amount.",
    },
    "total_claimed": "127482",
    "total_payable": "67067.10",
    "fraud_flags": [],
}


@pytest.mark.parametrize(
    ("amount", "shown"),
    [
        ("0", "Rs 0.00"),
        ("999", "Rs 999.00"),
        ("1000", "Rs 1,000.00"),
        ("67067.10", "Rs 67,067.10"),
        ("100000", "Rs 1,00,000.00"),
        ("201962.52", "Rs 2,01,962.52"),
        ("12345678.9", "Rs 1,23,45,678.90"),
        (Decimal("-3529.85"), "-Rs 3,529.85"),
        (41573.05, "Rs 41,573.05"),
    ],
)
def test_rupees_use_indian_digit_grouping(amount, shown):
    assert views.inr(amount) == shown


def test_worksheet_rows_show_each_line_and_add_up_to_the_totals():
    rows = views.worksheet_rows(WORKSHEET)
    assert [row["line"] for row in rows] == [f"CLM-0004-L0{n}" for n in range(1, 6)]
    assert rows[0] == {
        "line": "CLM-0004-L01",
        "claimed": "Rs 74,726.00",
        "deducted": "Rs 37,747.58",
        "payable": "Rs 36,978.42",
        "reason": "proportional_cut",
        "clause": "new_india_arogya_sanjeevani:4.1.1",
    }
    assert (rows[3]["deducted"], rows[3]["reason"], rows[3]["clause"]) == ("Rs 0.00", "", "")
    assert views.totals(WORKSHEET) == {
        "claimed": "Rs 1,27,482.00",
        "deducted": "Rs 60,414.90",
        "co_pay": "Rs 3,529.85",
        "payable": "Rs 67,067.10",
    }


def test_every_deduction_keeps_its_clause_and_the_calculator_s_explanation():
    rows = views.deduction_rows(WORKSHEET)
    assert len(rows) == 5  # four lines with a deduction, then the co-pay
    assert rows[0] == {
        "line": "CLM-0004-L01",
        "reason": "proportional_cut",
        "clause": "new_india_arogya_sanjeevani:4.1.1",
        "amount": "Rs 37,747.58",
        "explanation": "Proportional cut after room/ICU breach, factor 0.494854.",
    }
    assert (rows[-1]["line"], rows[-1]["reason"]) == ("whole claim", "co_pay")


def test_flags_get_the_kind_the_api_metrics_use():
    injection = "extraction: possible prompt injection in CLM-9001-DOC01: 'note to ai'"
    duplicate = "duplicate claim id CLM-0004 already in history"
    assert views.flag_rows([injection, duplicate, "something else"]) == [
        ("injection", injection),
        ("duplicate", duplicate),
        ("other", "something else"),
    ]


def test_plan_rows_mark_each_step_as_the_planner_does():
    plan = {
        "revision": 1,
        "steps": [
            {"name": "extract", "agent": "extraction", "status": "done"},
            {"name": "fraud_screen", "agent": "fraud", "status": "skipped"},
            {"name": "settle", "agent": "settlement", "status": "pending"},
        ],
    }
    assert views.plan_rows(plan) == [
        {"step": "✓ extract", "agent": "extraction"},
        {"step": "– fraud_screen", "agent": "fraud"},
        {"step": "· settle", "agent": "settlement"},
    ]


def test_an_approval_given_on_an_earlier_worksheet_is_shown_void():
    first = {
        "approvals": [{"level": "adjudicator", "approver_id": "alice", "decided_at": "t1"}],
        "review": {"worksheet_hash": "h1"},
        "settlement": None,
    }
    seen = views.remember_approvals([], first)
    assert seen == [
        {"level": "adjudicator", "approver_id": "alice", "decided_at": "t1", "worksheet_hash": "h1"}
    ]
    assert views.remember_approvals(seen, first) == seen  # seen once, kept once
    edited = {"approvals": [], "review": {"worksheet_hash": "h2"}, "settlement": None}
    seen = views.remember_approvals(seen, edited)
    assert [a["void"] for a in views.mark_void(seen, views.current_hash(edited))] == [True]
    settled = {
        "approvals": [{"level": "adjudicator", "approver_id": "alice", "decided_at": "t2"}],
        "review": None,
        "settlement": {"worksheet_hash": "h2"},
    }
    seen = views.remember_approvals(seen, settled)
    assert views.current_hash(settled) == "h2"
    assert [a["void"] for a in views.mark_void(seen, "h2")] == [True, False]


METRICS = """
# TYPE claimsense_claims_processed_total counter
claimsense_claims_processed_total{outcome="settled"} 3.0
claimsense_claims_processed_total{outcome="rejected"} 1.0
claimsense_claims_processed_created{outcome="settled"} 1.7e9
# TYPE claimsense_review_decisions_total counter
claimsense_review_decisions_total{decision="approve",level="adjudicator"} 3.0
claimsense_review_decisions_total{decision="edit",level="senior"} 1.0
# TYPE claimsense_rupees_deducted_total counter
claimsense_rupees_deducted_total{reason="co_pay"} 3529.85
claimsense_rupees_deducted_total{reason="proportional_cut"} 41573.05
# TYPE claimsense_fraud_flags_total counter
claimsense_fraud_flags_total{kind="injection"} 1.0
# TYPE claimsense_turnaround_seconds histogram
claimsense_turnaround_seconds_bucket{le="+Inf"} 4.0
claimsense_turnaround_seconds_count 4.0
claimsense_turnaround_seconds_sum 120.0
# TYPE claimsense_claims_total counter
claimsense_claims_total{outcome="ready_for_approval"} 4.0
# TYPE claimsense_cost_usd_total counter
claimsense_cost_usd_total 0.08
# TYPE claimsense_tool_calls_total counter
claimsense_tool_calls_total{status="ok",tool="calculate"} 7.0
claimsense_tool_calls_total{status="blocked",tool="settle_claim"} 1.0
# TYPE claimsense_in_flight gauge
claimsense_in_flight 0.0
"""


def test_dashboard_numbers_come_from_the_metrics_text():
    numbers = views.dashboard(METRICS)
    assert numbers["processed"] == {"settled": 3, "rejected": 1}
    assert numbers["processed_total"] == 4
    assert numbers["decisions"] == {"adjudicator approve": 3, "senior edit": 1}
    assert numbers["edit_rate"] == pytest.approx(0.25)
    assert numbers["deducted"] == {"co_pay": 3529.85, "proportional_cut": 41573.05}
    assert numbers["flags"] == {"injection": 1}
    assert numbers["turnaround_mean_s"] == pytest.approx(30.0)
    assert numbers["cost_per_claim_usd"] == pytest.approx(0.02)
    assert numbers["tool_calls"] == {"ok": 7, "blocked": 1}
    assert numbers["in_flight"] == 0


def test_a_dashboard_with_no_traffic_has_no_rates():
    numbers = views.dashboard("")
    assert numbers["processed_total"] == 0
    assert (numbers["edit_rate"], numbers["turnaround_mean_s"], numbers["cost_per_claim_usd"]) == (
        None,
        None,
        None,
    )


def test_a_packet_from_documents_keeps_the_filled_documents_only():
    packet = views.packet_from_documents(
        " CLM-7001 ", "POL-1", {"claim_form": "form text", "discharge_summary": "  "}, ""
    )
    assert packet == {
        "claim_id": "CLM-7001",
        "policy_number": "POL-1",
        "documents": {"claim_form": "form text"},
    }


def test_a_packet_needs_a_claim_id_and_a_document_or_an_extracted_claim():
    with pytest.raises(ValueError, match="claim id"):
        views.packet_from_documents("", "POL-1", {"claim_form": "x"}, "")
    with pytest.raises(ValueError, match="document"):
        views.packet_from_documents("CLM-7001", "POL-1", {}, "")
    packet = views.packet_from_documents("CLM-7001", "", {}, '{"claim_id": "CLM-7001"}')
    assert packet == {"claim_id": "CLM-7001", "documents": {}, "claim": {"claim_id": "CLM-7001"}}


def test_an_extracted_claim_is_a_json_object_for_the_same_claim():
    with pytest.raises(ValueError, match="JSON"):
        views.packet_from_documents("CLM-7001", None, {"a": "x"}, "{not json")
    with pytest.raises(ValueError, match="claim_id"):
        views.packet_from_documents("CLM-7001", None, {"a": "x"}, '{"claim_id": "CLM-9"}')


def test_a_packet_json_is_an_object_with_a_claim_id():
    assert views.packet_from_json('{"claim_id": "CLM-7001", "documents": {}}') == {
        "claim_id": "CLM-7001",
        "documents": {},
    }
    for bad in ("[]", "{}", "not json"):
        with pytest.raises(ValueError):
            views.packet_from_json(bad)


def test_markdown_escape_leaves_no_link_or_image():
    escaped = views.md_escape("![x](http://example.invalid/t.png) *bold* _CLM_0004_")
    assert "](" not in escaped
    assert "\\*bold\\*" in escaped and "\\_CLM\\_0004\\_" in escaped


@pytest.mark.parametrize(
    ("level", "phrase"), [("adjudicator", "an adjudicator"), ("senior", "a senior")]
)
def test_levels_read_with_the_right_article(level, phrase):
    assert views.a_level(level) == phrase
