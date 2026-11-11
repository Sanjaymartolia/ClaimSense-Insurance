# eval/observability: OpenTelemetry traces for ClaimSense (L14)

Owner: Eval & Red-Team. The full write-up, with results and a step-by-step guide, is
[docs/OBSERVABILITY_REPORT.md](../../docs/OBSERVABILITY_REPORT.md).

Monitoring (`eval/monitoring`) tells you *that* something is wrong. This package shows *what
happened*: every claim is one trace, and every step of it (graph node, tool call, guardrail,
model call, the person's review) is a span with a parent, a start, an end and attributes.

## Run it

```bash
pip install -e ".[dev,agents,observability,docs]"

# 1. the simple way: spans in memory, one trace printed as a tree (free, no server)
python -m eval.observability show --stub                  # CLM-0004
python -m eval.observability show --stub CLM-9001 --variant guarded --json

# 2. the production way: spans over OTLP to Jaeger, a normal batch and a tool outage
python -m eval.observability setup                        # once: Jaeger 2.22.0, ~65 MB
python -m eval.observability run --stub --label my-trace-run --keep
#    open http://127.0.0.1:16686, service "claimsense"; Ctrl+C stops Jaeger
python -m eval.observability down                         # only after an interrupted run
```

**Real models.** Leave out `--stub` with `OPENROUTER_API_KEY` set: the agents call OpenRouter and
every model call becomes a `chat` span (tokens, model, latency; never the prompt or the reply).
`show` costs about $0.001 per claim; `run` sends 40 claims (about $0.03).

**Other backends.** The same spans go to any OTLP backend with `--backend otlp-env`:

```bash
# Langfuse (cloud or self-hosted): Basic auth = base64("<public key>:<secret key>")
#   printf '%s' "pk-...:sk-..." | base64 -w 0      # -w 0: one line, or the header is dropped
export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT="https://cloud.langfuse.com/api/public/otel/v1/traces"
export OTEL_EXPORTER_OTLP_TRACES_HEADERS="Authorization=Basic <base64>"
python -m eval.observability run --stub --backend otlp-env --label my-langfuse-run

# LangSmith, over OTLP (the exporter appends /v1/traces)
export OTEL_EXPORTER_OTLP_ENDPOINT="https://api.smith.langchain.com/otel"
export OTEL_EXPORTER_OTLP_HEADERS="x-api-key=<key>,Langsmith-Project=claimsense-eval"
python -m eval.observability run --stub --backend otlp-env --label my-langsmith-run
```

The check `backend_accepted_every_span` counts what the backend accepted: a wrong key fails the
run (the SDK's flush alone reports success even then).

**LangSmith's own LangChain tracing** (`LANGSMITH_TRACING=true`) is refused, by this package and
by the DeepEval suite. It bypasses the redaction, and `LANGSMITH_HIDE_INPUTS/OUTPUTS` do not hide
a run's error text (the exception and its traceback, which can quote the model's reply). Use the
OTLP route above.

`run` options: `--backend jaeger|otlp-env|memory`, `--split dev|redteam`, `--workers 4`,
`--error-rate 0.7`, `--delay 1.5`, `--seed 0`, `--open`, `--keep`. A label that already exists is
refused: a report may quote it. Exit code: 0 every check holds, 1 a check failed, 2 cannot start.

Outputs in `runs/observability/<label>/`: `summary.json` (everything the report quotes),
`spans.csv` (one row per span: names, times, status; no attributes), `trees.txt` (one trace per
phase), `red.png` (errors and p95 per span name, normal against outage).

## What is where

| Notebook section | Here |
|---|---|
| 2 spans by hand, GenAI names | `otel.py`: `SpanObserver`, `run_claim` (`invoke_agent claimsense`, `node <name>`, `execute_tool <tool>`, `human_review`) |
| 3 auto-instrumentation | `otel.instrument_langchain` (real mode; content capture off) |
| 4 Jaeger; one trace across services | `jaeger.py`; `show` prints the `traceparent` header |
| 5 LangSmith | OTLP (`--backend otlp-env`); its own tracing refused by `otel.langsmith_problem` |
| 6 an outage from the spans | `run`: `analysis.red`, `analysis.error_paths` |
| 7 hooks | the product's `HookedToolBelt`; an ACL refusal is a span with an event |
| 8 a person in the loop | the `human_review` span (`hitl.*`); `analysis.gate` |
| 9 cost | `analysis.usage` |

The spans open *while* the pipeline runs, through `run_traced(observer=...)` in
`eval/agent_suite/trace.py`. Without an observer that function is unchanged.

## Rules this package keeps

- **Rule 4.** Every exporter sits behind `RedactingExporter`: an attribute leaves the process only
  if it is on an allowlist (ids, codes, counts, redacted argument shapes, model and token counts).
  Prompts, replies, tool arguments as the instrumentation records them and exception messages are
  dropped. `eval/tests/test_observability.py` checks all 52 dev and red-team claims for leaks,
  and every `run` sends a canary span with a forbidden attribute that must come out without it.
- Jaeger listens on 127.0.0.1 only, with OTLP over HTTP in and the UI and query API out; no
  gRPC, Zipkin, Jaeger-thrift, MCP or metrics port. It gets no key-like and no `OTEL_*`
  environment variable, and the exporter to it sends no header from the environment.
- `monitoring/`, `docker-compose.yml` and `src/` are not touched.

## Remove it

Delete `~/.claimsense/observability_stack` (or `$CLAIMSENSE_OBSERVABILITY_HOME`).

## Tests

`pytest eval/tests/test_observability.py -q`: no key, no Jaeger; two tests start a small HTTP
server on 127.0.0.1.
