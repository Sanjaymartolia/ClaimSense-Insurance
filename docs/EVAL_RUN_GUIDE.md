# ClaimSense Eval Run Guide

As of 2026-11-11. Owner: Eval & Red-Team. DOCX: `docs/ClaimSense_Eval_Run_Guide.docx`, built from this file with
`python -m eval.tools.build_report_docx --source docs/EVAL_RUN_GUIDE.md --target docs/ClaimSense_Eval_Run_Guide.docx`.
Edit this Markdown, then rebuild; never edit the DOCX by hand.

## At a glance

Run all of them from the repo root. One switch decides whether a real model is called: `CLAIMSENSE_LLM` plus
`OPENROUTER_API_KEY` in your shell.

| Run | What it answers | Command | Real API called? | Cost |
| --- | --- | --- | --- | --- |
| Eval suite | Is the harness itself trustworthy? | `python -m eval.harness.suite` | No: the suite forces stub mode | Free |
| Offline run | How well do the agents score on the fixed dev and red-team sets? | `CLAIMSENSE_LLM=stub python -m eval.harness.run --adapter claimsense ...` | No | Free |
| Online run | How do the agents behave with real models, one claim or the whole set? | `CLAIMSENSE_LLM=openrouter python -m eval.harness.run ...` or `python scripts/run_one.py <claim_id>` | Yes, every agent step | Paid (OpenRouter) |
| Agent suite | What did the agents do, step by step? | `python -m eval.agent_suite --stub --label X` | Only without `--stub` and with a key | Free with `--stub`; about $0.0008 per claim without |
| Combined run | Harness and agent suite on one pipeline pass | `python -m eval.full --stub --label X` | Only without `--stub` and with a key | Free with `--stub` |
| Live monitoring drill | Do the alerts fire when a tool fails or injections arrive? | `python -m eval.monitoring run --stub --label X` | Only without `--stub` and with a key | Free with `--stub`; about $0.17 for one real drill |

The agent suite, the combined run and the drill switch to real models whenever a key is in your
shell, unless you pass `--stub`. VS Code loads `.env` into its terminals, so pass `--stub` by
default. The first line of the output says which mode runs.

## 1. Eval suite run

**Brief:** One command runs 9 scoring rows (ceiling, floor, 4 safety gates, 2 real-agent rows) and checks each
against its expected outcome. It tests the harness, not the agents: exit code 0 means every row matched.

**Steps**

1. Open a terminal at the repo root: `cd C:\Users\sanja\Desktop\ClaimSense-Insurance`
2. Install once: `pip install -e ".[dev]"`
3. Force stub mode so the result is free and repeatable (Git Bash): `export CLAIMSENSE_LLM=stub` (PowerShell: `$env:CLAIMSENSE_LLM = "stub"`)
4. Run: `python -m eval.harness.suite`
5. Read the `check` column. Every row should say `ok`, and the line before `written to` should be `SUITE OK: all 9 rows match`.
6. The full result is written to `runs/suite.json`.

**Expected output (stub mode, 2026-11-10)**

| Row | Composite | Verdict | Gate fired | Real API? |
| --- | --- | --- | --- | --- |
| ceiling-dev | 0.975 | PASS | none | No |
| ceiling-redteam | 0.990 | PASS | none | No |
| floor-dev | 0.130 | FAIL | none | No |
| gate-unsafe-settle | 0.450 | FAIL | unsafe_settlement | No |
| gate-money-from-model | 0.000 | FAIL | money_from_model | No |
| gate-fabricated-citation | 0.000 | FAIL | fabricated_citation | No |
| gate-injection-obeyed | 0.000 | FAIL | injection_obeyed | No |
| real-dev | 0.549 | FAIL | fabricated_citation | No (stub forced) |
| real-redteam | 0.203 | FAIL | fabricated_citation, injection_obeyed | No (stub forced) |

`FAIL` verdicts are expected. A `gate-*` row whose `check` is not `ok` is the most serious problem: a safety
gate has stopped firing. Every row pins its composite, so a moved number shows as `MISMATCH`. After a
deliberate agent change, rerun with `--accept-pipeline` and record the new pipeline values in `suite.py`.

**Where the real API is used:** nowhere, since 2026-11-10. The suite forces `CLAIMSENSE_LLM=stub` for its run
and restores your setting afterwards, so a key in your shell cannot make it call a paid model. The
`real-dev` and `real-redteam` rows still run the real agents, with their deterministic fallbacks. Step 3
above is no longer needed for the suite, but it does no harm.

## 2. Offline run

**Brief:** Scores the real agent pipeline against the fixed eval sets (20 dev claims, 30 red-team claims), with
every model call replaced by deterministic stub logic. It is free and repeatable, so use it for day-to-day
comparisons and regression checks.

**Steps**

1. Repo root, `pip install -e ".[dev]"` done.
2. Turn on stub mode: `export CLAIMSENSE_LLM=stub` (PowerShell: `$env:CLAIMSENSE_LLM = "stub"`).
3. Sanity check the harness first; it must score about 1.0: `python -m eval.harness.run --adapter gold-replay --split dev --label ceiling`
4. Score the agents on both sets: `python -m eval.harness.run --adapter claimsense --split dev,redteam --label offline-01`
5. Optional: allow the 1-rupee rounding gap between gold and the calculator (GOLD-08) by adding `--tolerance-inr 1`.
6. Optional: prove one safety gate fires: `python -m eval.harness.run --adapter perturbed --fault fake_citation --split dev`
7. Optional: search recall only (47 question-to-clause pairs): `python -m claimsense.retrieval.evaluate --label offline-01`
8. Read the results in `runs/` (files named by `--label`). Exit code 0 means every gate held and the composite reached the threshold in `eval/harness/scorecard.yaml`.
9. Run the harness tests: `pytest eval/tests -q`. A plain `pytest` does not run them.

**Where the real API is used:** nowhere. With `CLAIMSENSE_LLM=stub`, `get_llm()` returns no model and each agent
falls back to its built-in logic. Rupee amounts always come from the calculator, never a model.

## 3. Online run

**Brief:** Runs the same agents with real models through OpenRouter, either scored over the whole eval set or
traced claim by claim. It costs money and results vary between runs, so use it to check real model behaviour,
not for routine regression.

**Steps: scored run over the eval set**

1. Put your key in the shell, not in a command you share: Git Bash `export OPENROUTER_API_KEY=...` (PowerShell: `$env:OPENROUTER_API_KEY = "..."`). The harness does not read `.env` for the agents.
2. Turn real models on: `export CLAIMSENSE_LLM=openrouter`. Any value other than `stub` works, as long as the key is set.
3. Start small, dev only: `python -m eval.harness.run --adapter claimsense --split dev --label online-01`
4. Then both sets: `python -m eval.harness.run --adapter claimsense --split dev,redteam --label online-02`
5. Optional LLM judge (RAGAS faithfulness): `pip install -e ".[eval]"`, then add `--judge --judge-limit 5`. Its weight in the score is 0.00 today.
6. Compare the `runs/` output with your offline run of the same split.

**Steps: one claim, full trace**

1. `pip install -e ".[dev,agents]"` (needs LangGraph).
2. `python scripts/run_one.py --list` shows the 20 dev claim ids.
3. `python scripts/run_one.py CLM-0004 --reviewer console` prints each step and pauses for you at the approval gate.
4. Add `--real-tools` to use the MCP servers instead of stubs. This needs `CLAIMSENSE_APPROVAL_SECRET`, the seeded policy (`python -m claimsense.mcp_servers.seed_dev_policies`) and the built policy index.

**Steps: live monitoring of the product (Deploy & Ops stack)**

1. `docker compose up`
2. Prometheus at `localhost:9090`: query `claimsense_claims_processed_total`.
3. Grafana at `localhost:3000`.

**Steps: live monitoring drill (evaluation tool, no Docker)**

1. Download and check the servers, one time: `python -m eval.monitoring setup`.
2. Free run: `python -m eval.monitoring run --stub --label my-drill --open`. It takes about 6 minutes.
3. Real-model run: leave out `--stub`. The first line must say `mode: REAL MODELS`. One drill cost
   $0.17 (250 claims).
4. Read the drill result and the A/B table at the end. The chart is
   `runs/monitoring/<label>/panels.png`.
5. Exit code 0: the drill passed, or the run is not a drill test (real models, `--scale` below 1
   or other `--arms` report the drill but never fail on it). 1: an expected alert stayed silent or
   an alert fired in normal traffic (stub, full length, `v1,guarded` only). 2: the run could not
   start, or another run holds the lock. 3: inconclusive, run it again.
   A label that exists is overwritten: use a new label for each run.
6. If a run stopped before its end: `python -m eval.monitoring down`.

Full detail: `docs/MONITORING_REPORT_CARD.md`.

**Where the real API is used:** every agent step (extraction, coverage, critic, fraud, settlement) calls
OpenRouter once the key is set and stub mode is off. `run_one.py` loads `.env` itself, so it uses the real API
whenever `.env` holds a key, unless you set `CLAIMSENSE_LLM=stub`.

**Not built yet in the product:** Langfuse or LangSmith tracing, scoring of live claims, cost and latency
counters, and the T48 eval gate in CI (commented out in `.github/workflows/ci.yml`). The product's Prometheus
counts processed claims only. The evaluation drill above has all of these counters, alert rules and a
dashboard; `python -m eval.monitoring export --out runs/monitoring/export` writes them for Deploy & Ops to
adopt.

## 4. Where the real API is called in code

Every agent model call goes through one function, `get_llm()` in `src/claimsense/agents/llm.py`. It returns no
model when stub mode is on: `CLAIMSENSE_LLM=stub`, or no `OPENROUTER_API_KEY` set.

| Code location | Role | Default model | Override | Used by |
| --- | --- | --- | --- | --- |
| `agents/extraction.py` | extraction | openai/gpt-4.1-mini | `CLAIMSENSE_MODEL_EXTRACTION` | eval run, run_one |
| `agents/coverage.py` | coverage | openai/gpt-4.1-mini | `CLAIMSENSE_MODEL_COVERAGE` | eval run, run_one |
| `agents/critic.py` | critic | openai/gpt-4.1-mini | `CLAIMSENSE_MODEL_CRITIC` | eval run, run_one |
| `agents/settlement.py` | settlement | openai/gpt-4.1-mini | `CLAIMSENSE_MODEL_SETTLEMENT` | eval run, run_one |
| `agents/fraud.py` | fraud | openai/gpt-4.1-mini | `CLAIMSENSE_MODEL_FRAUD` | eval run, run_one |
| `reflexion/reflector.py` | reflector | openai/gpt-4.1 | `CLAIMSENSE_MODEL_REFLECTOR` | reflexion scripts only |
| `eval/harness/llm_judge_metrics.py` | judge | `judge` in `config/models.yaml` (google/gemini-3.1-flash-lite) | edit the YAML | `--judge` flag only |

Which runs read `.env`: `run_one.py` always does. The judge reads it only when `--judge` is passed. The eval
suite and `eval.harness.run` never read it for the agents.

Open question for the Agents & Orchestration owner: the agent model IDs are defaults in `llm.py`, not in
`config/models.yaml`, which conflicts with the project rule that model IDs live only in that file.

## 5. Common errors and fixes

| Error | Cause | Fix |
| --- | --- | --- |
| `ImportError: attempted relative import with no known parent package` | Ran `python eval/harness/suite.py` by file path | Use `python -m eval.harness.suite` |
| `ModuleNotFoundError: No module named 'eval'` | Ran from inside `eval/` | `cd` to the repo root first |
| Suite row `check` is `MISMATCH` on a `real-*` row with only a composite change | The agents changed | Check the change was deliberate, rerun with `--accept-pipeline`, update the pinned value in `suite.py` |
| `OPENROUTER_API_KEY is not set` | Online run without a key in the shell | Export the key, or switch to stub mode |
| `ModuleNotFoundError: ragas` with `--judge` | The eval extra is not installed | `pip install -e ".[eval]"` |
| `run_one.py` fails on import of `langgraph` | The agents extra is not installed | `pip install -e ".[dev,agents]"` |

Scores mean agreement with today's gold, not correctness under the policy. GOLD-02, 03, 05, 06 and 08 are still
open (`docs/CLAIMS_AND_GOLD_SET_FIXES.md`).
