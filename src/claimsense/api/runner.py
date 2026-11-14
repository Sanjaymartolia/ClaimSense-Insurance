"""Runs claims for the case API: one LangGraph run per request, streamed as events (L8, L14, L16).

A request starts a claim or answers its pending review. The graph then runs until the next review
pause (``interrupt()``) or the end, and every node's update becomes an event as it happens. The
SQLite checkpointer keeps each case across requests and restarts (thread id = case id).

Each run gets its own ``Team`` and compiled graph (the build docstring asks for one Team per
running claim), its own hook audit log (for the tool metrics), and the requesting reviewer as the
review gate's identity. One lock per case stops two runs of the same case at once. As after a
process restart, a resumed run gets a fresh tool budget (``graph/nodes.py::Nodes``).

Rubric D3: every run has a run id (the first event, every tool's audit record, ``run.start`` and
``run.end`` in the audit sink of ``api/audit.py``) and, when ``CLAIMSENSE_OTEL`` asks for it, one
trace: a ``claim.run`` span with a child per graph node and per tool call (``claimsense.tracing``).

Rule 4: events and summaries carry the plan, trace lines, the worksheet and the review payload,
which by design hold ids, amounts, clauses and flags. The packet (documents, diagnosis, bill
descriptions) stays in the checkpoint and is never sent or logged.
"""

from __future__ import annotations

import contextlib
import logging
import os
import threading
import time
import uuid
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from claimsense import __version__

from . import audit as audit_sink
from . import metrics
from .auth import ApiIdentityProvider, Reviewer, parse_reviewers

log = logging.getLogger("claimsense.api")

TOOLS = ("stub", "real", "mcp")
Event = dict[str, Any]


@dataclass(frozen=True)
class Settings:
    """`stub` tools: in-process stand-ins fed by the packet's policy record (dev and demo).
    `real`: the tool servers' code in this process (`real_services()`). `mcp`: the same servers as
    their own processes, every call over the MCP protocol (`agents/mcp_services.py`). Both use the
    signed approval store of the claims database."""

    tools: str = "stub"
    checkpoints: str = "claimsense_checkpoints.sqlite"
    reviewers: Mapping[str, Reviewer] = field(default_factory=dict)
    audit_log: str = ""  # a JSON-lines file for the audit trail (api/audit.py); empty: none
    otel: str = ""  # "otlp" or "console" turns tracing on (claimsense.tracing); empty: off

    def __post_init__(self) -> None:
        if self.tools not in TOOLS:
            raise ValueError(f"CLAIMSENSE_TOOLS must be one of {TOOLS}, not {self.tools!r}")

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            tools=os.environ.get("CLAIMSENSE_TOOLS", "stub"),
            checkpoints=os.environ.get("CLAIMSENSE_CHECKPOINTS", "claimsense_checkpoints.sqlite"),
            reviewers=parse_reviewers(os.environ.get("CLAIMSENSE_REVIEWERS", "")),
            audit_log=os.environ.get("CLAIMSENSE_AUDIT_LOG", ""),
            otel=os.environ.get("CLAIMSENSE_OTEL", ""),
        )


def config(case_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": case_id}, "recursion_limit": 60}


def error_event(name: str) -> Event:
    """An error names its class or condition only: messages can quote claim data."""
    return {"event": "error", "data": {"error": name}}


def _admissible(values: Mapping[str, Any]) -> bool:
    return getattr(values.get("admissibility"), "admissible", True)


class CaseService:
    def __init__(self, settings: Settings, tracer_provider: Any = None) -> None:
        from claimsense.agents import make_stub_services
        from claimsense.graph.build import sqlite_checkpointer  # needs the `agents` extra
        from claimsense.mcp_servers.approvals import InMemoryApprovalStore

        self.settings = settings
        self.mcp: Any = None
        if settings.tools == "mcp":  # one set of server processes for every claim run
            from claimsense.agents.mcp_services import McpTools

            log.info("starting the MCP tool servers (policy-kb opens its index first)")
            self.mcp = McpTools().start()
        self.checkpointer = sqlite_checkpointer(settings.checkpoints)
        # Stub tools only: what the claims database keeps across claims, for this process. Decided
        # claims join this history, so a bill sent again is flagged as a duplicate (demo scene 2).
        self.stub_approvals = InMemoryApprovalStore()
        self.stub_history = make_stub_services()
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        self._reader: Any = None
        # Tracing (rubric D3): a provider given here (tests), or one CLAIMSENSE_OTEL asks for.
        self._own_provider = None if tracer_provider else _tracer_provider(settings.otel)
        provider = tracer_provider or self._own_provider
        self.tracer: Any = provider.get_tracer("claimsense.api") if provider else None

    # ------------------------------------------------------------------ reading
    def exists(self, case_id: str) -> bool:
        return self.snapshot(case_id).created_at is not None

    def snapshot(self, case_id: str) -> Any:
        # Read through a compiled graph, never the bare checkpointer: compiling gives the reader
        # the checkpoint types `ClaimState` names, which LangGraph's strict msgpack mode requires.
        if self._reader is None:
            from claimsense.agents import Team, make_stub_services
            from claimsense.graph.build import build_graph

            self._reader = build_graph(Team(make_stub_services()), self.checkpointer)
        return self._reader.get_state(config(case_id))

    def pending_review(self, case_id: str) -> dict[str, Any] | None:
        interrupts = self.snapshot(case_id).interrupts
        return interrupts[0].value if interrupts else None

    def approved_by(self, case_id: str, approver_id: str) -> bool:
        tokens = self.snapshot(case_id).values.get("approvals") or []
        return any(token.approver_id == approver_id for token in tokens)

    def busy(self, case_id: str) -> bool:
        lock = self._locks.get(case_id)
        return bool(lock is not None and lock.locked())

    def summary(self, case_id: str) -> dict[str, Any]:
        return summarize(case_id, self.snapshot(case_id))

    def close(self) -> None:
        if self.mcp is not None:
            self.mcp.close()
        if self._own_provider is not None:
            self._own_provider.shutdown()  # sends the spans still in the batch
        self.checkpointer.conn.close()

    # ------------------------------------------------------------------ running
    def start(self, case_id: str, packet: dict[str, Any], reviewer: Reviewer) -> Iterator[Event]:
        from claimsense.graph.state import initial_state

        with self._case_lock(case_id) as free:
            if not free:
                yield error_event("CaseBusy")
                return
            if self.exists(case_id):
                yield error_event("CaseExists")
                return
            yield from self._segment(
                case_id, initial_state(packet), packet, reviewer, kind="start", first=True
            )

    def decide(self, case_id: str, decision: dict[str, Any], reviewer: Reviewer) -> Iterator[Event]:
        from langgraph.types import Command

        with self._case_lock(case_id) as free:
            if not free:
                yield error_event("CaseBusy")
                return
            snapshot = self.snapshot(case_id)
            if not snapshot.interrupts:
                yield error_event("NoDecisionPending")
                return
            values = snapshot.values
            yield from self._segment(
                case_id,
                Command(resume=decision),
                values.get("packet") or {},
                reviewer,
                kind="decision",
                decision=decision.get("decision"),
                admissible=_admissible(values),
            )

    @contextlib.contextmanager
    def _case_lock(self, case_id: str) -> Iterator[bool]:
        with self._locks_guard:
            lock = self._locks.setdefault(case_id, threading.Lock())
        free = lock.acquire(blocking=False)
        try:
            yield free
        finally:
            if free:
                lock.release()

    def _segment(
        self,
        case_id: str,
        graph_input: Any,
        packet: dict[str, Any],
        reviewer: Reviewer,
        *,
        kind: str,
        decision: str | None = None,
        first: bool = False,
        admissible: bool = True,
    ) -> Iterator[Event]:
        from claimsense.agents.llm import stub_mode
        from claimsense.hooks.hooks import AuditLog

        run_id = uuid.uuid4().hex  # this run, apart from every other run of the same claim
        run = {
            "run_id": run_id,
            "case_id": case_id,
            "claim_id": packet.get("claim_id"),
            "kind": kind,
            "decision": decision,
            "approver_id": reviewer.approver_id,  # from the token; the token itself never
            "level": reviewer.level.value,
        }
        audit_sink.run_event("run.start", **run)
        yield {"event": "run", "data": {"run_id": run_id, "case_id": case_id, "kind": kind}}
        spans = _RunSpans(self.tracer, run) if self.tracer is not None else None

        audit = AuditLog(run_id=run_id)
        app = self._graph(packet, reviewer, audit)
        cfg = config(case_id)
        started = time.monotonic()
        failed: Exception | None = None
        metrics.IN_FLIGHT.inc()
        try:
            with metrics.llm_usage(not stub_mode()):
                stream = app.stream(graph_input, cfg, stream_mode="updates")
                for event in events(stream, admissible):
                    if spans is not None and event["event"] == "step":
                        spans.node(event["data"]["node"])
                    yield event
        except Exception as exc:  # noqa: BLE001 - an event for the client, never a crash
            failed = exc
        finally:
            metrics.IN_FLIGHT.dec()
            metrics.record_tool_calls(audit.records)

        state = app.get_state(cfg)
        values = state.values
        if failed is not None:
            outcome = type(failed).__name__
        elif state.interrupts:
            outcome = "awaiting_review"
        else:
            outcome = str(values.get("status"))
        audit_sink.run_event(
            "run.end",
            **run,
            status=outcome,
            worksheet_hash=_worksheet_hash(state),
            tool_calls=len(audit.records),
        )
        if spans is not None:
            spans.finish(audit.records, outcome, failed)
        if first:
            metrics.record_first_segment(values, time.monotonic() - started, failed is not None)
        if failed is not None:
            metrics.record_outcome(values, "error", packet.get("received_at"))
            log.warning("case %s stopped: %s", case_id, type(failed).__name__)
            yield error_event(type(failed).__name__)
            return
        if state.interrupts:
            return  # paused for review: the `review` event is already sent
        status = values.get("status")
        metrics.record_outcome(values, status, packet.get("received_at"))
        yield {
            "event": "done",
            "data": {
                "status": status,
                "settlement": values.get("settlement"),
                "letter": values.get("letter"),
            },
        }

    def _graph(self, packet: dict[str, Any], reviewer: Reviewer, audit: Any) -> Any:
        from claimsense.agents import Team
        from claimsense.graph.build import build_graph, production_review_kwargs

        identity = ApiIdentityProvider(reviewer)
        review = (
            production_review_kwargs(identity)  # signs into the store settle_claim verifies
            if self.settings.tools != "stub"
            else {"identity_provider": identity, "approval_store": self.stub_approvals}
        )
        return build_graph(
            Team(self._services(packet)),
            self.checkpointer,
            tool_hooks=True,
            hook_options={"audit": audit},
            **review,
        )

    def _services(self, packet: dict[str, Any]) -> Any:
        if self.settings.tools == "mcp":
            from claimsense.agents.mcp_services import mcp_services

            return mcp_services(self.mcp)
        if self.settings.tools == "real":
            from claimsense.agents.services import real_services

            return real_services()

        from claimsense.agents import PastClaim, PolicyInfo, make_stub_services
        from claimsense.agents.services import real_calculate

        raw_policy = packet.get("fixture_policy")
        policy = PolicyInfo.model_validate(raw_policy) if raw_policy else None
        number = (
            policy.policy_number if policy else (packet.get("claim") or {}).get("policy_number")
        )
        history = [PastClaim.model_validate(h) for h in packet.get("fixture_history") or []]
        if number:
            history += self.stub_history.claim_history(number)
        services = make_stub_services(
            policies={policy.policy_number: policy} if policy else None,
            history={number: history} if number and history else None,
        )
        services.calculate = real_calculate  # the product calculator, as the CI eval gate runs it
        services.record_history = self.stub_history.record_history
        return services


# ---------------------------------------------------------------------- views
def plan_view(plan: Any) -> dict[str, Any]:
    from claimsense.graph import planner

    return {
        "revision": plan.revision,
        "steps": [
            {"name": s.name, "agent": getattr(s.agent, "value", s.agent), "status": s.status}
            for s in plan.steps
        ],
        "text": planner.render(plan),
    }


def events(stream: Iterable[dict[str, Any]], admissible: bool = True) -> Iterator[Event]:
    """LangGraph `updates` chunks -> events. While the claim is ruled not admissible its worksheet
    (the calculator's Rs 0, ADR-0010) is not shown, as the repudiation review does not show it."""
    for chunk in stream:
        for node, update in chunk.items():
            if node == "__interrupt__":
                yield {"event": "review", "data": update[0].value}
                continue
            update = update if isinstance(update, dict) else {}
            admissible = _admissible(update) if "admissibility" in update else admissible
            if update.get("plan") is not None:
                yield {"event": "plan", "data": plan_view(update["plan"])}
            trace = list(update.get("trace") or [])
            yield {"event": "step", "data": {"node": node, "trace": trace}}
            if update.get("worksheet") is not None and admissible:
                yield {"event": "worksheet", "data": update["worksheet"].model_dump(mode="json")}


def summarize(case_id: str, snapshot: Any) -> dict[str, Any]:
    values = snapshot.values
    review = snapshot.interrupts[0].value if snapshot.interrupts else None
    worksheet = values.get("worksheet")
    plan = values.get("plan")
    return {
        "case_id": case_id,
        "claim_id": values.get("claim_id"),
        "status": "awaiting_review" if review else values.get("status"),
        "review": review,
        "plan": plan_view(plan) if plan is not None else None,
        "worksheet": worksheet.model_dump(mode="json")
        if worksheet is not None and _admissible(values)
        else None,
        "fraud_flags": list(values.get("fraud_flags") or []),
        "approvals": [
            {
                "level": t.level.value,
                "approver_id": t.approver_id,
                "decided_at": t.decided_at.isoformat(),
            }
            for t in values.get("approvals") or []
        ],
        "edits": len(values.get("edit_log") or []),
        "settlement": values.get("settlement"),
        "letter": values.get("letter"),
        "trace": list(values.get("trace") or []),
    }


# ---------------------------------------------------------------------- audit and tracing (D3)
def _worksheet_hash(snapshot: Any) -> str | None:
    """The worksheet the run ended on: the pending review's, else the settled one's."""
    if snapshot.interrupts:
        return (snapshot.interrupts[0].value or {}).get("worksheet_hash")
    settlement = snapshot.values.get("settlement") or {}
    if isinstance(settlement, dict) and settlement.get("worksheet_hash"):
        return str(settlement["worksheet_hash"])
    sheet = snapshot.values.get("worksheet")
    return sheet.content_hash() if hasattr(sheet, "content_hash") else None


def _tracer_provider(mode: str) -> Any:
    """The provider `CLAIMSENSE_OTEL` asks for; None if off, unknown, or no observability extra."""
    if not mode:
        return None
    try:
        from claimsense import tracing
    except ImportError:
        log.warning("CLAIMSENSE_OTEL=%s needs the observability extra: tracing is off", mode)
        return None
    exporter = tracing.exporter_for(mode)
    if exporter is None:
        log.warning("CLAIMSENSE_OTEL=%s is neither otlp nor console: tracing is off", mode)
        return None
    return tracing.provider(exporter, simple=mode == "console", version=__version__)


def _ns(timestamp: str) -> int:
    return int(datetime.fromisoformat(timestamp).timestamp() * 1_000_000_000)


class _RunSpans:
    """One claim run as one trace: a root `claim.run`, a child per graph node as its update
    arrives, and a child per tool call from the hooks' audit records. Only `claimsense.*`
    attributes from content-free values (ids, names, statuses); the exporter redacts anyway."""

    def __init__(self, tracer: Any, run: Mapping[str, Any]) -> None:
        from opentelemetry import trace

        self._trace = trace
        self.tracer = tracer
        self.run_id = run["run_id"]
        keys = ("run_id", "case_id", "claim_id", "kind", "decision", "level")
        attributes = {f"claimsense.{k}": run[k] for k in keys if run.get(k) is not None}
        self.root = tracer.start_span("claim.run", attributes=attributes)
        self.context = trace.set_span_in_context(self.root)
        self.last = time.time_ns()

    def _child(self, name: str, start: int, end: int, **attributes: Any) -> None:
        attrs = {"claimsense.run_id": self.run_id}
        attrs.update({f"claimsense.{k}": v for k, v in attributes.items() if v is not None})
        span = self.tracer.start_span(
            name, context=self.context, start_time=start, attributes=attrs
        )
        span.end(end_time=end)

    def node(self, name: str) -> None:
        """A node's update arrived: its span runs from the previous update to now."""
        now = time.time_ns()
        self._child(f"node {name}", self.last, now, node=name)
        self.last = now

    def finish(self, records: Iterable[Any], status: str, failed: Exception | None) -> None:
        for rec in records:
            end = _ns(rec.timestamp)
            start = end - int((rec.duration_ms or 0) * 1_000_000)
            self._child(
                f"tool {rec.tool}",
                start,
                end,
                tool=rec.tool,
                agent=rec.agent,
                tool_status=rec.status,
                allowed=rec.allowed,
            )
        self.root.set_attribute("claimsense.status", status)
        if failed is not None:  # the class only: a message can quote claim text
            error = self._trace.Status(self._trace.StatusCode.ERROR, type(failed).__name__)
            self.root.set_status(error)
        self.root.end()
