"""adjudication-calc MCP server (READ-ONLY). ClaimSense Role 4 (Tools, Control & Security), L7.

One tool, ``calculate``: a claim and the clause chosen for each bill line in, the worksheet out.
It wraps ``agents.services.real_calculate``, the team calculator in ``calc/adjudication.py``, so
there is no second calculator. Every rupee comes from code (rule 1): the caller sends clause ids,
never an amount, and every deduction in the result cites its clause.

Errors come back as a ``ToolError``, never raised to the agent. A claim that does not validate is
reported by the number of failed fields only, never their values: the claim holds health details
(rule 4).

    python -m claimsense.mcp_servers.adjudication_calc     # stdio; needs .[mcp]
"""

from __future__ import annotations

from pydantic import BaseModel, ValidationError

from claimsense.contracts import Claim, Worksheet


class ToolError(BaseModel):
    """Structured error returned at the MCP boundary instead of raising to an agent."""

    error: str
    code: str = "calc_error"
    retryable: bool = False


def _tool_calculate(
    claim: dict,
    clause_choices: dict[str, str],
    version: int = 1,
    fraud_flags: list[str] | None = None,
) -> Worksheet | ToolError:
    """[read] Compute the worksheet for a claim from the clause chosen for each bill line.

    Returns a ``Worksheet``: every amount comes from the team calculator and every deduction cites
    its clause. Returns a ``ToolError`` when the claim or a clause choice is not valid.
    """
    from claimsense.agents.services import real_calculate

    try:
        parsed = Claim.model_validate(claim)
    except ValidationError as exc:
        return ToolError(
            error=f"the claim is not valid ({exc.error_count()} field errors)",
            code="invalid_claim",
        )
    try:
        return real_calculate(parsed, clause_choices, version=version, fraud_flags=fraud_flags)
    except (ValueError, KeyError) as exc:
        return ToolError(error=f"calculation refused ({type(exc).__name__})", code="invalid_input")


def server():
    """The adjudication-calc MCP app. Needs the optional ``[mcp]`` extra (fastmcp)."""
    from fastmcp import FastMCP

    mcp = FastMCP("adjudication-calc")
    mcp.tool(name="calculate")(_tool_calculate)
    return mcp


def main() -> None:
    """Start the adjudication-calc MCP server over stdio."""
    server().run(show_banner=False)


if __name__ == "__main__":
    main()
