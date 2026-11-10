"""Memory tests run against the real claims-db store (ADR-0005)."""

import pytest


@pytest.fixture
def db(tmp_path):
    from claimsense.mcp_servers.claims_db import ClaimsDatabase

    store = ClaimsDatabase(str(tmp_path / "claims.db"))
    yield store
    store.close()
