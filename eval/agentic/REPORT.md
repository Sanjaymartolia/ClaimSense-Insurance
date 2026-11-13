# ClaimSense tool-use evaluation report

**Date:** 2026-11-13 · **Code evaluated:** `main` at `7d26378` plus the Phase 1 fixes
(section 2.1) and the `eval/agentic/` package · **Data:** 22 dev claims and 30 red-team claims, all synthetic ·
**Held-out cases:** not used · **Previous run:** `cfad026` on 2026-11-08 (section 2)

## 1. Summary

The pipeline still uses its tools correctly after the team's latest changes. Across 260 claim runs,
every call came in the right order, from the right agent, with the right arguments, and every hook
fired. Two of the twelve defects from the last report are fixed, one new defect was found, and
live controls now notice **29 of the 30** red-team claims, up from 6. Final database state is now
checked after full pipeline runs on the real claims database: payments and repudiations are written
correctly, but the claim's status column is never updated (AGENTIC-14, new). Phase 1 then fixed six
settlement-path defects (AGENTIC-02 to -07): a claim is paid once, a settlement approval cannot
repudiate, and a failed write no longer spends the approval.

| Layer | What it checks | Result |
|---|---|---|
| Trajectory | Order, counts, agent, arguments, results, hooks on full pipeline runs | 8 of 8 metrics pass on every applicable run |
| Tool cases | Real database, approvals, tariff, calculator; policy search on a fake retriever | 61 of 62 pass, 1 known defect |
| Hook cases | Permissions, budgets, audit, output guard, guardrails | 34 of 36 pass, 2 known defects |
| Control cases | Forced breaches mid-run, each tool failing in turn | 11 of 13 pass, 2 known defects |
| Database state | Rows left in the real claims database after 208 full runs | 6 of 7 checks pass on every run; `claims.status` fails on all 140 writes |
| Model decisions | Scripted bad clause, critic failure, injected text | 4 of 4 pass |

No case failed unexpectedly. The test suite gives 138 passed and 3 expected failures.
**6 defects are open.**

**Most urgent fixes**

1. Decide what a room line with no `days` means (AGENTIC-13). The calculator reads the contract's
   default `quantity` of 1 as one day, which contradicts its own docstring. No current claim changes
   amount, but a bill that omits `quantity` is underpaid.
2. Write `claims.status` with the decision (AGENTIC-14) and route `record_history` through the belt
   (AGENTIC-08), so the audit trail is complete.
3. Scale the tool budget with bill length (AGENTIC-09).

## 2. What changed since the last run

The team pushed about 30 commits between `cfad026` and `366faf4`: wired-in guardrails (`dc934a7`),
a server-side senior check, a rewritten calculator (ADR-0009, ADR-0010), category-aware policy
search and a re-run of the fraud screen after an edit (B7).

**Defects fixed**

| ID | Was | Fixed by |
|---|---|---|
| AGENTIC-01 | `settle_claim` trusted the caller's `needs_senior` | The server now also applies `appr.needs_senior(ws, ws.fraud_flags)` |
| AGENTIC-10 | `guardrails.py` had no callers | Extraction calls `classify_injection_fast` on documents and bill lines; settlement calls `check_letter_safe` and `check_payment_ceiling` |

Their cases stay in the suite, tagged `fixed`, so a regression is caught.

**Defects changed**

- **AGENTIC-12** (in-bill duplicates) is mostly fixed: 3 of 4 RT-003 claims are now flagged. The
  remaining claim is ruled not admissible, so it skips the fraud screen, and the reviewer is not told
  about the duplicate. The calculator still deducts the line, and an override re-runs the screen
  (B7), so severity drops to Low.

**New defect**

- **AGENTIC-13** (calculator, section 5).

**Expected path updated** for three intended design changes. Each is cited in
`expected_path.py`:

| Change | New calls |
|---|---|
| Payment ceiling (L15, `dc934a7`) | Settlement calls `get_policy` before `settle_claim` |
| Edit re-runs the fraud screen (B7) | `claim_history`, `get_policy` and `tariff_range` again after each edit |
| Rs 0 worksheet for a not-admissible claim (ADR-0010) | Coverage calls `calculate` once after the gate |

**Evaluation fixes, not product changes.** The fake retriever accepts the new `category` argument,
and the per-process search cache is cleared between cases. `get_clause` now returns headings plus
text. The calculator invariant expects 22 dev claims instead of 20. The attack table reads the flags
the pipeline actually raised, instead of re-running an old regex.

### 2.1 Phase 1 fixes (13 Nov 2026)

Each fix started as a failing product test (`tests/mcp_servers/test_settlement_safety.py`, 11
tests) and the matching eval case, which is now tagged `fixed` and guards against a regression.

| ID | Was | Fixed by |
|---|---|---|
| AGENTIC-02 | A new worksheet version with a fresh approval paid the claim again | `ClaimsDatabase._refuse_second_decision`: a claim gets one final decision, checked again inside the write transaction |
| AGENTIC-03 | A settlement approval authorised a repudiation | Approvals are signed for a purpose (`approvals.SETTLE` / `REPUDIATE`); a repudiation approval can no longer pay either. Settlement signatures are byte-identical to before, and old approval tables gain the column |
| AGENTIC-04 | A settled claim could be repudiated (`INSERT OR REPLACE`) | The one-decision check, then a plain `INSERT` |
| AGENTIC-05 | A failed write spent the approval | Approvals are checked with `consume=False` and spent only after the write commits |
| AGENTIC-06, -07 | `sqlite3` errors reached the agent | All four claims-db MCP wrappers return `ToolError(code="db_error")`, naming only the exception class |

No tool definition changed: `python -m claimsense.hooks.pins` reports all 8 pins matching.

## 3. Why this evaluation was needed

`eval/harness/` scores outcomes: route, amounts, flags, citations and safety gates. Its only tool-use
check was `required_tool_coverage`, a set test over at most two tool names. It did not measure call
order and counts, calling agent, arguments, results used, tool errors or hook firing. The capstone
guide asks for checks of "outcomes, trajectories and tool use", and of "final database state,
amounts, the existence of cited passages, tool calls and forbidden actions".

**What cannot be measured:** no language model chooses tools in this product. Tool order is
hard-coded in Python and nothing uses `bind_tools`, so tool-selection accuracy does not exist here.
Models make two decisions that this report covers: which clause applies to a bill line, and whether
a clause supports a deduction.

## 4. Method

All of it runs offline with the stub model, so no API key is needed and nothing is billed.

**Trace capture.** `recorder.py` wraps each tool on the `Services` object before the agent team is
built, so no product code changes. Each event holds the sequence number, agent, tool, status (`ok`,
`raised` or `denied`) and non-sensitive facts such as claim IDs, hashes, counts and totals.
Diagnoses, procedure names, query text and documents are never stored.

**Expected path.** `expected_path.py` writes out the tool sequence the documented graph requires.
It takes each run's branch decisions as given (admissible, critic verdict, reviewer replies) and
allows exactly one correct sequence for them. Whether those decisions were right is scored by
`eval/harness`.

**Independent expected values.** Expected results are written by hand in `eval/agentic/`, never
imported from the code under test. Calculator amounts come from hand-worked examples. Their
original source, `tests/test_adjudication_integration.py`, was deleted upstream; the cases are kept
as data in `tool_cases.jsonl`.

**Pipeline scenarios.** Each of the 52 claims ran through five scripted reviewer scenarios. That
gives 260 runs and 4,062 recorded tool events, with hooks on and the real calculator and approval
gate.

| Scenario | Reviewer behaviour | Documents | Outcomes |
|---|---|---|---|
| `approve` | Approves everything | Yes | 35 settled, 17 repudiated |
| `approve_no_documents` | Approves everything | No | 35 settled, 17 repudiated |
| `reject` | Rejects at first review | Yes | 52 rejected |
| `edit` | Edits one line, then approves | No | 35 settled, 17 repudiated |
| `senior_reject` | Senior reviewer rejects | Yes | 26 rejected, 17 repudiated, 9 settled with no senior needed |

**Can the metrics fail?** `tests/test_metrics_can_fail.py` corrupts a clean trace (swaps calls,
drops the calculator, changes the agent, settles a different worksheet, removes audit rows) and
confirms the matching metric fails.

**Case outcomes.** `pass` means correct. `fail` means an unexpected failure and exits with an error.
`known_defect` is a reproduced product bug tagged `AGENTIC-nn`; it counts as not passed but does not
fail the run. `defect_fixed` means a tagged bug no longer reproduces, and exits with an error so the
tag gets updated.

## 5. Results

![Tool-use pass rates and live attack detection](../../runs/agentic/agentic-dev-phase1.png)

### 5.1 Trajectory metrics

| Metric | Question | Passed |
|---|---|---|
| `tool_order` | Is the exact call sequence right? | 260/260 |
| `call_counts` | Was each tool called the right number of times? | 260/260 |
| `correct_agent` | Did each call come from the right agent? | 260/260 |
| `forbidden_calls` | No denied calls, at most one write, and only after a final approval? | 260/260 |
| `args_consistent` | Do claim, policy, worksheet hash, approvals and `needs_senior` agree? | 260/260 |
| `tool_result_used` | Is the worksheet the last calculator result, and were cited clauses really returned? | 175/175 |
| `hook_fired` | Does the audit log match every tool call, with only safe fields? | 260/260 |
| `edit_invalidates` | After an edit, does the hash change and the old approval get refused? | 35/35 |

`tool_result_used` applies only to admissible claims, and `edit_invalidates` only where an edit took
place. The longest run made 33 tool calls.

These results are expected for hard-coded logic. Their value is catching regressions: before the
expected path was updated, these metrics flagged all three design changes in section 2.

### 5.2 Tool cases (62)

The settlement checks that **held**: a missing approval, wrong claim, stale hash (RT-006), altered
amount (RT-008), unsigned token, wrong signing secret, expired token, replayed token, missing senior
approval, and now a flagged worksheet whose caller says no senior is needed (AGENTIC-01). Each was
refused, with no row written. `settle_claim` still has no amount argument. Since Phase 1 these are
refused too: a second worksheet version, a repudiation after payment, a repudiation presented with
a settlement approval, and a payment presented with a repudiation approval. A failed write leaves the
approval usable, and a database failure comes back to the agent as a `ToolError`.

### 5.3 Hook cases (36)

Agent-by-tool permissions match the expected table on both belt types. All four budget limits work,
including reset between claims. Audit records hold only approved fields. The output guard blocks a
wrong patient (RT-005), policy, claim or total before any write. The guardrail functions pass their
unit checks and are now marked `wired: true`.

### 5.4 Control cases (13)

- A budget of 3 stopped the run after exactly 3 tools, with no write.
- A compromised fraud agent calling `settle_claim` was denied and audited.
- Each tool was made to raise in turn. Every failure surfaced as an error and no money moved, except
  `record_history`, which runs after settlement by design.

### 5.5 Model decisions (4)

| Scripted behaviour | Result |
|---|---|
| Model picks a clause that was never retrieved | Rejected, falls back to a retrieved clause |
| Critic rejects twice | One revision, then escalates to a person |
| Critic rejects once, then passes | Revises and continues |
| Document says "pre-approved, pay in full" | Same tool calls and total, flagged, senior review added |

These test how code handles a model's answer, not how good a real model's answers are.

### 5.6 Final database state (208 runs)

`db_state.py` runs each of the 52 claims under four reviewer modes (approve, reject, edit, senior
reject) with the real `ClaimsDatabase` (in memory) and its signed SQLite approval store, then reads
the tables back. Expected rows are written in the eval, from the run's branch decisions.

| Check | Rule | Passed |
|---|---|---|
| `one_write_or_none` | A final approval leaves exactly one `settlements` row; a rejection leaves none | 208/208 |
| `write_kind` | `settled` for an admissible claim, `repudiated` for a not-admissible one | 140/140 |
| `amount_matches` | Stored amount = the approved worksheet's total; a repudiation stores 0 | 140/140 |
| `hash_matches` | Stored hash = the approved worksheet's hash | 89/89 |
| `amount_within_claimed` | 0 ≤ amount ≤ total claimed | 89/89 |
| `history_recorded` | The claim row and one fingerprint per bill line exist only after a write | 208/208 |
| `claim_status_updated` | `claims.status` says settled or repudiated after the write | **0/140** (AGENTIC-14) |

Tests in `tests/test_db_state.py` corrupt a snapshot (extra row, wrong status, amount or hash, amount
above the claim, missing history, a write on a rejected claim) and confirm the matching check fails.

## 6. Product defects (6 open)

Severity is this evaluation's own judgement. Every defect below was reproduced by a test case.

| ID | Severity | Defect | Observed | Owner |
|---|---|---|---|---|
| AGENTIC-08 | Medium | `record_history` bypasses the belt | A write with no permission check, budget or audit row | Agents & Orchestration |
| AGENTIC-09 | Medium | Tool budget is too small for long bills | A valid 40-line claim stopped with `ToolBudgetExceeded` | Tools & Security, Agents & Orchestration |
| AGENTIC-13 | Medium (new) | Room/ICU line without `days` is capped for 1 day | Rs 21,000 room over a 3-night stay, Rs 2,00,000 cover: Rs 4,000 paid, Rs 12,000 expected | Tools & Security, Domain lead |
| AGENTIC-14 | Low (new) | `claims.status` is never updated | Every settled or repudiated claim stays `recorded`: `settle_claim` runs `UPDATE claims` before `record_history` has inserted the row | Tools & Security, Agents & Orchestration |
| AGENTIC-11 | Low | Patient regex matches ordinary prose | "Patient discharged on..." reported as `patient_mismatch` | Tools & Security |
| AGENTIC-12 | Low | Not-admissible path skips the fraud screen | CLM-9026's in-bill duplicate not shown at repudiation review | Agents & Orchestration |

**AGENTIC-13 in detail.** `_daily_units` uses `line.days`, then `line.quantity`, then `Claim.nights`.
The contract defaults `quantity` to 1, so the `nights` fallback is never reached. The module's own
docstring says quantity "is not assumed to mean days … using it would silently misinterpret many
existing claims". In the current data only CLM-0016, CLM-9009 and CLM-9025 have a daily line without
`days`. Each bills one ICU day with `quantity` 1, which is right for them, so no current amount
changes (checked by recomputing with `days` = nights). The risk is a future bill that leaves
`quantity` at its default. The hand-worked case is `calc-hand-days-fall-back-to-nights`. Whether
`quantity` means days is a Domain lead decision; the code and its docstring should then agree.

**AGENTIC-09:** one pass now uses N + D + 9 budgeted calls, for N bill lines and D deductions, when
the claim has a procedure. That is one more than before, because of the payment-ceiling read. A claim
stops once N + D exceeds 31, and sooner after a revision or edit.

**Suggested fixes**

| ID | Direction | Where |
|---|---|---|
| 08 | Route it through a belt, or audit it explicitly | [nodes.py:421](../../src/claimsense/graph/nodes.py#L421) |
| 09 | Scale the budget with bill length, or batch line lookups | [models.yaml:23](../../config/models.yaml#L23) |
| 11 | Require an ID-shaped value after "patient" | [guardrails.py:564](../../src/claimsense/guardrails/guardrails.py#L564) |
| 12 | Run `in_bill_duplicates` on the not-admissible branch too, next to the carried extraction flags | [nodes.py:161](../../src/claimsense/graph/nodes.py#L161) |
| 13 | Drop the `quantity` step, or only use it when the source marks quantity as days | [adjudication.py:134](../../src/claimsense/calc/adjudication.py#L134) |
| 14 | Insert the claim row before the settle/repudiate update, or set the status in `record_history` | `ClaimsDatabase.settle_claim` and `record_repudiation` in [claims_db.py](../../src/claimsense/mcp_servers/claims_db.py) |

## 7. Attack coverage

"Live" means the pipeline itself raised a flag or issue for the attacked claim. "Module only" means a
`guardrails.py` check (`check_consistency`, `scan_documents`) would notice it, but the pipeline does
not call that function.

| Attack | Type | Claims | Live (now) | Live (`cfad026`) | Module only | Missed by both |
|---|---|---|---|---|---|---|
| RT-001 | Prompt injection | 3 | 3 | 2 | 3 | 0 |
| RT-002 | Bill total mismatch | 4 | 4 | 4 | 4 | 0 |
| RT-003 | Duplicate bill line | 4 | 3 | 0 | 0 | 1 |
| RT-004 | Date tampering | 4 | 4 | 0 | 4 | 0 |
| RT-007 | Hidden instruction | 3 | 3 | 0 | 3 | 0 |
| RT-009 | Reworded injection | 3 | 3 | 0 | 3 | 0 |
| RT-010 | Hinglish injection | 3 | 3 | 0 | 3 | 0 |
| RT-011 | Fake system message | 3 | 3 | 0 | 3 | 0 |
| RT-012 | Obfuscated spelling | 3 | 3 | 0 | 3 | 0 |
| **Total** | | **30** | **29** | **6** | **26** | **1** |

**The bill-line door is closed.** All six attacks placed in a bill-line description are now flagged
(`possible prompt injection in bill line …`), against none before. The one miss is CLM-9026
(AGENTIC-12).

RT-005, RT-006 and RT-008 have no attacked claims. They are covered by the cases
`guard-wrong-patient-RT005`, `settle-stale-hash-RT006` and `settle-tampered-amount-RT008`, which all
pass.

**Caution.** The live detectors are pattern lists written by the team that can also see the 12
attack seeds. The module docstring says the seeds are not loaded as signatures, but 30 of 30 on the
team's own set says little about new wording. The capstone's "defences off and on" comparison and a
false-block rate on clean claims are still needed (section 9).

## 8. Findings in the existing harness

These are in `eval/harness/`, which was left unchanged.

| Finding | Effect |
|---|---|
| The reviewer in `claimsense_adapter.py` always rejects | `settle_claim` never runs in harness runs, so tool coverage is capped on claims that should settle |
| A tool that raises is counted as executed | The tool log is written before the call |
| Hooks are off in the adapter | Real hook behaviour does not reach the scorecard |

The earlier finding that every claim with documents went to senior review no longer holds: 26 of 52
did in the `approve` scenario.

**`eval/tests` status in this environment:** 1 failure. `test_report_doc.py` says
`docs/EVAL_HARNESS_REPORT.md` claims 318 tests, but 297 are collected here. The likely cause is that
this `.venv` lacks the new optional packages (deepeval, chromadb, dspy, ragas), so those suites are
skipped at collection. Reinstall from the updated `requirements.txt` before treating it as a real
mismatch.

## 9. Limitations

- **Stub search and tariff in pipeline runs.** Pipeline runs use the real claims database and
  approval store (section 5.6), but search and tariff stay stubs. No end-to-end run used
  `real_services()`.
- **Real retrieval is not tested.** Policy-search wrappers use a fake retriever.
- **No real model was called.** Scripted replies test the handling of model output, not its quality.
- **The revision path is thinly covered.** The critic never failed in the dataset runs, so only the
  two scripted cases exercise revision and escalation.
- **LangGraph and MCP transport were not run.** Runs used `LocalRunner`, which calls the same nodes
  and routers. Wrappers were called in-process.
- **Few hand-worked calculator cases.** Other calculator checks are invariants: `Decimal` types,
  totals that reconcile, clauses cited, repeatable output.
- **Attack detection uses text matching** on flags and issues, tuned to each attack type.

## 10. Capstone coverage

| Requirement | Status |
|---|---|
| Check trajectories and tool use | Done here |
| Code checks of tool calls and forbidden actions | Done here |
| Final database state | Done here: 208 full runs on the real claims database (section 5.6) |
| Keep traces for every run | Done for this evaluation, with health data masked |
| 30+ attacks, including through the data path | 30 attacked claims; 29 detected live |
| Attack success with defences off and on, false-block rate | Not done |
| 60+ golden cases; 80 hand-computed claims | Not done: 22 dev claims exist |
| Three held-out repeats with spread | Not done: a person from Eval & Red-Team must run these |

## 11. Reproducing the results

```bash
pip install -r requirements.txt
python -m eval.agentic.run --label agentic-dev-phase1
pytest eval/agentic/tests
```

Outputs go to `runs/agentic/`: `<label>.json`, `<label>.traces.jsonl` and `<label>.png`. The
`cfad026` results are kept as `agentic-dev.*`, the run before the database checks as
`agentic-dev-366faf4.*`, and the run before the Phase 1 fixes as `agentic-dev-dbstate.*`.

| Check | Result |
|---|---|
| `pytest eval/agentic/tests` | 138 passed, 3 expected failures |
| Two consecutive runs | Byte-identical JSON reports |
| `ruff check` and `ruff format --check` on `eval/agentic` | Clean |
| Changes in the repository | The eval: `eval/agentic/`, `runs/agentic/`. The Phase 1 product fixes: `mcp_servers/claims_db.py` and `mcp_servers/approvals.py`, tested in `tests/mcp_servers/` |

## 12. Recommended next steps

1. **Domain lead:** rule on AGENTIC-13 (does `quantity` mean days?).
2. **Tools & Security:** review the Phase 1 settlement fixes (section 2.1), and scale the tool
   budget with bill length (AGENTIC-09).
3. **Agents & Orchestration:** bring `record_history` under the belt (AGENTIC-08), and flag in-bill
   duplicates on the not-admissible branch (AGENTIC-12). Fix the claim status write with Tools &
   Security (AGENTIC-14).
4. **Eval & Red-Team:** write new attack wordings that the team has not seen, and measure defences
   off and on with a false-block rate on clean dev claims.
5. **Eval & Red-Team:** run one end-to-end pass on `real_services()` through LangGraph with the
   real model (the online run).
