"""Reviewer identity for the case API (L14): from a token in the environment, never the body."""

import pytest

from claimsense.api.auth import ApiIdentityProvider, Reviewer, find_reviewer, parse_reviewers
from claimsense.contracts import ApprovalLevel

from .conftest import ALICE, auth, make_client


def test_parse_reviewers():
    reviewers = parse_reviewers(" k1=alice:adjudicator , k2=bob:senior,")
    assert reviewers == {
        "k1": Reviewer("alice", ApprovalLevel.ADJUDICATOR),
        "k2": Reviewer("bob", ApprovalLevel.SENIOR),
    }
    assert parse_reviewers("") == {}


@pytest.mark.parametrize(
    ("spec", "message"),
    [
        ("k1=alice:adjudicator,hidden-key-xyz", "entry 2 is not"),
        ("hidden-key-xyz=alice:boss", "entry 1: level must be"),
        ("=alice:senior", "entry 1 is not"),
        ("hidden-key-xyz=:senior", "entry 1 is not"),
    ],
)
def test_a_bad_entry_names_its_position_never_its_token(spec, message):
    with pytest.raises(ValueError, match=message) as error:
        parse_reviewers(spec)
    assert "hidden-key-xyz" not in str(error.value)


def test_find_reviewer():
    reviewers = parse_reviewers("k1=alice:adjudicator")
    assert find_reviewer(reviewers, "k1") == Reviewer("alice", ApprovalLevel.ADJUDICATOR)
    assert find_reviewer(reviewers, "k2") is None
    assert find_reviewer(reviewers, "") is None


def test_identity_comes_from_the_token_and_holds_only_its_level():
    provider = ApiIdentityProvider(Reviewer("bob", ApprovalLevel.SENIOR))
    who = provider.authenticate("CLM-1", ApprovalLevel.SENIOR)
    assert (who.approver_id, who.level, who.auth_source) == (
        "bob",
        ApprovalLevel.SENIOR,
        "api-token",
    )
    with pytest.raises(PermissionError):
        provider.authenticate("CLM-1", ApprovalLevel.ADJUDICATOR)


def test_case_routes_need_a_reviewer_token():
    client = make_client()
    response = client.get("/demo/claims")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert client.get("/demo/claims", headers=auth("wrong-key")).status_code == 401
    assert client.get("/claims/CLM-0004").status_code == 401
    assert client.post("/claims/CLM-0004/decision", json={"decision": "approve"}).status_code == 401
    listed = client.get("/demo/claims", headers=auth(ALICE))
    assert listed.status_code == 200
    claims = listed.json()["claims"]
    assert {"claim_id": "CLM-0004", "source": "golden_dev"} in claims
    assert {"claim_id": "CLM-9001", "source": "redteam"} in claims


def test_no_reviewers_configured_closes_the_case_routes():
    client = make_client(reviewers="")
    assert client.get("/demo/claims", headers=auth(ALICE)).status_code == 503


def test_health_and_metrics_stay_open():
    client = make_client(reviewers="")
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/metrics/").status_code == 200
