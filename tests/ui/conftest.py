"""Case UI tests: the case API app in memory (stub models and tools) behind the UI's client."""

import pytest

from claimsense.ui.client import ApiClient
from tests.api.conftest import make_client


@pytest.fixture(autouse=True)
def _stub_models(monkeypatch):
    """Never a paid model call, even in a terminal that has the key loaded."""
    monkeypatch.setenv("CLAIMSENSE_LLM", "stub")


@pytest.fixture
def api() -> ApiClient:
    return ApiClient(make_client())
