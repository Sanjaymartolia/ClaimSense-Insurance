"""eval/observability: OpenTelemetry spans for the pipeline (L14). No network, no key, no Jaeger.

The rule-4 tests matter most: every span that leaves the process goes through the same redaction,
and the memory exporter these tests read gets the same copy as Jaeger, Langfuse or LangSmith.
"""

from __future__ import annotations

import contextlib
import json
import os
import threading

import pytest

pytest.importorskip("opentelemetry.sdk", reason='needs pip install -e ".[observability]"')
pytest.importorskip("langgraph", reason='needs pip install -e ".[agents]"')
os.environ["CLAIMSENSE_LLM"] = "stub"  # these tests never call a model

from opentelemetry.sdk.trace import TracerProvider  # noqa: E402
from opentelemetry.sdk.trace.export import SimpleSpanProcessor  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: E402
    InMemorySpanExporter,
)
from opentelemetry.trace import Status, StatusCode  # noqa: E402

from eval.agent_suite.dataset import load_dataset  # noqa: E402
from eval.agent_suite.suite import VARIANTS  # noqa: E402
from eval.agent_suite.trace import Trace, _ToolLogTap, run_traced  # noqa: E402
from eval.monitoring.live import Fault  # noqa: E402
from eval.observability import analysis, otel  # noqa: E402


@pytest.fixture(scope="module")
def cases():
    return {c.claim_id: c for c in load_dataset(("dev", "redteam"))}


def _strings(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list | tuple):
        return [s for v in value for s in _strings(v)]
    return []


def _claim_text(ec) -> set[str]:
    """Free text of a claim that must never appear in a span: descriptions, diagnosis, documents."""
    raw = ec.claim.model_dump()
    texts = {b.description for b in ec.claim.bill_lines}
    texts.add((raw.get("hospitalisation") or {}).get("diagnosis") or "")
    texts.update(_strings(raw.get("documents") or {}))
    return {t for t in texts if t and len(t) >= 8}


# ------------------------------------------------------------------------------- redaction
def test_redaction_keeps_only_allowlisted_attributes():
    memory = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(otel.RedactingExporter(memory)))
    tracer = provider.get_tracer("t")
    with tracer.start_as_current_span("chat model") as span:
        span.set_attributes(
            {
                "claim.id": "CLM-1",
                "gen_ai.request.model": "m",
                "gen_ai.usage.input_tokens": 5,
                "gen_ai.input.messages": "Patient X, diagnosis Y",
                "traceloop.entity.input": "the prompt",
                "gen_ai.tool.call.arguments": '{"q": "cataract"}',
            }
        )
        span.add_event(
            "exception", {"exception.type": "ValueError", "exception.message": "Patient X"}
        )
        span.set_status(Status(StatusCode.ERROR, "ValueError: Patient X"))
    (out,) = memory.get_finished_spans()
    assert dict(out.attributes) == {
        "claim.id": "CLM-1",
        "gen_ai.request.model": "m",
        "gen_ai.usage.input_tokens": 5,
        "claimsense.redacted_attributes": 3,
    }
    assert dict(out.events[0].attributes) == {"exception.type": "ValueError"}
    assert out.status.status_code == StatusCode.ERROR
    assert out.status.description == "ValueError"


# ------------------------------------------------------------------- one claim, one trace
def test_a_claim_is_one_trace_with_each_step_as_a_child(cases):
    tel = otel.telemetry()
    t, trace_id = otel.run_claim(tel, cases["CLM-0004"].eval_case)
    rows = tel.rows()
    assert {r.trace_id for r in rows} == {trace_id}
    (root,) = analysis.roots(rows)
    assert root.name == otel.ROOT_SPAN and root.parent_id is None
    by_id = {r.span_id: r for r in rows}
    nodes = [r for r in rows if r.name.startswith("node ")]
    tools = [r for r in rows if r.name.startswith("execute_tool")]
    assert [n.name.split(" ", 1)[1] for n in sorted(nodes, key=lambda r: r.start_ns)] == t.path
    assert len(tools) == len(t.tool_spans)
    assert all(by_id[s.parent_id].name.startswith("node ") for s in tools)
    review = next(r for r in rows if r.name == "human_review")
    assert by_id[review.parent_id].name == "node human_review"
    assert review.attrs["hitl.decision"] == "reject"
    assert root.attrs["claim.route"] == t.route
    assert root.attrs["claim.settlement_inr"] == t.settlement_inr
    assert root.attrs["claim.id"] == "CLM-0004"


def test_spans_hold_no_claim_text(cases):
    """Rule 4: names, attributes and events of every span, for every dev and red-team claim."""
    tel = otel.telemetry()
    for case in cases.values():
        otel.run_claim(tel, case.eval_case, **VARIANTS["v1"])
    dumped = json.dumps([s.to_json() for s in tel.memory.get_finished_spans()])
    texts = {text for c in cases.values() for text in _claim_text(c.eval_case)}
    assert len(texts) > 50  # the check has something to find
    leaks = sorted(text for text in texts if text in dumped)
    assert leaks == []


def test_the_observer_changes_nothing_in_the_run(cases):
    for cid in ("CLM-0004", "CLM-0007", "CLM-9001"):
        plain = run_traced(cases[cid].eval_case).to_dict()
        watched, _ = otel.run_claim(otel.telemetry(), cases[cid].eval_case)
        watched = watched.to_dict()
        for d in (plain, watched):
            d.pop("seconds")
            for s in d["spans"]:
                s.pop("ms")
        assert watched == plain, cid


# ------------------------------------------------------------------------------ incidents
def test_a_tool_outage_is_an_error_span_and_shows_in_the_red_table(cases):
    import random

    tel = otel.telemetry()
    prepare = Fault(error_rate=1.0, delay_s=0.0).hook(random.Random(0))  # noqa: S311
    case = cases["CLM-0004"]  # has a procedure, so the fraud agent asks for the tariff range
    t, trace_id = otel.run_claim(tel, case.eval_case, prepare=prepare)
    rows = tel.rows()
    failed = [r for r in rows if r.name == "execute_tool tariff_range"]
    assert failed and all(r.error for r in failed)
    assert {r.attrs["error.type"] for r in failed} == {"TimeoutError"}
    assert analysis.red(rows)["execute_tool tariff_range"]["error_pct"] == 100.0
    (path,) = analysis.error_paths(rows)
    assert path["claim_id"] == "CLM-0004" and "tariff_range[FAILED]" in path["path"]
    root = analysis.roots(rows)[0]
    assert root.error == (t.status == "error")


def test_an_acl_refusal_leaves_a_span():
    tel = otel.telemetry()
    trace = Trace("CLM-X", "dev")
    with tel.tracer.start_as_current_span("node fraud"):
        _ToolLogTap(trace, otel.SpanObserver(tel.tracer)).append(
            {"agent": "fraud", "tool": "settle_claim", "allowed": False}
        )
    refused = next(r for r in tel.rows() if r.name == "execute_tool settle_claim")
    assert refused.attrs["claimsense.status"] == "blocked"
    assert trace.spans[0].status == "blocked"
    span = next(s for s in tel.memory.get_finished_spans() if s.name == refused.name)
    assert [e.name for e in span.events] == ["refused by the tool ACL"]


def test_the_guardrail_is_a_span_and_a_blocked_claim_has_no_agent_steps(cases):
    tel = otel.telemetry()
    t, _ = otel.run_claim(tel, cases["CLM-9001"].eval_case, **VARIANTS["guarded"])
    rows = tel.rows()
    guard = next(r for r in rows if r.name == "guardrail input_guardrail")
    assert guard.attrs["claimsense.guardrail.verdict"] == "flag"
    assert guard.attrs["claimsense.guardrail.findings"] >= 1
    assert t.status == "blocked" and not [r for r in rows if r.name.startswith("node ")]


def test_gate_and_usage_are_read_from_the_spans(cases):
    tel = otel.telemetry()
    for cid in ("CLM-0001", "CLM-0004", "CLM-0007"):
        otel.run_claim(tel, cases[cid].eval_case)
    g = analysis.gate(tel.rows())
    assert g["claims"] == 3 and g["sent_to_person"] == 3 and g["share_sent_to_person"] == 1.0
    assert g["decisions"] == {"reject": g["reviews"]}
    u = analysis.usage(tel.rows())
    assert u == {"model_call_spans": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}


# ------------------------------------------------- real mode: model-call spans, content off
def test_model_calls_become_child_spans_without_their_text_run_after_run():
    """The real-mode path, offline: LangChain's fake chat model stands in for OpenRouter.

    Two runs in one process, because the instrumentation cannot be re-instrumented (a second
    `instrument()` records nothing); `instrument_langchain` forwards instead.
    """
    pytest.importorskip("opentelemetry.instrumentation.langchain")
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
    from langchain_core.messages import AIMessage

    usage = {"input_tokens": 11, "output_tokens": 3, "total_tokens": 14}
    for _ in range(2):
        tel = otel.telemetry()
        assert otel.instrument_langchain(tel)
        assert os.environ[otel.CONTENT_SWITCH] == "false"
        model = GenericFakeChatModel(
            messages=iter([AIMessage(content="REPLY-TEXT-X", usage_metadata=usage)])
        )
        with tel.tracer.start_as_current_span("node coverage"):
            model.invoke("PROMPT-TEXT-X with a diagnosis")
        otel.uninstrument_langchain()
        model2 = GenericFakeChatModel(messages=iter([AIMessage(content="after")]))
        model2.invoke("not forwarded")  # after the run: no target, so no span
        rows = tel.rows()
        chat = [r for r in rows if r.attrs.get("gen_ai.operation.name") == "chat"]
        assert len(chat) == 1
        node = next(r for r in rows if r.name == "node coverage")
        assert chat[0].parent_id == node.span_id and chat[0].trace_id == node.trace_id
        assert chat[0].attrs["gen_ai.usage.input_tokens"] == 11
        assert analysis.usage(rows)["output_tokens"] == 3
        dumped = json.dumps([s.to_json() for s in tel.memory.get_finished_spans()])
        assert "TEXT-X" not in dumped and "diagnosis" not in dumped


# ------------------------------------------------------------------------- reading OTLP JSON
def test_spans_read_back_as_otlp_json_give_the_same_tree():
    body = {
        "resourceSpans": [
            {
                "resource": {"attributes": []},
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "0af7651916cd43dd8448eb211c80319c",
                                "spanId": "b7ad6b7169203331",
                                "name": otel.ROOT_SPAN,
                                "startTimeUnixNano": "1000000",
                                "endTimeUnixNano": "9000000",
                                "attributes": [
                                    {"key": "claim.id", "value": {"stringValue": "CLM-1"}},
                                    {"key": "claim.settlement_inr", "value": {"intValue": "42"}},
                                    {"key": "claim.route", "value": {"stringValue": "r"}},
                                ],
                                "status": {},
                            },
                            {
                                "traceId": "0af7651916cd43dd8448eb211c80319c",
                                "spanId": "00f067aa0ba902b7",
                                "parentSpanId": "b7ad6b7169203331",
                                "name": "execute_tool tariff_range",
                                "startTimeUnixNano": "2000000",
                                "endTimeUnixNano": "3000000",
                                "attributes": [],
                                "status": {"code": 2},
                            },
                        ]
                    }
                ],
            }
        ]
    }
    rows = analysis.from_otlp(body)
    root, tool = rows
    assert root.parent_id is None and root.attrs["claim.settlement_inr"] == 42
    assert tool.parent_id == root.span_id and tool.error and tool.ms == 1.0
    assert analysis.tree(rows).splitlines()[1].strip().startswith("execute_tool tariff_range")


def test_otlp_ids_in_base64_are_read_as_hex():
    assert analysis._otlp_id("AAAAAAAAAAE=", 16) == "0000000000000001"


# --------------------------------------------------------------------------------- Jaeger
def test_jaeger_listens_on_127_0_0_1_only_and_keeps_only_what_is_needed():
    from eval.observability import jaeger

    cfg = jaeger.config(14318, 26686, 26685)
    ext, rec = cfg["extensions"], cfg["receivers"]
    assert rec == {"otlp": {"protocols": {"http": {"endpoint": "127.0.0.1:14318"}}}}
    assert ext["jaeger_query"]["http"]["endpoint"] == "127.0.0.1:26686"
    assert ext["jaeger_query"]["grpc"]["endpoint"] == "127.0.0.1:26685"
    assert "ai" not in ext["jaeger_query"] and "otlp_proxy" not in ext["jaeger_query"]
    assert cfg["service"]["extensions"] == ["jaeger_storage", "jaeger_query"]
    assert cfg["service"]["telemetry"]["metrics"] == {"level": "none"}
    endpoints = json.dumps(cfg)
    assert "0.0.0.0" not in endpoints and "localhost" not in endpoints  # noqa: S104


def test_jaeger_archives_are_pinned_for_five_platforms():
    from eval.observability import jaeger

    assert set(jaeger.SHA256) == {
        "windows-amd64",
        "linux-amd64",
        "linux-arm64",
        "darwin-amd64",
        "darwin-arm64",
    }
    assert all(len(h) == 64 and int(h, 16) >= 0 for h in jaeger.SHA256.values())
    win = jaeger.archive("windows-amd64")
    assert win.filename == f"jaeger-{jaeger.VERSION}-windows-amd64.zip"
    assert win.url.startswith("https://github.com/jaegertracing/jaeger/releases/download/v")
    assert jaeger.archive("linux-arm64").filename.endswith("linux-arm64.tar.gz")


def test_a_streamed_api_answer_is_read_as_one_body():
    from eval.observability import jaeger

    one = '{"result": {"resourceSpans": [{"scopeSpans": []}]}}'
    assert len(jaeger.parse_traces(f"{one}\n{one}")["resourceSpans"]) == 2
    assert jaeger.parse_traces("") == {"resourceSpans": []}


def _otlp_body(spans) -> dict:
    """What an OTLP backend stores, as JSON (ids in base64, as the protobuf JSON mapping writes)."""
    from google.protobuf.json_format import MessageToDict
    from opentelemetry.exporter.otlp.proto.common.trace_encoder import encode_spans

    return MessageToDict(encode_spans(list(spans)))


class _FakeJaeger:
    def __init__(self, tel, drop: str | None = None) -> None:
        self.spans = [
            s for s in tel.memory.get_finished_spans() if f"{s.context.trace_id:032x}" != drop
        ]

    def services(self):
        return ["claimsense"]

    def find_traces(self, start, end, depth=1000):
        return _otlp_body(self.spans)

    def get_trace(self, trace_id):
        return _otlp_body(s for s in self.spans if f"{s.context.trace_id:032x}" == trace_id)


def test_the_read_back_proves_every_trace_arrived(cases):
    from eval.observability.__main__ import _read_back

    tel = otel.telemetry()
    ids = [otel.run_claim(tel, cases[c].eval_case)[1] for c in ("CLM-0001", "CLM-0004")]
    rows = tel.rows()
    good = _read_back(_FakeJaeger(tel), rows, 0, 1, wait_s=0)
    assert good["ok"] and good["traces_found"] == 2 and good["unredacted_keys_stored"] == []
    lost = _read_back(_FakeJaeger(tel, drop=ids[1]), rows, 0, 1, wait_s=0)
    assert not lost["ok"] and lost["traces_found"] == 1


@contextlib.contextmanager
def _local_server(get=None, post=None):
    """A one-thread HTTP server on 127.0.0.1. `get(path)` and `post(path)` return (code, body)."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        def _answer(self, fn):
            if fn is None:
                code, body = 405, b""
            else:
                code, body = fn(self.path)
            self.send_response(code)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802 - the http.server name
            self._answer(get)

        def do_POST(self):  # noqa: N802
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            self._answer(post)

        def log_message(self, *args):
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()


def test_a_404_from_jaeger_fails_the_read_back_instead_of_crashing_the_run(cases, tmp_path):
    """Jaeger API v3 answers 404 "No traces found" when nothing is stored, the very loss the
    read-back is there to catch: it must give ok=False (exit 1, outputs written), not an error."""
    from eval.observability import jaeger
    from eval.observability.__main__ import _read_back

    def get(path):
        if path.startswith("/api/v3/services"):
            return 200, b'{"services": ["claimsense"]}'
        return 404, b'{"error": {"httpCode": 404, "message": "No traces found"}}'

    tel = otel.telemetry()
    otel.run_claim(tel, cases["CLM-0004"].eval_case)
    with _local_server(get=get) as port:
        out = _read_back(jaeger.Jaeger(tmp_path, 1, port, 2), tel.rows(), 0, 1, wait_s=0)
    assert not out["ok"] and out["traces_found"] == 0 and out["example_spans_stored"] == 0


def test_run_with_memory_backend_writes_its_outputs(tmp_path, monkeypatch, capsys):
    from eval.observability import __main__ as cli

    monkeypatch.setattr(cli, "RUNS_DIR", tmp_path)
    monkeypatch.setenv("CLAIMSENSE_OBSERVABILITY_HOME", str(tmp_path / "home"))
    args = ["run", "--stub", "--backend", "memory", "--label", "t1", "--delay", "0"]
    assert cli.main(args) == cli.OK
    summary = json.loads((tmp_path / "t1" / "summary.json").read_text(encoding="utf-8"))
    assert summary["ok"] and summary["mode"] == "stub" and summary["claims_per_phase"] == 20
    assert summary["checks"]["exported_spans_redacted"]
    assert summary["red"]["outage"]["execute_tool tariff_range"]["errors"] > 0
    assert cli.CANARY not in summary["red"]["normal"]  # the canary is not part of the analysis
    assert (tmp_path / "t1" / "spans.csv").exists() and (tmp_path / "t1" / "trees.txt").exists()
    assert "every_claim_traced" in capsys.readouterr().out
    assert not (tmp_path / "home").exists()  # no machine-wide Jaeger lock for a memory run
    # A label that exists is refused: a report may quote it (the drill-1 lesson).
    assert cli.main(args) == cli.CANNOT_START


def test_a_run_fails_when_the_backend_refuses_spans_or_redaction_is_off(tmp_path, monkeypatch):
    """force_flush says True even when every batch got a 401, and a redaction check that reads
    the redacted copy can never fail: both checks must be able to fail."""
    from eval.observability import __main__ as cli

    monkeypatch.setattr(cli, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(otel, "keep", lambda key: True)  # redaction switched off
    with _local_server(post=lambda path: (401, b"")) as port:
        monkeypatch.setenv(
            "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", f"http://127.0.0.1:{port}/v1/traces"
        )
        args = ["run", "--stub", "--backend", "otlp-env", "--label", "t2", "--delay", "0"]
        assert cli.main(args) == cli.CHECK_FAILED
    summary = json.loads((tmp_path / "t2" / "summary.json").read_text(encoding="utf-8"))
    assert summary["delivered"]["sent"] == 0 and summary["delivered"]["failed"] > 0
    assert not summary["checks"]["backend_accepted_every_span"]
    assert not summary["checks"]["exported_spans_redacted"]


def test_the_jaeger_ports_never_clash_and_no_otlp_credential_reaches_jaeger(monkeypatch):
    import socket

    from eval.observability import jaeger
    from eval.observability.__main__ import _local_exporter

    busy = socket.socket()
    try:
        try:
            busy.bind(("127.0.0.1", 16685))  # the gRPC default is taken: its search hits the UI's
            busy.listen()
        except OSError:
            pass  # already taken by something else: the same case
        otlp, ui, grpc = jaeger.pick_ports()
    finally:
        busy.close()
    assert len({otlp, ui, grpc}) == 3

    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_HEADERS", "Authorization=Basic RkFLRQ==")
    assert not any(k.startswith("OTEL_") for k in jaeger.child_env())
    exporter = _local_exporter("http://127.0.0.1:4318/v1/traces")
    assert "authorization" not in exporter._client._headers
    assert os.environ["OTEL_EXPORTER_OTLP_TRACES_HEADERS"]  # put back for the other backends


def test_ctrl_c_while_jaeger_starts_stops_it(tmp_path, monkeypatch):
    import subprocess
    import sys

    from eval.monitoring import stack
    from eval.observability import jaeger

    monkeypatch.setenv("CLAIMSENSE_OBSERVABILITY_HOME", str(tmp_path))
    monkeypatch.setattr(jaeger, "ensure_binary", lambda log=print: tmp_path / "jaeger.exe")
    started = []

    def spawn(cmd, cwd, env, log_path):  # a sleeping process stands in for Jaeger
        started.append(subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"]))
        return started[0]

    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(stack, "_spawn", spawn)
    monkeypatch.setattr(stack, "wait_for", interrupted)
    with pytest.raises(KeyboardInterrupt):
        jaeger.start(log=lambda message: None)
    assert started[0].poll() is not None
    assert not (tmp_path / "pids.json").exists()


# ---------------------------------------------------------------------------- LangSmith
def test_langsmith_own_tracing_is_always_refused(monkeypatch):
    """HIDE_INPUTS/OUTPUTS do not hide a run's error text (it can quote the model's reply), and
    no environment variable can: LangSmith gets redacted spans over OTLP instead (rule 4)."""
    for ns in ("LANGSMITH", "LANGCHAIN"):
        for name in ("TRACING", "TRACING_V2", "HIDE_INPUTS", "HIDE_OUTPUTS"):
            monkeypatch.delenv(f"{ns}_{name}", raising=False)
    assert otel.langsmith_problem() is None
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    assert "rule 4" in otel.langsmith_problem()
    monkeypatch.setenv("LANGSMITH_HIDE_INPUTS", "true")
    monkeypatch.setenv("LANGSMITH_HIDE_OUTPUTS", "true")
    assert "rule 4" in otel.langsmith_problem()
    monkeypatch.setenv("LANGSMITH_TRACING", "1")  # LangSmith treats this as off
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")  # the older name switches it on
    assert "rule 4" in otel.langsmith_problem()
    monkeypatch.delenv("LANGCHAIN_TRACING_V2")
    assert otel.langsmith_problem() is None
