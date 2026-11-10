"""Memory tests run against the real claims-db store (ADR-0005)."""

import sys
from pathlib import Path

import pytest

# claims_db_server.py does `import approval_security` as a top-level module, so it doesn't import as
# a package module. Delete this once it uses `from claimsense.mcp_servers import approval_security`.
_MCP_SERVERS = Path(__file__).resolve().parents[2] / "src" / "claimsense" / "mcp_servers"
if str(_MCP_SERVERS) not in sys.path:
    sys.path.insert(0, str(_MCP_SERVERS))


@pytest.fixture
def db(tmp_path):
    from claimsense.mcp_servers.claims_db_server import ClaimsDatabase

    store = ClaimsDatabase(str(tmp_path / "claims.db"))
    yield store
    store.close()
