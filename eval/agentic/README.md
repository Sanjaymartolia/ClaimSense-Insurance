# Tool-use evaluation

Checks how ClaimSense uses its tools: whether calls happen in the right order, from the right
agent, with the right arguments; whether the tools and hooks behave; and whether results are the
ones that end up on the worksheet. It complements `eval/harness`, which scores outcomes.

```bash
pip install -e ".[dev]" matplotlib
python -m eval.agentic.run --label agentic-dev   # report, traces and chart in runs/agentic/
pytest eval/agentic/tests
```

Offline: the stub LLM is forced, so no key is used and nothing is billed. Exit code 0 means no
unexpected failure.

## Read this before quoting a number

- **No model selects tools.** Tool order is hard-coded, so tool-selection accuracy does not exist
  here. If agents become ReAct loops, this needs a new metric.
- **Pipeline runs use stub tools** with the real calculator, approval gate and hooks. The real
  database, approval, tariff and policy-kb code is covered only by the direct tool cases, and
  policy-kb uses a fake retriever. An end-to-end run on `real_services()` is not done.
- **The expected path is conditional.** Admissibility, critic verdicts and reviewer replies are
  read from the run. Whether those decisions were right is scored by `eval/harness`.
- **High pass rates on deterministic code are expected.** They catch regressions. The tests in
  `tests/test_metrics_can_fail.py` show each metric fails on a corrupted trace.

## What is checked

| Layer | Files | Coverage |
|---|---|---|
| Trajectory | `expected_path.py`, `trajectory_eval.py` | 8 metrics, 52 claims, 5 reviewer scenarios |
| Controls | `trajectory_eval.py` | budget and ACL breach mid-run, each tool failing in turn |
| Tools | `tool_cases.jsonl`, `tool_eval.py` | every MCP tool and error code, settlement matrix, hand-worked calculator cases |
| Hooks | `hook_cases.jsonl`, `hook_eval.py` | ACL matrix, budgets, audit, output guard, guardrails, attack table |
| Model decisions | `llm_eval.py` | scripted replies: bad clause, critic failure, injected text |

`guardrails.py` is scored, but no product code calls it. The attack table keeps it separate from
live controls.

## Case outcomes

| Status | Meaning | Effect |
|---|---|---|
| `pass` | Behaves as specified | none |
| `fail` | Unexpected failure | run exits 1 |
| `known_defect` | Product bug, tagged `AGENTIC-nn` | counted as not passed; run still exits 0 |
| `defect_fixed` | A tagged bug no longer reproduces | run exits 1, so remove the tag |

Defect descriptions are in `DEFECTS` in `run.py`. Fix them in the owning module, not here.

## Adding a case

Add a line to the matching `.jsonl` file with `case_id` and `expect`, and a scenario function if
the setup is new. Write the expected value by hand; never copy it from a run. Calculator amounts
must be hand-worked by a person (`CLAUDE.md`). Held-out cases are never used here.
