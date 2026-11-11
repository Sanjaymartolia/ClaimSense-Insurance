# eval/deepeval_suite: the pipeline's unit tests, written with DeepEval (AAI-13)

Owner: Eval & Red-Team. Results and the tool review: [docs/OBSERVABILITY_REPORT.md](../../docs/OBSERVABILITY_REPORT.md).

| File | What it checks | Needs |
|---|---|---|
| `test_trajectory.py` | no crash, and each node called the tools the design requires (`ToolCorrectnessMetric` on `node:tool` names); no forbidden tool ran, one policy search per bill line, and the tool budget held (`TrajectoryRulesMetric`, deterministic) | nothing: free |
| `test_payload_quality.py` | the review payload meets the checklist (`GEval`); each deduction is faithful to its clause (`FaithfulnessMetric`) | a key and `CLAIMSENSE_DEEPEVAL_JUDGE=1`; costs money |

## Run it

```bash
pip install -e ".[dev,agents,deepeval]"

# before any `deepeval` command: no .env loading, no usage events (the CLI reads both first)
export DEEPEVAL_DISABLE_DOTENV=1 DEEPEVAL_TELEMETRY_OPT_OUT=1

# stub agents, no judge: free (74 tests, about 10 s)
CLAIMSENSE_LLM=stub deepeval test run eval/deepeval_suite

# real agents, no judge (about $0.04: 52 claims)
deepeval test run eval/deepeval_suite

# real agents and the LLM judge (add about $0.02 for the judge)
CLAIMSENSE_DEEPEVAL_JUDGE=1 deepeval test run eval/deepeval_suite
```

PowerShell: `$env:DEEPEVAL_DISABLE_DOTENV = "1"; $env:DEEPEVAL_TELEMETRY_OPT_OUT = "1";
$env:CLAIMSENSE_LLM = "stub"; deepeval test run eval/deepeval_suite`. Plain `pytest
eval/deepeval_suite` runs the same tests without DeepEval's results table. On Windows, with the
output sent to a file, also set `PYTHONUTF8=1` (DeepEval's table has characters cp1252 lacks).

## Know this before you run it

- **`.env`.** `import deepeval` copies `.env` into the environment; with a key there, the stub
  tests would call real models. `conftest.py` sets `DEEPEVAL_DISABLE_DOTENV=1` before the import
  for plain `pytest`. The `deepeval` CLI imports DeepEval before pytest starts, so export the
  variable yourself (above).
- **The pytest plugin is off by default.** `pyproject.toml` adds `-p no:deepeval`, so other
  pytest runs do not load DeepEval at all; `deepeval test run` turns the plugin back on.
- The first line of the run says `ClaimSense agents: stub` or `REAL MODELS`. Read it.
- Telemetry: `conftest.py` opts out for the pytest session, but the CLI sends one event before
  pytest starts unless `DEEPEVAL_TELEMETRY_OPT_OUT=1` is exported first. Do not run
  `deepeval login`: results would go to Confident AI's cloud.
- LangSmith's own tracing (`LANGSMITH_TRACING=true`) stops the suite: it would upload error text
  from the real-mode agents (rule 4).
- DeepEval keeps the last run in `.deepeval/` (gitignored). The test cases hold claim ids, routes,
  amounts, `node:tool` names, the status and an exception type only, never claim text.
- The judge is uncalibrated (no Cohen's kappa against people yet). Read its scores; do not gate a
  release on them.
