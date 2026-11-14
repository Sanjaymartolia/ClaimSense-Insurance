"""The case UI's screens, driven by Streamlit's AppTest against the case API app in memory.

Each test clicks through one scene of the capstone demo (guide p. 10) the way the adjudicator
would, with stub agents and tools: nothing here calls a model.
"""

import json
from pathlib import Path

import pytest

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest  # noqa: E402

import claimsense.ui  # noqa: E402
from claimsense.api.demo import demo_packet  # noqa: E402
from claimsense.ui import views  # noqa: E402
from tests.api.conftest import ALICE, ALICE_SENIOR, BOB  # noqa: E402

APP = str(Path(claimsense.ui.__file__).with_name("app.py"))
TEXT_ELEMENTS = (
    "title", "header", "subheader", "markdown", "text", "code", "caption",
    "error", "warning", "info", "success", "json",
)  # fmt: skip


def run(at: AppTest) -> AppTest:
    at = at.run()
    assert not at.exception, [e.value for e in at.exception]  # the page itself never fails
    return at


def open_ui(api) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["api"] = api
    return run(at)


def sign_in(at: AppTest, token: str) -> AppTest:
    at.text_input(key="token").input(token)
    at.button(key="sign_in").click()
    return run(at)


def act_as(at: AppTest, approver_id: str) -> AppTest:
    acting = at.radio(key="acting")
    acting.set_value(next(o for o in acting.options if o.startswith(approver_id)))
    return run(at)


def click(at: AppTest, key: str) -> AppTest:
    at.button(key=key).click()
    return run(at)


def shown(at: AppTest) -> str:
    """Every text on the page, tables and metrics included, as one string."""
    parts = [str(element.value) for kind in TEXT_ELEMENTS for element in getattr(at, kind)]
    for table in at.dataframe:  # cell by cell: to_string() would cut long explanations short
        parts += [str(cell) for cell in [*table.value.columns, *table.value.to_numpy().ravel()]]
    parts += [f"{metric.label} {metric.value}" for metric in at.metric]
    parts += [box.label for box in at.expander]
    return "\n".join(parts)


def test_before_sign_in_the_page_asks_for_a_reviewer_token(api):
    at = open_ui(api)
    assert not at.exception
    assert "Sign in with a reviewer token" in shown(at)


def test_scene_1_the_room_rent_cut_is_explained_line_by_line_then_settles(api):
    at = click(sign_in(open_ui(api), ALICE), "scene_1")
    page = shown(at)
    assert "awaiting review" in page
    assert "Proportional cut after room/ICU breach, factor 0.494854." in page
    assert "Rs 67,067.10" in page and "Rs 1,27,482.00" in page
    page = shown(click(at, "approve"))
    assert "settled" in page
    assert "Amount payable: Rs 67067.10" in page  # the letter


def test_scene_2_the_injected_note_and_the_bill_sent_again_are_flagged(api):
    at = click(sign_in(open_ui(api), ALICE), "scene_2")
    page = shown(at)
    assert "injection" in page and "possible prompt injection" in page
    at = click(click(at, "scene_1"), "approve")  # CLM-0004 settles: now it is in the history
    page = shown(click(at, "scene_2b"))
    assert "duplicate claim id CLM-0004 already in history" in page


def test_scene_3_an_edit_voids_the_earlier_approval_and_needs_both_levels_again(api):
    at = act_as(sign_in(sign_in(open_ui(api), ALICE), BOB), "alice")
    at = click(click(at, "scene_3"), "approve")
    assert "This review needs a senior reviewer" in shown(at)
    at = act_as(at, "bob")
    at.selectbox(key="edit_line").select("CLM-0019-L04")
    at.text_input(key="edit_amount").input("6000")
    at.text_input(key="edit_reason").input("bill shows Rs 6,000")
    page = shown(click(at, "edit_submit"))
    assert "void" in page  # alice's approval, given on the first worksheet
    assert "earlier approvals void" in page  # the API's own trace line
    assert "Rs 2,01,903.62" in page  # the calculator's new total
    page = shown(click(at, "approve"))  # bob is senior; the review now needs an adjudicator
    assert "this review needs an adjudicator reviewer" in page
    at = click(act_as(at, "alice"), "approve")
    at = click(act_as(at, "bob"), "approve")
    assert "settled" in shown(at)


def test_the_four_eyes_rule_is_the_api_s_and_the_page_shows_it(api):
    at = act_as(sign_in(sign_in(open_ui(api), ALICE), ALICE_SENIOR), "alice · adjudicator")
    at = click(click(at, "scene_3"), "approve")
    at = click(act_as(at, "alice · senior"), "approve")
    assert "four eyes" in shown(at)


def test_a_claim_ruled_not_admissible_shows_why_and_is_repudiated(api):
    at = sign_in(open_ui(api), ALICE)
    at.selectbox(key="demo_claim").select("CLM-0001")
    page = shown(click(at, "demo_start"))
    assert "Not admissible." in page
    page = shown(click(at, "approve"))
    assert "repudiated" in page


def test_a_packet_pasted_as_json_starts_a_claim_under_its_case_id(api):
    packet = demo_packet("CLM-0004")  # a synthetic packet, as an intake system would send it
    at = sign_in(open_ui(api), ALICE)
    at.radio(key="upload_mode").set_value("Packet JSON")
    at = run(at)
    at.text_area(key="up_packet_json").input(json.dumps(packet, default=str))
    at.text_input(key="up_case_id").input("UPLOAD-1")
    page = shown(click(at, "up_start"))
    assert "UPLOAD" in page and "awaiting review" in page and "Rs 67,067.10" in page


def test_documents_without_an_extracted_claim_get_the_api_s_reason_in_stub_mode(api):
    at = sign_in(open_ui(api), ALICE)
    at.text_input(key="up_claim_id").input("CLM-7001")
    at.text_area(key="up_itemised_bill").input("Ward charges, 3 days: Rs 18,000")
    page = shown(click(at, "up_start"))
    assert "stub mode reads no documents: send a pre-extracted claim" in page


def test_the_dashboard_shows_the_edit_rate_the_metrics_give(api):
    at = click(click(sign_in(open_ui(api), ALICE), "scene_1"), "approve")
    at.radio(key="page").set_value("Dashboard")
    at = run(at)
    expected = views.dashboard(api.metrics_text())["edit_rate"]
    metric = next(m for m in at.metric if m.label == "Edit rate")
    assert metric.value == f"{expected:.0%}"
    assert "Rupees deducted by reason" in shown(at)


class MarkdownFlagApi:
    """A stand-in API whose claim carries a fraud flag written as markdown."""

    FLAG = "duplicate bill ![x](http://example.invalid/t.png) [click](http://example.invalid)"

    def health(self):
        return {"status": "ok", "version": "test", "llm": "stub", "tools": "stub"}

    def me(self, token):
        return {"approver_id": "alice", "level": "adjudicator"}

    def demo_claims(self, token):
        return [{"claim_id": "CLM-7001", "source": "test"}]

    def case(self, token, case_id):
        return {
            "case_id": case_id,
            "claim_id": "CLM-7001",
            "status": "awaiting_review",
            "review": {"kind": "worksheet", "level": "adjudicator", "worksheet_hash": "h1"},
            "plan": None,
            "worksheet": None,
            "fraud_flags": [self.FLAG],
            "approvals": [],
            "edits": 0,
            "settlement": None,
            "letter": None,
            "trace": [],
        }


def test_text_from_the_documents_is_shown_as_text_never_as_markdown():
    at = sign_in(open_ui(MarkdownFlagApi()), "any-token")
    at.text_input(key="open_case_id").input("CLM-7001")
    at = click(at, "open_case")
    assert any(MarkdownFlagApi.FLAG in element.value for element in at.text)
    markdown = [
        str(element.value) for kind in ("markdown", "caption") for element in getattr(at, kind)
    ]
    assert not any("example.invalid" in value for value in markdown)


def test_no_screen_shows_a_reviewer_token(api):
    at = click(sign_in(sign_in(open_ui(api), ALICE), BOB), "scene_1")
    page = shown(at)
    assert ALICE not in page and BOB not in page
    assert at.text_input(key="token").value == ""  # the field is cleared after each sign-in
