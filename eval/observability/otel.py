"""OpenTelemetry for the ClaimSense pipeline: provider, redaction, and one span per step.

Notebook sections 2 to 4, applied to ClaimSense:

    notebook                                ClaimSense
    --------------------------------------  ------------------------------------------------------
    TracerProvider + Resource               `Telemetry`: one provider per run, never the global one,
                                            so tests and repeated runs never share state
    tracer.start_as_current_span(...)       `SpanObserver`: `run_traced(observer=...)` opens a span
                                            around every node, tool call, guardrail and review
    invoke_agent / chat / execute_tool      the GenAI names (`invoke_agent claimsense`,
                                            `execute_tool policy_search`, model calls)
    business span `claim`                   the root span carries claim.route, claim.settlement_inr,
                                            claim.flags, claim.citations, cost and tokens
    LangchainInstrumentor().instrument()    `instrument_langchain`: model-call spans in real mode,
                                            with prompt and completion capture OFF
    exporter: memory, console, OTLP         `Telemetry(otlp=...)`: memory always, OTLP when asked

**Rule 4 (no health details).** Every exporter is wrapped in `RedactingExporter`. It keeps an
attribute only if it is on an allowlist: attributes this package writes from values that are
already content-free (ids, codes, counts, redacted argument shapes), and the instrumentation's
model, token and operation keys. Everything else (prompts, completions, tool arguments and results
as the instrumentation records them, exception messages) is dropped before a span leaves the
process. The memory exporter gets the same redacted copy, so what the tests check is exactly what
Jaeger, Langfuse or LangSmith (over OTLP) would receive.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
)
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, Status, StatusCode, Tracer

# The redaction rule lives in the product (`claimsense.tracing`), which traces the case API with
# it; this package uses and re-exports it, so there is one allowlist.
from claimsense.tracing import (  # noqa: F401 - re-exported for this package and its tests
    EVENT_KEYS,
    LIBRARY_KEYS,
    LIBRARY_PREFIXES,
    OWN_PREFIXES,
    RedactingExporter,
    keep,
    redact,
)
from eval.agent_suite.trace import Span, Trace, run_traced
from eval.harness.models import EvalCase

from .analysis import SpanRow, from_readable

SERVICE_NAME = "claimsense"
AGENT_NAME = "claimsense"
ROOT_SPAN = f"invoke_agent {AGENT_NAME}"


# -------------------------------------------------------------------------------- provider
@dataclass
class Telemetry:
    """One run's tracer provider: spans always go to memory, and to OTLP when an exporter is given.

    Memory uses a `SimpleSpanProcessor` (each span is kept the moment it ends, so analysis sees all
    of them). OTLP uses a `BatchSpanProcessor`, as in production: spans are sent in the background
    and the pipeline never waits on the network.
    """

    provider: TracerProvider
    memory: InMemorySpanExporter
    tracer: Tracer
    processors: tuple[SpanProcessor, ...] = ()
    otlp: RedactingExporter | None = None

    def rows(self) -> list[SpanRow]:
        return [from_readable(s) for s in self.memory.get_finished_spans()]

    def flush(self, timeout_s: float = 10.0) -> bool:
        return self.provider.force_flush(int(timeout_s * 1000))

    def shutdown(self) -> None:
        self.provider.shutdown()


def telemetry(otlp: SpanExporter | None = None, *, version: str = "") -> Telemetry:
    """A fresh provider (never the global one). `otlp`, if given, is sent to in the background."""
    from claimsense import __version__

    resource = Resource.create(
        {"service.name": SERVICE_NAME, "service.version": version or __version__}
    )
    provider = TracerProvider(resource=resource)
    memory = InMemorySpanExporter()
    processors: list[SpanProcessor] = [SimpleSpanProcessor(RedactingExporter(memory))]
    remote = RedactingExporter(otlp) if otlp is not None else None
    if remote is not None:
        processors.append(BatchSpanProcessor(remote))
    for p in processors:
        provider.add_span_processor(p)
    tracer = provider.get_tracer("claimsense.eval.observability")
    return Telemetry(provider, memory, tracer, tuple(processors), remote)


# -------------------------------------------------------------------------- span per step
def _span_name(s: Span) -> str:
    if s.kind == "tool":
        return f"execute_tool {s.name}"
    if s.kind == "node":
        return f"node {s.name}"
    return f"{s.kind} {s.name}"


def _start_attributes(s: Span) -> dict[str, Any]:
    if s.kind == "tool":
        attrs = {
            "gen_ai.operation.name": "execute_tool",
            "gen_ai.tool.name": s.name,
            "claimsense.node": s.node,
            "claimsense.tool.args": json.dumps(s.args, sort_keys=True),  # already redacted
        }
        if s.agent:
            attrs["claimsense.agent"] = s.agent
        return attrs
    if s.kind == "node":
        return {"claimsense.node": s.name}
    return {"claimsense.step": s.kind}


def _finish(otel: Any, s: Span) -> None:
    """Copy what the step recorded onto its span, after it ran."""
    otel.set_attribute("claimsense.status", s.status)
    if s.status == "error":
        etype = s.output.split(":", 1)[0] or "error"
        otel.set_attribute("error.type", etype)
        otel.set_status(Status(StatusCode.ERROR, etype))
    elif s.status == "blocked":
        otel.add_event("refused by the tool ACL", {"claimsense.agent": s.agent})
    elif s.kind == "tool":
        otel.set_attribute("claimsense.tool.result", s.output)  # summary: ids and counts only
    elif s.kind == "guardrail":
        otel.set_attribute(
            "claimsense.guardrail.verdict", "clean" if s.output == "clean" else "flag"
        )
        findings = 0 if s.output == "clean" else int(s.output.split(" ", 1)[0] or 0)
        otel.set_attribute("claimsense.guardrail.findings", findings)


class SpanObserver:
    """`eval.agent_suite.trace.Observer` that turns each step into an OpenTelemetry span.

    A span is opened before the step starts, so the model-call spans the LangChain
    instrumentation opens inside a node become that node's children (context is per thread).
    """

    def __init__(self, tracer: Tracer, clock: Callable[[], float] = time.perf_counter) -> None:
        self.tracer = tracer
        self.clock = clock

    @contextmanager
    def step(self, span: Span) -> Iterator[None]:
        with self.tracer.start_as_current_span(
            _span_name(span),
            attributes=_start_attributes(span),
            record_exception=False,  # an exception message can quote claim text
            set_status_on_exception=False,
        ) as otel:
            try:
                yield
            except BaseException as e:
                otel.add_event("exception", {"exception.type": type(e).__name__})
                otel.set_attribute("error.type", type(e).__name__)
                otel.set_status(Status(StatusCode.ERROR, type(e).__name__))
                raise
            finally:
                _finish(otel, span)

    def review(self, payload: dict, decide: Callable[[dict], dict]) -> dict:
        """L14 section 8: the person's decision, on the trace next to the agents' steps."""
        ws = payload.get("worksheet") or {}
        attrs: dict[str, Any] = {
            "hitl.level": str(payload.get("level", "")),
            "hitl.kind": str(payload.get("kind", "")),
            "hitl.fraud_flags": len(payload.get("fraud_flags") or []),
            "hitl.critic_notes": len(payload.get("critic") or []),
            "hitl.escalated": bool(payload.get("escalation")),
        }
        if ws.get("total_payable") is not None:
            attrs["hitl.proposed_inr"] = round(float(ws["total_payable"]))
        t0 = self.clock()
        with self.tracer.start_as_current_span("human_review", attributes=attrs) as otel:
            answer = decide(payload)
            otel.set_attributes(
                {
                    "hitl.decision": str(answer.get("decision", "")),
                    "hitl.reviewer": str(answer.get("approver_id", "")),
                    "hitl.edits": len(answer.get("edits") or []),
                    "hitl.wait_s": round(self.clock() - t0, 4),
                }
            )
        return answer


def business_attributes(t: Trace) -> dict[str, Any]:
    """The facts you search on later ("which claims paid over Rs 50,000?"). No claim text."""
    attrs: dict[str, Any] = {
        "claim.status": t.status,
        "claim.route": t.route or "",
        "claim.flags": list(t.flags),
        "claim.citations": list(t.citations),
        "claim.revisions": t.revisions,
        "claim.escalated": t.escalated,
        "claim.tool_calls": len(t.tool_spans),
        "claim.tool_errors": sum(s.status == "error" for s in t.tool_spans),
        "claim.llm_calls": t.llm_calls,
        "claim.tokens": t.tokens,
        "claim.cost_usd": round(t.cost, 6),
        "claim.seconds": round(t.seconds, 4),
    }
    if t.settlement_inr is not None:
        attrs["claim.settlement_inr"] = int(t.settlement_inr)
    return attrs


def run_claim(
    tel: Telemetry,
    case: EvalCase,
    *,
    phase: str = "",
    variant: str = "v1",
    **kwargs: Any,
) -> tuple[Trace, str]:
    """One claim inside its own root span. Returns the eval trace and the OTel trace id (hex)."""
    from claimsense.agents.llm import stub_mode

    start = {
        "gen_ai.operation.name": "invoke_agent",
        "gen_ai.agent.name": AGENT_NAME,
        "gen_ai.conversation.id": case.claim_id,
        "claim.id": case.claim_id,
        "claim.split": case.split,
        "claim.variant": variant,
        "claimsense.mode": "stub" if stub_mode() else "real",
    }
    if phase:
        start["claimsense.phase"] = phase
    with tel.tracer.start_as_current_span(
        ROOT_SPAN, kind=SpanKind.INTERNAL, attributes=start, record_exception=False
    ) as root:
        t = run_traced(case, variant=variant, observer=SpanObserver(tel.tracer), **kwargs)
        root.set_attributes(business_attributes(t))
        if t.status == "error":
            etype = (t.error or "error").split(":", 1)[0]
            root.set_attribute("error.type", etype)
            root.set_status(Status(StatusCode.ERROR, etype))
    return t, f"{root.get_span_context().trace_id:032x}"


# ------------------------------------------------------------------- auto-instrumentation
#: The LangChain instrumentation records prompts and completions unless this is "false".
CONTENT_SWITCH = "TRACELOOP_TRACE_CONTENT"


class _Forward(SpanProcessor):
    """Hands the instrumentation's spans to the current run's processors (memory, OTLP).

    The LangChain instrumentation (0.63) patches LangChain once per process: after
    `uninstrument()`, a second `instrument()` records nothing (checked 11 November 2026). So it is
    instrumented once, against a provider that only forwards, and each run changes the targets.
    """

    targets: tuple[SpanProcessor, ...] = ()

    def on_start(self, span: Any, parent_context: Any = None) -> None:
        for p in self.targets:
            p.on_start(span, parent_context=parent_context)

    def on_end(self, span: ReadableSpan) -> None:
        for p in self.targets:
            p.on_end(span)

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True


_FORWARD = _Forward()
_LANGCHAIN_PROVIDER: TracerProvider | None = None


def instrument_langchain(tel: Telemetry) -> bool:
    """Notebook section 3: a span for every model call, with content capture OFF (rule 4).

    Returns False if the instrumentation is not installed. Model-call spans become children of the
    node span that is open when the call is made, and go through the same redaction.
    """
    global _LANGCHAIN_PROVIDER
    os.environ[CONTENT_SWITCH] = "false"
    try:
        from opentelemetry.instrumentation.langchain import LangchainInstrumentor
    except ImportError:
        return False
    if _LANGCHAIN_PROVIDER is None:
        _LANGCHAIN_PROVIDER = TracerProvider(resource=tel.provider.resource)
        _LANGCHAIN_PROVIDER.add_span_processor(_FORWARD)
        inst = LangchainInstrumentor()
        if not inst.is_instrumented_by_opentelemetry:
            inst.instrument(tracer_provider=_LANGCHAIN_PROVIDER)
    _FORWARD.targets = tel.processors
    return True


def uninstrument_langchain() -> None:
    """Stop forwarding model-call spans. LangChain stays patched; its spans then go nowhere."""
    _FORWARD.targets = ()


# ------------------------------------------------------------------------------- LangSmith
def _langsmith_env(name: str) -> str | None:
    """Read a setting the way langsmith 0.14 does (`langsmith.utils.get_env_var`): the first
    non-empty of LANGSMITH_<name> and LANGCHAIN_<name>. LangSmith switches tracing on only for
    the exact value "true"; this check uses the same rule."""
    for namespace in ("LANGSMITH", "LANGCHAIN"):
        value = os.environ.get(f"{namespace}_{name}")
        if value is not None and value.strip() != "":
            return value
    return None


def _langsmith_tracing() -> bool:
    return (_langsmith_env("TRACING_V2") or _langsmith_env("TRACING") or "") == "true"


def langsmith_problem() -> str | None:
    """LangSmith's own LangChain tracing (LANGSMITH_TRACING=true) runs outside the redaction
    above. LANGSMITH_HIDE_INPUTS/OUTPUTS do not cover the run's error text (repr and traceback,
    which can quote the model's reply) and only code can set an anonymizer, so it is refused
    (rule 4). LangSmith still gets the spans, redacted, over OTLP (`--backend otlp-env`)."""
    if not _langsmith_tracing():
        return None
    return (
        "LANGSMITH_TRACING is on. LangSmith's own tracing uploads each run's error text, which "
        "can quote claim details, and no environment variable hides it (rule 4). Switch "
        "LANGSMITH_TRACING off, and send redacted spans to LangSmith with --backend otlp-env "
        "(see eval/observability/README.md)."
    )
