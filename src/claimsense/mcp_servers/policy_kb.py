"""policy-kb MCP server (READ-ONLY). Owner: Tools & Security (T16).

Run during development:  python -m claimsense.mcp_servers.policy_kb   (stdio)
Inside Docker use HTTP transport.
Tools return structured errors instead of raising, so an agent never sees a crash.
"""

from pydantic import BaseModel

from claimsense.contracts import Clause, RetrievedPassage


class ToolError(BaseModel):
    error: str
    retryable: bool = False


def search_wording(query: str, k: int = 5) -> list[RetrievedPassage] | ToolError:
    """[read] Hybrid search over policy clauses."""
    return ToolError(error="not implemented (T16): needs retrieval index from T10")


def get_clause(clause_id: str) -> Clause | ToolError:
    """[read] Fetch one clause by id."""
    return ToolError(error="not implemented (T16)")


def main() -> None:
    from fastmcp import FastMCP  # optional dependency: pip install -e ".[mcp]"

    mcp = FastMCP("policy-kb")
    mcp.tool(search_wording)
    mcp.tool(get_clause)
    mcp.run()


if __name__ == "__main__":
    main()
