"""The agents' tools over MCP (L7, L15): every server in its own process, every call over stdio.

Three of the four servers start here. policy-kb opens its index before it answers (about two
minutes cold), so the run with all four is opt-in: CLAIMSENSE_MCP_E2E=1 (see the last test).
"""

import json
import os
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("fastmcp")
pytest.importorskip("langchain_mcp_adapters")

from claimsense.agents import CoverageAgent, make_stub_services  # noqa: E402
from claimsense.agents.mcp_services import (  # noqa: E402
    McpTools,
    _result,
    mcp_services,
    stdio_connections,
)
from claimsense.agents.services import real_calculate  # noqa: E402
from claimsense.contracts import ApprovalLevel, Claim  # noqa: E402
from claimsense.hooks.pins import ToolPinError, load_pins  # noqa: E402
from claimsense.mcp_servers import approvals as appr  # noqa: E402
from claimsense.mcp_servers import claims_db, tariff  # noqa: E402
from claimsense.mcp_servers.seed_dev_policies import seed_dev_policies  # noqa: E402
from claimsense.reflexion.cases import packet_from_fixture  # noqa: E402

DEV = Path(__file__).resolve().parents[2] / "eval" / "golden_dev" / "claims.jsonl"
SECRET = "test-only-approval-secret"  # noqa: S105 - signs approvals in a throwaway database


def dev_packets() -> dict[str, dict]:
    lines = DEV.read_text(encoding="utf-8").splitlines()
    packets = [packet_from_fixture(json.loads(line)) for line in lines if line]
    return {packet["claim_id"]: packet for packet in packets}


def claim(claim_id: str) -> Claim:
    return Claim.model_validate(dev_packets()[claim_id]["claim"])


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """calc, tariff and claims-db over stdio, sharing a seeded claims database with this process."""
    path = tmp_path_factory.mktemp("mcp") / "claims.db"
    with pytest.MonkeyPatch.context() as env:
        env.setenv("CLAIMSENSE_CLAIMS_DB", str(path))
        env.setenv("CLAIMSENSE_APPROVAL_SECRET", SECRET)
        env.setenv("CLAIMSENSE_LLM", "stub")
        db = claims_db.ClaimsDatabase(str(path))
        previous = claims_db._DB  # noqa: SLF001
        claims_db.set_db(db)
        seed_dev_policies(db)
        try:
            with McpTools(stdio_connections(["adjudication-calc", "tariff", "claims-db"])) as tools:
                yield SimpleNamespace(tools=tools, services=mcp_services(tools), db=db)
        finally:
            claims_db.set_db(previous)
            db.close()


def test_calculate_over_mcp_is_the_calculator(world):
    coverage = CoverageAgent(make_stub_services())
    for packet in dev_packets().values():
        dev = Claim.model_validate(packet["claim"])
        choices = coverage.choose_clauses(dev)[0]
        assert world.services.calculate(dev, choices, version=3) == real_calculate(
            dev, choices, version=3
        )


def test_tariff_over_mcp_is_the_table(world):
    pairs = [
        ("Appendectomy", "tier_1"),
        ("appendectomy ", "tier_2"),
        ("Cataract surgery", "tier_3"),
    ]
    for procedure, tier in pairs:
        assert world.services.tariff_range(procedure, tier) == tariff.tariff_range(procedure, tier)
    assert world.services.tariff_range("no such procedure", "tier_1") is None
    assert world.services.tariff_range("Appendectomy", "tier_9") is None
    assert world.services.tariff_range(None, "tier_1") is None


def test_policy_and_history_come_from_the_shared_database(world):
    dev = claim("CLM-0004")
    assert world.services.get_policy(dev.policy_number) == claims_db.get_policy(dev.policy_number)
    assert world.services.get_policy("NO-SUCH-POLICY") is None
    world.services.record_history(dev, None)  # written by this process, read by the server
    seen = world.services.claim_history(dev.policy_number)
    assert dev.claim_id in [past.claim_id for past in seen]


def test_settlement_over_mcp_needs_the_signed_approval_for_this_worksheet(world):
    dev = claim("CLM-0006")
    sheet = world.services.calculate(dev, {})
    edited = sheet.model_copy(update={"version": 2})
    approver = appr.DemoIdentityProvider().authenticate(dev.claim_id, ApprovalLevel.ADJUDICATOR)

    def settle(worksheet, tokens):
        return world.services.settle_claim(dev.claim_id, worksheet, tokens, False)

    with pytest.raises(PermissionError):
        settle(sheet, [])
    token = appr.issue_approval(sheet, approver, store=world.db.approval_store)  # signed here
    with pytest.raises(PermissionError):
        settle(edited, [token])  # the approval binds the exact worksheet
    receipt = settle(sheet, [token])  # checked by the server, in its own process
    assert (receipt["status"], Decimal(receipt["amount"])) == ("settled", sheet.total_payable)
    with pytest.raises(PermissionError):
        settle(sheet, [token])  # paid once


def test_a_server_whose_tools_changed_does_not_load():
    pins = {**load_pins(), "tariff/tariff_lookup": "0" * 16}
    with pytest.raises(ToolPinError, match="tariff/tariff_lookup"):
        McpTools(stdio_connections(["tariff"]), pins=pins).start()


def test_each_server_gets_only_the_settings_it_reads(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-not-a-key")
    monkeypatch.setenv("CLAIMSENSE_APPROVAL_SECRET", SECRET)
    monkeypatch.setenv("CLAIMSENSE_TARIFF_CSV", "tariffs.csv")
    envs = {name: c["env"] for name, c in stdio_connections().items()}
    assert set(envs) == {"policy-kb", "adjudication-calc", "tariff", "claims-db"}
    assert not any("OPENROUTER_API_KEY" in env for env in envs.values())
    assert [n for n, env in envs.items() if "CLAIMSENSE_APPROVAL_SECRET" in env] == ["claims-db"]
    assert [n for n, env in envs.items() if "CLAIMSENSE_TARIFF_CSV" in env] == ["tariff"]


def test_a_failed_call_names_the_tool_never_the_server_text():
    async def fail(**_):
        raise RuntimeError("server error quoting the claim: Laparoscopic cholecystectomy")

    tools = McpTools({})
    tools._tools[("policy-kb", "get_clause")] = SimpleNamespace(coroutine=fail)  # noqa: SLF001
    tools._thread.start()  # noqa: SLF001 - the loop alone, no server
    try:
        with pytest.raises(RuntimeError, match="policy-kb/get_clause") as error:
            tools.call("policy-kb", "get_clause", {"clause_id": "x"})
        assert "cholecystectomy" not in str(error.value)
    finally:
        tools.close()


def test_a_start_that_fails_before_connecting_says_why_at_once(monkeypatch):
    # 14 Nov: MCP SDK 2 broke the adapters' import, and start() waited out its timeout instead.
    monkeypatch.setitem(sys.modules, "langchain_mcp_adapters.tools", None)
    with pytest.raises(ImportError):
        McpTools({}, start_timeout=5).start()


def test_a_tool_error_comes_back_as_the_in_process_tool_behaves():
    def error(code: str) -> dict:
        return {"error": "why", "code": code, "retryable": False}

    assert _result({"status": "settled"}, "t") == {"status": "settled"}
    assert _result(error("no_match"), "t", not_found=("no_match",)) is not None
    with pytest.raises(PermissionError, match="why"):
        _result(error("approval_denied"), "t")
    with pytest.raises(ValueError, match="why"):
        _result(error("invalid_input"), "t")
    with pytest.raises(RuntimeError, match="db_error"):
        _result(error("db_error"), "t")


@pytest.mark.skipif(
    os.environ.get("CLAIMSENSE_MCP_E2E") != "1",
    reason="starts policy-kb, which opens the policy index (about 2 min): CLAIMSENSE_MCP_E2E=1",
)
def test_claims_run_the_same_over_mcp_as_in_process(tmp_path, monkeypatch):
    """All four servers: the first review matches the in-process run, then a claim settles."""
    pytest.importorskip("langgraph")
    pytest.importorskip("chromadb")
    from langgraph.types import Command

    from claimsense.agents import Team
    from claimsense.agents.services import real_services
    from claimsense.api.demo import demo_packet
    from claimsense.graph.build import build_graph, memory_checkpointer, production_review_kwargs
    from claimsense.graph.state import initial_state

    monkeypatch.setenv("CLAIMSENSE_CLAIMS_DB", str(tmp_path / "claims.db"))
    monkeypatch.setenv("CLAIMSENSE_APPROVAL_SECRET", SECRET)
    monkeypatch.setenv("CLAIMSENSE_LLM", "stub")
    db = claims_db.ClaimsDatabase(str(tmp_path / "claims.db"))
    previous = claims_db._DB  # noqa: SLF001
    claims_db.set_db(db)
    seed_dev_policies(db)

    def first_review(services, packet):
        app = build_graph(
            Team(services), memory_checkpointer(), tool_hooks=True, **production_review_kwargs()
        )
        cfg = {"configurable": {"thread_id": packet["claim_id"]}}
        for _ in app.stream(initial_state(packet), cfg):
            pass
        return app, cfg, app.get_state(cfg).interrupts[0].value

    try:
        with McpTools() as tools:
            for claim_id in ("CLM-0004", "CLM-0001", "CLM-9001"):
                packet = demo_packet(claim_id)
                _, _, local = first_review(real_services(), packet)
                app, cfg, remote = first_review(mcp_services(tools), packet)
                assert remote == local, claim_id
            app, cfg, _ = first_review(mcp_services(tools), demo_packet("CLM-0004"))
            for _ in app.stream(Command(resume={"decision": "approve", "approver_id": "a1"}), cfg):
                pass
            assert app.get_state(cfg).values["status"] == "settled"
    finally:
        claims_db.set_db(previous)
        db.close()
