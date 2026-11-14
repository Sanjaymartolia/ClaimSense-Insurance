"""The claim flow over HTTP (L16), stub models and tools. Demo scenes: a room-rent cut approved
(CLM-0004), an injected note (CLM-9001), the same bill sent again (CLM-0004 twice), and an edit
that voids the earlier approval (CLM-0019, which needs a senior)."""

import re
from decimal import Decimal

import pytest

pytest.importorskip("langgraph.checkpoint.sqlite")

from claimsense.agents.clauses import HOSPITALISATION  # noqa: E402
from claimsense.api import demo  # noqa: E402

from .conftest import (  # noqa: E402
    ALICE,
    ALICE_SENIOR,
    BOB,
    CAROL,
    auth,
    decide,
    get,
    last,
    make_client,
    sse,
    start,
)


def test_a_claim_streams_to_its_first_review(client):
    events = sse(start(client, "CLM-0004"))
    names = [name for name, _ in events]
    assert names[:2] == ["run", "plan"]  # the run id first (rubric D3), then the plan
    assert names[-1] == "review"
    assert {"step", "worksheet"} <= set(names)
    review = last(events, "review")
    assert (review["kind"], review["level"]) == ("worksheet", "adjudicator")
    assert review["worksheet"] == last(events, "worksheet")

    case = get(client, "CLM-0004")
    assert case["status"] == "awaiting_review"
    assert case["review"] == review
    assert case["worksheet"] == review["worksheet"]
    assert case["approvals"] == []


def test_approval_settles_the_claim_once(client):
    review = last(sse(start(client, "CLM-0004")), "review")
    done = last(sse(decide(client, "CLM-0004", CAROL)), "done")
    assert done["status"] == "settled"
    assert done["settlement"]["worksheet_hash"] == review["worksheet_hash"]
    assert done["settlement"]["amount"] == review["worksheet"]["total_payable"]
    assert "Amount payable" in done["letter"]

    case = get(client, "CLM-0004")
    assert (case["status"], case["review"]) == ("settled", None)
    assert [(a["level"], a["approver_id"]) for a in case["approvals"]] == [("adjudicator", "carol")]
    assert decide(client, "CLM-0004", CAROL).status_code == 409


def test_an_edit_voids_the_earlier_approval(client):
    first = last(sse(start(client, "CLM-0019")), "review")
    senior = last(sse(decide(client, "CLM-0019", ALICE)), "review")
    assert senior["level"] == "senior"
    assert senior["worksheet_hash"] == first["worksheet_hash"]
    assert [a["approver_id"] for a in get(client, "CLM-0019")["approvals"]] == ["alice"]

    edit = {"line_id": "CLM-0019-L04", "amount": "6000", "reason": "the bill shows Rs 6,000"}
    again = last(sse(decide(client, "CLM-0019", BOB, "edit", edits=[edit])), "review")
    assert again["level"] == "adjudicator"  # an edited worksheet goes back to the desk
    assert again["worksheet_hash"] != first["worksheet_hash"]
    line = next(x for x in again["worksheet"]["lines"] if x["line_id"] == "CLM-0019-L04")
    assert Decimal(line["claimed"]) == Decimal("6000")
    case = get(client, "CLM-0019")
    assert (case["approvals"], case["edits"]) == ([], 1)

    sse(decide(client, "CLM-0019", ALICE))
    done = last(sse(decide(client, "CLM-0019", BOB)), "done")
    assert done["status"] == "settled"
    assert done["settlement"]["worksheet_hash"] == again["worksheet_hash"]


def test_a_review_needs_its_level_and_the_senior_is_another_person(client):
    sse(start(client, "CLM-0019"))
    assert decide(client, "CLM-0019", BOB).status_code == 403  # adjudicator review, senior key
    sse(decide(client, "CLM-0019", ALICE))
    assert decide(client, "CLM-0019", ALICE).status_code == 403  # senior review, adjudicator key
    same_person = decide(client, "CLM-0019", ALICE_SENIOR)
    assert same_person.status_code == 403
    assert "four eyes" in same_person.json()["detail"]
    assert last(sse(decide(client, "CLM-0019", BOB)), "done")["status"] == "settled"


def test_reject_ends_the_claim(client):
    sse(start(client, "CLM-0006"))
    done = last(sse(decide(client, "CLM-0006", ALICE, "reject", note="ask for the bill")), "done")
    assert (done["status"], done["settlement"]) == ("rejected", None)
    assert get(client, "CLM-0006")["status"] == "rejected"


def test_a_claim_ruled_not_admissible_is_repudiated(client):
    events = sse(start(client, "CLM-0001"))
    assert "worksheet" not in [name for name, _ in events]  # its Rs 0 sheet is not shown
    review = last(events, "review")
    assert (review["kind"], review["worksheet"]) == ("repudiation", None)
    assert get(client, "CLM-0001")["worksheet"] is None

    done = last(sse(decide(client, "CLM-0001", ALICE)), "done")
    assert done["status"] == "repudiated"
    assert done["settlement"] == {"status": "repudiated", "claim_id": "CLM-0001"}


def test_a_not_admissible_claim_lists_its_lines_and_an_edit_overrides_the_ruling(client):
    sse(start(client, "CLM-0001"))
    case = get(client, "CLM-0001")
    assert case["worksheet"] is None  # its Rs 0 sheet stays hidden (ADR-0010)
    ids = case["line_ids"]
    assert ids and all(re.fullmatch(r"CLM-0001-L\d+", i) for i in ids)  # ids only, no bill text

    edit = {"line_id": ids[0], "clause_id": HOSPITALISATION, "reason": "the stay is covered"}
    again = last(sse(decide(client, "CLM-0001", ALICE, "edit", edits=[edit])), "review")
    assert (again["kind"], again["level"]) == ("worksheet", "adjudicator")
    case = get(client, "CLM-0001")
    assert case["worksheet"] is not None and case["edits"] == 1
    assert case["line_ids"] == ids


def test_an_injected_note_is_flagged_for_the_reviewer(client):
    review = last(sse(start(client, "CLM-9001")), "review")
    assert any("prompt injection" in flag for flag in review["fraud_flags"])


def test_the_same_bill_sent_again_is_a_duplicate(client):
    sse(start(client, "CLM-0004"))
    sse(decide(client, "CLM-0004", ALICE))
    review = last(sse(start(client, "CLM-0004", case_id="CLM-0004-again")), "review")
    assert any("duplicate claim id CLM-0004" in flag for flag in review["fraud_flags"])
    assert any("duplicate bill lines already claimed" in flag for flag in review["fraud_flags"])


def test_an_intake_packet_is_accepted(client):
    packet = demo.demo_packet("CLM-0004")
    fields = ("claim_id", "policy_number", "documents", "claim", "fixture_policy")
    body = {key: packet[key] for key in fields}
    response = client.post("/claims", headers=auth(ALICE), json=body, params={"case_id": "in-1"})
    assert last(sse(response), "review")["claim_id"] == "CLM-0004"
    assert get(client, "in-1")["claim_id"] == "CLM-0004"

    other = {**body, "claim_id": "CLM-0005"}  # the packet and its claim disagree
    assert client.post("/claims", headers=auth(ALICE), json=other).status_code == 422
    no_claim = {"claim_id": "X-1", "documents": {"bill": "text"}}  # stub mode reads no documents
    assert client.post("/claims", headers=auth(ALICE), json=no_claim).status_code == 422


def test_refusals(client):
    sse(start(client, "CLM-0004"))
    assert start(client, "CLM-0004").status_code == 409  # the case exists
    assert start(client, "CLM-9999").status_code == 404  # no such synthetic claim
    assert client.get("/claims/nope", headers=auth(ALICE)).status_code == 404
    assert decide(client, "nope", ALICE).status_code == 404
    assert start(client, "CLM-0006", case_id="-bad").status_code == 422
    assert decide(client, "CLM-0004", ALICE, "edit").status_code == 422  # an edit without edits
    bad_edit = [{"line_id": "CLM-0004-L01", "amount": "-1", "reason": "x"}]
    assert decide(client, "CLM-0004", ALICE, "edit", edits=bad_edit).status_code == 422
    with client.app.state.cases._case_lock("CLM-0004"):  # a run of this case in progress
        assert decide(client, "CLM-0004", ALICE).status_code == 409


def test_no_diagnosis_or_bill_text_leaves_the_api(client):
    """Rule 4: the packet stays in the checkpoint; responses hold ids, amounts and clauses."""
    for claim_id in ("CLM-0004", "CLM-0001"):
        claim = demo.demo_packet(claim_id)["claim"]
        private = [claim["diagnosis"], *(line["description"] for line in claim["bill_lines"])]
        bodies = [
            start(client, claim_id).text,
            client.get(f"/claims/{claim_id}", headers=auth(ALICE)).text,
            decide(client, claim_id, ALICE).text,
            client.get(f"/claims/{claim_id}", headers=auth(ALICE)).text,
        ]
        for body in bodies:
            for text in private:
                assert text not in body, f"{claim_id}: {text!r} reached a response"


def test_a_case_survives_a_restart(tmp_path):
    path = str(tmp_path / "cases.sqlite")
    before = make_client(checkpoints=path)
    review = last(sse(start(before, "CLM-0004")), "review")

    after = make_client(checkpoints=path)  # a new process reading the same file
    case = get(after, "CLM-0004")
    assert case["status"] == "awaiting_review"
    assert case["review"]["worksheet_hash"] == review["worksheet_hash"]
    assert last(sse(decide(after, "CLM-0004", ALICE)), "done")["status"] == "settled"
    for client in (before, after):
        client.app.state.cases.checkpointer.conn.close()
