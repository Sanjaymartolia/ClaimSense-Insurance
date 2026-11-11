"""Observability for ClaimSense: OpenTelemetry traces of the claims pipeline (L14, AAI-14).

Owner: Eval & Red-Team. How to run it: `eval/observability/README.md`. The full write-up:
`docs/OBSERVABILITY_REPORT.md`.

    notebook section                      here
    1   the agent as a black box          the pipeline as `run_traced` runs it (eval/agent_suite)
    2   OpenTelemetry by hand             otel.py: Telemetry, SpanObserver, run_claim
    3   auto-instrumentation              otel.instrument_langchain (real mode, content off)
    4   Jaeger, one trace across services jaeger.py; `show` prints a traceparent header
    5   LangSmith                         environment variables only; otel.langsmith_problem
                                          refuses to run unless inputs and outputs are hidden
    6   an outage, debugged from spans    `run`: analysis.red, analysis.error_paths
    7   hooks that watch and act          the product's HookedToolBelt; its ACL refusals are spans
    8   a person in the loop              the `human_review` span; analysis.gate
    9   what did it cost                  analysis.usage

Two ways, as the lecture asks: the **simple** way (`show`) keeps spans in memory and prints them;
the **production** way (`run`) batches them over OTLP to Jaeger (or Langfuse, Phoenix, a
Collector), with the same redaction in front of every exporter.
"""
