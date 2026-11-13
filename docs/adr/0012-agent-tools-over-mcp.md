# ADR-0012: Agent tools over MCP (stdio servers, pinned at the protocol)

**Status:** proposed (review by Tools & Security and Agents & Orchestration)
**Owner / layers:** Tools & Security (servers), Agents & Orchestration (`agents/mcp_services.py`);
written by Eval & Red-Team in Phase 2b. L7, L15
**Date:** 2026-11-14

## Context
The four tool servers had FastMCP entry points, but the agents imported them as Python modules
(`real_services()`): no code was an MCP client, and `langchain-mcp-adapters` was declared but
never used (rubric D2, "Not 3"). The agents call tools synchronously through `Services`, in an
order fixed in code (`eval/agentic`). Constraints: every rupee from the calculator (rule 1), the
approval bound to the exact worksheet and checked by claims-db (rule 3), no health details in logs
(rule 4), and tool pinning (L15).

## Options considered
- **A. `MultiServerMCPClient.get_tools()` as it comes.** The adapters open a new session, so a new
  server process over stdio, for every call. policy-kb opens its index before it answers (about two
  minutes cold), so every search would pay that. Rejected.
- **B. One open session per server, tools loaded with the adapters, called through `Services`.**
  Chosen. The graph, the agents, the tool belt and the hooks do not change.
- **C. A model chooses the MCP tools (ReAct).** Not now: the fixed tool order is deliberate and is
  what `eval/agentic` checks, and a model choosing tools widens the attack surface.
- **D. Streamable HTTP instead of stdio.** Needed when the servers run in their own containers
  (Phase 4). On one machine stdio needs no ports and no authentication.

## Decision
- `CLAIMSENSE_TOOLS=mcp` in the case API uses `agents/mcp_services.py`. `McpTools` starts the four
  servers (`mcp_servers.SERVERS`) over stdio and keeps one session per server open in one task on a
  background event loop (the MCP client's task groups must be entered and left by one task).
  `mcp_services(tools)` returns the same `Services` callables and contract types as in process.
- A new server, `adjudication-calc`, serves `calculate` by wrapping `real_calculate`: there is no
  second calculator.
- Each server module has `server()` (the app, built without opening data) and `main()` (stdio,
  no banner). Tests and the pin tool list the tools in memory through `server()`.
- **Pins at the protocol.** At connect the client compares what each running server advertises
  (tool name, description, argument schema without titles) with `config/tool_pins.json`, keyed
  `<server>/<tool>`. A difference stops the start. `python -m claimsense.hooks.pins` checks and
  records both the in-process and the MCP pins (the MCP part needs `.[mcp]`).
- **Least privilege.** Each server gets only the settings it reads (`SERVER_ENV`), on top of the
  MCP SDK's safe base (PATH and the like). No model key reaches a tool server; the approval secret
  goes to claims-db alone.
- A `ToolError` comes back as the in-process callable behaves: `None` or `[]` for "not found",
  `PermissionError` for a refused approval, otherwise an exception naming the tool and the code.
- Calls use the tool's coroutine, not `ainvoke`, so no LangChain callback or tracer receives the
  arguments, which hold the whole claim (rule 4).
- **Not over MCP:** the review gate signs approvals and the memory node writes the claim history
  straight into the claims database file (`CLAIMSENSE_CLAIMS_DB`), which the claims-db server reads.

## Consequences
- Parity, from the tests: `calculate` over MCP equals the calculator on every dev claim (worksheet
  and hash, so an approval survives the trip); tariff ranges, policies and history match; a
  settlement over MCP needs the signed approval for the exact worksheet and pays once; a server
  whose tool definition changed is refused. With all four servers (`CLAIMSENSE_MCP_E2E=1`), claims
  reach the same first review as in process, and a claim settles.
- Start-up: the API starts the servers at boot in `mcp` mode; policy-kb takes about two minutes
  cold. A call times out after 120 s.
- The graph process and the claims-db server share one SQLite file: one machine, or one shared
  volume in Docker Compose. HTTP transport and compose services are Deploy & Ops work (Phase 4).
- A FastMCP upgrade that writes schemas differently trips the pin check. Review the change, then
  run `python -m claimsense.hooks.pins --update`.
- fastmcp 4 brings MCP SDK 2, which `langchain-mcp-adapters` does not support yet: 0.3.1 fails on
  import (`mcp.server.fastmcp` is gone) and 0.3.2 requires `mcp<2`. On 14 Nov a fresh
  `.[agents,mcp]` install resolved to fastmcp 4.2.0 with adapters 0.3.1, so the extras now cap
  `fastmcp<4` and require adapters `>=0.3.2`. Under fastmcp 4.2.0 the 8 MCP pins still matched;
  `hooks/pins.py` reads `Tool.inputSchema`, which SDK 2 renames `input_schema`. Lift the cap when
  the adapters support SDK 2, after the MCP tests and the pin check pass.
- CI installs `.[mcp]` in `test` (the MCP tests) and `eval-gate` (the MCP pins).
- The claims-db tools got their first descriptions (`[read]` / `[write]`); the in-process pins did
  not change.
- Open for Tools & Security: make `record_history` a claims-db write tool, so the memory node also
  goes through the protocol.

## Links
`agents/mcp_services.py`, `mcp_servers/adjudication_calc.py`, `hooks/pins.py`;
`tests/orchestration/test_mcp_services.py`, `tests/mcp_servers/test_adjudication_calc.py`,
`tests/security/test_guardrails_l15.py`; `docs/FRAMEWORK_RUBRIC_SCORE.md` (D2).
