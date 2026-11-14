"""OpenTelemetry for the product (rubric D3): the redaction rule, and the tracer the case API uses.

**Rule 4 (no health details).** Every exporter is wrapped in `RedactingExporter`. It keeps an
attribute only if it is on an allowlist: attributes ClaimSense writes from values that are already
content-free (ids, codes, counts, names of steps and tools), and an instrumentation's model, token
and operation keys. Everything else (prompts, completions, tool arguments and results, exception
messages) is dropped before a span leaves the process. `eval/observability` uses the same rule
from here, so there is one allowlist.

The case API traces only when asked: `CLAIMSENSE_OTEL=otlp` (the standard `OTEL_EXPORTER_OTLP_*`
settings name the collector) or `console`. It needs the `observability` extra; the API imports
this module only when tracing is on.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import Event, ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.trace import Status, StatusCode

SERVICE_NAME = "claimsense"

# ------------------------------------------------------------------------------- redaction
#: Attributes ClaimSense writes itself, only ever from content-free values.
OWN_PREFIXES: tuple[str, ...] = ("claim.", "claimsense.", "hitl.")

#: Attributes of the LangChain instrumentation (and of the GenAI conventions) that hold no claim
#: content: which model, how many tokens, what kind of step. Prompts, completions, tool arguments
#: and results are not on this list, so they never leave the process.
LIBRARY_KEYS: frozenset[str] = frozenset(
    {
        "gen_ai.operation.name",
        "gen_ai.system",
        "gen_ai.provider.name",
        "gen_ai.request.model",
        "gen_ai.response.model",
        "gen_ai.request.temperature",
        "gen_ai.request.max_tokens",
        "gen_ai.response.finish_reasons",
        "gen_ai.response.id",
        "gen_ai.agent.name",
        "gen_ai.conversation.id",
        "gen_ai.tool.name",
        "llm.request.type",
        "traceloop.span.kind",
        "traceloop.workflow.name",
        "traceloop.entity.name",
        "traceloop.entity.path",
        "error.type",
    }
)
LIBRARY_PREFIXES: tuple[str, ...] = ("gen_ai.usage.", "llm.usage.")

#: The only attribute kept on an `exception` event: its type. A message can quote claim text.
EVENT_KEYS: frozenset[str] = frozenset({"exception.type", "exception.escaped"})


def keep(key: str) -> bool:
    return key.startswith(OWN_PREFIXES + LIBRARY_PREFIXES) or key in LIBRARY_KEYS


def _error_type(span: ReadableSpan, attrs: dict[str, Any]) -> str:
    if attrs.get("error.type"):
        return str(attrs["error.type"])
    for event in span.events:
        if event.name == "exception" and (event.attributes or {}).get("exception.type"):
            return str((event.attributes or {})["exception.type"])
    return "error"


def redact(span: ReadableSpan) -> ReadableSpan:
    """A copy of `span` with every attribute off the allowlist removed (rule 4)."""
    attrs: dict[str, Any] = {k: v for k, v in (span.attributes or {}).items() if keep(k)}
    dropped = len(span.attributes or {}) - len(attrs)
    if dropped:
        attrs["claimsense.redacted_attributes"] = dropped
    events = [
        Event(
            e.name,
            {k: v for k, v in (e.attributes or {}).items() if keep(k) or k in EVENT_KEYS},
            e.timestamp,
        )
        for e in span.events
    ]
    status = span.status
    if status.status_code == StatusCode.ERROR:  # the description can be an exception message
        status = Status(StatusCode.ERROR, _error_type(span, attrs))
    return ReadableSpan(
        name=span.name,
        context=span.context,
        parent=span.parent,
        resource=span.resource,
        attributes=attrs,
        events=events,
        links=span.links,
        kind=span.kind,
        status=status,
        start_time=span.start_time,
        end_time=span.end_time,
        instrumentation_scope=span.instrumentation_scope,
    )


class RedactingExporter(SpanExporter):
    """Wraps any exporter: each span is redacted before the inner exporter sees it.

    It also counts what the backend accepted (`sent`) and refused (`failed`). The SDK's batch
    processor ignores the export result and its `force_flush` returns True anyway, so these
    counts are the only proof of delivery when no read-back is possible."""

    def __init__(self, inner: SpanExporter) -> None:
        self.inner = inner
        self.sent = 0
        self.failed = 0

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        result = self.inner.export([redact(s) for s in spans])
        if result is SpanExportResult.SUCCESS:
            self.sent += len(spans)
        else:
            self.failed += len(spans)
        return result

    def shutdown(self) -> None:
        self.inner.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self.inner.force_flush(timeout_millis)


# ------------------------------------------------------------------------- the product's tracer
def exporter_for(mode: str) -> SpanExporter | None:
    """The exporter `CLAIMSENSE_OTEL` names: `otlp`, `console`, or None for anything else."""
    if mode == "otlp":
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        return OTLPSpanExporter()  # endpoint and headers from the OTEL_EXPORTER_OTLP_* settings
    if mode == "console":
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter

        return ConsoleSpanExporter()
    return None


def provider(exporter: SpanExporter, *, simple: bool = False, version: str = "") -> TracerProvider:
    """A tracer provider of its own (never the global one) whose spans are redacted on the way
    out. `simple` exports each span as it ends (tests, the console); otherwise in batches."""
    resource = Resource.create({"service.name": SERVICE_NAME, "service.version": version})
    tp = TracerProvider(resource=resource)
    redacting = RedactingExporter(exporter)
    processor = SimpleSpanProcessor if simple else BatchSpanProcessor
    tp.add_span_processor(processor(redacting))
    return tp
