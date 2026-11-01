# Reflexion experiment (E3): plan day 4 and day 5

Owner: Dhruvi Ramani (Agents & Orchestration, Reflexion part). Harness: Spandan's
`src/claimsense/reflexion/`. This folder holds the run outputs and the write-up.

| Read | For |
|---|---|
| `REPORT-SECTION.md` | the report section: method, results (PENDING slots for the reviewed run), design decisions, limitations |
| `VIVA-NOTES.md` | plain-language explanation, file map, likely questions |
| `harness-check-stub/` | a complete stub-mode run (auto-approved, stamped "HARNESS CHECK ONLY") proving the loop runs |
| `run-01/` | the reviewed run, once it has been done with a real model |

## What was added (no existing file changed)

| File | What |
|---|---|
| `src/claimsense/reflexion/cases.py` | `load_cases()`: turns `eval/golden_dev/` into `DevCase` objects. Maps starter-pack categories and gold reason codes onto the contracts; raises on anything unmapped. Also `stub_services_factory()` and `RULE_DISAGREEMENTS`. |
| `src/claimsense/reflexion/reporting.py` | Markdown/JSON rendering shared by both scripts: per-case tables, error breakdown, lesson and ablation tables, spread across repeats. |
| `scripts/run_reflexion_experiment.py` | Day 4: `baseline`, `experiment`, `status`. Writes `baseline.md/json`, `report.md/json`, `playbook.json` into `--out`. |
| `scripts/run_reflexion_heldout.py` | Day 5, for the Evaluation owner: before/after on the held-out set with the frozen playbook, 3 repeats, spread. Refuses anything inside the repo. |
| `tests/orchestration/test_cases.py` | 9 tests: loading, contract validity, gold reconciliation, reason-code mapping, unknown codes raise, stub dry run of all 20, both scripts end to end including every refusal. |
| `docs/experiments/reflexion/` | this folder |

The plan's day-1 text asked for `load_cases()` inside `evaluator.py`; it lives in `cases.py`
instead so that no teammate file is touched. Import: `from claimsense.reflexion.cases import load_cases`.

## How to run day 4

```bash
source .venv/bin/activate            # macOS/Linux; Windows Git Bash: .venv/Scripts/activate
pytest tests/orchestration -q        # 30 tests, stub mode, no key needed

# 1. baseline with an empty playbook
python scripts/run_reflexion_experiment.py baseline --out docs/experiments/reflexion/run-01

# 2. full experiment: a person answers y/n for every proposed lesson at the terminal
python scripts/run_reflexion_experiment.py experiment --reviewer "<name>" \
    --out docs/experiments/reflexion/run-01 --after-runs 2

# 3. check the frozen playbook
python scripts/run_reflexion_experiment.py status --out docs/experiments/reflexion/run-01
```

Stub mode is the default whenever `OPENROUTER_API_KEY` is absent or `CLAIMSENSE_LLM=stub`.
For the reported run: put the key in `.env` (never commit it), run from a network that reaches
`openrouter.ai`, use `--approve console`, and ideally have the domain lead be the reviewer.
`--approve auto` exists only to check the harness and stamps the report as not reportable.

## How to run day 5 (Evaluation owner)

```bash
python scripts/run_reflexion_heldout.py \
    --playbook docs/experiments/reflexion/run-01/playbook.json \
    --heldout ../claimsense-heldout \
    --out ../claimsense-heldout-results/run-01 --repeat 3
```

It refuses to run if the playbook is not frozen, changed since freezing, contains a lesson learned
from a held-out case, if a held-out id also appears in the dev set, or if the held-out directory or
the output directory is inside the repository. Held-out files are expected in the `golden_dev`
format. Paste its `heldout_report.md` tables into `REPORT-SECTION.md` section 4.3.

## Reviewed run, 1 Nov 2026 (real model, human gate) — the reported result

`run-01/`: real model (`openai/gpt-4.1-mini`; reflector overridden with
`CLAIMSENSE_MODEL_REFLECTOR` because `openai/gpt-4.1` is not on the course key), reviewer
Dhruvi Ramani at the console. Baseline Rs 65,989.27 / exact 0.3 / edit rate 0.2; after pass
identical in both runs. 14 lessons proposed, 2 approved, 12 rejected with reasons, 0 withdrawn.
Frozen hash `6b4c530d988ac0615a32c258af3968d54475de1bc0dcce98edb2e20de14559b7`. Full reading in
`REPORT-SECTION.md` section 4.2.

## Harness check, 1 Nov 2026 (stub mode, auto-approve, not a result)

| metric | before | after |
|---|---|---|
| settlement_error_total_rs | 65989.27 | 65989.27 |
| exact_match_rate | 0.3 | 0.3 |
| edit_rate | 0.2 | 0.2 |

6 cases exact, 6 within Rs 1 (rounding), 8 real misses, all of them gold-vs-calculator rule
disagreements. Three lessons proposed, none harmful, none helpful. Full output in
`harness-check-stub/`.

## Findings to settle with Spandan and the domain lead

1. **Gold applies the proportional cut to pharmacy and not to the procedure line.** The reference
   calculator does the opposite (exempts medicines per clause 4.1.1 Note b, cuts procedure).
   CLM-0004, 0011, 0012, 0014. One reading must be chosen and the gold relabelled.
2. **Gold deducts in-bill duplicate lines; the system only flags duplicates against history**, and
   a flag never changes an amount. CLM-0005, 0009, 0010, 0015. Should a duplicate be payable 0,
   under which clause?
3. **Gold is whole rupees, the calculator is paise.** Cut lines differ by up to Rs 0.50 and the
   simulated adjudicator counts that as an edit. Relabel gold to paise, or add a tolerance to the
   evaluator (Spandan's file).
4. **Headroom.** With the reference calculator, a clause choice changes an amount only for
   non-payable or waiting-period clauses, which the pipeline already gets right here. E3 needs dev
   cases where the clause choice decides the money, or the real model making a mistake the stub does not.
5. `agents/clauses.py` has four `TODO` clause ids; lessons quote them verbatim.
6. `calc/adjudication.py` is unimplemented (T15); `--calculator team` is ready for it.

## Contribution-log row (paste into `CONTRIBUTIONS.md`)

| 2026-11-01 | Dhruvi Ramani | Reflexion day 4/5: eval-format case loader, day-4 experiment runner, day-5 held-out runner, shared reporting, 9 tests, stub harness check, report section and viva notes | `src/claimsense/reflexion/cases.py`, `reporting.py`, `scripts/run_reflexion_experiment.py`, `scripts/run_reflexion_heldout.py`, `tests/orchestration/test_cases.py`, `docs/experiments/reflexion/` | Loop runs end to end in stub mode; before == after because every remaining miss is a gold-vs-calculator rule disagreement (listed in README). AI-assisted implementation; findings and framing reviewed by Dhruvi. | In review | Reviewed run needs a real model off the corporate network; gold rule decisions with domain lead |
