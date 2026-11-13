"""Case API helpers: stub models and tools, checkpoints in memory, four synthetic reviewers."""

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from claimsense.api.auth import parse_reviewers
from claimsense.api.main import create_app
from claimsense.api.runner import Settings

# Test reviewer keys. Alice holds an adjudicator key and a senior key (the four-eyes case).
ALICE = "alice-adjudicator-key"
CAROL = "carol-adjudicator-key"
BOB = "bob-senior-key"
ALICE_SENIOR = "alice-senior-key"
REVIEWERS = (
    f"{ALICE}=alice:adjudicator,{CAROL}=carol:adjudicator,"
    f"{BOB}=bob:senior,{ALICE_SENIOR}=alice:senior"
)


@pytest.fixture(autouse=True)
def _stub_models(monkeypatch):
    """Never a paid model call, even in a terminal that has the key loaded."""
    monkeypatch.setenv("CLAIMSENSE_LLM", "stub")


@pytest.fixture
def client():
    return make_client()


def make_client(checkpoints: str = ":memory:", reviewers: str = REVIEWERS) -> TestClient:
    settings = Settings(checkpoints=checkpoints, reviewers=parse_reviewers(reviewers))
    return TestClient(create_app(settings))


def auth(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


def start(client: TestClient, claim_id: str, key: str = ALICE, **params: str):
    return client.post(f"/demo/claims/{claim_id}", headers=auth(key), params=params)


def decide(client: TestClient, case_id: str, key: str, decision: str = "approve", **body: Any):
    return client.post(
        f"/claims/{case_id}/decision", headers=auth(key), json={"decision": decision, **body}
    )


def get(client: TestClient, case_id: str, key: str = ALICE) -> dict[str, Any]:
    response = client.get(f"/claims/{case_id}", headers=auth(key))
    assert response.status_code == 200, response.text
    return response.json()


def sse(response) -> list[tuple[str, Any]]:
    """The (event, data) pairs of a server-sent-events response."""
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    pairs = []
    for block in response.text.split("\n\n"):
        if block.strip():
            fields = dict(line.split(": ", 1) for line in block.splitlines())
            pairs.append((fields["event"], json.loads(fields["data"])))
    return pairs


def last(pairs: list[tuple[str, Any]], event: str) -> Any:
    found = [data for name, data in pairs if name == event]
    assert found, f"no {event!r} event in {[name for name, _ in pairs]}"
    return found[-1]
