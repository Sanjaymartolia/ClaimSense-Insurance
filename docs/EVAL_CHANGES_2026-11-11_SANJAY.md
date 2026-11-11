# Eval changes, 11 November 2026

**Date:** 2026-11-11
**Name:** Sanjay (Eval & Red-Team), with Claude Code
**Scope:** `eval/`, docs and two config files. No file in `src/`, `monitoring/`,
`docker-compose.yml`, `.github/`, `data/`, `eval/golden_dev/` or `eval/redteam/` was changed.
**Status:** not committed yet.

## In short

- **DeepEval** test suite for the pipeline (AAI-13).
- **OpenTelemetry tracing** (AAI-14, L14 notebook), in two forms:
  - the simple way: spans in memory, printed as a tree;
  - the production way: spans sent to a local Jaeger.
- **Both modes work:** stub (free) and real models (your OpenRouter key).
- **A full report,** with a step-by-step terminal guide: `docs/OBSERVABILITY_REPORT.md`.

## 1. New folders and files

| Path | What it is |
|---|---|
| `eval/observability/__init__.py` | Package map: notebook sections 1–9 and where each one is |
| `eval/observability/__main__.py` | The command `python -m eval.observability` with `show`, `setup`, `run`, `down` |
| `eval/observability/otel.py` | OpenTelemetry set-up, the span for each step, redaction (rule 4), LangChain model-call spans, the LangSmith guard |
| `eval/observability/analysis.py` | Span tree, RED table, what a claim did after an error, approval gate, cost, chart |
| `eval/observability/jaeger.py` | Downloads Jaeger 2.22.0 (SHA-256 pinned), starts it on 127.0.0.1 only, reads traces back |
| `eval/observability/README.md` | How to run it |
| `eval/deepeval_suite/support.py` | Shared helpers: traced claims, the expected tools, an offline model, a custom metric, the judge model |
| `eval/deepeval_suite/test_trajectory.py` | 74 free tests: right tools called (`ToolCorrectnessMetric`), no forbidden tool, tool budget held |
| `eval/deepeval_suite/test_payload_quality.py` | 40 opt-in LLM-judge tests: `GEval` checklist and `FaithfulnessMetric` |
| `eval/deepeval_suite/conftest.py`, `__init__.py`, `README.md` | Telemetry off, stub/real mode in the header, how to run it |
| `eval/tests/test_observability.py` | 21 offline tests (no key, no network, no Jaeger) |
| `docs/OBSERVABILITY_REPORT.md` + `docs/ClaimSense_Observability_Report.docx` | The report (ASD-STE100 style) |
| `docs/EVAL_CHANGES_2026-11-11_SANJAY.md` | This file |
| `runs/observability/stub-jaeger-2/` | The stub run the report quotes (after the review fixes): `summary.json`, `spans.csv`, `trees.txt`, `red.png` |
| `runs/observability/stub-jaeger/` | The first stub run, before the review. Kept as it was |

## 2. Changed files

| File | What changed |
|---|---|
| `eval/agent_suite/trace.py` | New optional `observer=` argument on `run_traced`. It opens a span around each node, tool call, guardrail and review. With no observer the run is unchanged (the pinned suite scores did not move) |
| `pyproject.toml` | Two new extras: `observability` (OpenTelemetry SDK, OTLP exporter, LangChain instrumentation) and `deepeval`. pytest `addopts` now has `-p no:deepeval` |
| `requirements.txt` | Mirrors the two new extras |
| `.gitignore` | Adds `.deepeval/` (DeepEval's local results) |
| `eval/tests/test_report_doc.py` | Its child pytest clears `addopts`, so it now passes `-p no:deepeval` again (review fix) |
| `CLAUDE.md` | New section "Observability and DeepEval", the DeepEval plugin warning, the layout row, test count 292 |
| `README.md` | Run commands and a link to the new report |
| `eval/README.md` | Commands, two layout rows, test count 292 |
| `docs/TEAM_GUIDE.md` (+ PDF, DOCX, HTML rebuilt) | Three rows in the "at a glance" table and the quick reference |
| `docs/EVAL_HARNESS_REPORT.md` (+ DOCX) | Test count 269 → 292 |
| `docs/TECHNICAL_REPORT_EVAL_AND_MONITORING.md` (+ DOCX) | Test count 269 → 292 |
| `docs/FRAMEWORK_RUBRIC_SCORE.md` (+ DOCX) | Test count 269 → 292 (the scores did not change) |

## 3. DeepEval and `.env`

- **The problem.** `import deepeval` copies `.env` into the environment. DeepEval also installs a
  pytest plugin that loads in every pytest run. With a key in `.env`, the "free" stub tests would
  call paid models.
- **The fix.** `-p no:deepeval` in `pyproject.toml` stops the plugin in normal runs. The suite's
  `conftest.py` sets `DEEPEVAL_DISABLE_DOTENV=1` before DeepEval is imported.
- **For the `deepeval` command.** It imports DeepEval before pytest starts, so export the
  variables first:
  `DEEPEVAL_DISABLE_DOTENV=1 DEEPEVAL_TELEMETRY_OPT_OUT=1 CLAIMSENSE_LLM=stub deepeval test run eval/deepeval_suite`.

## 4. Outside the repository

- **Jaeger 2.22.0:** in `~/.claimsense/observability_stack`, about 65 MB. Delete the folder to
  remove it.
- **Packages in `.venv`:**
  - opentelemetry-sdk 1.45.2, opentelemetry-exporter-otlp-proto-http 1.45.2,
    opentelemetry-instrumentation-langchain 0.63.0;
  - deepeval 4.3.3 (it moved `click` from 8.5.1 to 8.3.3).

## 5. Results (stub mode)

| Check | Result |
|---|---|
| `python -m eval.observability show --stub` | CLM-0004 = one trace of 26 spans |
| `python -m eval.observability run --stub --label stub-jaeger-2` | 40 claims to Jaeger, all 40 traces and all 663 spans read back, 7 of 7 checks pass |
| What the outage showed | All 13 claims that called the tariff tool crashed at that call (confirms MON-01) |
| `DEEPEVAL_DISABLE_DOTENV=1 DEEPEVAL_TELEMETRY_OPT_OUT=1 CLAIMSENSE_LLM=stub deepeval test run eval/deepeval_suite` | 74 of 74 pass |
| `pytest eval/tests` | 292 tests: 286 pass, 4 strict `xfail`, 2 skip |
| `pytest` (product) | 124 pass, 4 skip, 1 `xfail` (same as before) |
| `python -m eval.harness.suite` | 9 of 9 rows match |
| Rule 4 | No claim text in any span, in Jaeger, or in the DeepEval cache |

**Real mode:** built and tested offline with a fake model. A run with real models needs your key.
See `docs/OBSERVABILITY_REPORT.md`, Sections 12.7 and 12.11 (about $0.03 and $0.04).

## 6. Fixes after the code review

An adversarial review (independent agents: one set looks for defects, a second set tries to
disprove each one with a probe) found 13 code defects and 9 errors in the report. All are fixed.
Full table: `docs/OBSERVABILITY_REPORT.md`, Section 8.1.

| Area | Defect | Fix |
|---|---|---|
| Jaeger read-back | A 404 from Jaeger ("No traces found") stopped the run with exit 2 and no outputs | A 404 counts as "no traces": the check fails, exit 1, outputs written |
| Delivery check | `exporter_flushed` passed even when the backend refused every span (wrong Langfuse key) | Replaced by `backend_accepted_every_span`, which counts accepted spans |
| Redaction check | It read the redacted copy, so it could never fail | A canary span with a forbidden attribute in every run |
| Jaeger ports | UI and gRPC could get the same port, so Jaeger did not start | gRPC moves above the UI port |
| Ctrl+C | Pressed while Jaeger started, Jaeger stayed up | Jaeger is stopped |
| Lock | A memory run took the Jaeger lock in your home folder | Only Jaeger runs take it |
| Credentials | A Langfuse key in `OTEL_*` reached the local Jaeger | Jaeger gets no `OTEL_*` variable and no header from the environment |
| LangSmith | Its own tracing uploads error text even with inputs/outputs hidden | Its own tracing is refused; LangSmith gets the redacted spans over OTLP |
| DeepEval `.env` | `import deepeval` loads `.env`, so plain `pytest eval/deepeval_suite` could use a real key | `conftest.py` sets `DEEPEVAL_DISABLE_DOTENV=1` |
| DeepEval telemetry | The CLI sent one usage event before `conftest.py` ran | Docs: export `DEEPEVAL_TELEMETRY_OPT_OUT=1` first |
| DeepEval crash | A crashed pipeline passed the tool tests | A crash fails both tests |
| DeepEval tools | Names only: a missing calculator call in coverage passed | `node:tool` names, and a count of the policy searches |
| Test-count test | Its child pytest loaded the DeepEval plugin | Passes `-p no:deepeval` again |

Four new tests; the eval test count is now 292 (290, plus 2 from the team's merge). The new evidence run is `stub-jaeger-2`.

## 7. Also uncommitted, from earlier the same day

- `docs/TECHNICAL_REPORT_EVAL_AND_MONITORING.md` (+ DOCX): the technical report from eval harness
  to monitoring.
- Updates to `docs/AGENT_SUITE_REPORT.md`, `docs/EVAL_RUN_GUIDE.md`,
  `docs/EvalSuite_AgentSuite_Note.md`, `docs/MONITORING_REPORT_CARD.md` and
  `eval/monitoring/README.md`.
- `eval/monitoring/live.py` and `eval/tests/test_monitoring.py`: the fix for "idle" claims at the
  start of a drill, with its test.
