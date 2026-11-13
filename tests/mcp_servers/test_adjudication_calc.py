"""adjudication-calc MCP server: the team calculator over MCP, nothing computed twice (rule 1)."""

import asyncio
import json
from pathlib import Path

import pytest

pytest.importorskip("fastmcp")

from fastmcp import Client  # noqa: E402

from claimsense.agents import CoverageAgent, make_stub_services  # noqa: E402
from claimsense.agents.services import real_calculate  # noqa: E402
from claimsense.contracts import Claim, Worksheet  # noqa: E402
from claimsense.mcp_servers import adjudication_calc  # noqa: E402
from claimsense.reflexion.cases import packet_from_fixture  # noqa: E402

DEV = Path(__file__).resolve().parents[2] / "eval" / "golden_dev" / "claims.jsonl"


def dev_claims() -> list[Claim]:
    lines = DEV.read_text(encoding="utf-8").splitlines()
    return [Claim.model_validate(packet_from_fixture(json.loads(x))["claim"]) for x in lines if x]


def calls(arguments: list[dict]) -> list:
    """Each call's result, over one in-memory MCP session."""

    async def run() -> list:
        async with Client(adjudication_calc.server()) as client:
            return [await client.call_tool_mcp("calculate", a) for a in arguments]

    return asyncio.run(run())


def value(result) -> dict:
    assert not result.isError
    return json.loads(result.content[0].text)


def test_the_server_offers_one_read_tool():
    async def listing():
        async with Client(adjudication_calc.server()) as client:
            return await client.list_tools()

    tools = asyncio.run(listing())
    assert [tool.name for tool in tools] == ["calculate"]
    assert tools[0].description.startswith("[read]")


def test_every_dev_claim_gets_the_calculators_worksheet(monkeypatch):
    monkeypatch.setenv("CLAIMSENSE_LLM", "stub")
    coverage = CoverageAgent(make_stub_services())
    claims = dev_claims()
    choices = [coverage.choose_clauses(claim)[0] for claim in claims]
    results = calls(
        [
            {
                "claim": c.model_dump(mode="json"),
                "clause_choices": ch,
                "version": 2,
                "fraud_flags": ["f"],
            }
            for c, ch in zip(claims, choices, strict=True)
        ]
    )
    assert len(results) == len(claims) >= 20
    for claim, chosen, result in zip(claims, choices, results, strict=True):
        sheet = Worksheet.model_validate(value(result))
        expected = real_calculate(claim, chosen, version=2, fraud_flags=["f"])
        assert sheet == expected
        assert sheet.content_hash() == expected.content_hash()  # an approval survives the trip


def test_a_claim_that_does_not_validate_is_refused_without_its_text():
    claim = dev_claims()[0].model_dump(mode="json")
    claim["bill_total"] = "not money"
    error = value(calls([{"claim": claim, "clause_choices": {}}])[0])
    assert error["code"] == "invalid_claim"
    assert claim["diagnosis"] not in error["error"]
    assert "not money" not in error["error"]


def test_a_claim_the_calculator_refuses_is_a_tool_error_not_a_crash():
    claim = dev_claims()[0].model_dump(mode="json")
    claim["bill_lines"][1]["line_id"] = claim["bill_lines"][0]["line_id"]  # one id twice
    error = value(calls([{"claim": claim, "clause_choices": {}}])[0])
    assert (error["code"], error["error"]) == ("invalid_input", "calculation refused (ValueError)")
