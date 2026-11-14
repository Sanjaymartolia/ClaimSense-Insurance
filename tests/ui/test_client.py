"""The UI's client of the case API, against the API app in memory (stub agents and tools)."""

import pytest

from claimsense.ui.client import ApiClient, ApiError, parse_sse
from tests.api.conftest import ALICE, BOB


def test_parse_sse_reads_named_events_and_skips_comments():
    lines = [
        "event: plan",
        'data: {"revision": 0}',
        "",
        ": keep-alive",
        "",
        "",
        "event: done",
        'data: {"status": "settled", "amount": "67067.10"}',
    ]  # the last event has no blank line after it: the stream ended
    assert list(parse_sse(lines)) == [
        ("plan", {"revision": 0}),
        ("done", {"status": "settled", "amount": "67067.10"}),
    ]


def test_parse_sse_yields_each_event_as_soon_as_it_is_complete():
    def stream():
        yield "event: plan"
        yield 'data: {"revision": 0}'
        yield ""
        raise AssertionError("read past the first event: the page would show nothing live")

    assert next(parse_sse(stream())) == ("plan", {"revision": 0})


def test_an_api_that_is_not_running_is_reported_not_raised_raw():
    client = ApiClient.from_url("http://127.0.0.1:9")  # nothing listens on the discard port
    with pytest.raises(ApiError) as error:
        client.health()
    assert error.value.status == 0
    assert "not reachable" in error.value.detail


def test_a_claim_runs_end_to_end_through_the_client(api):
    assert api.health()["status"] == "ok"
    assert api.me(ALICE) == {"approver_id": "alice", "level": "adjudicator"}
    assert "CLM-0004" in [claim["claim_id"] for claim in api.demo_claims(ALICE)]
    events = list(api.start_demo(ALICE, "CLM-0004"))
    assert [name for name, _ in events[:2]] == ["run", "plan"]
    assert events[-1][0] == "review" and events[-1][1]["level"] == "adjudicator"
    finished = list(api.decide(ALICE, "CLM-0004", {"decision": "approve"}))
    assert finished[-1][0] == "done" and finished[-1][1]["status"] == "settled"
    assert api.case(ALICE, "CLM-0004")["status"] == "settled"
    assert "claimsense_claims_processed_total" in api.metrics_text()


def test_a_demo_claim_can_start_under_another_case_id(api):
    events = list(api.start_demo(ALICE, "CLM-0004", case_id="CLM-0004-first"))
    assert events[-1][0] == "review"
    case = api.case(ALICE, "CLM-0004-first")
    assert (case["case_id"], case["claim_id"]) == ("CLM-0004-first", "CLM-0004")


def test_api_refusals_carry_the_api_s_reason_and_never_the_token(api):
    with pytest.raises(ApiError) as error:
        api.me("not-a-reviewer-token")
    assert error.value.status == 401
    assert "not-a-reviewer-token" not in str(error.value)
    with pytest.raises(ApiError) as error:
        api.case(ALICE, "CLM-NOPE")
    assert error.value.status == 404
    list(api.start_demo(ALICE, "CLM-0019"))
    with pytest.raises(ApiError) as error:
        list(api.decide(BOB, "CLM-0019", {"decision": "approve"}))
    assert (error.value.status, error.value.detail) == (
        403,
        "this review needs an adjudicator reviewer",
    )
    assert BOB not in str(error.value)
    with pytest.raises(ApiError) as error:
        list(api.start_demo(ALICE, "CLM-0019"))
    assert error.value.status == 409
    with pytest.raises(ApiError) as error:
        list(api.start_packet(ALICE, {"claim_id": "CLM-7001", "documents": {"bill": "x"}}))
    assert (error.value.status, error.value.detail) == (
        422,
        "stub mode reads no documents: send a pre-extracted claim",
    )


def test_a_validation_refusal_is_summarised_as_one_line(api):
    with pytest.raises(ApiError) as error:
        list(api.decide(ALICE, "CLM-0004", {"decision": "edit"}))
    assert error.value.status == 422
    assert "an edit needs at least one line edit" in error.value.detail
