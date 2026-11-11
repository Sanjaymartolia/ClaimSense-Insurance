"""L13 section 1: the agent under test, and a trace for every run.

A **trace** is the record of one claim. A **span** is one step inside it:

    node       one graph node (plan, extract, admissibility, coverage, fraud, critic, ...)
    tool       one tool call through an agent's ToolBelt, with its arguments, result, time, and
               whether it failed or the ACL refused it
    llm        one model call, with tokens and cost (only when a real model runs)
    guardrail  the optional input guardrail in front of the graph (section 5.1)

LangSmith, Langfuse and OpenTelemetry store the same shape (L14), so a trace written here can be
exported later without changing the metrics. Every metric in this package is computed from traces.

How it is recorded without touching `src/`:

- `TracedRunner` subclasses `graph.local.LocalRunner` and times every node it runs. It is the same
  topology and the same nodes the `claimsense` harness adapter uses.
- `instrument_services` wraps each callable on the per-claim `Services` object. `ToolBelt` logs the
  calling agent just before it calls the tool, so `_ToolLogTap` (the tool log, as a list subclass)
  tells the wrapper which agent made each call, and records ACL refusals, which never reach a tool.
- Model calls are collected with LangChain's `collect_runs` while each node runs, so they need no
  callback wiring in the agents. In stub mode there are no model calls and no llm spans.
- `run_traced(observer=...)` lets another package watch each step *while it runs* (`Observer`).
  `eval.observability` uses it to open an OpenTelemetry span around every node, tool call,
  guardrail check and human review. With no observer nothing changes.

Rule 4 (no health details in logs): span arguments are redacted to their shape. Only ids that carry
no health detail (`clause_id`, `category`, `version`, ...) are kept verbatim; free text such as a
search query (a bill-line description) is recorded as `<text N chars>`. `Trace.to_dict()` is what
gets written to disk and holds no claim text.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import asdict, dataclass, field
from functools import cache
from typing import Any, Protocol

from eval.harness.claimsense_adapter import ClaimSenseAdapter, _observed
from eval.harness.models import AgentOutput, EvalCase

#: Every tool on `Services` that an agent or node can reach. `record_history` is called by the
#: `memory_update` node directly, not through a ToolBelt, so it carries no agent.
TOOL_NAMES: tuple[str, ...] = (
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

#: Tools that move money or write a decision. None may execute during evaluation (rule 3).
FORBIDDEN_TOOLS: frozenset[str] = frozenset({"settle_claim", "record_repudiation"})

#: Argument names whose values are ids with no health detail, so they are kept verbatim.
SAFE_ARG_KEYS: frozenset[str] = frozenset({"clause_id", "category", "city_tier", "version", "k"})


# ------------------------------------------------------------------------------------ records
@dataclass
class Span:
    kind: str  # node | tool | llm | guardrail
    name: str  # node name, tool name, or model id
    node: str = ""  # the graph node a tool or llm span ran inside
    agent: str = ""  # the agent whose ToolBelt made the call ("" = called by the node itself)
    ms: float = 0.0
    status: str = "ok"  # ok | error | blocked
    args: dict = field(default_factory=dict)  # redacted
    args_key: str = ""  # hash of the full arguments, to find exact repeats
    output: str = ""  # redacted summary of the result, or the error
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = 0.0

    @property
    def ok(self) -> bool:
        return self.status == "ok"


@dataclass
class Trace:
    claim_id: str
    split: str
    variant: str = "v1"
    mode: str = "stub"  # stub | llm
    spans: list[Span] = field(default_factory=list)
    #: pipeline end status (`rejected` once the eval reviewer declines), or `blocked` / `error`
    status: str = "running"
    route: str | None = None
    settlement_inr: int | None = None
    flags: list[str] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)
    clause_choices: dict[str, str] = field(default_factory=dict)
    admissible: bool | None = None
    critic_passed: bool | None = None
    revisions: int = 0
    escalated: bool = False
    extraction_issues: int = 0
    error: str | None = None
    seconds: float = 0.0
    # In memory only, never written to disk (they can hold claim text):
    review_payloads: list[dict] = field(default_factory=list)
    clause_texts: dict[str, str] = field(default_factory=dict)
    output: AgentOutput | None = None
    # Bookkeeping while the run is live:
    _node: str = ""
    _agent: str = ""

    # -------------------------------------------------------------- views
    @property
    def node_spans(self) -> list[Span]:
        return [s for s in self.spans if s.kind == "node"]

    @property
    def tool_spans(self) -> list[Span]:
        return [s for s in self.spans if s.kind == "tool"]

    @property
    def llm_spans(self) -> list[Span]:
        return [s for s in self.spans if s.kind == "llm"]

    @property
    def path(self) -> list[str]:
        """The nodes in the order they ran."""
        return [s.name for s in self.node_spans]

    @property
    def llm_calls(self) -> int:
        return len(self.llm_spans)

    @property
    def tokens(self) -> int:
        return sum(s.tokens_in + s.tokens_out for s in self.llm_spans)

    @property
    def cost(self) -> float:
        return sum(s.cost for s in self.llm_spans)

    def calls(self, tool: str, *, executed_only: bool = True) -> list[Span]:
        """Spans for one tool. By default only calls that ran (not ones the ACL refused)."""
        return [
            s
            for s in self.tool_spans
            if s.name == tool and (not executed_only or s.status != "blocked")
        ]

    def to_dict(self) -> dict:
        """What is written to disk. No claim text, no review payloads (rule 4)."""
        out = {
            k: v
            for k, v in asdict(self).items()
            if k not in {"review_payloads", "clause_texts", "output", "_node", "_agent"}
        }
        out.update(llm_calls=self.llm_calls, tokens=self.tokens, cost=self.cost, path=self.path)
        return out


class Observer(Protocol):
    """Watches a run while it happens (L14: a span is opened before a step and closed after it).

    `step` is entered before the step starts and left after `span` is filled in (status, output,
    time). It must not swallow an exception. `review` must call `decide(payload)` once and return
    its answer unchanged.
    """

    def step(self, span: Span) -> AbstractContextManager[Any]: ...

    def review(self, payload: dict, decide: Callable[[dict], dict]) -> dict: ...


def _watch(observer: Observer | None, span: Span) -> AbstractContextManager[Any]:
    return nullcontext() if observer is None else observer.step(span)


# ---------------------------------------------------------------------------- redaction
def redact_args(kwargs: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in kwargs.items():
        if key in SAFE_ARG_KEYS and isinstance(value, str | int):
            out[key] = value
        elif isinstance(value, str):
            out[key] = f"<text {len(value)} chars>"
        elif isinstance(value, dict):
            out[key] = f"<{len(value)} entries>"
        elif isinstance(value, list | tuple):
            out[key] = f"<{len(value)} items>"
        else:
            out[key] = f"<{type(value).__name__}>"
    return out


def args_key(kwargs: dict[str, Any]) -> str:
    """Stable fingerprint of a call's full arguments. Two calls with the same key are repeats."""
    text = repr(sorted((k, repr(v)) for k, v in kwargs.items()))
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _short(clause_id: str) -> str:
    return clause_id.split(":")[-1]


def summarise_result(result: Any) -> str:
    """One line about a tool result, with no claim text in it."""
    if result is None:
        return "none"
    if isinstance(result, list):
        ids = [getattr(getattr(r, "clause", None), "clause_id", None) for r in result]
        if ids and all(ids):
            return f"{len(result)} passages: " + ", ".join(_short(i) for i in ids)
        return f"{len(result)} items"
    if hasattr(result, "total_payable"):
        return f"worksheet v{result.version}, payable Rs {result.total_payable}"
    if hasattr(result, "clause_id") and hasattr(result, "text"):
        return f"clause {_short(result.clause_id)}"
    if hasattr(result, "period_start"):
        return "policy found"
    if isinstance(result, tuple) and len(result) == 2:
        return f"range {result[0]}-{result[1]}"
    if isinstance(result, dict):
        return f"status {result.get('status', '?')}"
    return type(result).__name__


def _remember_clauses(trace: Trace, result: Any) -> None:
    """Keep the policy text the agents were shown (not claim text), for the judge in section 6."""
    items = result if isinstance(result, list) else [result]
    for item in items:
        clause = getattr(item, "clause", item)
        cid, text = getattr(clause, "clause_id", None), getattr(clause, "text", None)
        if cid and isinstance(text, str):
            trace.clause_texts.setdefault(cid, text)


# ---------------------------------------------------------------------------- instrumentation
class _ToolLogTap(list):
    """`Services.tool_log`, but it also tells the trace who is calling and records ACL refusals.

    `ToolBelt.call` appends `{agent, tool, allowed}` and only then calls the tool, so the agent of
    the next tool span is the agent of the last allowed entry.
    """

    def __init__(self, trace: Trace, observer: Observer | None = None) -> None:
        super().__init__()
        self.trace = trace
        self.observer = observer

    def append(self, entry: dict) -> None:  # type: ignore[override]
        super().append(entry)
        if entry.get("allowed"):
            self.trace._agent = str(entry.get("agent", ""))
            return
        span = Span(
            "tool",
            str(entry.get("tool", "?")),
            node=self.trace._node,
            agent=str(entry.get("agent", "")),
            status="blocked",
            output="refused by the agent's tool ACL",
        )
        self.trace.spans.append(span)
        with _watch(self.observer, span):  # a hook that acts leaves a record (L14 section 7.4)
            pass


def _wrap_tool(
    name: str, fn: Callable[..., Any], trace: Trace, observer: Observer | None = None
) -> Callable[..., Any]:
    def traced(*args: Any, **kwargs: Any) -> Any:
        span = Span(
            "tool",
            name,
            node=trace._node,
            agent=trace._agent,
            args=redact_args(kwargs),
            args_key=args_key(kwargs),
        )
        trace._agent = ""  # consumed: a later direct call must not inherit it
        trace.spans.append(span)
        t0 = time.perf_counter()
        with _watch(observer, span):
            try:
                result = fn(*args, **kwargs)
            except Exception as e:
                span.status, span.output = "error", f"{type(e).__name__}: {str(e)[:120]}"
                raise
            finally:
                span.ms = (time.perf_counter() - t0) * 1000
            span.output = summarise_result(result)
        if name in ("policy_search", "get_clause"):
            _remember_clauses(trace, result)
        return result

    traced.__name__ = name
    return traced


def instrument_services(services: Any, trace: Trace, observer: Observer | None = None) -> Any:
    """Wrap every tool on one claim's `Services`. Call before building the `Team`."""
    services.tool_log = _ToolLogTap(trace, observer)
    for name in TOOL_NAMES:
        setattr(services, name, _wrap_tool(name, getattr(services, name), trace, observer))
    return services


@contextmanager
def _llm_capture(trace: Trace, node: str) -> Iterator[None]:
    """Collect the LangChain model runs made while one node runs, as llm spans."""
    if trace.mode != "llm":
        yield
        return
    try:
        from langchain_core.tracers.context import collect_runs
    except ImportError:  # pragma: no cover - real mode always has langchain-core
        yield
        return
    with collect_runs() as collector:
        yield
    for root in collector.traced_runs:
        for run in _walk(root):
            if run.run_type in ("llm", "chat_model"):
                trace.spans.append(_llm_span(run, node))


def _walk(run: Any) -> Iterator[Any]:
    yield run
    for child in getattr(run, "child_runs", None) or []:
        yield from _walk(child)


def _llm_span(run: Any, node: str) -> Span:
    """Tokens and cost from a LangChain run, best effort: providers report them differently."""
    usage: dict = {}
    outputs = getattr(run, "outputs", None) or {}
    usage = dict((outputs.get("llm_output") or {}).get("token_usage") or {})
    if not usage:
        try:
            message = outputs["generations"][0][0]["message"]["kwargs"]
            meta = message.get("usage_metadata") or {}
            usage = {
                "prompt_tokens": meta.get("input_tokens", 0),
                "completion_tokens": meta.get("output_tokens", 0),
            }
            usage.update((message.get("response_metadata") or {}).get("token_usage") or {})
        except (KeyError, IndexError, TypeError):
            usage = {}
    params = (getattr(run, "extra", None) or {}).get("invocation_params") or {}
    ms = 0.0
    if getattr(run, "end_time", None) and getattr(run, "start_time", None):
        ms = (run.end_time - run.start_time).total_seconds() * 1000
    return Span(
        "llm",
        str(params.get("model") or params.get("model_name") or run.name),
        node=node,
        ms=ms,
        status="error" if getattr(run, "error", None) else "ok",
        tokens_in=int(usage.get("prompt_tokens") or 0),
        tokens_out=int(usage.get("completion_tokens") or 0),
        cost=float(usage.get("cost") or 0.0),
    )


@cache
def _runner_class() -> type:
    from claimsense.graph.local import LocalRunner

    class TracedRunner(LocalRunner):
        """`LocalRunner` with one node span per step. Same nodes, same routers."""

        def __init__(
            self, team: Any, trace: Trace, observer: Observer | None = None, **kwargs: Any
        ) -> None:
            super().__init__(team, **kwargs)
            self.trace = trace
            self.observer = observer

        def _run(self, nodes: dict, packet: dict):  # noqa: ANN202 - ClaimState
            return super()._run({n: self._timed(n, fn) for n, fn in nodes.items()}, packet)

        def _timed(self, name: str, fn: Callable[[dict], dict]) -> Callable[[dict], dict]:
            trace, observer = self.trace, self.observer

            def run(state: dict) -> dict:
                span = Span("node", name)
                trace.spans.append(span)
                trace._node = name
                t0 = time.perf_counter()
                with _watch(observer, span):
                    try:
                        with _llm_capture(trace, name):
                            return fn(state)
                    except Exception as e:
                        span.status, span.output = "error", f"{type(e).__name__}: {str(e)[:120]}"
                        raise
                    finally:
                        span.ms = (time.perf_counter() - t0) * 1000
                        trace._node = ""

            return run

    return TracedRunner


# ---------------------------------------------------------------------------- running a claim
@cache
def _adapter(calculator: str, pass_documents: bool) -> ClaimSenseAdapter:
    """Reused for its packet builder and its state -> output mapping, so a traced run and a
    harness run see the same claim and are scored the same way."""
    return ClaimSenseAdapter(calculator=calculator, pass_documents=pass_documents)


def _mode() -> str:
    from claimsense.agents.llm import stub_mode

    return "stub" if stub_mode() else "llm"


class _NoFraudScreen:
    """Stands in for `FraudAgent` in the `lean-pr` variant (L13 section 7.1, the teammate's PR).

    The fraud node still runs, but the screen makes no tool call: no claim history, no policy
    period, no tariff range. It keeps the extraction notes exactly as `FraudAgent.run` appends
    them, so those still reach the reviewer.
    """

    def run(self, claim: Any, extraction_issues: list[str] | None = None) -> list[str]:
        return [f"extraction: {i}" for i in (extraction_issues or [])]


def run_traced(
    case: EvalCase,
    *,
    variant: str = "v1",
    pass_documents: bool = True,
    guardrail: bool = False,
    calculator: str = "reference",
    fraud_screen: bool = True,
    prepare: Callable[[Any], None] | None = None,
    observer: Observer | None = None,
) -> Trace:
    """Run one claim through the real pipeline and return its trace.

    guardrail=True puts the product's input guardrail (`claimsense.guardrails.scan_documents`) in
    front of the graph, the way L13 section 5.1 does: a flagged claim goes straight to a person and
    no agent runs. Nothing in the product wires it in today, so this measures what it *would* do.

    fraud_screen=False is the change section 7.1 puts through the gate: the fraud agent's three
    tool calls are skipped (see `_NoFraudScreen`). It exists to show what the gate catches.

    prepare, if given, is called with this claim's `Services` before the tools are wrapped.
    `eval.monitoring` uses it to make a tool fail (section 8.6); because the fault sits under the
    tracing wrapper, it shows up in the trace as an `error` tool span, like a real outage would.

    observer, if given, watches each step while it runs (see `Observer`). It changes nothing in
    the run or in the returned trace.
    """
    adapter = _adapter(calculator, pass_documents)
    imports = adapter._imports
    trace = Trace(case.claim_id, case.split, variant=variant, mode=_mode())
    started = time.perf_counter()
    packet = adapter._packet(case.claim)

    if guardrail:
        from .guardrail import screen_documents

        span = Span("guardrail", "input_guardrail")
        t0 = time.perf_counter()
        with _watch(observer, span):
            findings = screen_documents(packet.get("documents") or {})
            span.ms = (time.perf_counter() - t0) * 1000
            span.output = f"{len(findings)} finding(s)" if findings else "clean"
        trace.spans.append(span)
        if findings:
            trace.status, trace.route, trace.flags = "blocked", "needs_review", ["prompt_injection"]
            trace.seconds = time.perf_counter() - started
            trace.output = AgentOutput(
                claim_id=case.claim_id,
                route="needs_review",
                review_flags=["prompt_injection"],
                observed_claim_keys=_observed(case.claim),
                latency_s=trace.seconds,
                status="blocked",
            )
            return trace

    policy = adapter._policy(case.claim)
    services = imports["make_stub_services"](policies={policy.policy_number: policy})
    services.calculate = (
        imports["reference_calculate"] if calculator == "reference" else imports["real_calculate"]
    )
    if prepare is not None:
        prepare(services)
    instrument_services(services, trace, observer)
    team = imports["Team"](services)
    if not fraud_screen:
        team.fraud = _NoFraudScreen()
    runner = _runner_class()(team, trace, observer)

    def reviewer(payload: dict) -> dict:
        trace.review_payloads.append(payload)
        if observer is None:
            return adapter._decline(payload)
        return observer.review(payload, adapter._decline)

    try:
        state = runner.run(packet, reviewer=reviewer)
    except Exception as e:  # noqa: BLE001 - a crash is a result, recorded and scored
        trace.status, trace.error = "error", f"{type(e).__name__}: {e}"
        trace.seconds = time.perf_counter() - started
        trace.output = AgentOutput(
            claim_id=case.claim_id,
            review_flags=["pipeline_error"],
            actions=adapter._actions(services.tool_log),
            observed_claim_keys=_observed(case.claim),
            latency_s=trace.seconds,
            error=trace.error,
        )
        return trace
    trace.seconds = time.perf_counter() - started

    worksheet = adapter._worksheet(state)
    admissibility = state.get("admissibility")
    critic = state.get("critic_report")
    trace.status = str(state.get("status", ""))
    trace.route = adapter._route(state)
    trace.flags = adapter._flags(state)
    trace.settlement_inr = worksheet.settlement_inr if worksheet else None
    trace.clause_choices = dict(state.get("clause_choices") or {})
    trace.admissible = getattr(admissibility, "admissible", None)
    trace.critic_passed = getattr(critic, "passed", None)
    trace.revisions = int(state.get("revisions") or 0)
    trace.escalated = bool(state.get("escalation"))
    trace.extraction_issues = len(state.get("extraction_issues") or [])
    citations = set(trace.clause_choices.values())
    citations.update(getattr(admissibility, "clause_ids", None) or [])
    trace.citations = sorted(c for c in citations if c)
    # Field for field what `ClaimSenseAdapter.run` returns, so the harness scorer gives a traced
    # run the same score as an adapter run (eval/tests/test_full.py checks this).
    trace.output = AgentOutput(
        claim_id=case.claim_id,
        route=trace.route,
        worksheet=worksheet,
        review_flags=trace.flags,
        citations=trace.citations,
        actions=adapter._actions(services.tool_log),
        rationales={
            line_id: f"Line {line_id} was adjudicated under clause {clause_id}."
            for line_id, clause_id in sorted(trace.clause_choices.items())
        },
        observed_claim_keys=_observed(case.claim),
        latency_s=trace.seconds,
        prompt_tokens=sum(s.tokens_in for s in trace.llm_spans),
        completion_tokens=sum(s.tokens_out for s in trace.llm_spans),
        cost_usd=trace.cost,
        status=trace.status,
    )
    return trace


# ---------------------------------------------------------------------------- reading a trace
def format_trace(t: Trace) -> str:
    """The waterfall, as text: nodes, and under each the tool and model calls it made."""
    money = "-" if t.settlement_inr is None else f"Rs {t.settlement_inr:,}"
    lines = [
        f"[{t.variant}] {t.claim_id} ({t.split}, {t.mode}) | route {t.route} | {money} | "
        f"{t.seconds * 1000:.0f} ms | {t.llm_calls} LLM calls, ${t.cost:.5f} | status {t.status}"
    ]
    for s in t.spans:
        mark = "" if s.ok else f"  <-- {s.status.upper()}"
        if s.kind in ("node", "guardrail"):
            lines.append(f"  {s.kind:<9} {s.name:<14} {s.ms:7.1f} ms  {s.output}{mark}")
        elif s.kind == "llm":
            lines.append(
                f"      llm  {s.name} {s.ms:6.0f} ms  {s.tokens_in} in / {s.tokens_out} out  "
                f"${s.cost:.5f}{mark}"
            )
        else:
            args = ", ".join(f"{k}={v}" for k, v in s.args.items())
            who = f"{s.agent}: " if s.agent else ""
            lines.append(f"      └ {who}{s.name}({args[:70]}) -> {s.output[:70]}{mark}")
    if t.flags:
        lines.append(f"  flags: {', '.join(t.flags)}")
    if t.error:
        lines.append(f"  error: {t.error}")
    return "\n".join(lines)


def show_trace(t: Trace) -> None:
    print(format_trace(t))
