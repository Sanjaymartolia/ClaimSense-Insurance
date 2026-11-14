from fastapi.testclient import TestClient

from claimsense.api.main import app, create_app
from claimsense.api.runner import Settings


def test_health():
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_says_whether_the_agents_are_stubbed_and_which_tools_run(monkeypatch):
    monkeypatch.setenv("CLAIMSENSE_LLM", "stub")
    body = TestClient(create_app(Settings(tools="real"))).get("/health").json()
    assert (body["llm"], body["tools"]) == ("stub", "real")
    monkeypatch.setenv("CLAIMSENSE_LLM", "real")
    assert TestClient(create_app(Settings())).get("/health").json()["llm"] == "real"
