# Reflexion experiment (signature challenge B, L12): how to run it and what is here

Owner: Dhruvi Ramani (Agents & Orchestration, Reflexion part). The whole `src/claimsense/reflexion/`
package is this part's code; the harness files in it (`evaluator.py`, `loop.py`, `playbook.py`,
`reflector.py`, `metrics.py`, `review_cli.py`) started as Spandan Basu's boilerplate.
This folder holds the run outputs and the write-up.

If you are new to Reflexion, read `REPORT-SECTION.md` section 1 first: it explains the idea in plain
words and how it differs from the adjudicator approval in the graph.

| Read | For |
|---|---|
| `REPORT-SECTION.md` | the report section: what Reflexion is, the loop, method, results, every lesson with its review note, design decisions, what the brief asks and where it is answered, open items |
| `run-01/` | the reviewed run of 1 Nov 2026: real model, human gate, frozen playbook (`playbook.json` is the playbook) |
| `harness-check-stub/` | a complete stub-mode run, auto-approved, stamped "HARNESS CHECK ONLY", proving the loop runs on the current gold (rerun 7 Nov 2026) |
| `langgraph-check/` | the real-model baseline run through the LangGraph executor instead of the local runner, same numbers |
| `run-02/` | the reviewed run of 7 Nov 2026 on the gold as corrected by the 4 Nov 2026 audit, tolerance Rs 1 |
| `run-03/` | the reviewed run of 12 Nov 2026 on the final gold (ADR-0006/0007/0009), tolerance Rs 1 |
| `run-04/` | the reviewed run of 14 Nov 2026 with triage (ADR-0014), tolerance Rs 1: **the current result**; `REPORT-SECTION.md` section 10.4. Its frozen playbook has the same hash as `run-03` (no approved lesson in either) |
| `dspy-harness-check-stub/` | the L12 §6-7 comparison (DSPy Predict/ChainOfThought, BootstrapFewShot, BootstrapFewShot + coach, GEPA, the playbook, the retrieval ceiling) run offline with stub LMs on 12 Nov 2026: proves the loop, stamped "HARNESS CHECK ONLY" |
| `dspy-run-01/` | the same comparison with the real models, 12 Nov 2026: GEPA reaches the retrieval ceiling (1.0) and is the chosen method; `REPORT-SECTION.md` section 9.4 |

## Files of this part

| File | What |
|---|---|
| `src/claimsense/reflexion/cases.py` | `load_cases()`: turns `eval/golden_dev/` into `DevCase` objects. Maps starter-pack categories and gold reason codes onto the contracts; raises on anything unmapped. Also `stub_services_factory()`, `MATERNITY_EXCLUSION` and `RULE_DISAGREEMENTS`. |
| `src/claimsense/reflexion/evaluator.py` | the evaluator (code, no model): simulated adjudicator, critic rejections, difference from gold; rounding tolerance |
| `src/claimsense/reflexion/reflector.py` | one model call per mistake → one lesson; blocks lessons that quote amounts or ids |
| `src/claimsense/reflexion/playbook.py` | the playbook: lessons and their status, retrieval of approved lessons, freeze with SHA-256 |
| `src/claimsense/reflexion/loop.py` | baseline → learn → ablate → withdraw → after → freeze; the held-out guards |
| `src/claimsense/reflexion/metrics.py` | settlement error, exact-match rate, edit rate |
| `src/claimsense/reflexion/review_cli.py` | the human gate at the terminal (`y`/`n` plus a reason); `propose-from-edits` turns a claim run's adjudicator edits into PROPOSED lessons (never approves) |
| `src/claimsense/reflexion/triage.py` | before reflection: only a clause-choice mistake becomes a lesson; the rest go to an engineering backlog with a reason; `known_clause_ids()` is the registry the reflector may cite (ADR-0014) |
| `src/claimsense/reflexion/from_edits.py` | brief step 9 offline: `edit_log` records from a run (`run_one.py --edits-out`) → triage → reflect → PROPOSED; the graph never writes a lesson |
| `src/claimsense/reflexion/reporting.py` | Markdown/JSON rendering shared by both scripts |
| `scripts/run_reflexion_experiment.py` | Day 4: `baseline`, `experiment`, `status`. Writes `baseline.md/json`, `report.md/json`, `playbook.json` into `--out`. |
| `scripts/run_reflexion_heldout.py` | Day 5, for the Evaluation owner: before/after on the held-out set with the frozen playbook, 3 repeats, spread. Refuses anything inside the repo. |
| `src/claimsense/reflexion/dspy_coverage.py` | L12 §6-7 on ClaimSense: the `ChooseClauses` DSPy signature (the shipped coverage prompt as its instruction), `render_inputs` (the same facts as `CoverageAgent._ask_model`), `coverage_examples`, the clause-accuracy metric with GEPA feedback (`make_metric`), `program_chooser` (plugs a compiled program into the agent), offline `StubLM` / `OracleStubLM`, `configure_dspy` (models from `agents.llm.MODELS`) |
| `src/claimsense/reflexion/optimizers.py` | the comparison: `split_cases` (admissible dev claims, alternating train/test), `compile_bootstrap`, `compile_gepa`, `measure` (clause accuracy + the pipeline's settlement error / edit rate per row), `choose_winner`, `comparison_md`, `plot`, `save_program` / `load_program` |
| `scripts/run_reflexion_dspy.py` | runs the eight rows of the notebook's §9 table on the dev claims and writes `report.md`, `results.json`, `plot.png`, `programs/*.json` into `--out` |
| `tests/orchestration/test_dspy_coverage.py` | 13 tests, offline: examples leak nothing, metric and reachable lines, stub LM == stub analyst through the pipeline, oracle coach bootstraps demos, program save/load, GEPA runs offline, the `chooser` seam is validated, winner rule, the script end to end (skipped when `dspy` is not installed) |
| `tests/orchestration/test_cases.py` | loading, contract validity, gold reconciliation, reason-code mapping, the gold relabels, unknown codes raise, stub dry run of all 22, the tolerance, both scripts end to end including every refusal |
| `tests/orchestration/test_reflexion.py` | 5 harness tests: learn → approve → improve → ablate → freeze on synthetic cases |
| `tests/orchestration/test_playbook_in_graph.py` | T46 and step 9: `load_frozen` refuses an unfrozen or edited playbook; a frozen lesson is used in a normal run (`lessons_used`); no playbook → no lessons; PROPOSED/REJECTED lessons never reach a run; an adjudicator edit becomes exactly one PROPOSED lesson only through the offline step, and the CLI refuses a frozen playbook |
| `tests/orchestration/test_reflexion_triage.py` | triage rules (claim-level, gate clauses, same-clause gold gaps, critic arithmetic, REF-17), the clause-id registry, the reflector dropping invented ids, a refused lesson never proposed again, `learn()` writing the backlog |

Outside these files this part touches `agents/coverage.py` and `agents/__init__.py` only: the
playbook hook (`CoverageAgent.lessons_for()`) already existed, and on 12 Nov 2026 a `chooser`
argument was added (four lines) so a compiled DSPy program can replace the clause-selection call
alone, with the agent's candidate validation, admissibility and calculator untouched. `loop.py`'s
run functions pass it through.

## 1. Run it without a model (stub mode, anyone, two minutes)

```bash
pip install -e ".[dev,agents]"       # once, inside your virtualenv
pytest tests/orchestration -q        # no key, no network

# baseline with an empty playbook (what the system does before any lesson)
python scripts/run_reflexion_experiment.py baseline --out /tmp/reflexion-check --tolerance-rs 1

# the whole loop with every lesson auto-approved: a harness check, NOT a result
python scripts/run_reflexion_experiment.py experiment --approve auto --reviewer "<name>" \
    --out /tmp/reflexion-check --after-runs 2 --tolerance-rs 1
```

Stub mode is on whenever `OPENROUTER_API_KEY` is not set, or when `CLAIMSENSE_LLM=stub`. The stub
coverage analyst picks clauses deterministically and the stub reflector writes template lessons, so
the numbers prove the loop runs, nothing more. `--approve auto` prints a warning and stamps
`report.md` "HARNESS CHECK ONLY".

## 2. Run it with the real model (the reported run)

Each team member uses their **own** OpenRouter key. Keys live only in your shell or in a local
`.env` that git ignores. Never paste a key into a file that is committed, a chat, or a screenshot.

**Step 1: network.** Use a network that reaches `openrouter.ai` (corporate proxies block it).

**Step 2: key and models.** The course key does not allow `openai/gpt-4.1`, which is the
reflector's default, so point the reflector at `gpt-4.1-mini` too.

```powershell
# Windows PowerShell (nothing here is saved to disk)
$env:OPENROUTER_API_KEY = "<your own key>"
$env:CLAIMSENSE_MODEL_REFLECTOR = "openai/gpt-4.1-mini"
```

```bash
# macOS / Linux / Git Bash
export OPENROUTER_API_KEY="<your own key>"
export CLAIMSENSE_MODEL_REFLECTOR="openai/gpt-4.1-mini"
```

Other model ids can be overridden the same way (`CLAIMSENSE_MODEL_COVERAGE`, `_CRITIC`,
`_FRAUD`, `_EXTRACTION`, `_SETTLEMENT`); the defaults are in `src/claimsense/agents/llm.py`.

**Step 3: baseline.** Pick a new output folder; a folder with a frozen playbook is refused.

```bash
python scripts/run_reflexion_experiment.py baseline \
    --out docs/experiments/reflexion/run-02 --tolerance-rs 1
```

The first line printed is the banner. Check it says `mode: REAL MODEL via OpenRouter`; if it says
`STUB`, the key is not in the environment.

**Step 4: the experiment.** A person sits at the terminal. For every proposed lesson the script
prints the lesson, when it applies and the clauses it cites, and asks `approve? [y/n]`. On `n` it
asks for the reason, which is stored with the lesson. Approve a lesson only if it restates the
policy wording correctly and would help on a *different* claim; reject anything that encodes the
gold file's demo rules against the wording, cites a clause id that does not exist, is vague, or
duplicates an approved lesson.

```bash
python scripts/run_reflexion_experiment.py experiment --reviewer "<your name>" \
    --out docs/experiments/reflexion/run-02 --after-runs 2 --tolerance-rs 1
```

Stages, printed as `[1/6]` to `[6/6]`: baseline → learning pass with the human gate → ablation
(leave one approved lesson out at a time) → withdraw harmful lessons → after pass, twice → freeze.
It writes `report.md`, `report.json`, `playbook.json` (frozen, with its hash) into `--out`.

**Step 5: check the frozen playbook.**

```bash
python scripts/run_reflexion_experiment.py status --out docs/experiments/reflexion/run-02
```

**Step 6: report.** Copy the before/after table and the lesson counts from `report.md` into
`REPORT-SECTION.md` section 4. Commit the `run-02/` folder (no key is ever written into it).

Useful switches: `--executor langgraph` runs the real LangGraph graph instead of the local runner
(same numbers, slower); `--calculator team` uses the team calculator through
`agents.services.real_calculate`; `--tolerance-rs 0` is strict scoring.

### What `--tolerance-rs` does

The development gold is written in whole rupees; the calculator keeps paise. A correctly cut line
can therefore differ from the gold by up to Rs 0.50, and strict scoring treats that as a mistake,
which in `run-01` produced two "do not round prematurely" lessons that no clause choice can act on.
With `--tolerance-rs 1`, a line within Rs 1 of the gold counts as agreeing: the simulated
adjudicator does not edit it and no mistake is raised for it. Settlement error in rupees is always
reported exactly; only `exact_match_rate` and the mistake list change. The tolerance is printed in
the banner and stored in every result file. Agreed with the lead: this belongs in the evaluator,
the gold is not changed.

## 2b. The L12 §6-7 comparison: DSPy, BootstrapFewShot, GEPA against the playbook

The L12 hands-on notebook (`L12_self_improvement_handson.ipynb`, sections 6-9) builds a DSPy
signature for its claims assistant, compiles it with BootstrapFewShot (alone and with a stronger
teacher) and GEPA, and puts every lever in one table beside the Reflexion playbook.
`scripts/run_reflexion_dspy.py` does the same on ClaimSense, with one difference that follows from
project rule 1: the DSPy program picks *clauses*, never rupees, so the metric is clause accuracy and
the money is measured beside it through the ordinary pipeline. Full description in
`REPORT-SECTION.md` section 9.

```bash
pip install -e ".[dev,agents,reflexion]"      # the reflexion extra is dspy (+ matplotlib for the plot)
pytest tests/orchestration/test_dspy_coverage.py -q

# offline harness check (stub LMs; stamped HARNESS CHECK ONLY, never a result)
python scripts/run_reflexion_dspy.py --out docs/experiments/reflexion/dspy-harness-check-stub \
    --tolerance-rs 1 --gepa-metric-calls 30

# the real run (your own key; a few hundred model calls, cents; GEPA is the slow part)
export OPENROUTER_API_KEY="<your own key>"
export CLAIMSENSE_MODEL_REFLECTOR="openai/gpt-4.1-mini"    # the course key has no gpt-4.1
python scripts/run_reflexion_dspy.py --out docs/experiments/reflexion/dspy-run-01 --tolerance-rs 1
```

The banner must say `mode: REAL MODEL via OpenRouter`; a `STUB` banner means the key is not in the
environment. Switches: `--gepa-metric-calls N` (default 100; the notebook used 150 on 12 training
claims), `--bootstrap-demos N` (default 4), `--skip bootstrap coach gepa` to leave out slow rows,
`--threads N` for GEPA, `--seed N`, `--playbook <path>` (default: the frozen `run-02` playbook) and
`--calculator team`. The script refuses any `--cases` path that names the held-out set.

Outputs in `--out`: `report.md` (banner, split, the one table, the chosen method and why, every
optimised instruction, per-case rows), `results.json`, `plot.png`, and `programs/*.json`, one file
per compiled program (instruction + demos: the notebook's "the improvement is a file", §7.5).

## 3. Day 5: held-out run (Evaluation owner only)

Use the **latest frozen** playbook: `run-03` today, `run-04` once the rerun after ADR-0014 is
frozen (its hash goes into `eval/experiments/configs/E3_reflexion.yaml` as well).

```bash
python scripts/run_reflexion_heldout.py \
    --playbook docs/experiments/reflexion/run-03/playbook.json \
    --heldout data/claimsense-heldout \
    --out ../claimsense-heldout-results/run-03 --repeat 3 --tolerance-rs 1
```

The held-out set lives in `data/claimsense-heldout/` since 14 Nov 2026 (Spandan's ADR-0013, a folder
the agents and Claude sessions are denied); the script accepts that folder or any path outside the
repo. Use the same `--tolerance-rs` as the day-4 run. It refuses to run if the playbook is not frozen,
changed since freezing, contains a lesson learned from a held-out case, if a held-out id also
appears in the dev set, or if the held-out directory or the output directory is inside the
repository. Held-out files are expected in the `golden_dev` format. Paste its `heldout_report.md`
tables into `REPORT-SECTION.md` section 4.4.

## 4. Results so far

| Run | Gold | Model | Tolerance | Before → after | Lessons |
|---|---|---|---|---|---|
| `run-01/` (1 Nov 2026, reviewed) | pre-audit | `openai/gpt-4.1-mini`, reviewer Dhruvi Ramani at the console | 0 | Rs 65,989.27 / exact 0.30 / edit 0.20 → identical, both after runs | 14 proposed, 2 approved, 12 rejected with reasons, 0 withdrawn; frozen hash `6b4c530d…` |
| `harness-check-stub/` (7 Nov 2026, not a result) | post-audit (4 Nov) | stub, auto-approved | Rs 1 | Rs 186,368.94 / exact 0.50 / edit 0.30 → identical | 6 template lessons, none harmful |
| `run-02/` (7 Nov 2026, reviewed) | post-audit (4 Nov) | `openai/gpt-4.1-mini`, reviewer Dhruvi Ramani at the console | Rs 1 | Rs 186,368.94 / exact 0.50 / edit 0.30 → identical, both after runs | 19 proposed, 1 approved, 18 rejected with reasons, 0 withdrawn; frozen hash `b5666378…` |
| `run-03/` (12 Nov 2026, reviewed) | final (ADR-0006/0007/0009) | `openai/gpt-4.1-mini`, reviewer Dhruvi Ramani at the console | Rs 1 | Rs 112,102.91 / exact 0.864 / edit 0.136 / critic rejection 0.182 → identical, both after runs | 16 proposed, 0 approved, 16 rejected with reasons, 0 withdrawn; frozen hash `4f53cda1…` |
| `run-04/` (14 Nov 2026, reviewed, triage on) | final, after the revert of `78114a5` | `openai/gpt-4.1-mini`, reviewer Dhruvi Ramani at the console | Rs 1 | Rs 39,904.80 / exact 0.909 / edit 0.091 / critic rejection 0.182 → identical, both after runs | 1 proposed, 0 approved, 1 rejected with reason, 9 mistakes triaged to the backlog (8 REF-17 critic items, 1 duplicate); frozen hash `4f53cda1…` (same as run-03: no approved lesson in either) |
| held-out, 60 claims (14 Nov 2026, frozen `run-04` playbook, `data/claimsense-heldout`) | reviewed held-out gold (ADR-0013) | `openai/gpt-4.1-mini`, no reflection | Rs 1 | Rs 178,203.73 / exact 0.883 / edit 0.117 / critic 0.05 → identical (0 approved lessons; one repeat) | the E3 before/after; `REPORT-SECTION.md` 4.5; report file outside the repo |
| `dspy-harness-check-stub/` (12 Nov 2026, not a result) | current (ADR-0006/0007/0009) | stub LMs (student = top candidate, coach = gold replay) | Rs 1 | test half (7 claims): clause accuracy 0.574 for every method, 1.0 for the retrieval ceiling; settlement error Rs 18,052.33 for every row | all eight rows run, 5 programs saved, GEPA loop runs offline |
| `dspy-run-01/` (12 Nov 2026, real models, Dhruvi Ramani's key) | current | `openai/gpt-4.1-mini` as student, coach and reflector | Rs 1 | test clause accuracy: agent prompt 0.645, + playbook 0.61, Predict 0.574, ChainOfThought 0.917, BootstrapFewShot 0.952, + coach 0.952, **GEPA 1.0** (= ceiling); settlement error Rs 18,052.33 in every row | **GEPA chosen**; its 2,777-char instruction is `dspy-run-01/programs/gepa.json`; reading in `REPORT-SECTION.md` 9.4 |

Why the stub baseline error grew from Rs 65,989 to Rs 186,369 between the two gold versions: the
audit relabelled CLM-0018 (caesarean, excluded under clause 7.15, gold now Rs 0) and the pipeline
has no exclusion check yet, and it re-filed CLM-0016's ICU line, where the calculator now applies
the proportional cut to the other lines and the gold does not. Both are listed in
`RULE_DISAGREEMENTS` and in `REPORT-SECTION.md` section 7. Full reading of `run-01` in
`REPORT-SECTION.md` section 4.2 and of `run-02` in section 4.3.

**The gold moved after `run-02`, so `run-03` is the current result.** ADR-0006, ADR-0007 and
ADR-0009 (11 Nov 2026, commits `74fbd2c` to `5221ef4`) changed the gold and the calculator. `run-03`
reran the reviewed experiment on that gold: Rs 112,102.91 total error over 22 claims, exact-match
0.864, edit rate 0.136, three real misses left (CLM-0008: the 6.2 specific wait has no list in the
admissibility check; CLM-0021 and CLM-0022: the cataract sub-limit, clause 4.3, is informational in
the calculator). All 16 proposed lessons were rejected with reasons; the frozen playbook has no
approved lesson, so the held-out run will measure before == after by construction. New since
`run-02`: a critic-rejection rate of 0.182, the critic refusing the DEC-04 duplicate-line deduction
cited under clause 2 (REF-17, a critic item). Use `run-03/playbook.json` for the held-out run.

## 5. Decisions taken with the lead (walkthrough, Nov 2026)

1. **Pharmacy / procedure reading.** The gold is **not** relabelled now: a relabel changes every
   owner's scores. The loader's mapping stays as it is and the disagreement is reported.
2. **Duplicate bill lines.** Stay a fraud flag for the human adjudicator. No clause pays them at zero.
3. **Rounding.** A tolerance in the Reflexion evaluator (`--tolerance-rs`), not a change to the gold.
   The evaluator is part of this folder, so it was done here.
4. Headroom, TODO clause ids in `agents/clauses.py`, and the team calculator are the lead's to look
   at separately.

## 6. Findings still open

1. **ICU-breach proportional cut (CLM-0016).** The gold caps the ICU day but applies no proportional
   cut because the room rent is within its cap; the calculator applies clause 4.1.1 Note (b) to an
   ICU breach too. Needs a domain ruling.
2. **Exclusions (CLM-0018).** The coverage analyst's admissibility check has no exclusion rule
   (AGT-02 in the gold audit); until it does, CLM-0018 is a known baseline miss.
3. **Headroom.** With the reference calculator a clause choice changes an amount only for
   non-payable or waiting-period clauses, which the pipeline already gets right. A measurable
   before/after needs dev cases where the clause choice decides the money.
4. `agents/clauses.py` still has four `TODO` clause ids; lessons quote them verbatim.

## 7. The playbook in a normal claim run, and live edits → lessons (T46, brief step 9; ADR-0014)

Until 13 Nov 2026 only the two experiment scripts ever passed a playbook to the team. Now:

```bash
# a normal claim run that reads the frozen playbook (real model; stub mode is refused by run_one)
python scripts/run_one.py CLM-0004 --playbook docs/experiments/reflexion/run-03/playbook.json
#   prints:  Playbook: 4f53cda18c2b, 0 approved lessons     (or "Playbook: none" without the flag)
#   and, after the coverage step, lessons_used: [...]        (the lesson ids the analyst read)

# an adjudicator edits a line at the console; the run appends the edit to a JSON-lines file
python scripts/run_one.py CLM-0004 --reviewer console --edits-out runs/edits.jsonl
#   at the pause type: edit  ->  line id, the clause that should govern it, why

# offline: edits -> triage -> one PROPOSED lesson each (nothing is approved here)
python -m claimsense.reflexion.review_cli propose-from-edits runs/live-playbook.json --edits runs/edits.jsonl
# the human gate, then a new freeze = a new hash = a new deploy
python -m claimsense.reflexion.review_cli review runs/live-playbook.json --reviewer "<your name>"
```

Rules, all enforced in code: `Playbook.load_frozen` refuses a playbook that is not frozen or whose
approved lessons changed after freezing; `propose-from-edits` refuses a frozen playbook; the graph
never writes a lesson (`memory_update` records claim history only); PROPOSED, REJECTED and WITHDRAWN
lessons are never retrieved. The edit record holds ids, clauses, the line category and the reason the
adjudicator typed, nothing from the documents.

## 8. Two questions the team asked

**How is Reflexion evaluated?** By code, twice over. On the dev claims: settlement error is the
first worksheet shown to the adjudicator minus the gold, in `Decimal`, with a Rs 1 rounding
tolerance; edit rate comes from a simulated adjudicator who knows the gold; each approved lesson is
removed in turn and the set rerun (a lesson is harmful if removing it lowers error or edits); the
after pass runs twice. On the held-out claims (E3): the Evaluation owner runs the 60 claims in `data/claimsense-heldout/` once,
without and with the frozen playbook, three repeats, with the spread and the lesson-generation cost
(`eval/experiments/e3.py`). The eval harness itself never loads a playbook: lessons learned on dev
claims would inflate the dev score. Clause-level accuracy is measured separately in section 2b.

**How is the playbook used in deployment?** As a versioned file, like a prompt. A frozen
`playbook.json` is loaded once at start (`Playbook.load_frozen`) and handed to `Team(playbook=...)`;
the coverage analyst reads at most three approved lessons that share a clause or wording with the
claim and records their ids in `lessons_used`. New lessons come only from the offline review of
adjudicator edits (section 7). Approving a lesson changes the hash, so a new playbook is a new
release. Nothing in the loop changes an amount: the calculator decides the rupees and a person
approves the settlement.

## Contribution-log rows

Both rows are in `CONTRIBUTIONS.md` (1 Nov 2026 and 7 Nov 2026).
