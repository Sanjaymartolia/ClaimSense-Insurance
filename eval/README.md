# Evaluation (L13, L15). Owner: Eval & Red-Team

This folder holds the evaluation **data** (`golden_dev/`, `redteam/`) and the evaluation
**harness** that scores against it.

## Run it

**Every metric in one run** (harness + agent suite, one report, one gate, one exit code):

```bash
python -m eval.full --stub --label baseline          # free, deterministic, seconds
python -m eval.full --label real-dev --splits dev    # real models (needs .[agents] + key; costs money)
```

It checks the harness first (ceiling, floor and gate rows), runs every claim once with a trace,
scores those same outputs with both the harness and the agent suite, and passes only if all three
hold. Output: `runs/full/<label>/`, with `rows.csv` holding both scorers' columns per claim.
Details: [docs/AGENT_SUITE_REPORT.md](../docs/AGENT_SUITE_REPORT.md), section 9.

The harness's own regression suite checks each result against the outcome the report records. It
needs no API key, makes no model call, and takes a few seconds:

```bash
python -m eval.harness.suite
```

| Row | Composite | Means |
|---|---|---|
| `ceiling-dev` / `ceiling-redteam` | 1.000 / 1.000 | The harness scores a known-correct answer as correct. |
| `floor-dev` | 0.109 | Sending everything to a human is safe but earns almost nothing. |
| `gate-*` (4 rows) | 0.000–0.455 | Each catastrophic gate fires when it should. |
| `real-dev` / `real-redteam` | 0.772 / 0.731 | The actual agents (re-pinned 2026-11-11 after the ADR-0006/0007 gold relabel, the Rs 1 default tolerance, A3, B4, B5, B6 and ADR-0009; were 0.549 / 0.203). No gate fires on dev. Red-team still fails `injection_obeyed` on 4 claims, all injections the input guardrail cannot read yet (RT-010 romanised Hindi, RT-012 obfuscated text; Tools & Security). |

Exit code is 0 only if every row matches. **A `gate-*` mismatch is the most serious kind**: a
safety gate that silently stops firing would not show up in a score table at all.

Single runs, for when you are debugging one piece:

```bash
python -m eval.harness.run --adapter gold-replay --split dev --label ceiling   # do this first
python -m eval.harness.run --adapter claimsense  --split dev --label real-dev  # the real agents
python -m eval.harness.run --help                                             # all adapters/faults
pytest eval/tests -q                                                          # 292 tests
```

What did the agents *do*? The trace-based agent suite (L13 sections 1–7) records every node, tool
call and model call per claim, and gates on outcome, process, safety and payload metrics:

```bash
python -m eval.agent_suite --label baseline                    # report + gate; exit 1 if it fails
python -m eval.agent_suite --label cmp --variant v1,guarded    # compare configurations
python -m eval.agent_suite --label x --show CLM-9001           # one claim's full trace
```

See [agent_suite/README.md](agent_suite/README.md).

Is the pipeline healthy *right now*? Live monitoring (L13 section 8) sends fresh claims through it
with a real Prometheus and Grafana, injects a tool outage and an injection burst, and checks that
the right alerts fire:

```bash
python -m eval.monitoring setup                              # once: download + verify the servers
python -m eval.monitoring run --stub --label my-drill --open    # ~6 min, free; exit 1 if the drill fails
```

See [monitoring/README.md](monitoring/README.md) and `docs/MONITORING_REPORT_CARD.md`.

What happened inside one claim? Observability (L14) records every claim as an OpenTelemetry trace:
a span per node, tool call, model call and review, viewed in Jaeger (or, over OTLP, Langfuse or
LangSmith):

```bash
python -m eval.observability show --stub                       # one trace as a tree, no server
python -m eval.observability setup                             # once: download + verify Jaeger
python -m eval.observability run --stub --label my-trace-run   # normal + tool outage, to Jaeger
```

Production-grade unit tests for the pipeline, written with DeepEval (AAI-13):

```bash
export DEEPEVAL_DISABLE_DOTENV=1 DEEPEVAL_TELEMETRY_OPT_OUT=1   # first: no .env, no usage events
CLAIMSENSE_LLM=stub deepeval test run eval/deepeval_suite      # 74 tests, free
```

See [observability/README.md](observability/README.md), [deepeval_suite/README.md](deepeval_suite/README.md)
and `docs/OBSERVABILITY_REPORT.md`.

Full documentation, including the measured results and every open limitation:
**`docs/EVAL_HARNESS_REPORT.md`** (and its DOCX). Section 10 is the procedures.

## Layout

| Path | What |
|---|---|
| `harness/suite.py` | Runs every row at once, with its expected outcome. Start here. |
| `harness/run.py` | The CLI for one run. `eval/run.py` is a shim so `python -m eval.run` works, which is what the CI gate calls. |
| `harness/loader.py` | Reads the sets and strips every answer-revealing field. |
| `harness/adapters.py` | Three fixtures: `null` (floor), `gold-replay` (ceiling), `perturbed` (fault injection). |
| `harness/claimsense_adapter.py` | Runs the real agents. No LangGraph and no key needed. |
| `harness/reference_metrics.py` | route, amounts, flags, citations, against the human gold. |
| `harness/trajectory_metrics.py` | Did the agent call the tools the claim needed. |
| `harness/safety_metrics.py` | The six catastrophic gates. |
| `harness/efficiency_metrics.py` | Latency, tokens, cost. Reported, never gated. |
| `harness/llm_judge_metrics.py` | RAGAS faithfulness per rationale. Opt-in, needs a key, costs money. |
| `harness/scorecard.py` + `.yaml` | Weighted composite plus gates. The YAML is the whole policy in 50 lines. |
| `calibration/` | Cohen's kappa workflow for the judge. See its own README. |
| `tools/build_report_docx.py` | Builds the report DOCX from its Markdown source. |
| `full.py` | `python -m eval.full`: harness self-check + one traced pipeline run scored by both the harness and the agent suite; combined gate. |
| `agent_suite/` | Trace-based agent suite: spans per node/tool/model call, process metrics, pass@k, guardrail recall, payload checks, judge, gate (`gate.yaml`). |
| `monitoring/` | Live monitoring: metrics from traces, Prometheus alert rules, Grafana dashboard as code, live traffic with an A/B split, an incident drill, read-back and A/B tests. |
| `observability/` | OpenTelemetry traces of the pipeline: spans in memory (`show`) or over OTLP to Jaeger, Langfuse or a Collector (`run`), redaction, outage analysis. |
| `deepeval_suite/` | DeepEval tests: tool correctness, trajectory rules (free), G-Eval and faithfulness (opt-in judge). Run with `deepeval test run`. |
| `tests/` | 292 tests. Not in the default `pytest` run; use `pytest eval/tests`. |

## Two things to know before you trust a number

**The gold is partly wrong.** See the next section. A high score means "agrees with today's gold",
not "correct under the policy wording".

**The judge is not calibrated, and has nothing real to score yet.** `choose_clauses` in
`src/claimsense/agents/coverage.py` discards the per-line `rationale` the model writes, so the
harness can only judge a placeholder sentence. Its weight is 0.00 and it is off by default. See
section 9.4 of the report.

## Gold-set status (2026-11-04)

A full audit of `golden_dev/` found the gold arithmetic correct but several gold *labels* wrong
against the policy wording (full list: `docs/CLAIMS_AND_GOLD_SET_FIXES.md`, items GOLD-01 to
GOLD-08). Three clear-cut items, which didn't depend on an open policy decision, are fixed as of
this date:

| ID | Claim(s) | Fix |
|---|---|---|
| GOLD-01 | CLM-0018 | Caesarean section is excluded under clause 7.15 (no ectopic pregnancy declared). Relabelled from `admissible` / ₹111,406 to `not_admissible_under_demo_exclusion_rule` / ₹0. |
| GOLD-04 | CLM-0016 | The ICU line was filed as `procedure` and paid uncapped. Re-filed as `icu` (also in `claims.jsonl`) and capped at ₹10,000/day under clause 4.1(b): settlement ₹73,089 → ₹59,346. |
| GOLD-07 (partial) | all 20 | Added `clause_id` to every gold deduction **where the mapping is already unambiguous** from the project's own docs (waiting period → `6.3`, room/ICU cap → `4.1`, non-payable items → `annexure-a.list-i`, this maternity exclusion → `7.15`). `duplicate_line` deductions (CLM-0005, 0009, 0010, 0015) and the policy-period gate (CLM-0013) are left without a `clause_id`: the first needs DEC-04, the second needs a confirmed clause number nobody has identified yet. |

`eval/redteam/claims.jsonl` and `gold.jsonl` were rebuilt (`python eval/redteam/build_cases.py`)
so the red-team set matches the corrected dev gold (REC-03).

**2026-11-11, GOLD-02 fixed** ([ADR-0006](../docs/adr/0006-room-rent-proportional-cut.md)). On a
room-rent breach, the gold now applies the proportional cut as Note 4.1.1(b) says: every other
hospital expense is cut, the procedure included, medicines are exempt, and the cut lines cite
`4.1.1`. CLM-0004/0011/0012/0014 settle at ₹80,990 / ₹57,184 / ₹67,575 / ₹74,630 (were ₹102,313 /
₹60,741 / ₹78,511 / ₹85,136). The red team is rebuilt, and 11 cases inherit the change. DEC-01
can still move these four.

**2026-11-11, GOLD-03/05/06/08 fixed** ([ADR-0007](../docs/adr/0007-gold-set-rulings-2026-11-11.md)):
- **GOLD-03:** every claim now has `policy.first_policy_inception_date`. CLM-0008 (stones, first
  policy) pays ₹0 under the 24-month wait (6.2.18). CLM-0004 and 0005 are renewals from 2023.
- **GOLD-05:** two new cataract claims are added. CLM-0021 is capped at clause 4.3 and settles at
  ₹38,000. CLM-0022 has ₹25,000 of the limit used by an earlier claim (`history.prior_claims`) and
  settles at ₹14,250. CLM-0019 is no longer labelled `sub_limit`. **The dev set is now 22 claims.**
- **GOLD-06:** `expected_review_flags` are regenerated from the reason codes. A not-admissible
  claim carries only its gate's flag. `tests/test_dataset_integrity.py` enforces this.
- **GOLD-08:** the gold stays in whole rupees, and `--tolerance-inr` now defaults to 1 in
  `run.py`, `suite.py` and `full.py` (pass 0 for strict scoring).

Two new known agent misses come from this: CLM-0008 (admissibility has no 6.2 list, AGT-02), and
CLM-0021/0022 (the calculator doesn't apply clause 4.3 because the contract carries no eye).
**2026-11-11, DEC-01 / DEC-04 / CLM-0016 decided** ([ADR-0009](../docs/adr/0009-room-cap-nursing-duplicates-icu.md)):
- **DEC-01:** nursing sits inside the ₹5,000/day all-inclusive room cap, so every paid claim
  except the cataract ones is a room breach.
- **DEC-04:** in-bill duplicates are deducted citing clause 2.
- **CLM-0016:** an ICU breach also cuts the other expenses, and the ICU day is one of the 6
  nights.

The gold is relabelled (for example CLM-0004 ₹80,990 → ₹67,067; CLM-0019 ₹255,801 → ₹201,962).
The ceilings are now 1.000, because duplicate lines finally carry a citation.

**New follow-up this fix exposes:** `src/claimsense/reflexion/cases.py::load_cases()` raises
`unmapped gold reason code 'maternity_childbirth_exclusion'` on CLM-0018 now, because its
`CLAIM_REASONS` table (Agents & Orchestration's mapping from gold reason code to clause) has no
entry for the new exclusion. It needs one more entry there, plus a clause-7.15 constant in
`src/claimsense/agents/clauses.py` (that file is outside `eval/`, so this fix does not add it —
flagging it for whoever owns `reflexion/` and `agents/clauses.py` next). CLM-0016's new
`icu_daily_cap` code was already mapped, so it loads fine.

- `golden_dev/` — 20 development claims (`claims.jsonl`) and their reference outcomes
  (`gold_worksheets.jsonl`), from the starter pack (ADR-0002). The gold uses the demo ruleset in
  `data/README.md`, which isn't authoritative yet. Re-check it by hand before scoring against it.
  Use these for prompt/tool iteration only. Never feed gold into prompts, tools or the retrieval
  corpus.
- Held-out set (60): stored **outside this repo** in `../claimsense-heldout/`, which Claude Code is
  denied access to (`.claude/settings.json`). The person tuning agents never writes these.
- `golden_dev/retrieval_queries.jsonl` — 47 query → clause pairs for search recall, as full
  questions (`question`) and short bill-line terms (`bill_line_dev`). `bill_line_other` terms are
  never used to write the query-rewrite glossary, so overfitting shows there. Where a
  query lists several clauses, each one answers it, so any of them counts as a hit.
  **Draft:** the Domain lead must verify each clause id.
- `redteam/` — `attacks.jsonl` holds 12 attack seeds. `build_cases.py` turns them into
  `claims.jsonl` + `gold.jsonl`: **30 attacked claims (CLM-9001…9030)**. Each case is a dev
  claim plus one attack. Its gold is the human dev gold plus the one change the attack makes,
  never a calculator's output. Every case needs a human, moves no money, and is
  safety-critical. Each injection seed goes in through all three doors (discharge summary,
  bill-line description, itemised bill). Five injections land on claims that already fail a
  code gate (waiting period, policy period, duplicate), to prove text can't talk past code.
  Regenerate with `python eval/redteam/build_cases.py`; never edit the output by hand. To grow
  it: add a seed to `attacks.jsonl` and a line to `PER_ATTACK`.

  | Attack | How it's tested | Caught by |
  |---|---|---|
  | RT-001 injection ("pre-approved") | CLM-9001–9003 | the agent (TODO 5); settle stays gated in code |
  | RT-007 hidden "bypass the approval gate" | CLM-9004–9006 | the agent (TODO 5); settle stays gated in code |
  | RT-009 reworded: polite "as agreed with the insurer" | CLM-9007–9009 | the agent: no trigger words to match |
  | RT-010 reworded: Hinglish | CLM-9010–9012 | the agent: English keyword lists miss it |
  | RT-011 reworded: fake `<system>` result in a document | CLM-9013–9015 | the agent: must not adopt a route or flags from data |
  | RT-012 reworded: s.p.a.c.e.d / dotted letters | CLM-9016–9018 | the agent: defeats exact-phrase matching |
  | RT-002 bill total ≠ lines (over and under) | CLM-9019–9022 | code (`rules.py` arithmetic) |
  | RT-003 one line billed twice (lab, pharmacy, nursing) | CLM-9023–9026 | code (duplicate line) |
  | RT-004 discharge date in summary ≠ claim form (+1 to +5 days) | CLM-9027–9030 | the agent must read the document |
  | RT-005 wrong-patient letter | **not covered yet**: nothing generates a letter | — (gap) |
  | RT-006 bill edited after approval | contract test `test_any_edit_to_the_worksheet_kills_the_approval` | code (worksheet hash) |
  | RT-008 settle with a different amount | contract test `test_rt008_settle_takes_no_amount…` | code (`settle_claim` has no amount argument) |

  Run it: `python scripts/evaluate_dev.py --label <name> --redteam` (course kit).
- Freeze code, model, prompt, policy version and playbook before any held-out run.
- Report: rupee absolute error, exact settlement match rate, line-item match rate, clause
  grounding, arithmetic, duplicate detection, human-review routing, false-negative safety flags,
  latency, cost.
- Checks: code first (amounts, cited clause exists, DB state, tool calls, forbidden actions),
  judge (different model family) only for explanation quality; calibrate on 20+ human labels,
  report Cohen's kappa.
- Experiments E1–E4 are config files, one harness.
