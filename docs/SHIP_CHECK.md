# ClaimSense: the whole evaluation in one command

**For:** the team, from a Windows PowerShell terminal at the repository root.
**Updated:** 13 November 2026 (Eval & Red-Team).
**Code:** `eval/ship/runner.py`. The individual commands are still in `docs/Run_command_all.md`.

One command runs every evaluation and gives one answer: **is this commit safe to ship?**

---

## 1. Set up once

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install --no-deps "ragas>=0.4,<0.5"          # Python 3.14 only
python -m claimsense.retrieval.index             # build the search index (needed by retrieval and RAGAS)
```

## 2. The command

### Free rehearsal (no key, no cost, about 10 minutes)

```powershell
python -X utf8 -m eval.ship --label X-stub --stub
```

### The ship decision (real models, costs money, roughly 40 minutes: an estimate)

The key must be in the terminal's environment. Having it in `.env` is not enough: no tool here
reads `.env` on its own, so a run never spends money by accident. If you see
`OPENROUTER_API_KEY is not set`, load it into this terminal first:

```powershell
# 1. Load .env into this terminal (prints nothing; repeat in every new terminal)
Get-Content .env | ForEach-Object { if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') { Set-Item "env:$($Matches[1])" $Matches[2].Trim().Trim('"').Trim("'") } }

# 2. Stub mode off, then check (prints only "key loaded", never the key)
Remove-Item Env:CLAIMSENSE_LLM -ErrorAction SilentlyContinue
python -c "import os; print('key loaded' if os.getenv('OPENROUTER_API_KEY') else 'key NOT loaded')"

# 3. Run
python -X utf8 -m eval.ship --label X-real
```

If step 2 prints `key NOT loaded`, check that the line in `.env` reads exactly
`OPENROUTER_API_KEY=...`. Never print, paste or share the key.

Replace `X` with your initials and the date, for example `ss-1113`. Do not type a literal `X`.
Use a new label every time: a label that exists is refused.

While lint and format still fail on `main`, a real run ends in `DO NOT SHIP`. To see the
real-model results of the other stages first, add `--skip lint,format`. The verdict is then
`NOT VERIFIED`, never `SHIP`, because a skipped blocking stage does not count as passed.

## 3. What it runs

| # | Stage | What it checks | Blocks shipping? | Real-mode cost |
|---|---|---|---|---|
| 1 | `tests` | Product tests, always offline (as in CI) | Yes | free |
| 2 | `lint` | `ruff check .` (as in CI) | Yes | free |
| 3 | `format` | `ruff format --check .` (as in CI) | Yes | free |
| 4 | `tool-pins` | Tool definitions unchanged since review | Yes | free |
| 5 | `release-gate` | `eval.full`: harness self-check, all 22 dev + 30 red-team claims, harness scorecard and its 6 safety gates, agent suite and `gate.yaml`, combined gate | Yes | about $0.07 |
| 6 | `tool-use` | `eval.agentic`: tool order, calling agent, arguments, hooks, guardrails, tool correctness (always offline) | Yes | free |
| 7 | `deepeval` | DeepEval trajectory tests (code checks; no judge) | Yes | about $0.04 |
| 7b | `deepeval-judge` | DeepEval payload judge, GEval + faithfulness (real mode only) | No, report only: uncalibrated | about $0.02 |
| 8 | `security` | Security scoreboard: each defence against the attacks, honest claims alongside | No, report only | real agents |
| 9 | `retrieval` | Policy-search recall on 47 queries | No, report only | free (local model) |
| 10 | `ragas` | RAGAS rationale groundedness on 5 dev claims (real mode only) | No, report only: uncalibrated, weight 0.00 | small |
| 11 | `attacker` | Adaptive attacker, only with `--attack` (real mode only) | No, report only | real agents |

Costs are the team's last recorded figures (`docs/Run_command_all.md`, `eval/deepeval_suite/README.md`).

## 4. Reading the answer

The last line is the verdict, and the exit code matches it:

| Verdict | Exit | Meaning |
|---|---|---|
| `SHIP` | 0 | Every blocking stage ran and passed, with real models |
| `REHEARSAL PASSED` | 0 | The same, but in stub mode. Not a ship decision: no model was called |
| `DO NOT SHIP` | 1 | A blocking stage failed. Open its log |
| `NOT VERIFIED` | 2 | A blocking stage could not run (missing package, index or key). Fix the setup and rerun |

Results go to `runs/ship/<label>/`:

- `summary.md` and `summary.json`: one row per stage, with its result, time and output folder.
- `logs/<stage>.log`: everything that stage printed.

Each tool also keeps its usual output: `runs/full/<label>-full/`,
`runs/agentic/<label>-agentic.*`, `runs/security/<label>-sec/` and `runs/retrieval_<label>.png`.

## 5. Options

```powershell
python -m eval.ship --label X --list                        # show the stages, run nothing
python -m eval.ship --label X --stub --skip retrieval       # leave out the 6-12 minute retrieval stage
python -m eval.ship --label X --stub --only lint,tests      # run just these stages
python -m eval.ship --label X --attack                      # add the adaptive attacker (paid)
python -m eval.ship --label X --variant guarded             # gate on another agent-suite variant
python -m eval.ship --label X --workers 4 --judge-limit 5   # parallel claims; RAGAS claim count
```

A skipped blocking stage is not "passed". With `--skip` on a blocking stage, the verdict can only
be `NOT VERIFIED` or `DO NOT SHIP`.

## 6. Last results

`X-real` (real models, 13 November 2026, commit `18e0d31`): **DO NOT SHIP**.

| Stage | Result |
|---|---|
| tests, tool-pins, tool-use | passed |
| lint, format | **failed** (as below) |
| release-gate | passed in real mode: composite 0.984, every gate held |
| deepeval | **failed**, but only the paid GEval "review payload checklist" judge: 18 claims scored 0.0. Every code-checked trajectory test passed |
| security, retrieval, ragas | ran (report only) |

The DeepEval judge was blocking in that run. It is uncalibrated, like RAGAS, so it has since moved
to its own report-only stage, `deepeval-judge`. Its 0.0 scores still need a look: either the
review payload lacks what the checklist asks for, or the judge is not shown it. Calibrate it
(`eval/calibration`) before it may block again.


`ss-1113-stub` (stub mode, 13 November 2026, commit `366faf4`): **DO NOT SHIP**.

| Stage | Result |
|---|---|
| tests | passed |
| lint | **failed**: 113 ruff errors in product code (mostly line length), the same errors CI reports |
| format | **failed**: 3 files would be reformatted |
| tool-pins | passed (8 of 8 tools match) |
| release-gate | passed: composite 0.984 (needs 0.85), every gate held |
| tool-use | passed: 260/260 runs on all 8 metrics; 11 open defects, all known |
| deepeval | passed |
| security | input guardrail: 0 of 30 attacks cleared, 18 of 18 injections shown |
| retrieval | ran (chart `runs/retrieval_ss-1113-stub.png`) |
| ragas | skipped (needs a real model) |

The only blockers are lint and format. The code owners can fix them with `ruff check --fix .` plus
hand edits for line length, then run `ruff format .`.

## 7. Rules

- Pass `--stub` unless you mean to pay. Without it the command refuses to start when no key is
  loaded, or when `CLAIMSENSE_LLM=stub` is set.
- Never print, paste or commit `OPENROUTER_API_KEY`.
- Never run the held-out set with this command; it uses dev and red-team claims only.
- Do not lower a threshold to get `SHIP`. The gates live in `eval/harness/scorecard.yaml` and
  `eval/agent_suite/gate.yaml`.
