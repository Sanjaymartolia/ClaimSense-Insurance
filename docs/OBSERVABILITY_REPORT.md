# ClaimSense: Production Evaluation Tools and Observability

| Item | Value |
|---|---|
| Document | CS-EVAL-TR-002, Issue 1 |
| Date | 11 November 2026 |
| Owner | Eval & Red-Team |
| Readers | The six ClaimSense roles, and the course reviewers |
| Writing standard | ASD-STE100 style, about 80% (Section 2.4) |
| Related | `docs/TECHNICAL_REPORT_EVAL_AND_MONITORING.md` (CS-EVAL-TR-001) |

---

## 1. Summary

This report records two pieces of work. The first piece applies lecture AAI-13 (production
evaluation). The second piece applies lecture AAI-14 and the L14 hands-on notebook
(observability). Section 12 is a step-by-step guide for the terminal.

- **Production evaluation tools.** We examined the nine tools that AAI-13 names. We built a test
  suite with DeepEval. The harness had RAGAS before this work. LangSmith and Langfuse need configuration
  only. Section 3 gives each decision and its reason.
- **DeepEval suite.** `eval/deepeval_suite/` holds 118 tests. 74 tests need no model and no key.
  All 74 pass in stub mode, through `pytest` and through `deepeval test run`. The other 44 tests
  use an LLM judge. They are opt-in because they cost money. They have not run yet.
- **Observability, the simple way.** `python -m eval.observability show` records one claim as an
  OpenTelemetry trace in memory and prints it as a tree. Claim CLM-0004 gives 26 spans.
- **Observability, the production way.** `python -m eval.observability run` sends 40 claims to a
  local Jaeger over OTLP: 20 normal claims, then the same 20 during a tariff-tool outage. Jaeger
  stored all 40 traces. The backend accepted all 663 spans. All seven checks of the run passed.
- **What the traces showed.** During the outage, 13 claims called the tariff tool and all 13
  calls failed. Each of the 13 claims stopped with a `TimeoutError` at that call. No claim tried
  again or used another path. This confirms finding MON-01 from the spans alone.
- **Rule 4 (no health details).** Each exporter sits behind an allowlist. A test runs all 52 dev
  and red-team claims and finds no claim text in any span. Jaeger gave back all 663 spans of the
  run, and no span holds an attribute outside the allowlist. A canary span with a forbidden
  attribute goes out with each run. It proves that the redaction is in the export path.
- **Real models.** The real-model path is built and tested offline with a fake model. A run with
  real models needs your key. Section 12.7 tells you how to do it. It costs about $0.03.
- **Side effects found and controlled.** DeepEval copies `.env` into the environment when Python
  imports it, and its pytest plugin loads in every pytest run. With a key in `.env`, stub tests
  can call paid models. The suite sets `DEEPEVAL_DISABLE_DOTENV=1` before the import, and
  `pyproject.toml` stops the plugin (finding OBS-02).
- **Adversarial review.** A review of this work found 13 defects. One check did not fail
  in any condition. A lost trace stopped the run with the wrong exit code. A DeepEval test
  passed when the pipeline crashed. All 13 are fixed, each with a test or a probe (Section 8.1).

---

## 2. Introduction

### 2.1 Purpose

This report tells the team which production evaluation tools ClaimSense uses and why. It also
tells the team how to see inside one claim. A trace shows which steps ran, in which order, how
long each step took, and where a failure started.

### 2.2 Scope

The work is in the evaluation area of the repository (`eval/`). It does not change the product
code in `src/`. It does not change the files of Deploy & Ops (`monitoring/`, `docker-compose.yml`,
`.github/`). One evaluation file got a small, optional extension (Section 6.1).

### 2.3 Sources

The sources are three course documents: AAI-13 (Monitoring and Evaluation of Multi-Agent
Systems), AAI-14 (Observability for AI Agents) and the notebook `L14_observability_handson_2`.
The documents are for personal use. This report describes their ideas in its own words and
applies them to ClaimSense. It does not copy slides or notebook code.

### 2.4 Writing standard

This report follows the ASD-STE100 rules for most text:

- one topic in each sentence, and short sentences.
- the active voice, and commands in procedures.
- one word for one meaning.

Tool names, metric names and code names stay as they are, because a reader must type them
exactly. Some technical verbs are not in the STE dictionary (for example "export" and "trace"),
and this report uses them.

### 2.5 Terms

| Term | Meaning in this report |
|---|---|
| Span | The record of one unit of work: a name, a start, an end, a parent, attributes and a status |
| Trace | All the spans of one claim. They share one trace id |
| Attribute | One key and value on a span, for example `claim.route = needs_review` |
| OTLP | The OpenTelemetry protocol that sends spans to a backend |
| Exporter | The part that sends finished spans to a place (memory, Jaeger, Langfuse) |
| Backend | A server that keeps spans and lets you search them (Jaeger, Langfuse, LangSmith) |
| Redaction | The removal of attributes that can hold claim text, before a span leaves the process |
| Stub mode | The agents use deterministic code. No model call. Free |
| Real mode | The agents call models through OpenRouter. It costs money |
| Judge | An LLM that scores an output against a rubric |

---

## 3. Production evaluation tools (AAI-13)

### 3.1 The nine tools

AAI-13 names nine production tools. The table gives our decision for each tool.

| Tool | What it does | Decision for ClaimSense | Reason |
|---|---|---|---|
| OpenTelemetry | The open standard for traces. Every backend below accepts it | **Built** (Section 6) | One instrumentation, many backends. The choice of backend stays open |
| DeepEval | Tests for LLM output, in the style of pytest. Many metrics, and custom metrics | **Built** (Section 4) | AAI-13 recommends it for task-specific gates in CI |
| RAGAS | Metrics for retrieval and generation, for example faithfulness | **Already built** (`--judge` in the harness) | ragas 0.4.3 is the newest release. No change |
| Jaeger | An open-source trace viewer and store | **Built** (local, Section 6.5) | The notebook uses it. It runs on this machine without Docker |
| LangSmith | A hosted platform for LangChain traces and evaluation | **Configuration only** (Section 6.8) | It accepts OTLP, so the same exporter sends redacted spans to it. Its own LangChain tracing is refused (rule 4) |
| Langfuse | An open-source platform for traces and evaluation. You can host it yourself | **Configuration only** (Section 6.9) | It accepts OTLP. `.env.example` has its keys. The same exporter sends to it |
| Arize Phoenix | An open-source trace viewer with evaluation | Report only | It accepts OTLP, so it needs the same configuration as Langfuse |
| Logfire | A general observability platform with LLM support | Report only | It accepts OTLP. The team has no account |
| promptfoo | A configuration-driven matrix of prompts and models, with red-team plug-ins | Report only | It runs on Node.js. Our red-team set (30 claims) does this job |
| OpenAI Evals | A registry of evaluation templates for model comparisons | Report only | ClaimSense does not compare base models now |

### 3.2 How the tools fit together

AAI-13 gives a rule of thumb. Use RAGAS for retrieval health and DeepEval for unit tests in CI.
Use LangSmith or Langfuse for traces and evaluation in one place. ClaimSense now follows this rule:

| Question | Tool in ClaimSense |
|---|---|
| Are the rationales supported by the retrieved clause? | RAGAS faithfulness (`python -m eval.harness.run --judge`) |
| Did the pipeline call the right tools, and never a forbidden tool? | DeepEval (`deepeval test run eval/deepeval_suite`) |
| What did one claim do, step by step? | OpenTelemetry spans in Jaeger, Langfuse or LangSmith |
| Is the pipeline healthy now? | Prometheus and Grafana (`eval/monitoring`, CS-EVAL-TR-001) |

### 3.3 Installed versions

Two new optional extras hold the new packages (`pyproject.toml` and `requirements.txt`). CI
installs only `.[dev]`, so CI does not change.

| Extra | Packages |
|---|---|
| `observability` | opentelemetry-sdk 1.45.2, opentelemetry-exporter-otlp-proto-http 1.45.2, opentelemetry-instrumentation-langchain 0.63.0 |
| `deepeval` | deepeval 4.3.3. It changes click from 8.5.1 to 8.3.3. uvicorn accepts this version |

---

## 4. The DeepEval suite

### 4.1 Design

Each claim is one DeepEval test case. The suite has two files.

| Test | Metric | Claims | Needs |
|---|---|---|---|
| The pipeline does not crash, and each node calls the tools that its design specifies | `ToolCorrectnessMetric` (DeepEval), threshold 1.0 | 22 dev | Nothing |
| No crash, no forbidden tool, one policy search for each bill line, and the tool budget holds | `TrajectoryRulesMetric` (custom, code only) | 22 dev + 30 red-team | Nothing |
| The review payload meets the checklist | `GEval` with the agent-suite checklist | 22 dev | Key, `CLAIMSENSE_DEEPEVAL_JUDGE=1` |
| Each deduction agrees with the clause that it cites | `FaithfulnessMetric` | 22 dev | Key, `CLAIMSENSE_DEEPEVAL_JUDGE=1` |

The expected tools come from the design of the pipeline, not from the gold answers. Each tool
name includes the node that must call it:

- for every claim that enters the graph, admissibility reads the policy
  (`admissibility:get_policy`).
- for an admissible claim, coverage also searches the policy and calculates the rupees in code
  (`coverage:policy_search`, `coverage:calculate`). The fraud agent reads the claim history
  (`fraud:claim_history`).
- for a claim with a procedure, the fraud agent also checks the tariff range
  (`fraud:tariff_range`).
- coverage searches the policy one time for each bill line, on each attempt.
  `ToolCorrectnessMetric` cannot count, so `TrajectoryRulesMetric` does this check.

These are the path checks of the agent suite (`eval/agent_suite/process.py`). A crash fails both
tests. Before the review, a crash left the claim without an admissibility result, and the tests
then expected only `get_policy`.

The forbidden tools are `settle_claim` and `record_repudiation`. The tool budget is
`budgets.max_tool_calls_per_claim` in `config/models.yaml` (40).

The judge model is `judge` in `config/models.yaml`. This model is from a different family than
the agents, as AAI-13 recommends. The judge has no calibration against people yet, so its scores
are opinions, not a gate.

### 4.2 Rule 4 in the test cases

DeepEval keeps each test case in its local cache (`.deepeval/`) and prints it when a test fails.
Thus a test case holds no claim text:

- the input is the claim id.
- the output is the route, the amount and the status.
- the tools are node and tool names only.
- the metadata holds the status, the type of an exception (not its message) and a count.

The judge reads the review payload and the policy text. Both hold no health details by design. A
check of the cache after a run found none of the claim texts in it.

### 4.3 A model that must not be called

DeepEval 4.3.3 makes a model object for each metric, also for a metric that never asks a model.
Without an OpenAI key, `ToolCorrectnessMetric` stops at once. The suite gives it `OfflineModel`.
This model stops the test if a metric calls it. The tests pass with it. This proves that tool
correctness needs no model and that no data leaves the machine.

### 4.4 Results

| Run | Command | Result | Time |
|---|---|---|---|
| Stub, plain pytest | `CLAIMSENSE_LLM=stub pytest eval/deepeval_suite` | 74 pass, 44 skip (judge off) | 5.6 s |
| Stub, DeepEval runner | `DEEPEVAL_DISABLE_DOTENV=1 DEEPEVAL_TELEMETRY_OPT_OUT=1 CLAIMSENSE_LLM=stub deepeval test run eval/deepeval_suite` | 74 of 74 pass, pass rate 100% | 8.3 s |
| Real models | `deepeval test run eval/deepeval_suite` | Not run yet (needs your key) | — |
| LLM judge | `CLAIMSENSE_DEEPEVAL_JUDGE=1 deepeval test run eval/deepeval_suite` | Not run yet (needs your key) | — |

In stub mode, no claim crashed. Each of the 22 dev claims called the tools that its path
specifies, from the correct node. Coverage searched the policy for each bill line. No claim, dev
or red-team, ran a forbidden tool. Each claim stayed within the tool budget of 40.

Three probes showed that the tests now fail when they must. A crash in `calculate` gave "pipeline
crashed: RuntimeError". When coverage did not call `calculate`, the tool score was 0.8, below the
threshold of 1.0. When coverage searched one of five lines, the rules metric gave 0.

---

## 5. Observability in brief (AAI-14)

**Monitoring and observability.** Monitoring tells you that something is wrong. Observability
helps you find out what happened. A system is observable when the data that it records
can answer a new question without a code change. ClaimSense has both now: `eval/monitoring` for
alerts, and `eval/observability` for traces.

**Three signals, and a fourth.** Metrics tell you that there is a problem. Traces show the path
of one request. Logs give the detail of each step. For agents, AAI-14 adds a fourth signal:
quality, which means the evaluation scores and human feedback for one run.

**A trace is a tree of spans.** Each step of a claim is one span: a graph node, a tool call, a
model call, a guardrail check, a review by a person. A span opened inside another span becomes
its child. All spans of one claim share one trace id.

**Names that every tool can read.** The OpenTelemetry GenAI conventions fix the names of agent
spans. Examples are `invoke_agent <name>` for a run, `execute_tool <tool>` for a tool call and
`chat <model>` for a model call. A backend that knows these names shows the spans correctly.

**Traces hold people's data.** A trace store keeps a copy of each request. Prompts, tool
arguments and results can hold personal data or secrets. Remove them before export. Removal
changes what the store keeps. It does not change what the agent sees.

**The cost of tracing.** For an agent, the CPU cost of a span is small compared with a model
call. The main cost is the volume of data that you send and keep.

---

## 6. What we built

### 6.1 Spans that open while the claim runs

A span must open before its step starts. Only then do the model-call spans inside a node become
children of that node. Before this work, the agent suite timed each node and each tool call
(`eval/agent_suite/trace.py`). We added one optional argument: `run_traced(observer=...)`.

- `observer.step(span)` opens around each node, tool call, guardrail check and ACL refusal.
- `observer.review(payload, decide)` opens around the decision of the person.

With no observer, the code takes the old path. The pinned scores of the harness suite did not
change (nine of nine rows match). A test runs three claims with and without an observer and
compares the two results field by field.

### 6.2 Span names and attributes

| Span | Name | Attributes (all content-free) |
|---|---|---|
| One claim (root) | `invoke_agent claimsense` | `claim.id`, `claim.route`, `claim.status`, `claim.settlement_inr`, `claim.flags`, `claim.citations`, `claim.tool_calls`, `claim.tool_errors`, `claim.llm_calls`, `claim.tokens`, `claim.cost_usd`, `claimsense.phase`, `claimsense.mode`, `gen_ai.conversation.id` |
| Graph node | `node <name>` | `claimsense.node`, `claimsense.status` |
| Tool call | `execute_tool <tool>` | `gen_ai.tool.name`, `claimsense.agent`, `claimsense.tool.args` (shapes only, for example `<text 28 chars>`), `claimsense.tool.result` (ids and counts), `error.type` |
| ACL refusal | `execute_tool <tool>` | `claimsense.status = blocked`, and the event "refused by the tool ACL" |
| Guardrail | `guardrail input_guardrail` | `claimsense.guardrail.verdict`, `claimsense.guardrail.findings` |
| Person's review | `human_review` | `hitl.level`, `hitl.kind`, `hitl.decision`, `hitl.reviewer`, `hitl.proposed_inr`, `hitl.fraud_flags`, `hitl.wait_s` |
| Model call (real mode) | from the instrumentation, for example `ChatOpenAI.chat` | `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens` |

The tool arguments and results use the redaction that the agent suite applies. Clause ids
and categories stay. Free text becomes its length only.

### 6.3 The simple way

`python -m eval.observability show` makes a new tracer provider for the run. It does not use the
global provider. It keeps each finished span in memory and prints each claim as an indented tree.
With `--json`, it also prints two spans in the form that an exporter sends. It also prints the
`traceparent` header. This header carries the trace id into another service, for example an MCP
server (notebook section 4.2).

### 6.4 The production way

```
claim -> run_traced(observer) -> spans -> BatchSpanProcessor  -> RedactingExporter -> OTLP/HTTP -> Jaeger
                                       \-> SimpleSpanProcessor -> RedactingExporter -> memory (analysis)
```

Each processor holds a `RedactingExporter`, and the redaction runs when a span is exported. The
batch processor keeps the spans in its queue before the redaction, in this process only. If you
put a Collector between the process and the backend, keep the redaction in the process.

`python -m eval.observability run`:

1. Starts Jaeger. You can also send to another OTLP backend, or keep the spans in memory only.
2. Sends the dev claims, four at a time (22 since 12 November 2026, 20 in the run of Section 7.2).
3. Sends the same claims again. During this phase, `tariff_range` waits 1.5 s and then fails
   70% of the time.
4. Sends one canary span with a forbidden attribute. Then it asks Jaeger for every trace of
   the run, and for one full trace.
5. Makes the RED table (rate, errors, duration) for each span name, for each phase.
6. Lists what each claim did after a tool failed.
7. Reads the approval gate and the model cost from the spans.
8. Writes `summary.json`, `spans.csv`, `trees.txt` and `red.png` to `runs/observability/<label>/`.

The run passes only if all its checks hold. A Jaeger run has seven checks. A run to another
backend has six, because only Jaeger can be read back:

- each claim gave one trace (`every_claim_traced`, `one_trace_per_claim`).
- the normal phase had no tool errors.
- the outage shows in the spans.
- the canary span came out without its forbidden attribute (`exported_spans_redacted`).
- the backend accepted each span, by count (`backend_accepted_every_span`). The SDK flush
  reports success also when the backend refuses each batch. Thus the exporter counts each
  answer.
- Jaeger returned every trace and the same number of spans for the example trace. No span
  that it returned has an attribute outside the allowlist (`jaeger_read_back`).

An answer of 404 from Jaeger ("No traces found") counts as a lost trace. The check fails and
the outputs are still written.

### 6.5 Jaeger

Jaeger v2.22.0 is one program. `python -m eval.observability setup` downloads it once (65 MB),
checks it against the SHA-256 that Jaeger publishes, and unpacks it in
`~/.claimsense/observability_stack`. The GitHub asset digests agree with these checksums. The
stock configuration of Jaeger opens many ports. Our configuration keeps only three, all on
127.0.0.1:

| Port | Use |
|---|---|
| 4318 (or the next free port) | OTLP over HTTP: spans in |
| 16686 (or the next free port) | The web UI and the query API v3 |
| 16685 (or the next free port above the UI port) | The query gRPC port (Jaeger needs it) |

There is no gRPC receiver, no Zipkin or Jaeger-thrift receiver, no MCP endpoint and no metrics
port. A check with `netstat` showed the three ports on 127.0.0.1 only. After the run, no
`jaeger.exe` process stayed. If you push Ctrl+C when Jaeger starts, the tool stops Jaeger. The
Jaeger process gets no `OTEL_*` variable, and its exporter sends no credential from the
environment.

### 6.6 Redaction (rule 4)

Every exporter sits behind `RedactingExporter`. It keeps an attribute only if the attribute is on
an allowlist:

- the attributes that this package writes itself (`claim.*`, `claimsense.*`, `hitl.*`), from
  values that hold no claim text.
- the instrumentation attributes that name the model, count tokens or name the kind of step.

The exporter removes all other attributes: prompts, replies, tool arguments as the
instrumentation records them, and the messages of exceptions. An exception keeps its type only.
The memory exporter gets the same redacted copy, so the tests check what Jaeger receives.

### 6.7 Model calls in real mode

In real mode, the LangChain instrumentation (OpenLLMetry) adds a span for each model call. It
records the model, the tokens and the time. It does not record the prompt or the reply, because
`TRACELOOP_TRACE_CONTENT` is set to `false`. The allowlist removes them a second time if this
setting changes.

The instrumentation of version 0.63 cannot be switched on a second time in one process (finding
OBS-03). Thus the package switches it on once and sends its spans to the current run.

### 6.8 LangSmith

LangSmith has two ways in:

- **Its own LangChain tracing** (`LANGSMITH_TRACING=true`). Its runs do not go through our
  redaction. `LANGSMITH_HIDE_INPUTS` and `LANGSMITH_HIDE_OUTPUTS` hide the prompts and the
  replies. They do not hide the error text of a run. This text is the exception and its
  traceback, and it can quote a reply of the model. No environment variable hides it. For this
  reason `eval.observability` and the DeepEval suite refuse to start when this tracing is on.
- **OTLP.** LangSmith accepts OTLP at `https://api.smith.langchain.com/otel`, with the header
  `x-api-key`. The option `--backend otlp-env` sends the same redacted spans to it
  (Section 12.9).

LangSmith switches its tracing on only for the exact value `true` in lower case. The check uses
the same rule.

### 6.9 Langfuse and other OTLP backends

Langfuse accepts OTLP. The option `--backend otlp-env` sends the same redacted spans to the
address in `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`, with the headers in
`OTEL_EXPORTER_OTLP_TRACES_HEADERS`. LangSmith, Arize Phoenix and an OpenTelemetry Collector
work the same way. Section 12.8 gives the steps.

### 6.10 Hooks and the person in the loop

AAI-14 separates hooks that watch from hooks that act. A hook that only watches must not be a guard,
because LangChain callbacks fail open: an error in a callback does not stop the run. ClaimSense
has hooks that act and fail closed: `HookedToolBelt` in `src/claimsense/hooks/` checks the
tool ACL and the tool budget before each call. A hook that acts must leave a record. Each ACL
refusal is now a span with the event "refused by the tool ACL".

The approval gate pauses the graph and gives the payload to a person. Each review is now a
`human_review` span. The spans show the share of claims sent to a person, each decision and the
time to decide. In evaluation, the reviewer is the harness. It always declines in a fraction of a
millisecond. Thus the gate figures describe the harness, not real adjudicators.

### 6.11 Notebook sections and where they are in ClaimSense

| Notebook | Idea | ClaimSense |
|---|---|---|
| 1 | The answer alone cannot explain a decision | One claim through `run_traced` |
| 2 | Spans by hand, GenAI names, attributes, events, status | `otel.SpanObserver`, `otel.run_claim` |
| 3 | A span for every step, plus one span for the business facts | `otel.instrument_langchain`, the root span |
| 4 | A trace viewer. One trace across services | `jaeger.py`; `show` prints `traceparent` |
| 5 | LangSmith | OTLP (`--backend otlp-env`). Its own tracing is refused: `otel.langsmith_problem` |
| 6 | An outage, debugged from spans | `run`: RED table, error paths |
| 7 | Callbacks watch and fail open. Middleware acts | `HookedToolBelt` fails closed. Refusals are spans |
| 8 | A person in the loop, on the trace | The `human_review` span, `analysis.gate` |
| 9 | Ask the traces what the run cost | `analysis.usage` |

---

## 7. Results

### 7.1 The simple way: claim CLM-0004 in stub mode

The trace has 26 spans:

- the root span.
- 7 node spans.
- 17 tool-call spans.
- 1 review span.

Part of the tree:

```
invoke_agent claimsense            38.0 ms   route=ready_for_approval Rs 80,990 status=rejected
  node admissibility                0.3 ms
    execute_tool get_policy         0.0 ms   coverage: {"policy_number": "<text 9 chars>"} -> policy found
  node coverage                     1.4 ms
    execute_tool policy_search      0.1 ms   coverage: {"category": "procedure", "query": "<text 28 chars>"} -> 2 passages
  node fraud                        0.9 ms
    execute_tool tariff_range       0.0 ms   fraud: {"city_tier": "tier_1", "procedure": "<text 28 chars>"} -> none
  node human_review                 0.5 ms
    human_review                    0.1 ms   decision=reject proposed=Rs 80990
```

### 7.2 The production way: run `stub-jaeger-2`

The run used stub agents and Jaeger 2.22.0. It sent 20 dev claims in each phase, four at a time.
The run took 6 s and made 662 claim spans: 380 in the normal phase and 282 in the outage. With
the canary span, the exporter sent 663 spans.

This run replaces the first evidence run, `stub-jaeger`. The review (Section 8.1) changed three
checks after that run. The folder of the first run stays as it was. The two runs gave the same
counts, the same errors and the same error paths. Only the times are different.

| Span | Normal: spans | Normal: errors | Normal: p95 | Outage: spans | Outage: errors | Outage: p95 |
|---|---|---|---|---|---|---|
| `invoke_agent claimsense` | 20 | 0% | 72.9 ms | 20 | 65.0% | 1,510.9 ms |
| `node fraud` | 14 | 0% | 11.6 ms | 14 | 92.9% | 1,506.7 ms |
| `execute_tool tariff_range` | 13 | 0% | 0.0 ms | 13 | 100% | 1,504.9 ms |
| `human_review` | 20 | 0% | 0.0 ms | 7 | 0% | 0.0 ms |

Chart: `runs/observability/stub-jaeger-2/red.png`. It shows the errors and the p95 time for each
span name, normal against outage.

- **Where the time went.** During the outage, the p95 time of a claim went from 73 ms to
  1,511 ms. The tariff call took almost all of this time. The other tools stayed below 1 ms.
- **What each claim did after the error.** In each of the 13 claims, the path was `get_policy ->
  calculate -> claim_history -> get_policy -> tariff_range[FAILED]`. Then the claim stopped with
  `TimeoutError`. No claim tried again, and no claim continued without the tariff range.
- **Seed note.** At an error rate of 70%, 13 failures from 13 calls are not the expected mean.
  They follow from seed 0: each of the 13 claims drew a number below 0.7. Another `--seed` gives
  a mix of passed and failed calls.
- **The gate.** In the normal phase, 20 of 20 claims went to a person. In the outage, only 7 of
  20 went to a person. The other 13 claims stopped before the review.
- **What Jaeger stored.** Jaeger accepted 663 of 663 spans and refused none. It listed the
  service `claimsense` and returned 40 of the 40 traces. The example trace had 23 spans in
  Jaeger and 23 spans sent. Jaeger returned all 663 spans, and no span had an attribute outside
  the allowlist. The canary came back without its forbidden attribute.
- **Checks.** All seven checks passed. Exit code 0.

### 7.3 Real mode

The real-model path has an offline test. LangChain's fake chat model stands in for OpenRouter. The
test finds these results:

- the model call becomes a `chat` span.
- the parent of that span is the node span that was open.
- the span keeps 11 input tokens and 3 output tokens.
- no text of the prompt or the reply is in any exported span.
- the second run in the same process also gets its spans.

A run with real models needs your OpenRouter key. Claude's shell has no key and must not read
`.env`. Section 12.7 gives the steps. Add the result of that run to this report as a new issue.

### 7.4 Tests

| Check | Result |
|---|---|
| `pytest eval/tests` | 299 tests: 288 pass, 9 strict `xfail` pass by failure, 2 skip |
| New tests in `eval/tests/test_observability.py` | 21. No key and no Jaeger. Two tests use a small HTTP server on 127.0.0.1 |
| DeepEval suite, stub | 74 pass. 44 judge tests skip until you opt in |
| Product tests (`pytest`) | 124 pass, 4 skip, 1 `xfail`. The same as before this work |
| Harness suite (`python -m eval.harness.suite`) | Nine of nine rows match. The new seam changed no score |
| `ruff check` and `ruff format --check` on the new and changed files | Clean |

---

## 8. Findings

| ID | Finding | Status |
|---|---|---|
| OBS-01 | When `tariff_range` fails, the claim stops with an error. The fraud agent has no fallback (`src/claimsense/agents/fraud.py`). The spans show this without a log or a metric. This confirms MON-01 | Open. Owner: Agents & Orchestration. The strict `xfail` for MON-01 stays |
| OBS-02 | `import deepeval` copies `.env` into the environment. The `deepeval` extra also installs a pytest plugin that loads in every pytest run, imports DeepEval and makes a `.deepeval/` folder. With a key in `.env`, the stub tests can call paid models | Controlled. The suite's `conftest.py` sets `DEEPEVAL_DISABLE_DOTENV=1` before the import. `pyproject.toml` adds `-p no:deepeval`. The `deepeval test run` command imports DeepEval before pytest starts, so export `DEEPEVAL_DISABLE_DOTENV=1` first (Section 12.10). `.deepeval/` is in `.gitignore` |
| OBS-03 | opentelemetry-instrumentation-langchain 0.63 records nothing after `uninstrument()` and a second `instrument()` in one process | Controlled. `instrument_langchain` instruments once and forwards spans to the current run |
| OBS-04 | LangSmith's own tracing sends the error text of each run (the exception and its traceback), also with `LANGSMITH_HIDE_INPUTS` and `LANGSMITH_HIDE_OUTPUTS` set to `true`. This text can quote a reply of the model. No environment variable hides it | Fixed. The tools refuse LangSmith's own tracing. LangSmith gets the redacted spans over OTLP. A test checks the refusal with both hide variables set |
| OBS-05 | `ToolCorrectnessMetric` (DeepEval 4.3.3) makes an OpenAI client even when it needs no model, and stops without a key | Controlled. `OfflineModel` refuses each call, which also proves that no call occurs |
| OBS-06 | The evaluation reviewer always declines at once, so the gate spans measure the harness, not people | Limit. Real figures need real adjudicators (Section 9) |

### 8.1 Adversarial review

A review with independent agents read the new code and this report. One set of agents looked
for defects. A second set of agents tried to disprove each defect with a probe. The second set
did not disprove any of the 13 code defects. The usage limit stopped 12 checks of the second set.
We then checked those 12 findings ourselves against the code. All 12 were correct. Nine were
errors in this report, and we corrected them. One was a code defect: `-q` hid the line that
tells you stub or real mode. The suite now writes that line directly to the terminal. The
other two repeated code defects in the table below.

| Defect | Effect before the fix | Fix | Proof |
|---|---|---|---|
| Jaeger answers 404 when it has no trace | A lost trace stopped the run with exit 2 and no outputs | A 404 counts as "no traces". The check fails, exit 1, and the outputs are written | Test |
| The SDK flush reports success when the backend refuses each batch | `--backend otlp-env` passed with a wrong key | The exporter counts each accepted and refused span. New check `backend_accepted_every_span` | Test (a server that answers 401) |
| The UI and gRPC ports could be the same | Jaeger did not start when port 16685 was in use | The gRPC port moves above the UI port | Test |
| Ctrl+C while Jaeger starts | Jaeger stayed up | Jaeger stops | Test |
| The redaction check read the redacted copy | The check could not fail | A canary span with a forbidden attribute | Test (redaction off makes the check fail) |
| A memory run took the Jaeger lock in the home folder | A test failed while another run held the lock | Only a Jaeger run takes the lock | Test |
| `import deepeval` loads `.env` | `pytest eval/deepeval_suite` could call paid models | `DEEPEVAL_DISABLE_DOTENV=1` in `conftest.py` | Probe with a false `.env` |
| LangSmith sends the error text | Claim details could reach LangSmith | Its own tracing is refused (OBS-04) | Test |
| The telemetry opt-out came after the first DeepEval event | One anonymous usage event went out | Export `DEEPEVAL_TELEMETRY_OPT_OUT=1` before the command (Section 12.10) | Code reading |
| The test-count test cleared `-p no:deepeval` | Each `pytest eval/tests` loaded the DeepEval plugin and `.env` | The test passes `-p no:deepeval` again | Code reading |
| OTLP credentials in the environment | The local Jaeger received the Langfuse key | No `OTEL_*` variable for Jaeger, and no header from the environment | Test |
| A crash left the claim without an admissibility result | The DeepEval tool tests passed for a crashed pipeline | A crash fails both tests | Probe |
| The DeepEval tool names had no node and no count | A missing calculator call in coverage passed | Node and tool names, and a count of the policy searches | Probe |

---

## 9. Limitations

- **No real-model result yet.** All results in Section 7 are from stub mode or from an offline
  test of the real-mode path.
- **The judge is uncalibrated.** The G-Eval and faithfulness scores need Cohen's kappa against
  people before you use them as a gate.
- **The outage is simulated.** The fault replaces the tariff tool inside the process. A real
  outage of an MCP server also shows the network call.
- **Each claim is one trace.** In the product, a claim pauses for a person and continues later. A
  paused and continued claim gives two traces. The attribute `gen_ai.conversation.id` (the claim
  id) joins them. The evaluation runner answers at once, so its claims stay in one trace.
- **No Collector.** Tail sampling (keep all errors and a small share of the rest) and central
  redaction belong in an OpenTelemetry Collector. This is Deploy & Ops work (Section 10).
- **The chart is from one stub run.** Stub times are microseconds. Real times are seconds.

---

## 10. Recommendations

1. Run the real-model steps in Sections 12.7 and 12.11 once. Add the results to this report.
2. Agents & Orchestration: give the fraud agent a fallback for a failed tariff call (OBS-01,
   MON-01). Then rerun `run` and look at the error paths again.
3. Deploy & Ops: put an OpenTelemetry Collector between the API and the backend. Use its
   redaction processor, a tail sampler that keeps every error, and the span-metrics connector for
   Prometheus.
4. Calibrate the judge against 20 or more human labels before the G-Eval tests become a gate.
5. When the product API runs claims, start each claim with the same root span and the same
   allowlist. Then production traces and evaluation traces look the same.

---

## 11. Cost

| Run | Mode | Cost |
|---|---|---|
| `show` (one claim) | stub | $0 |
| `show` (one claim) | real | about $0.001 |
| `run` (40 claims) | stub | $0 |
| `run` (40 claims) | real | about $0.03 (from $0.0008 per claim in the real-dev run of CS-EVAL-TR-001). Claims that stop early cost less |
| DeepEval suite, no judge (52 claims) | real | about $0.04 |
| DeepEval judge (up to 44 judged tests) | key | Not measured yet. DeepEval prints the cost at the end of the run |
| Jaeger | — | $0, on this machine |

---

## 12. Procedures: step by step in the terminal

The commands are for Git Bash. The PowerShell form is given where it is different. Do all steps
from the root folder of the repository.

### 12.1 Prepare the environment (one time)

1. Open a terminal in the repository folder.
2. Activate the virtual environment:
   - Git Bash: `source .venv/Scripts/activate`
   - PowerShell: `.venv\Scripts\Activate.ps1`
3. Install the extras: `pip install -e ".[dev,agents,observability,deepeval,docs]"`
4. Make sure that the install shows no error: `pip check`

### 12.2 Choose stub mode or real mode

Stub mode is free. Real mode costs money.

| Mode | Git Bash | PowerShell |
|---|---|---|
| Stub, for this command only | add `--stub` to an `eval.observability` command | the same |
| Stub, for the terminal | `export CLAIMSENSE_LLM=stub` | `$env:CLAIMSENSE_LLM = "stub"` |
| Real | `unset CLAIMSENSE_LLM`, and set `OPENROUTER_API_KEY` | `Remove-Item Env:CLAIMSENSE_LLM`, and set `$env:OPENROUTER_API_KEY` |

CAUTION: The VS Code terminal loads `.env`. If `.env` has a key and you do not use `--stub` or
`CLAIMSENSE_LLM=stub`, the agents call paid models.

Each command prints the mode on its first line. Read it before the claims start:

- `mode: stub (deterministic agents, no model calls, free)`
- `mode: REAL MODELS via OpenRouter (costs money; add --stub for a free run)`

### 12.3 See one claim as a trace (the simple way)

1. Type `python -X utf8 -m eval.observability show --stub`.
2. Read the tree of claim CLM-0004. Each line is a span: its name, its time and a short note.
3. To see other claims, add their ids: `python -X utf8 -m eval.observability show --stub CLM-0007 CLM-9001`.
4. To see the guardrail span, type `python -X utf8 -m eval.observability show --stub CLM-9001 --variant guarded`.
5. To see two spans as an exporter sends them, add `--json`.

NOTE: `-X utf8` is necessary on Windows when the output has special characters.

### 12.4 Install the trace viewer (one time)

1. Type `python -m eval.observability setup`.
2. Make sure that the line before the last line gives the path of `jaeger.exe`. The last line
   gives the folder that holds Jaeger.

NOTE: The download is 65 MB. The command checks the SHA-256 before it unpacks the file. If the
check fails, it deletes the file and stops.

### 12.5 Trace a normal batch and an outage (the production way, stub)

1. Type `python -X utf8 -m eval.observability run --stub --label my-trace-run --keep`.
2. Wait for the checks list. Each check must show `ok`.
3. Open the address on the line `open:` in a browser (normally `http://127.0.0.1:16686`).
4. Do steps 12.6 in the browser.
5. In the terminal, push Ctrl+C to stop Jaeger. The exit code is still 0 or 1, from the checks.

CAUTION: Use a new label for each run. The command refuses a label that exists, because
a report can quote that run.

### 12.6 Read the traces in Jaeger

1. In **Service**, select `claimsense`. Push **Find Traces**.
2. To find the failed claims, type `error=true` in **Tags**.
3. To find one claim, type `claim.id=CLM-0004` in **Tags**.
4. To find one phase, type `claimsense.phase=outage` in **Tags**.
5. Click a trace. The waterfall shows each span as a bar. Click a span to see its attributes.
6. Compare the bar of `execute_tool tariff_range` in a normal claim and in an outage claim.

### 12.7 Trace with real models

1. Set the key in the terminal (Section 12.2). Do not use `--stub`.
2. Type `python -X utf8 -m eval.observability show`. Make sure that the first line says `REAL MODELS`.
3. Make sure that the output says `prompts and replies NOT recorded`.
4. Type `python -X utf8 -m eval.observability run --label my-real-trace-run --keep`.
5. In Jaeger, open a claim. Each model call is a span under its node, with tokens and time.
6. Read the line `## 9 Model calls and cost` in the terminal for the tokens and the cost.

### 12.8 Send the spans to Langfuse

1. In Langfuse, make a project. Copy its public key and its secret key.
2. Make the header value: the text `Authorization=Basic ` and then base64 of
   `<public key>:<secret key>`. In Git Bash: `printf '%s' "pk-...:sk-..." | base64 -w 0`. The
   `-w 0` keeps the result on one line. Without it, `base64` breaks the line after 76
   characters. The exporter then sends no header, and it prints the encoded keys in a warning.
3. Set the address and the header:
   - `export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT="https://cloud.langfuse.com/api/public/otel/v1/traces"`
   - `export OTEL_EXPORTER_OTLP_TRACES_HEADERS="Authorization=Basic <base64>"`
4. Type `python -X utf8 -m eval.observability run --stub --backend otlp-env --label my-langfuse-run`.
5. Make sure that the line `## Export` says that the backend refused 0 spans. If it refused
   spans, the check `backend_accepted_every_span` fails. Then examine the key and the address.
6. Open the project in Langfuse. Look for the service `claimsense`.

CAUTION: Do not put the keys in a file that git tracks. Do not paste them in a report.

### 12.9 Send the spans to LangSmith

1. In LangSmith, make an API key. Make sure that `LANGSMITH_TRACING` is not set to `true`.
2. Set the address and the headers (PowerShell: `$env:NAME = "value"`):
   - `export OTEL_EXPORTER_OTLP_ENDPOINT="https://api.smith.langchain.com/otel"`
   - `export OTEL_EXPORTER_OTLP_HEADERS="x-api-key=<your key>,Langsmith-Project=claimsense-eval"`
3. Type `python -X utf8 -m eval.observability run --stub --backend otlp-env --label my-langsmith-run`.
4. Make sure that the line `## Export` says that the backend refused 0 spans.
5. Open the project `claimsense-eval` in LangSmith.

NOTE: For a LangSmith in the EU, use `https://eu.api.smith.langchain.com/otel`. A workspace
that uses agents needs other headers. Refer to LangSmith's page "Trace with OpenTelemetry".

CAUTION: Do not switch on LangSmith's own tracing (`LANGSMITH_TRACING=true`). It sends the
error text of each run, which can quote claim details. The commands refuse to start when it is
on (rule 4).

### 12.10 Run the DeepEval suite (stub)

1. Set the two DeepEval variables. Do this before each `deepeval` command, because the command
   reads them before it starts the tests:
   - Git Bash: `export DEEPEVAL_DISABLE_DOTENV=1 DEEPEVAL_TELEMETRY_OPT_OUT=1`
   - PowerShell: `$env:DEEPEVAL_DISABLE_DOTENV = "1"; $env:DEEPEVAL_TELEMETRY_OPT_OUT = "1"`
2. Type `CLAIMSENSE_LLM=stub deepeval test run eval/deepeval_suite`.
   - PowerShell: `$env:CLAIMSENSE_LLM = "stub"; deepeval test run eval/deepeval_suite`
3. Make sure that the line `ClaimSense agents: stub` is near the start.
4. Make sure that the end says `Pass Rate: 100.0%`. The 44 judge tests skip.

NOTE: With `DEEPEVAL_DISABLE_DOTENV=1`, DeepEval does not load `.env`. `DEEPEVAL_TELEMETRY_OPT_OUT=1`
stops its usage events. On Windows, if you send the output to a file, also set `PYTHONUTF8=1`.
Without it, DeepEval stops at the results table with a `UnicodeEncodeError`.

### 12.11 Run the DeepEval suite with real models and the judge

1. Set the key (Section 12.2) and the two DeepEval variables (Section 12.10, step 1). Remove
   `CLAIMSENSE_LLM`.
2. Type `deepeval test run eval/deepeval_suite`. Make sure that the line near the start says
   `REAL MODELS`.
3. To add the judge, type `CLAIMSENSE_DEEPEVAL_JUDGE=1 deepeval test run eval/deepeval_suite`.
4. Read the cost at the end of the run.

CAUTION: Do not type `deepeval login`. It sends the results to the cloud of Confident AI.

### 12.12 Run the tests

1. Type `pytest eval/tests/test_observability.py -q` for the 21 observability tests.
2. Type `pytest eval/tests -q` for all 299 evaluation tests.
3. Type `pytest -q` for the product tests.

### 12.13 Stop and clean up

1. If a run stopped before its end, type `python -m eval.observability down`.
2. To remove Jaeger, delete the folder `~/.claimsense/observability_stack`.
3. To remove DeepEval's local results, delete the folder `.deepeval/`.

### 12.14 Troubleshooting

| Message or symptom | Cause | Action |
|---|---|---|
| `already exists. Use a new --label` | The label is in `runs/observability/` | Use a new label |
| `another observability run is in progress` | A second `run` or `down` while a run works | Wait, or push Ctrl+C in the other terminal |
| `LANGSMITH_TRACING is on. ...` | LangSmith's own tracing is on | Switch it off. Send the spans over OTLP (Section 12.9) |
| `--backend otlp-env needs OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | No address for the backend | Do Section 12.8 step 3 |
| `Jaeger did not answer` | Jaeger stopped, or a firewall blocks 127.0.0.1 | Look at `~/.claimsense/observability_stack/run/jaeger.log` |
| `FAIL jaeger_read_back` | Jaeger did not return each trace within 30 s | Do the run again. If it fails again, look at `jaeger.log` |
| `FAIL backend_accepted_every_span` | The backend refused spans, for example with a wrong key | Examine the key, the address and the header (Section 12.8) |
| The mode line says `REAL MODELS` and you want a free run | A key is in the terminal | Push Ctrl+C. Add `--stub` |
| No `chat` spans in real mode | The `observability` extra is not installed | Do Section 12.1 step 3 |

### 12.15 Exit codes of `run`

| Code | Meaning |
|---|---|
| 0 | Every check holds |
| 1 | A check failed. The outputs are still written |
| 2 | The run could not start (label, lock, Jaeger, backend, LangSmith settings) |
| 130 | You pushed Ctrl+C before the run ended. With `--keep`, Ctrl+C after the run only stops Jaeger, and the code is 0 or 1 |

---

## 13. Quality control

| Check | Result |
|---|---|
| Library behaviour | Read from the installed source code and tested with small programs: DeepEval 4.3.3, opentelemetry-sdk 1.45.2, the LangChain instrumentation 0.63.0, langsmith 0.14.17 |
| Jaeger checksums | From `jaeger-2.22.0.sha256sum.txt` on the release. The GitHub asset digests agree for all five platforms |
| Jaeger listening addresses | `netstat` shows 127.0.0.1 only. No process stays after the run |
| Rule 4 | A test over all 52 dev and red-team claims. A check of the DeepEval cache. A check of all 663 spans that Jaeger returned. A canary span in each run |
| Adversarial review | 13 code defects found and fixed. 9 report errors corrected (Section 8.1) |
| Numbers in this report | From `runs/observability/stub-jaeger-2/summary.json` and from the test output |

---

## Appendix A. Files

| File | Change |
|---|---|
| `eval/observability/__init__.py`, `__main__.py`, `otel.py`, `analysis.py`, `jaeger.py`, `README.md` | New: the observability package |
| `eval/deepeval_suite/__init__.py`, `conftest.py`, `support.py`, `test_trajectory.py`, `test_payload_quality.py`, `README.md` | New: the DeepEval suite |
| `eval/tests/test_observability.py` | New: 21 tests |
| `eval/agent_suite/trace.py` | Changed: the optional `observer` argument (Section 6.1) |
| `pyproject.toml`, `requirements.txt` | Changed: the `observability` and `deepeval` extras, and `-p no:deepeval` |
| `.gitignore` | Changed: `.deepeval/` |
| `CLAUDE.md`, `README.md`, `eval/README.md` | Changed: commands and links |
| `eval/tests/test_report_doc.py` | Changed: its test-count check passes `-p no:deepeval` again |
| `docs/EVAL_HARNESS_REPORT.md`, `docs/TECHNICAL_REPORT_EVAL_AND_MONITORING.md`, `docs/FRAMEWORK_RUBRIC_SCORE.md` | Changed: the test count (269 to 299) |
| `runs/observability/stub-jaeger-2/` | New: the run that Section 7.2 quotes |
| `runs/observability/stub-jaeger/` | New: the first run, before the review. Kept as it was |

## Appendix B. Sources of the numbers

| Number | Source |
|---|---|
| 26 spans for CLM-0004 | `python -m eval.observability show --stub` |
| 662 claim spans, 663 spans sent, 40 traces, RED table, error paths, gate, checks | `runs/observability/stub-jaeger-2/summary.json` |
| 74 DeepEval tests, 100% | `deepeval test run` output, 12 November 2026 |
| 299 evaluation tests | `pytest eval/tests --collect-only` |
| $0.0008 per real claim | CS-EVAL-TR-001, Section 6 (real-dev run) |
