# Reflexion work log: what was done, what was observed, what is open

**Owner:** Dhruvi Ramani (Agents & Orchestration, Reflexion part).
**Scope:** `src/claimsense/reflexion/`, `scripts/run_reflexion_experiment.py`,
`scripts/run_reflexion_heldout.py`, `tests/orchestration/test_cases.py`,
`tests/orchestration/test_reflexion.py`, `docs/experiments/reflexion/`.
**Written:** 8 November 2026, from the files on `main` at commit `86cf567`.
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
| held-out set | 60 claims outside the repository. Only Eval & Red-Team runs them, once. |

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
| `reflexion/review_cli.py` | The human gate at the terminal. | `test_cases.py` (script end to end) |
| `reflexion/reporting.py` | Writes `report.md` and `report.json`. | `test_cases.py` |
| `scripts/run_reflexion_experiment.py` | Commands `baseline`, `experiment`, `status`. | `test_cases.py` |
| `scripts/run_reflexion_heldout.py` | Held-out run with a frozen playbook. Refuses an unfrozen, changed or leaky playbook. Refuses a path inside the repository. | `test_cases.py` |

The harness files (`evaluator.py`, `loop.py`, `playbook.py`, `reflector.py`, `metrics.py`,
`review_cli.py`) started as Spandan Basu's boilerplate. `cases.py`, `reporting.py`, both scripts
and `test_cases.py` are new.

### 3.2 Tests

| File | Count | What they check |
|---|---|---|
| `tests/orchestration/test_cases.py` | 11 | Loading, contract validity, gold reconciliation, reason-code mapping, the 4 Nov gold relabels, unknown codes raise, stub run of all 20 claims, the tolerance, both scripts end to end with every refusal. |
| `tests/orchestration/test_reflexion.py` | 5 | Learn, approve, improve, ablate, freeze on synthetic cases. Held-out refuses an unfrozen or leaky playbook. |

Recorded status on 7 November 2026: all tests in `tests/orchestration/` pass (51 tests, this
includes Spandan's tests). `ruff check` on the Reflexion files reports 0 problems.
This Mac has no virtual environment, so the numbers were not run again on 8 November.

### 3.3 Documents

| File | What |
|---|---|
| `docs/experiments/reflexion/README.md` | How to run in stub mode and in real mode. Env vars. Model override. Results table. Open findings. |
| `docs/experiments/reflexion/REPORT-SECTION.md` | The report section. What Reflexion is. The loop. Method. All results. Every lesson with its reason. Design decisions. Brief-to-code map. |
| `docs/experiments/reflexion/run-01/` | Reviewed run, 1 Nov 2026, pre-audit gold, strict scoring. |
| `docs/experiments/reflexion/run-02/` | Reviewed run, 7 Nov 2026, corrected gold, tolerance Rs 1. **This is the current result.** |
| `docs/experiments/reflexion/harness-check-stub/` | Stub run, auto-approved. Marked "HARNESS CHECK ONLY". Not a result. |
| `docs/experiments/reflexion/langgraph-check/` | Real-model baseline through the LangGraph executor. Same numbers as the local runner. |
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

### 4.3 Held-out run (Eval & Red-Team only)

```bash
python scripts/run_reflexion_heldout.py \
    --playbook docs/experiments/reflexion/run-02/playbook.json \
    --heldout ../claimsense-heldout \
    --out ../claimsense-heldout-results/run-02 --repeat 3 --tolerance-rs 1
```

Use the same `--tolerance-rs` as run-02. The script refuses to run when the playbook is not frozen,
when the playbook changed after the freeze, when a lesson came from a held-out case, when a held-out
id is also in the dev set, or when a path is inside the repository.

---

## 5. Results

All numbers are copied from `report.md` files in `docs/experiments/reflexion/`. Nothing is estimated.

### 5.1 Summary table

| Run | Date | Gold | Model | Tolerance | Error before | Error after | Lessons |
|---|---|---|---|---|---|---|---|
| run-01 | 1 Nov | pre-audit | gpt-4.1-mini | Rs 0 | Rs 65,989.27 | Rs 65,989.27 | 14 proposed, 2 approved, 12 rejected |
| harness-check-stub | 7 Nov | corrected | stub | Rs 1 | Rs 186,368.94 | Rs 186,368.94 | 6 template lessons, auto-approved |
| run-02 | 7 Nov | corrected | gpt-4.1-mini | Rs 1 | Rs 186,368.94 | Rs 186,368.94 | 19 proposed, 1 approved, 18 rejected |
| held-out | pending | — | — | Rs 1 | — | — | run-02 playbook, frozen |

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
| 6 | Run the held-out set with the frozen playbook. Paste the tables into REPORT-SECTION.md 4.4. | Eval & Red-Team | Final report |
| 7 | Add development claims with headroom (REF-09). | Domain & Product | Better result |

---

## 9. Where to read more

| Question | File |
|---|---|
| What is Reflexion, how does it differ from the graph's approval gate? | `docs/experiments/reflexion/REPORT-SECTION.md` section 1 |
| How do I run it? | `docs/experiments/reflexion/README.md` |
| Every lesson and why it was approved or rejected | `REPORT-SECTION.md` sections 4.2 and 4.3 |
| The brief's requirements and where each is met | `REPORT-SECTION.md` section 6 |
| What changed in the gold on 4 Nov | `docs/CLAIMS_AND_GOLD_SET_FIXES.md` GOLD-01, GOLD-04, GOLD-07 |
