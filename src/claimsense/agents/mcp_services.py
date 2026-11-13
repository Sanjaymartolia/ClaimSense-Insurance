"""The agents' tools over MCP (L7, L15). Selected with `CLAIMSENSE_TOOLS=mcp` in the case API.

`McpTools` starts the four tool servers (`mcp_servers.SERVERS`) as their own processes over stdio,
opens one session per server with `langchain-mcp-adapters`, loads the servers' tools as LangChain
tools, and keeps them open on one background event loop. `mcp_services(tools)` returns the usual
`Services`: the agents, the tool belt and the hooks see the same callables and contract types as
in process (`real_services()`), so the graph does not change. Every agent tool call goes over the
protocol.

- Pinned at the protocol: at connect, the tools each server advertises (name, description,
  arguments) must match `config/tool_pins.json`, or nothing loads (`hooks.pins.check_mcp_pins`).
- Least privilege: a server gets only the settings it reads (`SERVER_ENV`), on top of the MCP
  SDK's safe base (PATH and the like). No model key reaches a tool server; the approval secret
  goes to claims-db alone.
- A `ToolError` result comes back as the in-process callable behaves: `None` or `[]` where that
  means "not found", `PermissionError` for a refused approval, else an exception naming the tool.
- Calls skip LangChain's callbacks, so no tracer ever receives a claim (rule 4).

Not over MCP: the review gate signs approvals and the memory node writes the claim history
straight into the claims database file (`CLAIMSENSE_CLAIMS_DB`) that the claims-db server reads.
The graph and the servers share that file: one machine, or one shared volume (ADR-0012).
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import json
import os
import sys
import threading
from collections.abc import Iterable, Mapping
from decimal import Decimal
from typing import Any

from claimsense.contracts import ApprovalToken, Claim, Clause, RetrievedPassage, Worksheet

from .services import PastClaim, PolicyInfo, Services

#: Settings each server reads. Nothing else of this process's environment reaches it.
SERVER_ENV = {
    "policy-kb": (
        "CLAIMSENSE_POLICY_EFFECTIVE_DATE",
        "HF_HOME",
        "HF_HUB_OFFLINE",
        "SENTENCE_TRANSFORMERS_HOME",
    ),
    "adjudication-calc": (),
    "tariff": ("CLAIMSENSE_TARIFF_CSV",),
    "claims-db": (
        "CLAIMSENSE_CLAIMS_DB",
        "CLAIMSENSE_APPROVAL_SECRET",
        "CLAIMSENSE_REQUIRE_SIGNED_APPROVAL",
        "CLAIMSENSE_APPROVAL_TTL_SECONDS",
        "CLAIMSENSE_SENIOR_THRESHOLD_INR",
    ),
}
#: Read by every server: where the code and the config are, and UTF-8 on Windows.
SHARED_ENV = ("CLAIMSENSE_SRC", "CLAIMSENSE_REPO", "CLAIMSENSE_CONFIG", "PYTHONUTF8")
START_TIMEOUT = 600.0  # policy-kb opens its index before it answers: about two minutes cold
CALL_TIMEOUT = 120.0
_NOT_FOUND = object()


def stdio_connections(servers: Iterable[str] | None = None) -> dict[str, dict[str, Any]]:
    """One stdio connection per server: this Python, this working directory, its own settings."""
    from claimsense.mcp_servers import SERVERS

    connections = {}
    for name in servers or SERVERS:
        keys = (*SHARED_ENV, *SERVER_ENV[name])
        env = {key: os.environ[key] for key in keys if key in os.environ}
        connections[name] = {
            "transport": "stdio",
            "command": sys.executable,
            "args": ["-m", SERVERS[name]],
            "env": {"FASTMCP_LOG_LEVEL": "WARNING", **env},  # no start-up chatter on stderr
            "cwd": os.getcwd(),
        }
    return connections


class McpTools:
    """Open sessions to the MCP tool servers, and synchronous calls into them from any thread.

    The sessions live in one task on a background event loop, because the MCP client's task
    groups must be entered and left by the same task. Use it as a context manager, or call
    `start()` and `close()`.
    """

    def __init__(
        self,
        connections: Mapping[str, Mapping[str, Any]] | None = None,
        *,
        pins: dict[str, str] | None = None,
        call_timeout: float = CALL_TIMEOUT,
        start_timeout: float = START_TIMEOUT,
    ) -> None:
        self.connections = dict(connections) if connections is not None else stdio_connections()
        self.pins = pins  # None: the reviewed `config/tool_pins.json`
        self.call_timeout = call_timeout
        self.start_timeout = start_timeout
        self._tools: dict[tuple[str, str], Any] = {}
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever, name="claimsense-mcp", daemon=True
        )
        self._stop: asyncio.Event | None = None
        self._held: concurrent.futures.Future[None] | None = None

    def start(self) -> McpTools:
        self._thread.start()
        ready: concurrent.futures.Future[None] = concurrent.futures.Future()
        self._held = asyncio.run_coroutine_threadsafe(self._hold(ready), self._loop)
        try:
            ready.result(timeout=self.start_timeout)
        except BaseException as exc:
            self.close()
            # The MCP client's task groups wrap the cause (a ToolPinError, say) in exception groups.
            while isinstance(exc, BaseExceptionGroup) and len(exc.exceptions) == 1:
                exc = exc.exceptions[0]
            raise exc from None
        return self

    async def _hold(self, ready: concurrent.futures.Future[None]) -> None:
        """Open every session, check its pins, load its tools; keep them open until close()."""
        self._stop = asyncio.Event()
        try:  # everything that can fail, imports too: start() hears of it at once, not at timeout
            from langchain_mcp_adapters.client import MultiServerMCPClient
            from langchain_mcp_adapters.tools import convert_mcp_tool_to_langchain_tool

            from claimsense.hooks.pins import check_mcp_pins

            client = MultiServerMCPClient(self.connections)
            async with contextlib.AsyncExitStack() as stack:
                for server in self.connections:
                    session = await stack.enter_async_context(client.session(server))
                    listed = (await session.list_tools()).tools
                    check_mcp_pins(server, listed, self.pins)  # what it serves, not its source
                    for tool in listed:
                        self._tools[(server, tool.name)] = convert_mcp_tool_to_langchain_tool(
                            session, tool, server_name=server, handle_tool_errors=False
                        )
                ready.set_result(None)
                await self._stop.wait()
        except BaseException as exc:
            if not ready.done():
                ready.set_exception(exc)
            raise
        finally:
            self._tools.clear()

    def call(self, server: str, tool: str, arguments: dict[str, Any]) -> Any:
        """Call one tool; return the JSON value it sent back (None when it sent nothing)."""
        lc_tool = self._tools.get((server, tool))
        if lc_tool is None:
            raise RuntimeError(f"MCP tool {server}/{tool} is not connected")
        # The tool's own coroutine, not ainvoke(): no LangChain callback sees the arguments.
        future = asyncio.run_coroutine_threadsafe(lc_tool.coroutine(**arguments), self._loop)
        try:
            content, _artifact = future.result(timeout=self.call_timeout)
        except TimeoutError:
            future.cancel()
            raise TimeoutError(
                f"MCP tool {server}/{tool} gave no answer in {self.call_timeout:.0f} s"
            ) from None
        except Exception as exc:  # the tool raised, or the server or its session went away
            # The class only: a server's error text can quote the arguments (rule 4).
            raise RuntimeError(f"MCP tool {server}/{tool} failed ({type(exc).__name__})") from exc
        return _json_value(content)

    def close(self) -> None:
        """Close the sessions (each server sees its stdin close and exits), then the loop."""
        held = self._held
        if held is not None and not held.done():
            if self._stop is not None:
                self._loop.call_soon_threadsafe(self._stop.set)
            with contextlib.suppress(Exception):
                try:
                    held.result(timeout=30)
                except TimeoutError:
                    held.cancel()  # still connecting (a start that timed out): stop it
        if self._thread.is_alive():
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=10)
        if not self._thread.is_alive() and not self._loop.is_closed():
            self._loop.close()

    def __enter__(self) -> McpTools:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.close()


def _json_value(content: Any) -> Any:
    """A tool's return value: FastMCP sends it as one text block of JSON, or sends nothing."""
    if isinstance(content, str):
        text = content
    else:
        text = "".join(
            block.get("text", "")
            for block in content or []
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return json.loads(text) if text.strip() else None


def _result(value: Any, tool: str, *, not_found: tuple[str, ...] = ()) -> Any:
    """The tool's value. A ToolError becomes what the in-process tool does: `_NOT_FOUND` for the
    codes that mean "nothing there", PermissionError for a refused approval, else an exception."""
    is_error = isinstance(value, dict) and {"error", "code"} <= value.keys() <= {
        "error",
        "code",
        "retryable",
    }
    if not is_error:
        return value
    code, error = str(value["code"]), str(value["error"])
    if code in not_found:
        return _NOT_FOUND
    if code == "approval_denied":
        raise PermissionError(error)
    if code in ("invalid_input", "invalid_claim"):
        raise ValueError(f"{tool}: {error}")
    raise RuntimeError(f"{tool}: {error} ({code})")


def _dump(value: Any) -> Any:
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else value


def mcp_services(tools: McpTools) -> Services:
    """`Services` whose agent tools go over MCP. Build one per claim run (its tool log is per
    run); `tools` is shared and stays open."""
    from claimsense.mcp_servers import approvals as appr
    from claimsense.mcp_servers import claims_db

    def policy_search(query: str, category: str | None = None, k: int = 5):
        value = _result(
            tools.call(
                "policy-kb", "policy_search", {"query": query, "category": category, "k": k}
            ),
            "policy_search",
            not_found=("no_match",),
        )
        if value is _NOT_FOUND or value is None:
            return []
        return [RetrievedPassage.model_validate(item) for item in value]

    def get_clause(clause_id: str) -> Clause | None:
        value = _result(
            tools.call("policy-kb", "get_clause", {"clause_id": clause_id}),
            "get_clause",
            not_found=("unknown_clause", "empty_clause_id"),
        )
        return None if value is _NOT_FOUND else Clause.model_validate(value)

    def calculate(
        claim: Claim, clause_choices: dict[str, str], version: int = 1, fraud_flags=None, **_
    ) -> Worksheet:
        arguments = {
            "claim": claim.model_dump(mode="json"),
            "clause_choices": dict(clause_choices),
            "version": version,
            "fraud_flags": list(fraud_flags or []),
        }
        value = _result(tools.call("adjudication-calc", "calculate", arguments), "calculate")
        return Worksheet.model_validate(value)

    def tariff_range(procedure: str, city_tier: str) -> tuple[Decimal, Decimal] | None:
        value = _result(
            tools.call(
                "tariff", "tariff_lookup", {"procedure": procedure or "", "city_tier": city_tier}
            ),
            "tariff_lookup",
            not_found=("no_match", "unknown_tier", "empty_procedure"),
        )
        if value is _NOT_FOUND:
            return None
        return Decimal(value["minimum_expected_cost"]), Decimal(value["maximum_expected_cost"])

    def get_policy(policy_number: str) -> PolicyInfo | None:
        value = _result(
            tools.call("claims-db", "get_policy", {"policy_number": policy_number}),
            "get_policy",
            not_found=("unknown_policy",),
        )
        return None if value is _NOT_FOUND else PolicyInfo.model_validate(value)

    def claim_history(policy_number: str) -> list[PastClaim]:
        value = _result(
            tools.call("claims-db", "claim_history", {"policy_number": policy_number}),
            "claim_history",
        )
        return [PastClaim.model_validate(past) for past in value["claims"]]

    def settle_claim(
        claim_id: str, worksheet: Worksheet, approvals: list[ApprovalToken], needs_senior: bool
    ) -> dict[str, Any]:
        arguments = {
            "claim_id": claim_id,
            "worksheet": _dump(worksheet),
            "approvals": [_dump(token) for token in approvals],
            "needs_senior": needs_senior,
        }
        return _result(tools.call("claims-db", "settle_claim", arguments), "settle_claim")

    def record_repudiation(
        claim_id: str, reasons: list[str], approvals: list[ApprovalToken]
    ) -> dict[str, Any]:
        arguments = {
            "claim_id": claim_id,
            "reasons": list(reasons),
            "approvals": [_dump(token) for token in approvals],
        }
        return _result(
            tools.call("claims-db", "record_repudiation", arguments), "record_repudiation"
        )

    return Services(
        policy_search=policy_search,
        get_clause=get_clause,
        calculate=calculate,
        tariff_range=tariff_range,
        get_policy=get_policy,
        claim_history=claim_history,
        settle_claim=settle_claim,
        record_repudiation=record_repudiation,
        record_history=claims_db.record_history,  # the memory node writes the shared DB file
        senior_threshold=appr.senior_threshold_inr(),
    )
