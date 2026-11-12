# Terminal run report: stub vs real API

**Name:** Sanjay Singh (Eval & Red-Team), with Claude Code
**Date:** 12 November 2026
**For:** everyone on the team who runs an eval from a terminal.

Every eval tool runs in one of two modes. **Stub** uses the agents' deterministic fallbacks: no
model call, no key, $0, seconds. **Real** calls the models through OpenRouter: it costs money and
takes minutes. Section 1 shows what we got today in each mode. Section 3 gives every command in
both modes.

---

## 1. Results, 12 November 2026

| # | Eval set | Stub result | Real API result | Run folder (stub / real) |
|---|---|---|---|---|
| 1 | Release check, dev + red-team (`eval.full`) | **PASS**, composite 0.984 | **PASS**, composite 0.984, $0.0013 per claim, p95 26.4 s | `runs/full/full-sec-1112b` / `runs/full/release-check-sec-1112` |
| 2 | Release check + guard model (`CLAIMSENSE_GUARD_LLM=1`) | not possible (real only) | **FAIL**: p95 35.9 s, gate needs 30 s or less. Every other check passes | — / `runs/full/release-check-guard-1112` |
| 3 | Agent suite, `v1` and `guarded` | **PASS** both | **PASS** both: `v1` p95 25.7 s, `guarded` p95 29.2 s | `runs/agent_suite/agents-1112` / `runs/agent_suite/real-agents-sec-1112` |
| 4 | Security scoreboard (L15 section 9) | attacks cleared 0/30, injections shown 18/18 | **same as stub**; the guard model adds 0 catches | `runs/security/l15-scoreboard-b` / `runs/security/real-scoreboard-1112` |
| 5 | Adaptive attacker (L15 section 10) | not possible (real only) | **attacker did not win**: 6 rounds, 5 held, round 6 flagged | — / `runs/security/real-attack-1112` |
| 6 | Retrieval, 47 queries | **no key needed**: Recall@5 1.000, top-1 0.766, MRR 0.867 | same (retrieval calls no LLM) | `runs/retrieval_retrieval-1112.png` |
| 7 | Pipeline with the real retriever (new), dev + red-team | **PASS**, composite 0.984 (same as the stub table). With the search cache: p50 0.007 s, p95 3.8 s per claim (was 17.6 s / 33.7 s) | Harness: composite 0.976 and 0.980 (two runs), all gates held, p95 64-81 s before the cache. **Release check with the cache (`eval.full --variant real-retrieval`): composite 0.976, every harness gate held, $0.0017 and 4,554 tokens per claim, but p95 30.2 s: FAIL (gate needs 30 s or less)** | `runs/retrieval-stub-cache-1112.scorecard.json` / `runs/rr-real-1112.scorecard.json`, `runs/full/rr-release-1112c` |
| 8 | RAGAS faithfulness judge, real retriever, dev, 5 claims requested | not possible (real only) | `rationale_groundedness` 0.743 and 0.594 in two runs; 2 of 5 claims had a model rationale to judge. Uncalibrated, weight 0.00 | — / `runs/ragas-rr-1112.scorecard.json` |
| 9 | Harness suite (9 rows) | **OK**, 9 of 9 | always stub (it forces stub) | `runs/suite.json` |
| 10 | Framework rubric (9 dimensions) | **2.85 out of 5** (was 2.70): a written score, not a run | same (it runs no code) | `docs/FRAMEWORK_RUBRIC_SCORE.md` |

**What this means, in brief:**

1. **Stub and real give the same composite (0.984)** on the 52 dev and red-team claims. Route,
   amounts, flags and citations match. The calculator decides every rupee in both modes, and the
   guardrails are code. What changes with real models is latency, cost and the clause choices
   (`clause_match` 0.492 stub vs 0.502 real).
2. **Do not turn on the guard model (row 2).** It adds about 9 s per claim, pushes p95 past the
   30 s gate and catches nothing the pattern guardrail misses (row 4). Keep `CLAIMSENSE_GUARD_LLM`
   off.
3. **Security holds with real models.** No attacked claim is cleared, every injection reaches the
   reviewer, and the adaptive attacker did not find a way through in 6 rounds.
4. **Retrieval works (rows 6 and 7).** Until today no pipeline eval used it; every run used a
   fixed clause table. Now it can, and with real models it passes (0.976 and 0.980, every gate
   held). The re-ranker made each claim very slow (p95 64-81 s); a search cache in policy-kb
   fixes that without changing any result (section 4). Re-run row 7 real to confirm p95.
5. **The RAGAS score moves a lot between runs** (0.743 vs 0.594 on the same claims). Do not
   quote it until it is calibrated. Always use a new `--label`: a reused one overwrites the file.
6. **Tests today:** product tests all pass. Eval tests: 318 (316 pass, 1 `xfail` MON-01, 1 skip).
   Harness suite: 9 of 9 rows match.

---

## 2. Before you start (once)

### 2.1 Install

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1                    # PowerShell   (Git Bash: source .venv/Scripts/activate)
pip install -r requirements.txt               # everything
pip install --no-deps "ragas>=0.4,<0.5"       # Python 3.14 only (see note)
python -m claimsense.retrieval.index          # build the search index (chroma-data/), ~1 min
```

**Python 3.14 note.** `ragas` depends on `scikit-network`, which has no ready-made package for
3.14, and building it needs the Microsoft C++ Build Tools. RAGAS uses it only to generate test
sets, never for the judge. So `requirements.txt` installs RAGAS's other dependencies, and you add
RAGAS itself with `--no-deps`. On Python 3.11 to 3.13 `pip install -r requirements.txt` installs
RAGAS directly.

Check the install:

```powershell
pip check                                      # expect only: ragas requires scikit-network (3.14)
python -c "import chromadb, rank_bm25, sentence_transformers, ragas; print('ok')"
```

### 2.2 Switch between stub and real

The mode depends on whether `OPENROUTER_API_KEY` is set. VS Code loads `.env` into its
terminals, so **a VS Code terminal is in real mode unless you say otherwise**.

| I want | PowerShell | Git Bash |
|---|---|---|
| Stub, one command | add `--stub` (tools that have it) | add `--stub` |
| Stub, the whole terminal | `$env:CLAIMSENSE_LLM = "stub"` | `export CLAIMSENSE_LLM=stub` |
| Back to real | `Remove-Item Env:CLAIMSENSE_LLM` | `unset CLAIMSENSE_LLM` |
| Guard model on (not advised) | `$env:CLAIMSENSE_GUARD_LLM = "1"` | `export CLAIMSENSE_GUARD_LLM=1` |
| Guard model off | `Remove-Item Env:CLAIMSENSE_GUARD_LLM` | `unset CLAIMSENSE_GUARD_LLM` |

Rules:
- Never print, paste or commit the key. Never open `.env` in a shared screen.
- Use **a new `--label` for every run**. Most tools refuse a label that exists; the monitoring
  drill overwrites it. Never reuse a label a report quotes (`drill-2`, `drill-3`, `real-drill`,
  `release-check-sec-1112`, ...).
- On Windows add `-X utf8` to any command that prints tables (`python -X utf8 -m ...`).
- Do not pipe into `tee` in PowerShell: it writes UTF-16. Every tool saves its own results under
  `runs/`.

---

## 3. Commands, eval set by eval set

Replace `X` in each label with your initials and the date, for example `ss-1112`.

### 3.1 Release check: harness + agent suite in one run (`eval.full`)

This is the one to run before a merge. Exit 0 = ships, exit 1 = does not ship.

```powershell
# stub: free, ~1 min
python -X utf8 -m eval.full --stub --label full-X
# real: ~$0.07 for 52 claims, ~10 min
python -X utf8 -m eval.full --label release-check-X --splits dev,redteam
# real, faster (4 claims at a time)
python -X utf8 -m eval.full --label release-check-X --splits dev,redteam --workers 4
```

Look for: `composite`, `gates held`, the agent-suite checks (`FAIL` lines) and the last line,
`ALL GATES PASSED: safe to ship` or `GATE FAILED: this does not ship`. Output:
`runs/full/<label>/` (`full.json`, `card.png`, `traces.jsonl`).

### 3.2 Harness: is the final answer right?

```powershell
python -m eval.harness.suite                                                              # always stub; 9 of 9 rows must match
python -m eval.harness.run --adapter gold-replay --split dev --label ceiling-X           # sanity first: must score ~1.0
python -m eval.harness.run --adapter claimsense --split dev --label dev-X                # real if a key is set
python -m eval.harness.run --adapter claimsense --split redteam --label redteam-X
python -m eval.harness.run --adapter claimsense --split dev,redteam --label both-X
```

For stub, set `$env:CLAIMSENSE_LLM = "stub"` first (`eval.harness.run` has no `--stub` flag).
Output: `runs/<label>.scorecard.json`. Exit 0 only if every catastrophic gate holds and the
composite reaches the threshold.

### 3.3 Agent suite: what did the agents do?

```powershell
python -X utf8 -m eval.agent_suite --stub --label agents-X --variant v1,guarded          # stub
python -X utf8 -m eval.agent_suite --label real-agents-X --variant v1,guarded            # real, ~$0.13
python -X utf8 -m eval.agent_suite --stub --label agents-X --show CLM-0004               # one claim's full trace
```

Output: `runs/agent_suite/<label>/`. Exit 1 = a gate check failed (`eval/agent_suite/gate.yaml`).

### 3.4 Security (L15)

```powershell
pytest tests/security -q                                                      # 49 guardrail tests, free
python -m claimsense.hooks.pins                                               # tool pins match the reviewed tools
python -X utf8 -m eval.security scoreboard --stub --label scoreboard-X       # stub, ~1 min
python -X utf8 -m eval.security scoreboard --label real-scoreboard-X         # real, ~15 min, adds the guard-model row
python -X utf8 -m eval.security attack --label real-attack-X --rounds 6      # real only, 7 claim runs + 6 attacker calls
```

`attack` exit codes: 0 attacker did not win, 1 **attacker won** (its note is in
`runs/security/<label>/attacker_notes.jsonl`: add it to `eval/redteam/attacks.jsonl`), 2 cannot
start. Report card: `docs/SECURITY_REPORT_CARD.md`.

### 3.5 Retrieval on its own (no key in either mode)

```powershell
python -m claimsense.retrieval.index                                  # only after the knowledge base changes
python -X utf8 -m claimsense.retrieval.evaluate --label retrieval-X   # 47 queries, ~12 min on a laptop CPU
pytest tests/retrieval -q
```

The table shows Top-1, Recall@5 and MRR for each stage: Dense, BM25, RRF, + reranker,
+ rewrite, + category. The last column is what the product uses. Chart:
`runs/retrieval_<label>.png`.

### 3.6 Pipeline with the real retriever (new, section 4)

```powershell
# stub agents + real retriever: free, measures retrieval inside the pipeline
$env:CLAIMSENSE_LLM = "stub"
python -X utf8 -m eval.harness.run --adapter claimsense-real-retrieval --split dev,redteam --label rr-stub-X
Remove-Item Env:CLAIMSENSE_LLM
# real agents + real retriever: the closest eval to production
python -X utf8 -m eval.harness.run --adapter claimsense-real-retrieval --split dev,redteam --label rr-real-X
python -X utf8 -m eval.full --label rr-release-X --variant real-retrieval --workers 4
```

The first claim waits ~30 s while the retriever loads. If the index is missing, the command stops
at once with `the real retriever cannot open: ... Build the index: python -m
claimsense.retrieval.index`.

### 3.7 RAGAS judge: is the rationale backed by the clause? (real only)

```powershell
python -X utf8 -m eval.harness.run --adapter claimsense --split dev --judge --judge-limit 5 --label ragas-X
python -X utf8 -m eval.harness.run --adapter claimsense-real-retrieval --split dev --judge --judge-limit 5 --label ragas-rr-X
```

Look for `rationale_groundedness` in the run metrics (0 to 1, the mean over the judged claims;
`per_claim` and `worst_claim` are in the scorecard JSON). It is **uncalibrated and weighted 0.00**,
so it never changes the composite or the pass/fail. Raise `--judge-limit` only after a first run
looks sane: each judged line is several model calls.

### 3.8 One claim, end to end, with the real tools

```powershell
python -X utf8 scripts/run_one.py --list
python -X utf8 scripts/run_one.py CLM-0004 --real-tools            # real models + real retriever + MCP tools
```

`run_one.py` refuses to run in stub mode.

### 3.9 Observability, DeepEval, live monitoring

```powershell
python -X utf8 -m eval.observability show --stub CLM-0004                 # span tree in memory
python -X utf8 -m eval.observability run --stub --label obs-X             # Jaeger; `setup` once first
$env:DEEPEVAL_DISABLE_DOTENV = "1"; $env:DEEPEVAL_TELEMETRY_OPT_OUT = "1"; $env:CLAIMSENSE_LLM = "stub"
deepeval test run eval/deepeval_suite                                     # 74 tests, free
$env:CLAIMSENSE_DEEPEVAL_JUDGE = "1"; deepeval test run eval/deepeval_suite   # + paid judge tests
python -X utf8 -m eval.monitoring run --stub --label drill-X              # 4-min drill; `setup` once first
```

The monitoring drill is enforced only in stub mode. A real 4-minute drill cost $0.17 and is not
needed.

### 3.10 Framework rubric (no key, no run)

```powershell
python -m eval.tools.rubric_score                     # the score table
python -m eval.tools.rubric_score --plan --insurance  # + what would move it, + regulated weights
pytest eval/tests/test_rubric_report.py -q            # checks the arithmetic in the report
```

The rubric does **not** read the pipeline or any run. A person scores each dimension in section 3
of `docs/FRAMEWORK_RUBRIC_SCORE.md`, with evidence in section 5, and the tool only adds it up. It
stays the same until someone scores it again. Issue 2 (12 November) re-scored it from the code:
D4 2 to 3 (the coverage agent now calls the hybrid retriever), total 2.85. To change a score, edit
that report (sections 3 and 5), then run the test above and rebuild its DOCX:
`python -m eval.tools.build_report_docx --source docs/FRAMEWORK_RUBRIC_SCORE.md --target docs/ClaimSense_Framework_Rubric_Score.docx`.

### 3.11 Tests and lint (always free)

```powershell
pytest                                  # product tests
pytest eval/tests -q                    # eval tests (318)
ruff check . ; ruff format --check .
```

---

## 4. What changed today: retrieval and RAGAS in the pipeline

| | Before | After |
|---|---|---|
| Retrieval in eval runs | Every eval tool used `make_stub_services()`. Its `policy_search` ignores the query and returns a fixed clause list per bill category, even in real mode. The hybrid retriever never ran in an eval. | New adapter `claimsense-real-retrieval` (harness) and variant `real-retrieval` (agent suite, `eval.full`) use the real policy-kb search. Every other tool stays the same, so the run differs in retrieval only. The default runs are unchanged. |
| RAGAS judge input | The coverage agent dropped the model's rationale. The judge scored a sentence the adapter wrote itself ("Line L1 was adjudicated under clause 4.1"). | `CoverageAgent` keeps the model's own rationale and the clause wording it was shown. The adapter passes both to the judge, plus the claim's facts. A line with no model rationale is not judged. |
| Packages | `chromadb`, `rank_bm25`, `sentence_transformers` and `ragas` were not installed. `ragas` cannot install on Python 3.14 as listed. | All installed. `requirements.txt` and `pyproject.toml` install RAGAS's dependencies on 3.14, plus a `--no-deps` step (section 2.1). |

Stub agents + real retriever, dev split (`runs/retrieval-stub-dev-1112.scorecard.json`):


| Dev split, stub agents | Stub clause table (`dev-1112`) | Real retriever (`retrieval-stub-dev-1112`) |
|---|---|---|
| Result | PASS, composite 0.965 | **PASS, composite 0.965**, all gates held |
| route / amounts / flags / citations / tools | 0.955 / 0.943 / 0.955 / 1.000 / 1.000 | 0.955 / 0.943 / 0.955 / 1.000 / 1.000 |
| Weakest claims | CLM-0021, CLM-0022 (0.613) | the same |
| Seconds per claim (p50 / p95) | 0.01 / 0.01 | **17.6 / 33.7** |

The real retriever leads the stub agents to the same decision on every dev claim. The cost was
time: the cross-encoder re-ranker runs on the CPU, 1.5 to 3 s per search, one search per bill
line. With real models the real-retriever run then took p95 64-81 s per claim, far past the
30 s gate.

### 4.1 Fix 1: search cache (latency)

Only **17 of the 188** searches over the 52 claims are distinct: bill lines repeat across claims
("Pharmacy", "OT charges", room, ICU). Search is deterministic over a fixed index, so
`policy_kb.policy_search` now keeps each (query, category, k) answer in memory for the life of
the process (`_cached_hits`, up to 1,024 searches). Nothing is logged or written. The tool's
signature and description are unchanged, so its pin still matches.

| Stub agents + real retriever, 52 claims | Before | With the cache |
|---|---|---|
| Composite | 0.965 (dev) | **0.984**, all gates held (same as the stub table) |
| Seconds per claim, p50 / p95 / max | 17.6 / 33.7 / 36.9 | **0.007 / 3.8 / 15.3** |

The first claims still pay for their searches (max 15.3 s); after that a search is free. A new
bill-line wording costs one search (1.5 to 3 s) the first time it appears.

**Measured with real models** (`runs/full/rr-release-1112c`, 52 claims, one at a time): p50 11.4 s,
p95 **30.2 s**, max 39.8 s. The cache took p95 from 64-81 s to 30.2 s, but the release gate needs
30 s or less, so this run fails by 0.2 s. Everything else passes: composite 0.976, every harness
gate held, 0 of 30 attacks cleared, $0.0017 per claim. The slow claims are the first ones, while
the cache is still empty. A warm-up search of the common bill lines at start-up, or a GPU for the
re-ranker, should bring p95 under 30 s. Re-run with:

```powershell
python -X utf8 -m eval.full --label rr-release-1112c --variant real-retrieval --splits dev,redteam
```

### 4.2 Fix 2: tokens and cost in `eval.harness.run`

The harness adapter never counted the agents' model calls, so `tokens_per_claim` and
`cost_usd_per_claim` read **0** even in real mode. Only `eval.full` and `eval.agent_suite`
counted them. The adapter now counts them the same way (`count_llm_usage`, one shared parser
with `trace.py`). The RAGAS judge's own model calls are still not counted: they go through the
OpenAI client directly, not LangChain.

**Independent review.** Two reviewers checked these changes, and a separate verifier confirmed 7
findings. All 7 are fixed and each has a regression test:
- The judge skips placeholder sentences everywhere.
- `eval.full` and the agent suite give the scorer the same rationales as the harness.
- An adjudicator's edit drops the model's reason for the old clause.
- A missing index or a changed tool stops the run at once with exit 2 and a clear message.
- On Python 3.14 the `eval` extra lists every RAGAS dependency (`pillow` was missing).

Files: `eval/harness/real_retrieval.py` (new), `eval/harness/claimsense_adapter.py`,
`eval/harness/adapters.py`, `eval/harness/run.py`, `eval/harness/llm_judge_metrics.py`,
`eval/agent_suite/trace.py`, `eval/agent_suite/suite.py`, `src/claimsense/agents/coverage.py`,
`requirements.txt`, `pyproject.toml`. Tests: `eval/tests/test_real_retrieval_and_judge.py` (13), `tests/retrieval/test_policy_kb_cache.py` (3),
`tests/orchestration/test_coverage_rationales.py` (2).

---

## 5. Exit codes

| Tool | 0 | 1 | 2 | 3 |
|---|---|---|---|---|
| `eval.full` | ships | does not ship | cannot start | — |
| `eval.harness.run` | gates hold, composite reached | a gate or the composite failed | real retriever cannot open | — |
| `eval.agent_suite` | gate passes | gate fails | cannot start | — |
| `eval.security attack` | attacker did not win | **attacker won** | cannot start, model blocked | — |
| `eval.security scoreboard` | written | — | cannot start, label exists | — |
| `eval.monitoring run` | drill ok | drill failed | cannot start, lock held | inconclusive, rerun |
| `eval.observability run` | every check holds | a check failed | cannot start | — |

## 6. Common errors

| You see | Cause | Fix |
|---|---|---|
| `already exists: use a new --label` | the label was used before | pick a new label |
| `404 Model blocked by guardrail` | your OpenRouter workspace blocks that model | allow it at openrouter.ai, workspace guardrails, or set `CLAIMSENSE_MODEL_COVERAGE` |
| `'CLAIMSENSE_GUARD_LLM=1' is not recognized` | Git Bash syntax typed in PowerShell | `$env:CLAIMSENSE_GUARD_LLM = "1"` (section 2.2) |
| `the real retriever cannot open` / `StaleIndexError` | no index, or the knowledge base changed | `python -m claimsense.retrieval.index` |
| `ragas is not installed` | Python 3.14 skips it in requirements | `pip install --no-deps "ragas>=0.4,<0.5"` |
| `Microsoft Visual C++ 14.0 or greater is required` (scikit-network) | `pip install ragas` on Python 3.14 | use the `--no-deps` step instead |
| `UnicodeEncodeError` / garbled table | cp1252 console | add `-X utf8` |
| `ToolPinError` | a tool's code changed since review | review it, then `python -m claimsense.hooks.pins --update` |
| `tokens_per_claim 0`, `cost_usd_per_claim 0` in a real `eval.harness.run` | the harness did not count model calls before 12 Nov | update to `main`; in stub mode 0 is correct |
| Same command, different score | real models vary a little run to run; the second run overwrote the first's file | use a new `--label` for each run |
| A "stub" run costs money | a key is in the terminal and no `--stub` | add `--stub` or `$env:CLAIMSENSE_LLM = "stub"` |

## 7. Open items

- **Guard model latency (row 2).** Keep it off, or give the guard a faster model, before it can
  pass the 30 s p95 gate.
- **Re-ranker latency (section 4.1).** With real models and the cache, p95 is 30.2 s: the gate
  (30 s or less) fails by 0.2 s. Warm the cache at start-up or give the re-ranker a GPU, then re-run.
- **Real agents + real retriever** (section 3.6) and **RAGAS** (section 3.7) are ready but have
  not run with real models yet. Run them and add the numbers to section 1.
- **RAGAS judge** is uncalibrated: report Cohen's kappa (`eval/calibration/`) before quoting
  its number.
- **MON-01**: a failed tariff lookup still crashes the claim (`docs/MONITORING_REPORT_CARD.md`).
- Full security status: `docs/SECURITY_REPORT_CARD.md`.
