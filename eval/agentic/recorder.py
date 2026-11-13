"""Record every tool call a run makes, without changing the product.

`Team` reads `services.registry()` when it is built, so wrapping the callables on `Services` first
puts this recorder in the real path. The existing `tool_log` is written before a tool runs and has
no arguments or outcome, so it cannot show that a tool raised.

Only identifiers, counts, hashes and rupee totals are kept. Query text, procedure names, diagnoses
and documents never enter a trace (CLAUDE.md rule 4).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

TOOLS = (
    "policy_search",
    "get_clause",
    "calculate",
    "tariff_range",
    "get_policy",
    "claim_history",
    "settle_claim",
    "record_repudiation",
    "record_history",
)


class InjectedFault(RuntimeError):
    """Raised in place of a tool during failure-injection cases."""


def _worksheet_facts(ws: Any) -> dict[str, Any]:
    deductions = sum(len(line.deductions) for line in ws.lines) + (1 if ws.co_pay else 0)
    return {
        "claim_id": ws.claim_id,
        "worksheet_hash": ws.content_hash(),
        "total_payable": str(ws.total_payable),
        "n_deductions": deductions,
    }


def _tokens(approvals: list[Any]) -> list[dict[str, str]]:
    return [{"level": str(a.level.value), "hash": a.worksheet_hash} for a in approvals]


def _arg_facts(tool: str, args: tuple, kw: dict[str, Any]) -> dict[str, Any]:
    if tool == "calculate":
        return {
            "claim_id": kw["claim"].claim_id,
            "n_choices": len(kw["clause_choices"]),
            "version": kw.get("version"),
            "n_fraud_flags": len(kw.get("fraud_flags") or []),
        }
    if tool == "policy_search":
        return {"category": kw.get("category")}
    if tool == "get_clause":
        return {"clause_id": kw["clause_id"]}
    if tool in ("get_policy", "claim_history"):
        return {"policy_number": kw["policy_number"]}
    if tool == "tariff_range":
        return {"city_tier": kw["city_tier"]}
    if tool == "settle_claim":
        return {
            "claim_id": kw["claim_id"],
            "worksheet_hash": kw["worksheet"].content_hash(),
            "needs_senior": kw["needs_senior"],
            "approvals": _tokens(kw["approvals"]),
        }
    if tool == "record_repudiation":
        return {
            "claim_id": kw["claim_id"],
            "n_reasons": len(kw["reasons"]),
            "approvals": _tokens(kw["approvals"]),
        }
    if tool == "record_history":
        return {"claim_id": args[0].claim_id}
    return {}


def _result_facts(tool: str, result: Any) -> dict[str, Any]:
    if tool == "calculate":
        return _worksheet_facts(result)
    if tool == "policy_search":
        return {"clause_ids": [p.clause.clause_id for p in result]}
    if tool == "get_clause":
        return {"clause_id": result.clause_id if result is not None else None}
    if tool == "settle_claim":
        return {
            "status": result["status"],
            "amount": result["amount"],
            "worksheet_hash": result["worksheet_hash"],
        }
    if tool == "record_repudiation":
        return {"status": result["status"]}
    return {}


class _Log(list):
    """`tool_log` that reports refusals as they happen: a refused call never reaches the wrapper."""

    def __init__(self, on_denied: Callable[[dict], None]):
        super().__init__()
        self._on_denied = on_denied

    def append(self, entry: dict) -> None:
        super().append(entry)
        if not entry.get("allowed"):
            self._on_denied(entry)


class Recorder:
    def __init__(self, fail_on: str | None = None):
        self.events: list[dict[str, Any]] = []
        self.fail_on = fail_on
        self.log = _Log(self._denied)

    def _denied(self, entry: dict) -> None:
        self._add(entry["agent"], entry["tool"], "denied", None, {}, {})

    def _add(self, agent, tool, status, error_type, args, result) -> None:
        self.events.append(
            {
                "seq": len(self.events),
                "agent": agent,
                "tool": tool,
                "status": status,
                "error_type": error_type,
                "args": args,
                "result": result,
            }
        )

    def install(self, services: Any) -> None:
        """Call before `Team(services)`."""
        services.tool_log = self.log
        for name in TOOLS:
            setattr(services, name, self._wrap(name, getattr(services, name)))

    def _wrap(self, tool: str, fn: Callable[..., Any]) -> Callable[..., Any]:
        def call(*args: Any, **kw: Any) -> Any:
            # The belt logs immediately before invoking. record_history bypasses the belt, so it
            # has no agent at all, and that absence is itself recorded.
            agent = None if tool == "record_history" else self.log[-1]["agent"]
            facts = _arg_facts(tool, args, kw)
            try:
                if self.fail_on == tool:
                    raise InjectedFault(tool)
                result = fn(*args, **kw)
            except Exception as exc:
                self._add(agent, tool, "raised", type(exc).__name__, facts, {})
                raise
            self._add(agent, tool, "ok", None, facts, _result_facts(tool, result))
            return result

        call.original = fn  # type: ignore[attr-defined]
        return call
