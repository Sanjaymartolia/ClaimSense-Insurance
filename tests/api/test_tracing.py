"""Rubric D3: tracing from the product. Opt-in, one trace per claim run, every span redacted."""

import pytest

pytest.importorskip("opentelemetry.sdk")

from fastapi.testclient import TestClient  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: E402
    InMemorySpanExporter,
)

from claimsense import tracing  # noqa: E402
from claimsense.api.auth import parse_reviewers  # noqa: E402
from claimsense.api.main import create_app  # noqa: E402
from claimsense.api.runner import CaseService, Settings  # noqa: E402

from .conftest import ALICE, REVIEWERS, decide, sse, start  # noqa: E402
from .test_audit import claim_texts  # noqa: E402


def settings() -> Settings:
    return Settings(checkpoints=":memory:", reviewers=parse_reviewers(REVIEWERS))


def traced_client() -> tuple[TestClient, InMemorySpanExporter]:
    memory = InMemorySpanExporter()
    app = create_app(settings())
    app.state.cases = CaseService(settings(), tracer_provider=tracing.provider(memory, simple=True))
    return TestClient(app), memory


def test_each_run_is_one_trace_of_its_nodes_and_tool_calls():
    client, memory = traced_client()
    run_id = sse(start(client, "CLM-0004"))[0][1]["run_id"]
    spans = memory.get_finished_spans()
    (root,) = [s for s in spans if s.name == "claim.run"]
    assert root.attributes["claimsense.run_id"] == run_id
    assert root.attributes["claimsense.case_id"] == "CLM-0004"
    assert root.attributes["claimsense.status"] == "awaiting_review"
    children = [s for s in spans if s.parent and s.parent.span_id == root.context.span_id]
    names = {s.name for s in children}
    assert {"node extract", "node coverage"} <= names
    assert any(name.startswith("tool ") for name in names)
    assert all(s.context.trace_id == root.context.trace_id for s in children)
    assert all(s.attributes["claimsense.run_id"] == run_id for s in children)


def test_a_decision_is_a_trace_of_its_own():
    client, memory = traced_client()
    first = sse(start(client, "CLM-0004"))[0][1]["run_id"]
    second = sse(decide(client, "CLM-0004", ALICE))[0][1]["run_id"]
    roots = [s for s in memory.get_finished_spans() if s.name == "claim.run"]
    assert [r.attributes["claimsense.run_id"] for r in roots] == [first, second]
    assert roots[0].context.trace_id != roots[1].context.trace_id
    assert roots[1].attributes["claimsense.status"] == "settled"


def test_no_span_attribute_holds_claim_text():
    client, memory = traced_client()
    sse(start(client, "CLM-0004"))
    sse(decide(client, "CLM-0004", ALICE))
    values = [str(v) for s in memory.get_finished_spans() for v in (s.attributes or {}).values()]
    for fragment in claim_texts("CLM-0004"):
        assert not any(fragment in value for value in values), fragment


def test_an_attribute_off_the_allowlist_never_leaves_the_process():
    memory = InMemorySpanExporter()
    tracer = tracing.provider(memory, simple=True).get_tracer("test")
    attributes = {"claimsense.run_id": "r1", "input.value": "Laparoscopic cholecystectomy"}
    tracer.start_span("claim.run", attributes=attributes).end()
    (span,) = memory.get_finished_spans()
    assert "input.value" not in span.attributes
    assert span.attributes["claimsense.redacted_attributes"] == 1


def test_tracing_is_off_unless_asked():
    assert tracing.exporter_for("") is None and tracing.exporter_for("nonsense") is None
    service = CaseService(settings())
    try:
        assert service.tracer is None
    finally:
        service.close()
