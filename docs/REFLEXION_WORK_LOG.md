# Reflexion work log: what was done, what was observed, what is open

**Owner:** Dhruvi Ramani (Agents & Orchestration, Reflexion part).
**Scope:** `src/claimsense/reflexion/`, `scripts/run_reflexion_experiment.py`,
`scripts/run_reflexion_heldout.py`, `tests/orchestration/test_cases.py`,
`tests/orchestration/test_reflexion.py`, `docs/experiments/reflexion/`.
**Written:** 8 November 2026, from the files on `main` at commit `86cf567`. **Updated:** 12 November 2026 (DSPy / GEPA comparison, real run `dspy-run-01`, `run-03` on the final gold, REF-13 to REF-17); 13 November 2026 (T46 frozen loader in `run_one`, edits → proposed lessons, triage, ADR-0014, REF-18 to REF-21).
**Style:** ASD-STE100 (Simplified Technical English). Short sentences. One instruction per
sentence. Active voice. The same word for the same thing.

This document has one purpose. It helps a teammate debug the code and understand the problems.
It does not replace the report. The report is `docs/experiments/reflexion/REPORT-SECTION.md`.

---

## 1. Words used in this document

| Word | Meaning |
|---|---|
| gold | The correct worksheet for a development claim. File: `eval/golden_dev/gold_worksheets.jsonl`. |
| mistake | A difference between the agent output and the gold, an adjudicator edit, or a critic rejection. |
| lesson | One short rule that the model writes from one mistake. It names the clause and says when it applies. |
| playbook | The list of all lessons with their status. Only APPROVED lessons reach the agent. |
| human gate | A named person reads each lesson and types `y` or `n`. On `n` the person types a reason. |
| freeze | A SHA-256 hash of the approved lessons. After the freeze, the playbook does not change. |
| stub mode | The run without a model. The code picks clauses with fixed rules. It proves that the loop runs. |
| real mode | The run with a model through OpenRouter. This gives the reported result. |
| tolerance | A line within Rs 1 of the gold counts as correct. Switch: `--tolerance-rs 1`. |
| held-out set | 60 claims in `data/claimsense-heldout/`, a folder the agents are denied (ADR-0013). Only Eval & Red-Team runs them, once. |

---

## 2. What Reflexion does

1. Run the agent on the 20 development claims.
2. Compare each worksheet with the gold. The code does this. No model does this.
3. For each mistake, ask the model for one lesson.
4. Show each lesson to a person. The person approves or rejects it with a reason.
5. Put the approved lessons in the playbook.
6. Remove one approved lesson at a time and run again. This is the ablation. It finds lessons that
   make results worse. Those lessons are withdrawn.
7. Run the agent again with the playbook. Do this two times.
8. Freeze the playbook with a hash.
9. Eval & Red-Team runs the frozen playbook on the held-out set, once.

The playbook never changes a rupee. A lesson can change only which clause the coverage analyst
cites. The calculator computes every amount. A person approves every settlement.

---

## 3. What was built

### 3.1 Code

| File | What it does | Tests |
|---|---|---|
| `reflexion/cases.py` | Loads `eval/golden_dev/` into `DevCase` objects. Maps categories and reason codes to the contracts. Raises on an unknown code. Lists `RULE_DISAGREEMENTS`. | `test_cases.py` |
| `reflexion/evaluator.py` | Finds mistakes. Compares worksheet to gold with `Decimal`. Applies the tolerance. | `test_cases.py`, `test_reflexion.py` |
| `reflexion/reflector.py` | One model call per mistake. Returns one lesson. Blocks a lesson that quotes an amount, a name or an id. | `test_reflexion.py` |
| `reflexion/playbook.py` | Stores lessons. Status: PROPOSED, APPROVED, REJECTED, WITHDRAWN. Returns at most 3 approved lessons for a claim. Freezes with SHA-256. | `test_reflexion.py` |
| `reflexion/loop.py` | Runs baseline, learn, ablate, withdraw, after, freeze. Refuses the held-out set in `learn()`. | `test_reflexion.py`, `test_cases.py` |
| `reflexion/metrics.py` | Settlement error, exact-match rate, edit rate, critic-rejection rate. | `test_reflexion.py` |
| `reflexion/review_cli.py` | The human gate at the terminal. `propose-from-edits` files a claim run's adjudicator edits as PROPOSED lessons. It approves nothing. | `test_cases.py` (script end to end), `test_playbook_in_graph.py` |
| `reflexion/triage.py` | Decides before reflection if a mistake is a clause choice. Sends the rest to a backlog with a reason. Holds the clause-id registry the reflector may cite. | `test_reflexion_triage.py` |
| `reflexion/from_edits.py` | Reads `edit_log` records from a run. Triage, reflect, PROPOSED. The graph never writes a lesson. | `test_playbook_in_graph.py` |
| `reflexion/playbook.py` (13 Nov) | `load_frozen`: refuses an unfrozen or edited playbook. `duplicate_of`: a refused lesson is not proposed again. | `test_playbook_in_graph.py`, `test_reflexion_triage.py` |
| `scripts/run_one.py` (13 Nov) | `--playbook` loads a frozen playbook into a normal claim run (T46). `--edits-out` writes the run's edits. The console reviewer accepts `edit`. | manual; needs a real key |
| `reflexion/reporting.py` | Writes `report.md` and `report.json`. | `test_cases.py` |
| `scripts/run_reflexion_experiment.py` | Commands `baseline`, `experiment`, `status`. | `test_cases.py` |
| `scripts/run_reflexion_heldout.py` | Held-out run with a frozen playbook. Refuses an unfrozen, changed or leaky playbook. Refuses a path inside the repository. | `test_cases.py` |
| `reflexion/dspy_coverage.py` | L12 §6-7. The `ChooseClauses` DSPy signature. Renders the same facts as the agent prompt. Builds examples from dev cases. The clause-accuracy metric with GEPA feedback. Plugs a compiled program into the agent (`program_chooser`). Offline stub LMs. | `test_dspy_coverage.py` |
| `reflexion/optimizers.py` | The comparison. Train/test split. BootstrapFewShot and GEPA compile. One `measure()` per row: clause accuracy and the pipeline's rupees. Winner rule. Table and plot. Program save/load. | `test_dspy_coverage.py` |
| `scripts/run_reflexion_dspy.py` | Runs the eight rows of the notebook's §9 table. Writes `report.md`, `results.json`, `plot.png`, `programs/*.json`. | `test_dspy_coverage.py` |
| `agents/coverage.py`, `agents/__init__.py` | New `chooser` argument (four lines). Replaces only the clause-selection call. Validation, admissibility and calculator unchanged. | `test_dspy_coverage.py` |

The harness files (`evaluator.py`, `loop.py`, `playbook.py`, `reflector.py`, `metrics.py`,
`review_cli.py`) started as Spandan Basu's boilerplate. `cases.py`, `reporting.py`, both scripts
and `test_cases.py` are new.

### 3.2 Tests

| File | Count | What they check |
|---|---|---|
| `tests/orchestration/test_cases.py` | 11 | Loading, contract validity, gold reconciliation, reason-code mapping, the 4 Nov gold relabels, unknown codes raise, stub run of all 20 claims, the tolerance, both scripts end to end with every refusal. |
| `tests/orchestration/test_reflexion.py` | 5 | Learn, approve, improve, ablate, freeze on synthetic cases. Held-out refuses an unfrozen or leaky playbook. |
| `tests/orchestration/test_dspy_coverage.py` | 13 | Examples leak no eval-only field. Metric scores reachable lines and names the expected clause. Stub LM equals the stub analyst through the whole pipeline. Oracle coach bootstraps demos; program saves and loads. GEPA runs offline. The `chooser` seam is validated like the model. Winner rule. The script end to end. Skipped when `dspy` is not installed (CI). |
| `tests/orchestration/test_playbook_in_graph.py` | 8 | T46: `load_frozen` refuses an unfrozen or edited playbook. A frozen lesson is used in a normal run. No playbook, no lessons. PROPOSED and REJECTED lessons never reach a run. An edit becomes one PROPOSED lesson only through the offline step. The CLI refuses a frozen playbook. |
| `tests/orchestration/test_reflexion_triage.py` | 6 | Triage rules. The clause-id registry. The reflector drops invented ids. A refused lesson is not proposed again. `learn()` writes the backlog. |

Status on 13 November 2026: the first run of `pytest tests/orchestration -q` on the new code
passed every new test. The only failures were the 24 tests that load the dev gold, all with one
cause: the CLM-0021 gold total no longer reconciled (REF-21). Resolved the same night by reverting
the gold commit on `main` with the author's agreement.

Recorded status on 7 November 2026: all tests in `tests/orchestration/` pass (51 tests, this
includes Spandan's tests). `ruff check` on the Reflexion files reports 0 problems.
This Mac has no virtual environment, so the numbers were not run again on 8 November.

### 3.3 Documents

| File | What |
|---|---|
| `docs/experiments/reflexion/README.md` | How to run in stub mode and in real mode. Env vars. Model override. Results table. Open findings. |
| `docs/experiments/reflexion/REPORT-SECTION.md` | The report section. What Reflexion is. The loop. Method. All results. Every lesson with its reason. Design decisions. Brief-to-code map. |
| `docs/experiments/reflexion/run-01/` | Reviewed run, 1 Nov 2026, pre-audit gold, strict scoring. |
| `docs/experiments/reflexion/run-02/` | Reviewed run, 7 Nov 2026, corrected gold, tolerance Rs 1. |
| `docs/experiments/reflexion/run-03/` | Reviewed run, 12 Nov 2026, final gold, tolerance Rs 1. **This is the current result.** 0 approved lessons; frozen. |
| `docs/experiments/reflexion/harness-check-stub/` | Stub run, auto-approved. Marked "HARNESS CHECK ONLY". Not a result. |
| `docs/experiments/reflexion/langgraph-check/` | Real-model baseline through the LangGraph executor. Same numbers as the local runner. |
| `docs/experiments/reflexion/dspy-harness-check-stub/` | The L12 §6-7 comparison in stub mode, 12 Nov 2026. Marked "HARNESS CHECK ONLY". Not a result. |
| `docs/experiments/reflexion/dspy-run-01/` | The same comparison with real models, 12 Nov 2026. **GEPA chosen, test clause accuracy 1.0.** |
| `CONTRIBUTIONS.md` | Rows for 1 Nov and 7 Nov 2026. |

### 3.4 Commits

| Commit | Date | What |
|---|---|---|
| `889866b` | 1 Nov 2026 | Experiment runner, case loader, held-out runner, first results. |
| `577b288` | 2 Nov 2026 | Baseline through the LangGraph executor with the real model. |
| `4fe285e` | 7 Nov 2026 | Rounding tolerance, gold-audit mapping, run-02, README and report. |
| `425422c` | 7 Nov 2026 | Lint clean-up of the harness files. No behaviour change. |

---

## 4. How to run it

### 4.1 Stub mode (no key, two minutes)

```bash
pip install -e ".[dev,agents]"
pytest tests/orchestration -q
python scripts/run_reflexion_experiment.py baseline --out $TMPDIR/reflexion-check --tolerance-rs 1
python scripts/run_reflexion_experiment.py experiment --approve auto --reviewer "<name>" \
    --out $TMPDIR/reflexion-check --after-runs 2 --tolerance-rs 1
```

Stub mode is active when `OPENROUTER_API_KEY` is not set, or when `CLAIMSENSE_LLM=stub`.

### 4.2 Real mode (your own key)

1. Use a network that reaches `openrouter.ai`.
2. Set your key and the reflector model. Do not write the key to a committed file.

```bash
export OPENROUTER_API_KEY="<your own key>"
export CLAIMSENSE_MODEL_REFLECTOR="openai/gpt-4.1-mini"
```

3. Run the baseline into a new folder. A folder with a frozen playbook is refused.

```bash
python scripts/run_reflexion_experiment.py baseline --out docs/experiments/reflexion/run-03 --tolerance-rs 1
```

4. Check the first printed line. It must say `mode: REAL MODEL via OpenRouter`. If it says `STUB`,
   the key is not in the environment.
5. Run the experiment. Sit at the terminal. Answer `y` or `n` for each lesson. Type a reason on `n`.

```bash
python scripts/run_reflexion_experiment.py experiment --reviewer "<your name>" \
    --out docs/experiments/reflexion/run-03 --after-runs 2 --tolerance-rs 1
```

6. Check the frozen playbook.

```bash
python scripts/run_reflexion_experiment.py status --out docs/experiments/reflexion/run-03
```

### 4.2b DSPy and GEPA comparison (L12 §6-7)

```bash
pip install -e ".[dev,agents,reflexion]"
pytest tests/orchestration/test_dspy_coverage.py -q

# stub mode: harness check only
python scripts/run_reflexion_dspy.py --out docs/experiments/reflexion/dspy-harness-check-stub \
    --tolerance-rs 1 --gepa-metric-calls 30

# real mode: the result
export OPENROUTER_API_KEY="<your own key>"
export CLAIMSENSE_MODEL_REFLECTOR="openai/gpt-4.1-mini"
python scripts/run_reflexion_dspy.py --out docs/experiments/reflexion/dspy-run-01 --tolerance-rs 1
```

The first printed line is the banner. It must say `REAL MODEL`. The script writes `report.md`,
`results.json`, `plot.png` and `programs/*.json` into `--out`. Copy the one table into
`REPORT-SECTION.md` section 9.4. Switches: `--gepa-metric-calls`, `--bootstrap-demos`, `--skip`,
`--threads`, `--seed`, `--playbook`, `--calculator`.

### 4.3 Held-out run (Eval & Red-Team only)

```bash
python scripts/run_reflexion_heldout.py \
    --playbook docs/experiments/reflexion/run-04/playbook.json \
    --heldout data/claimsense-heldout \
    --out ../claimsense-heldout-results/run-04 --repeat 3 --tolerance-rs 1
```

Use the same `--tolerance-rs` as the experiment run. Use the latest frozen playbook (`run-03` today;
`run-04` after the rerun). The script refuses to run when the playbook is not frozen, when the
playbook changed after the freeze, when a lesson came from a held-out case, when a held-out id is
also in the dev set, or when a path is inside the repository.

### 4.4 The playbook in a normal claim run, and edits → lessons (13 Nov 2026, T46, ADR-0014)

```bash
# read the frozen playbook in a normal run (real key needed; run_one refuses stub mode)
python scripts/run_one.py CLM-0004 --playbook docs/experiments/reflexion/run-03/playbook.json
# the console reviewer can now type `edit`; the run writes its edits to a file
python scripts/run_one.py CLM-0004 --reviewer console --edits-out runs/edits.jsonl
# offline: edits -> PROPOSED lessons; then the human gate
python -m claimsense.reflexion.review_cli propose-from-edits runs/live-playbook.json --edits runs/edits.jsonl
python -m claimsense.reflexion.review_cli review runs/live-playbook.json --reviewer "<your name>"
```

1. `Playbook: <hash>, N approved lessons` is printed next to `Tools:`. Without `--playbook` it
   prints `Playbook: none`.
2. An unfrozen or edited playbook stops the run with `--playbook refused: ...`.
3. `lessons_used` is printed in the FINAL block. It can be `[]` when no approved lesson matches.
4. `propose-from-edits` approves nothing and refuses a frozen playbook. Start a new file.

### 4.5 run-04 (14 Nov 2026): what happened

1. `pytest tests/orchestration -q`: 147 passed (133 before the 13 Nov files, 14 new).
2. `ruff format` reformatted two files; `ruff check --fix` sorted one import block.
3. Stub harness check: ran, backlog section present, frozen.
4. Real run, console approval: baseline Rs 39,904.80, exact 0.909, edit 0.091, critic 0.182.
   8 exact, 12 within Rs 1, 2 real misses (CLM-0021, CLM-0022: cataract sub-limit). 1 lesson
   proposed (clause 4.3 on every procedure line), rejected. 9 mistakes triaged: 8 REF-17 critic
   items, 1 duplicate. After pass twice: identical. Frozen hash `4f53cda1…`.
5. `run_one.py CLM-0004 --playbook .../run-04/playbook.json`: `Playbook: 4f53cda18c2b, 0
   approved lessons`, `lessons_used: []`, settled Rs 67,067.10.
6. Held-out run (same day, Eval owner's agreement): `run_reflexion_heldout.py --playbook
   run-04/playbook.json --heldout data/claimsense-heldout --repeat 1 --tolerance-rs 1`. 60 claims.
   Before == after: Rs 178,203.73 total, mean Rs 2,970.06, exact 0.883, edit 0.117, critic 0.05.
   Report written outside the repo. REPORT-SECTION 4.5.

---

## 5. Results

All numbers are copied from `report.md` files in `docs/experiments/reflexion/`. Nothing is estimated.

### 5.1 Summary table

| Run | Date | Gold | Model | Tolerance | Error before | Error after | Lessons |
|---|---|---|---|---|---|---|---|
| run-01 | 1 Nov | pre-audit | gpt-4.1-mini | Rs 0 | Rs 65,989.27 | Rs 65,989.27 | 14 proposed, 2 approved, 12 rejected |
| harness-check-stub | 7 Nov | corrected | stub | Rs 1 | Rs 186,368.94 | Rs 186,368.94 | 6 template lessons, auto-approved |
| run-02 | 7 Nov | corrected | gpt-4.1-mini | Rs 1 | Rs 186,368.94 | Rs 186,368.94 | 19 proposed, 1 approved, 18 rejected |
| run-03 | 12 Nov | final (ADR-0006/7/9) | gpt-4.1-mini | Rs 1 | Rs 112,102.91 | Rs 112,102.91 | 16 proposed, 0 approved, 16 rejected |
| held-out | pending | — | — | Rs 1 | — | — | run-03 playbook, frozen `4f53cda1…` |

Other metrics for run-02: exact-match rate 0.50, edit rate 0.30, critic-rejection rate 0.00.
The after values are identical in both after runs. No lesson was withdrawn.
Frozen hash of run-02: `b566637830ffd4f5204d56d4a894ae83693ef6cdce40f153c1eaa9a7ce3f8e25`.

### 5.2 Why before equals after

The score did not change. This is the correct result for this data set. The reasons are:

1. The real model chose the same clauses as the stub on all 20 claims. No remaining miss is a
   clause-selection mistake.
2. Every remaining miss is a case where the gold and the calculator disagree on a rule (section 7).
   A lesson cannot change a rule. Only a person or a code change can.
3. The human gate rejected 18 lessons. Most of them tried to teach the agent to follow the gold
   against the policy wording. The rejection is the mechanism at work, not a failure.

A measurable improvement needs development claims where the clause choice decides the amount.
The current set has none.

### 5.3 Why the baseline error grew from Rs 65,989 to Rs 186,369

The 4 Nov gold audit changed two claims:

- CLM-0018 (caesarean). Gold is now Rs 0 under clause 7.15. The pipeline has no exclusion check,
  so it still pays the claim.
- CLM-0016 (ICU day). The ICU line is now capped at Rs 10,000. The calculator also applies the
  proportional cut to the other lines. The gold does not.

Both are listed in `cases.RULE_DISAGREEMENTS`.

---

### 5.4 DSPy and GEPA, stub mode (12 Nov 2026, harness check)

Seven test claims. Clause accuracy on reachable lines: 0.574 for every method, 1.0 for the gold
replay ceiling. Settlement error Rs 18,052.33 in every row. The stub student ignores its prompt, so
no optimiser can move it. The test misses are all one mistake: 4.1 cited where the adjudicator
cites 4.1.1 Note (b) on procedure and diagnostics lines after a room-rent breach. Real numbers
come from `dspy-run-01` (pending). Details in `REPORT-SECTION.md` section 9.

### 5.4b DSPy and GEPA, real models (12 Nov 2026, `dspy-run-01`)

`openai/gpt-4.1-mini` for student, coach and reflector. Seven test claims. Clause accuracy on
reachable lines: agent prompt 0.645; agent prompt + playbook 0.61; DSPy Predict 0.574; DSPy
ChainOfThought 0.917; BootstrapFewShot 0.952 (4 bootstrapped demos); BootstrapFewShot + coach 0.952;
**GEPA 1.0**, equal to the ceiling. Settlement error Rs 18,052.33, exact-match 0.857, edit rate 0.143
in every row: no lever moved a rupee. GEPA chosen. Its instruction (2,777 characters) states the
run-01/run-02 approved lesson as a rule and hard-codes Rs 5,000 per day, which is only right for a
sum insured of Rs 2.5 lakh or more (REF-16). Full reading in `REPORT-SECTION.md` 9.4.

### 5.4c run-03: the Reflexion experiment on the final gold (12 Nov 2026)

Real model, reviewer Dhruvi Ramani at the console. Before and after: Rs 112,102.91, exact-match
0.864, edit rate 0.136, critic-rejection rate 0.182, identical in both after runs. 16 lessons
proposed, 0 approved, 16 rejected with reasons: 8 from critic rejections of the duplicate-line
deduction (REF-17), 6 from CLM-0008 (waiting period is admissibility code), 2 from the cataract
claims (4.3 is informational in the calculator). Frozen hash
`4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945`. This playbook goes to the
held-out run. Reading in `REPORT-SECTION.md` 4.4.

### 5.5 The gold moved after run-02

ADR-0006, ADR-0007 and ADR-0009 (11 Nov 2026) changed the gold and the calculator. The stub
baseline on today's 22 dev claims is Rs 112,102.91 total error, exact-match 0.864, edit rate 0.136.
Three real misses remain: CLM-0008 (specific waiting period, no 6.2 list in admissibility),
CLM-0021 and CLM-0022 (cataract sub-limit, clause 4.3, informational in the calculator). The
run-02 tables describe the 7 Nov gold. See REF-13.

---

## 6. Problems found

Each problem has an id. Use the id in chat and in commits.

### REF-01: The gold and the calculator disagree on five rules

**Where:** `eval/golden_dev/gold_worksheets.jsonl`, `src/claimsense/calc/`,
`src/claimsense/reflexion/cases.py::RULE_DISAGREEMENTS`.
**Effect:** 10 of 20 development claims are a baseline miss. No lesson can fix them.
**Status:** 3 decided, 2 open. See section 7.
**Owner:** Spandan Basu (Agents & Orchestration and Domain lead).

### REF-02: The pipeline has no exclusion check in admissibility

**Where:** admissibility step in `src/claimsense/agents/` (gold audit item AGT-02).
**Effect:** CLM-0018 is paid Rs 111,406. The gold says Rs 0 under clause 7.15.
**Symptom in run-02:** The reflector proposed 6 lessons that say "apply clause 7.15 on every line".
All were rejected. Admissibility is deterministic code, not a clause choice.
**Status:** Open. Needs a code change in the graph.
**Owner:** Spandan Basu.

### REF-03: Unknown ICU rule after the gold audit

**Where:** CLM-0016, clause 4.1.1 Note (b).
**Question:** When only the ICU limit is breached, does the proportional cut apply to the other lines?
**Gold says:** No. The room rent is within its Rs 5,000 cap.
**Calculator says:** Yes.
**Status:** Open. Needs a domain ruling.
**Owner:** Spandan Basu.

### REF-04: A new gold reason code made the loader raise

**Where:** `src/claimsense/reflexion/cases.py::CLAIM_REASONS`.
**Cause:** The 4 Nov gold fix added the reason code `maternity_childbirth_exclusion`. The table did
not have it. `load_cases()` raised on CLM-0018. This is the designed behaviour: unknown codes fail
loudly.
**Fix:** One mapping line plus a test. Commit `4fe285e`. **Closed.**
**Note:** `eval/harness/claimsense_adapter.py` repeats `CATEGORY_MAP` instead of importing
`cases.py`, because of this problem. The two maps can drift. Merge them when ADR-0002 closes.

### REF-05: Rounding produced false mistakes

**Cause:** The gold is whole rupees. The calculator keeps paise. A correct line differs by up to
Rs 0.50. In run-01 this produced two lessons about rounding. No clause can act on them.
**Fix:** `--tolerance-rs 1` in the Reflexion evaluator. The gold is not changed. Rupee error is
still reported exactly. Commit `4fe285e`. **Closed.** Decided with the lead.

### REF-06: Every gold change forces a full rerun

**Effect:** A gold change makes the frozen playbook and the before/after numbers stale. A rerun
needs: a real-model run, a hand review of every lesson, a report rewrite, a red-team rebuild, and a
reason-code update in `cases.py`. This was done once already (run-02).
**Open gold items:** GOLD-02, GOLD-03, GOLD-05, GOLD-06, GOLD-08, DEC-01 to DEC-04 in
`docs/CLAIMS_AND_GOLD_SET_FIXES.md`, plus REF-02 and REF-03.
**Request to the team:** Apply the remaining gold fixes in one commit. Tell the Reflexion owner
before that commit. Then freeze the gold. The held-out run needs a frozen gold (CLAUDE.md rule 5).
**Status:** Open.

### REF-07: Wrong review note stored on one lesson

**Where:** `docs/experiments/reflexion/run-02/playbook.json`, lesson `LSN-c3b3ef85` (CLM-0018).
**Cause:** The reason for the ICU lesson was pasted by mistake at the terminal. The intended reason
is the admissibility one.
**Status:** Documented in the report, section 4.3. Not changed. The playbook is frozen.

### REF-08: The reflector invents clause ids

**Symptom:** 5 lessons in run-02 cite a clause id that does not exist in the policy.
**Current guard:** The human gate rejects them. `reflector.too_specific` blocks amounts, names and
claim ids, but not unknown clause ids.
**Possible fix:** Check each cited clause id against the policy index before the lesson is proposed.
**Status:** Open. Low priority. The gate catches it today.

### REF-09: No headroom in the development set

**Cause:** With the reference calculator, a clause choice changes an amount only for non-payable or
waiting-period clauses. The pipeline already gets those right.
**Effect:** The loop cannot show a measurable improvement on this set, even when it works.
**Possible fix:** Add development claims where the clause choice decides the money, for example
consumables versus medicines, the cataract sub-limit, or waiting-period edges.
**Status:** Open. Domain & Product item.

### REF-10: Four placeholder clause ids

**Where:** `src/claimsense/agents/clauses.py`, four `TODO` ids (waiting periods, non-payable items).
**Effect:** Lessons quote these ids as they are.
**Status:** Open. Agents & Orchestration item.

### REF-11: Team calculator not used in a reported run

**Where:** `calc/adjudication.py` exists. The switch `--calculator team` routes through
`agents.services.real_calculate`.
**Status:** Open. All reported runs use the reference calculator.

### REF-12: CI lint is red on main from other folders

**Where:** mostly `tests/test_adjudication_integration.py`.
**Effect:** The CI badge is red. The Reflexion files report 0 ruff problems.
**Status:** Open. Not a Reflexion item. Reported to Spandan on 7 Nov.

---

### REF-13: The gold moved after run-02; the reviewed run is stale

**Cause:** ADR-0006, ADR-0007 and ADR-0009 (11 Nov 2026, commits `74fbd2c` to `5221ef4`) changed
the gold worksheets and the calculator. The dev set now has 22 claims.
**Effect:** The `run-02` before/after tables no longer reproduce. The stub baseline is now
Rs 112,102.91 over 22 claims with three real misses (section 5.5).
**Fix:** Rerun `run_reflexion_experiment.py` with the real model on the final gold (`run-03`), review
the lessons at the console, update the report. Then freeze.
**Status:** Closed 12 Nov 2026. `run-03` done and frozen (section 5.4c).

### REF-14: Two gold clauses are never among the stub retriever's candidates

**Where:** `agents/services.py::_SEARCH` (stub `policy_search`).
**Symptom:** Nursing lines (gold 12.1 since DEC-01) get candidates 4.1 and 4.1.1 only. Cataract
procedure lines (gold 4.3) get 4.1 and 4.1.1 only. No prompt can cite a clause that was not
retrieved; the agent falls back to the top candidate.
**Effect:** These lines are "unreachable" in the DSPy comparison and are excluded from clause
accuracy. The ceiling row shows what retrieval allows.
**Fix:** Add `NURSING: [ROOM_RENT_LIMIT, HOSPITALISATION]` to the stub search, and route cataract
procedures to 4.3; or run the comparison with the real policy-kb retriever.
**Status:** Open. Owner of `agents/services.py` (Agents & Orchestration); real retriever is
Knowledge & Memory.

### REF-15: In stub mode the DSPy rows cannot differ from the baseline

**Cause:** The stub student answers every prompt with the top-ranked candidate, whatever the
instruction or demos say.
**Effect:** The stub comparison proves the loop and the plumbing, nothing else. All eight rows tie
except the ceiling.
**Status:** By design. The result is `dspy-run-01` with real models.

### REF-16: GEPA's instruction hard-codes a rupee constant

**Where:** `docs/experiments/reflexion/dspy-run-01/programs/gepa.json`.
**Symptom:** The instruction says "maximum allowable room rent is Rs 5000 per day". The policy cap
is 2% of the sum insured, at most Rs 5,000. Every training claim has a sum insured of Rs 2.5 lakh
or more, so the constant was never wrong in training.
**Effect:** On a smaller policy the instruction would tell the analyst the wrong cap. The
calculator would still pay correctly (rule 1), but the citation and rationale could be wrong.
**Fix:** Review the instruction like a lesson before it replaces the shipped prompt. Replace the
constant with the rule ("2% of the sum insured, at most Rs 5,000"), or add a low-sum-insured dev
claim so the metric catches it.
**Status:** Open. Blocks wiring the GEPA program into the coverage agent.

### REF-17: The critic rejects the DEC-04 duplicate-line deduction

**Where:** `agents/critic.py` (`REASON_KEYWORDS`), `agents/services.py::reference_calculate`.
**Symptom:** Since DEC-04 (ADR-0009) an in-bill duplicate line is deducted in full with reason
`other` under clause 2 (Operative Clause). The critic's keyword table has no entry for reason
`other`, so it reports the deduction as unsupported. Claims CLM-0005, 0009, 0010, 0015.
**Effect:** Critic-rejection rate 0.182 in run-03 (0.0 in run-02). Each rejection produced two
useless lesson proposals (8 of the 16 in run-03). The settlement is unchanged.
**Fix:** Teach the critic the duplicate rule: accept a reason-`other` deduction when the line is in
`in_bill_duplicates(claim)` and the clause is `C.OPERATIVE`; or give the deduction its own reason
code. Owner of `agents/critic.py`.
**Status:** Open. Reported 12 Nov 2026. Not a Reflexion bug.

### REF-18: No normal claim run could read the playbook

**Where:** `scripts/run_one.py`, `graph/demo.py`, `eval/agentic/pipeline.py`: every `Team(...)`
without a playbook.
**Symptom:** Only the two experiment scripts passed a playbook. The team asked how the playbook is
used in deployment and the code had no answer. The T46 handoff (Shashank → Spandan) was not done.
**Fix:** `Playbook.load_frozen` and `run_one.py --playbook` (13 Nov 2026). The held-out script uses
the same loader. ADR-0014 records the rule: only a frozen, unchanged playbook reaches a run.
**Status:** Done 13 Nov 2026. Tests in `test_playbook_in_graph.py`.

### REF-19: A live adjudicator edit never became a candidate lesson

**Where:** `graph/nodes.py::apply_edits` leaves the edits in `edit_log`; nothing outside
`reflexion/evaluator.py` read them.
**Symptom:** Brief step 9 ("adjudicator corrections become candidate lessons, used only after
review") was met only by the offline simulated adjudicator.
**Fix:** `run_one.py --edits-out` writes the records; `review_cli propose-from-edits` files
PROPOSED lessons offline (`reflexion/from_edits.py`). The graph is unchanged: it never writes a
lesson (ADR-0005).
**Status:** Done 13 Nov 2026.

### REF-20: The reflector proposed mistakes that no lesson can fix

**Where:** `reflexion/loop.py::learn`, `reflexion/reflector.py`, `reflexion/playbook.py::propose`.
**Symptom:** In `run-03`, 14 of 16 proposals were not clause choices: 8 from the critic refusing
the clause-2 duplicate-line deduction (REF-17), 6 from a waiting-period repudiation (6.2, the
admissibility gate). The same lesson was proposed twice for four cases. In `run-01`/`run-02`,
8 of 33 proposals cited an invented clause id (REF-08). Each cost the reviewer a decision and a
written reason.
**Fix:** `triage.is_clause_choice` sends non-clause mistakes to a backlog printed in `report.md`;
`Playbook.duplicate_of` stops a refused lesson from coming back; `reflector._checked` drops ids
not in `agents/clauses.py` and runs the amounts-and-ids block on the stub path too.
**Status:** Done 13 Nov 2026. Tests in `test_reflexion_triage.py`. The measured effect is the
`run-04` rerun.

### REF-21: The CLM-0021 gold total stopped reconciling

**Where:** `eval/golden_dev/gold_worksheets.jsonl`, record CLM-0021 (Domain & Product file).
**Symptom:** Commit `78114a5` (13 Nov, "CLM 0022 removed due to incorrect gold set") set
CLM-0021's `expected_settlement_inr` to 59850 while its line items still gave 40,000 allowed minus
2,000 co-pay, which is 38,000, the value since ADR-0007 (GOLD-05) and the value `run-03` and the
12 Nov eval run were scored against. 59,850 is the pre-ADR-0007 total. It also removed CLM-0022,
which at least 8 tests and the red-team set (CLM-9022) still count on. `gold_from_fixture` refused
the record, so the 24 tests that load the dev set and both Reflexion scripts failed with
`total_payable 59850 != computed 38000`.
**Fix:** With the author's agreement, the commit was reverted on `main` (`9b82c5f`, 14 Nov 2026,
01:58 IST): CLM-0021 back to 38000, CLM-0022 restored, 22 dev claims. Nothing else reads a copy
of the number. The cataract sub-limit question behind the change is logged as an open gold item for
the Domain lead to rule on after submission (if 59,850 is intended, the line items, GOLD-05 and the
harness pins must change together).
**Status:** Resolved by revert. Gold ruling open.

---

## 7. Gold versus calculator: the five disagreements

| # | Disagreement | Claims | Decision | Problem id |
|---|---|---|---|---|
| 1 | Gold cuts pharmacy lines and not the procedure line. The calculator exempts medicines and cuts procedure, per clause 4.1.1 Note (b). | CLM-0004, 0011, 0012, 0014 | Gold not relabelled now. Gap reported. | REF-01 |
| 2 | Gold deducts an in-bill duplicate line in full. The fraud agent only flags it. | CLM-0005, 0009, 0010, 0015 | Stays a fraud flag for the human. | REF-01 |
| 3 | Gold is whole rupees. The calculator keeps paise. | 4 to 6 claims | Tolerance Rs 1 in the evaluator. Done. | REF-05 |
| 4 | Gold excludes CLM-0018 under clause 7.15. The admissibility check has no exclusion rule. | CLM-0018 | Open. Code change in the graph. | REF-02 |
| 5 | Gold caps CLM-0016's ICU day with no proportional cut. The calculator applies the cut. | CLM-0016 | Open. Domain ruling. | REF-03 |

---

## 8. Open actions

| # | Action | Owner | Blocks |
|---|---|---|---|
| 1 | Rule on REF-03 (ICU-breach proportional cut). | Spandan Basu | Gold freeze |
| 2 | Decide REF-02 (exclusion check in admissibility). | Spandan Basu | Gold freeze |
| 3 | Apply the remaining gold fixes in one commit. Tell the Reflexion owner first. | Sanjay Martolia, Shashank Belligatti | Rerun, freeze |
| 4 | Rerun the Reflexion experiment once on the final gold. Update the report. | Dhruvi Ramani | Held-out |
| 5 | Freeze the gold. | Team | Held-out |
| 6 | Run the held-out set with the frozen `run-03` playbook. Paste the tables into REPORT-SECTION.md 4.5. | Eval & Red-Team | Final report |
| 7 | Add development claims with headroom (REF-09). | Domain & Product | Better result |
| 8 | ~~Run `scripts/run_reflexion_dspy.py` with real models (`dspy-run-01`). Paste the table into REPORT-SECTION 9.4. Choose the method.~~ Done 12 Nov 2026: GEPA. | Dhruvi Ramani | — |
| 11 | Review the GEPA instruction with the Domain lead (REF-16), then decide whether it replaces the inline coverage prompt via `config/prompts/`. | Dhruvi Ramani, Domain & Product | Wiring the prompt |
| 9 | ~~Rerun the Reflexion experiment on the final gold (`run-03`, REF-13).~~ Done 12 Nov 2026, frozen `4f53cda1…`. | Dhruvi Ramani | — |
| 12 | Teach the critic the DEC-04 duplicate-line deduction (REF-17). | Agents & Orchestration (critic owner) | Clean critic rate |
| 10 | Make nursing and cataract clauses retrievable in the stub search (REF-14). | Agents & Orchestration | Ceiling |
| 13 | ~~Rerun the experiment as `run-04` (real model, console approval, tolerance Rs 1). Freeze.~~ Done 14 Nov 2026: Rs 39,904.80 / exact 0.909 / edit 0.091 before and after; 1 proposed, 0 approved, 9 triaged; hash `4f53cda1…` (same as run-03, no approved lesson). REPORT-SECTION 10.4. The E3 config stays on `run-03`: same hash. | Dhruvi Ramani | — |
| 14 | ~~Run the held-out set with the frozen `run-04` playbook.~~ Done 14 Nov 2026 with the Eval owner's agreement: 60 claims, Rs 178,203.73 / exact 0.883 / edit 0.117 / critic 0.05, before == after (0 approved lessons), one repeat. REPORT-SECTION 4.5. | Dhruvi Ramani | — |
| 15 | Rule on the cataract sub-limit for CLM-0021/0022 (REF-21); if 59,850 is intended, change the line items, GOLD-05 and the harness pins together. | Domain & Product | Gold freeze |

---

## 9. Where to read more

| Question | File |
|---|---|
| What is Reflexion, how does it differ from the graph's approval gate? | `docs/experiments/reflexion/REPORT-SECTION.md` section 1 |
| How do I run it? | `docs/experiments/reflexion/README.md` |
| Every lesson and why it was approved or rejected | `REPORT-SECTION.md` sections 4.2 and 4.3 |
| The brief's requirements and where each is met | `REPORT-SECTION.md` section 6 |
| What changed in the gold on 4 Nov | `docs/CLAIMS_AND_GOLD_SET_FIXES.md` GOLD-01, GOLD-04, GOLD-07 |
