"""Product metrics (L13, L16): the names the eval alert rules query, and the brief's dashboard."""

import re
from decimal import Decimal
from pathlib import Path

import pytest
from prometheus_client import REGISTRY

from claimsense.api import metrics
from claimsense.contracts import DeductionReason

from .conftest import ALICE, decide, last, sse, start

ALERT_RULES = Path(__file__).resolve().parents[2] / "eval" / "monitoring" / "alert_rules.yml"
#: Series that need the right answer: only an eval run can produce them.
EVAL_ONLY = {"claimsense_correct_total", "claimsense_scored_total"}


def value(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


def deducted() -> dict[str, float]:
    return {
        r.value: value("claimsense_rupees_deducted_total", reason=r.value) for r in DeductionReason
    }


@pytest.mark.parametrize(
    ("flag", "kind"),
    [
        ("duplicate claim id CLM-1 already in history", "duplicate"),
        ("duplicate bill lines within this bill: L2 repeats L1", "duplicate"),
        ("procedure charges Rs 90000 above tariff range 40000-60000", "tariff"),
        ("sub-limits partly used earlier this policy year: cataract Rs 30000", "sub_limit"),
        ("admission date outside policy period", "dates"),
        ("L02: billed 5 days for a 3-night stay", "dates"),
        ("extraction: possible prompt injection in DOC01: 'duplicate'", "injection"),
        ("extraction: bill total 100 != sum of lines 90", "bill_total"),
        ("extraction: policy number in the documents differs from the registered policy", "other"),
    ],
)
def test_flag_kind(flag, kind):
    assert metrics.flag_kind(flag) == kind


def test_route_of():
    assert metrics.route_of({}) == "ready_for_approval"
    assert metrics.route_of({"fraud_flags": ["x"]}) == "needs_review"
    assert metrics.route_of({"extraction_issues": ["x"]}) == "needs_review"


def test_the_api_exposes_what_the_alert_rules_query(client):
    wanted = set(re.findall(r"claimsense_[a-z_]+", ALERT_RULES.read_text(encoding="utf-8")))
    exposed = client.get("/metrics/").text
    missing = sorted(name for name in wanted - EVAL_ONLY if name not in exposed)
    assert not missing, f"alert rules query series the API does not expose: {missing}"


def test_a_settled_claim_moves_the_dashboard(client):
    pytest.importorskip("langgraph.checkpoint.sqlite")
    routed = value("claimsense_claims_total", outcome="ready_for_approval")
    timed = value("claimsense_latency_seconds_count")
    settled = value("claimsense_claims_processed_total", outcome="settled")
    approvals = value("claimsense_review_decisions_total", level="adjudicator", decision="approve")
    turnaround = value("claimsense_turnaround_seconds_count")
    calculated = value("claimsense_tool_calls_total", tool="calculate", status="ok")
    rupees = deducted()

    review = last(sse(start(client, "CLM-0004")), "review")
    sse(decide(client, "CLM-0004", ALICE))

    assert value("claimsense_claims_total", outcome="ready_for_approval") == routed + 1
    assert value("claimsense_latency_seconds_count") == timed + 1
    assert value("claimsense_claims_processed_total", outcome="settled") == settled + 1
    assert (
        value("claimsense_review_decisions_total", level="adjudicator", decision="approve")
        == approvals + 1
    )
    assert value("claimsense_turnaround_seconds_count") == turnaround + 1
    assert value("claimsense_tool_calls_total", tool="calculate", status="ok") > calculated
    assert value("claimsense_in_flight") == 0
    sheet = review["worksheet"]
    cut = Decimal(sheet["total_claimed"]) - Decimal(sheet["total_payable"])
    moved = sum(deducted().values()) - sum(rupees.values())
    assert cut > 0
    assert moved == pytest.approx(float(cut))


def test_an_injected_note_trips_the_guardrail_metrics(client):
    pytest.importorskip("langgraph.checkpoint.sqlite")
    trips = value("claimsense_guardrail_trips_total", rule="prompt_injection")
    flagged = value("claimsense_claims_total", outcome="needs_review")
    injections = value("claimsense_fraud_flags_total", kind="injection")
    rejected = value("claimsense_claims_processed_total", outcome="rejected")
    rejects = value("claimsense_review_decisions_total", level="adjudicator", decision="reject")

    sse(start(client, "CLM-9001"))
    sse(decide(client, "CLM-9001", ALICE, "reject"))

    assert value("claimsense_guardrail_trips_total", rule="prompt_injection") == trips + 1
    assert value("claimsense_claims_total", outcome="needs_review") == flagged + 1
    assert value("claimsense_fraud_flags_total", kind="injection") == injections + 1
    assert value("claimsense_claims_processed_total", outcome="rejected") == rejected + 1
    assert (
        value("claimsense_review_decisions_total", level="adjudicator", decision="reject")
        == rejects + 1
    )
