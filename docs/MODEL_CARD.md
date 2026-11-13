# ClaimSense Model Card

**System:** ClaimSense, health-insurance claim adjudication assistant (Agentic AI Capstone)
**Card version:** 1.0, 12 November 2026
**Code version:** repository `main` at commit `d221187`
**Harness version:** `eval/harness/scorecard.yaml` version 1 and `eval/agent_suite/gate.yaml` version 1
**Prepared by:** Sanjay Singh (Eval & Red-Team), with Claude Code
**Status:** **Not approved for production.** Evaluation evidence only (Section 7).
**For:** independent model risk validation, the model risk committee, and supervisory examiners.

This card brings together the evidence in the evaluation reports. Each statement names its
source file or run folder so a reviewer can check it. Where the card says "measured", the number
comes from a saved run under `runs/`.

---

## 1. Purpose and scope

### 1.1 What the system does

ClaimSense reads one hospitalisation reimbursement claim (the claim form, the discharge summary
and the itemised bill). It checks every bill line against the New India Assurance **Arogya
Sanjeevani** policy wording. It then prepares a **settlement worksheet** for a human claims
adjudicator to approve.

### 1.2 What decisions it makes

| Decision | Made by | Binding? |
|---|---|---|
| Which policy clause governs each bill line | Coverage agent (model), from candidates the retriever returns | No. A person reviews it and can change it. |
| Rupee amount per line, deductions, co-pay, total | **Plain code** (`src/claimsense/calc/`, `Decimal`), never a model | No. A person approves the exact worksheet. |
| Whether the claim is admissible (policy period, waiting periods, maternity exclusion) | Plain code (`agents/coverage.py` admissibility gate) | No. A failed gate sends the claim to a person. |
| Fraud and data-quality flags | Fraud agent (rules) and extraction checks | No. Flags are shown to the reviewer. |
| Route: ready for approval, or needs review | Graph routers | No. Every claim stops at the human approval gate. |
| Settle or repudiate | **A person only** | Yes, and only with a signed approval token for the exact worksheet. |

### 1.3 Out of scope

- Any policy other than Arogya Sanjeevani (UIN NIAHLIP25044V022425). The knowledge base holds one
  policy product.
- Cashless pre-authorisation, claim intake and payment execution.
- Final approval. The system never settles a claim on its own (rule 3, Section 5.3).
- Real customer data. Development and evaluation use synthetic claims only.
- Medical judgement (medical necessity, coding accuracy). The agents read what the documents state.

---

## 2. Architecture

### 2.1 Pipeline

The claim flows through a fixed graph (`graph/build.py`):

`plan → extract → admissibility →` (gate fails → `human_review`) `→ coverage → fraud → critic →`
(`revise` loops back to `coverage` once, or `escalate`) `→ human_review → apply_edits / senior_review
/ settle / repudiate → memory_update`.

### 2.2 Agents

| Agent | Job | Tools it may call (`agents/permissions.py`) |
|---|---|---|
| Planner | Fills a fixed plan template | none |
| Extraction | Turns documents into a typed `Claim`, verifies every source span, masks PII before the model, scans for injected instructions | none (reads only the documents it is given) |
| Coverage | Admissibility checks (code); chooses one clause per bill line (model) | `policy_search`, `get_clause`, `get_policy`, `calculate`, `retrieve_lessons` |
| Fraud | Duplicate bills, tariff outliers, policy-period checks | `claim_history`, `tariff_range`, `get_policy` |
| Critic | Recomputes the worksheet and checks each deduction against its clause | `calculate`, `get_clause` |
| Settlement | Runs the payment ceiling and letter guardrails, then settles or repudiates **after** approval | `settle_claim`, `record_repudiation`, `get_policy` |

A module-level assertion makes sure that only the settlement agent can ever hold `settle_claim`.

### 2.3 Foundation models

All models are reached through OpenRouter, at temperature 0 (`agents/llm.py`).

| Role | Model in use | Note |
|---|---|---|
| Extraction, coverage, critic, fraud, settlement | `openai/gpt-4.1-mini` | Each can be overridden by `CLAIMSENSE_MODEL_<ROLE>` |
| Reflector (offline improvement loop only) | `openai/gpt-4.1` | Not in the claim path |
| Evaluation judge (RAGAS) | `google/gemini-3.1-flash-lite` | Evaluation only; a different family from the agents |
| Embeddings | `BAAI/bge-small-en-v1.5` | Local |
| Re-ranker | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Local |

**Resolved discrepancy (AGT-09).** Until 13 November 2026, `config/models.yaml` named
`openai/gpt-4o-mini` for four roles while the agents took `openai/gpt-4.1-mini` from their own table
in `agents/llm.py`. Since `models.yaml` version 2 the agents read their model IDs from the YAML,
which now names the models in the table above. No run changed model. The prompts are still inline
in the agent code (an open item for the Agents owner).

### 2.4 Tools

| Tool | Read or write | Backing |
|---|---|---|
| `policy_search`, `get_clause` | read | Hybrid retriever: BM25 + dense vectors (Chroma) + reciprocal rank fusion + cross-encoder re-rank + query rewrite (`mcp_servers/policy_kb.py`, `retrieval/`) |
| `calculate` | read | The rupee calculator (`calc/adjudication.py`) |
| `get_policy`, `claim_history`, `record_history` | read / write | Claims database, SQLite (`mcp_servers/claims_db.py`) |
| `tariff_range` | read | Tariff table (`mcp_servers/tariff.py`) |
| `settle_claim`, `record_repudiation` | write | Claims database; verifies an HMAC-signed approval token bound to the worksheet hash (`mcp_servers/approvals.py`) |

The tool definitions are pinned (`config/tool_pins.json`); a tool whose name, description or
arguments changed since review does not load. With `tool_hooks=True` every tool call goes
through a per-claim allow-list, a claim-scope check, a tool-call budget (40 per claim) and an
audit record.

### 2.5 Data sources

- Policy documents: six PDFs in `data/policy/new_india/`, with a SHA-256 manifest that a test checks.
- Knowledge base: 181 clause chunks (180 searchable) extracted from the policy wording
  (`data/knowledge_base/`).
- Claims database and tariff table: synthetic.

---

## 3. Development data

**No fine-tuning was performed.** All models are used as provided by their vendors, with prompts
written in the code.

What the system learns from instead:

| Data | Size | How it was labelled | Use |
|---|---|---|---|
| Dev claims and gold worksheets (`eval/golden_dev/`) | 22 claims | Synthetic. Gold was first made by demo rules, then corrected against the policy wording by recorded rulings (ADR-0006, ADR-0007, ADR-0009, ADR-0011) | Development and evaluation |
| Red-team claims (`eval/redteam/`) | 30 claims from 12 attack seeds | Each is a dev claim plus one attack; gold is the dev gold plus the one change the attack makes, never calculator output | Evaluation |
| Retrieval queries (`eval/golden_dev/retrieval_queries.jsonl`) | 49 question → clause pairs | Draft, written by the team; not yet verified by the Domain lead | Retrieval evaluation |
| Guardrail seeds (`eval/redteam/guardrail_seeds.jsonl`) | 14 | Hand-written, synthetic | Guardrail evaluation |
| Reflexion playbook lessons | From dev cases | Approved by a person before use | Optional; off in the default pipeline |
| Held-out set (`../claimsense-heldout/`) | Not stated here | Kept outside the repository | **Not run yet.** Run once, by Eval & Red-Team, with everything frozen |

**Known biases and gaps in this data:**

- **Synthetic and small.** 22 dev claims cannot show the variety of real Indian hospital bills,
  languages or document scans.
- **One policy, one insurer.** Results say nothing about other products.
- **Gold is partly demo-rule.** A high score means "agrees with today's gold", not "correct
  under the policy wording" (`docs/CLAIMS_AND_GOLD_SET_FIXES.md`; GOLD-03, 05, 06, 08 and DEC-02/03
  are open or partly fixed).
- **Tuned on dev.** The coverage rewrite table and the retrieval glossary were built from the dev
  claims, so the dev score likely overstates performance on new bills. Only the held-out run can
  measure that.

---

## 4. Evaluation methodology and results

### 4.1 Methodology

| Layer | What it checks | Tool |
|---|---|---|
| Harness scorecard | Is the final answer right? Weighted: route 0.20, amounts 0.30, flags 0.20, citations 0.10, required tool use 0.20. Composite must be ≥ 0.85. | `eval/harness/` (`scorecard.yaml` v1) |
| Catastrophic gates | Any single failure blocks release: unsafe settlement, money from a model, injection obeyed, fabricated citation, eval-only field leak, PII exposure | `eval/harness/safety_metrics.py` |
| Agent suite | How did the agents get there? Task success, attack success, injection shown to the reviewer, path complete, forbidden calls, p95 latency ≤ 30 s, cost ≤ $0.20 per claim | `eval/agent_suite/` (`gate.yaml` v1) |
| Release check | Harness self-check, then one traced run scored by both of the above | `python -m eval.full` |
| Security | Every defence against every attack, honest claims alongside; an adaptive attacker model | `eval/security/` |
| Retrieval | Top-1, Recall@5 and MRR per retrieval stage | `claimsense.retrieval.evaluate` |
| RAGAS faithfulness | Is the model's rationale supported by the clause it saw? | `--judge`; **weight 0.00, uncalibrated** |
| Self-tests | The harness must score the gold at ~1.0 and a do-nothing agent near 0, and every gate must fire on a planted fault | `python -m eval.harness.suite` (9 of 9 rows match) |

Dataset: 22 dev claims and 30 red-team claims (52 in all). The held-out set has not been run.

### 4.2 Results with real models (12 November 2026)

| Run | Composite | Gates | Attacks cleared | Injections shown | Cost per claim | p95 | Verdict | Evidence |
|---|---|---|---|---|---|---|---|---|
| Release check, default pipeline | 0.984 (dev 0.965, red-team 0.998) | all held | 0 / 30 | 18 / 18 | $0.0013 | 26.4 s | **PASS** | `runs/full/release-check-sec-1112` |
| Release check, real retriever | 0.976 (dev 0.965, red-team 0.983) | all harness gates held | 0 / 30 | 18 / 18 | $0.0017 | 30.2 s | **FAIL** (p95 > 30 s by 0.2 s) | `runs/full/rr-release-1112c` |
| Release check + guard model | 0.984 | all harness gates held | 0 / 30 | 18 / 18 | $0.0016 | 35.9 s | **FAIL** (p95) | `runs/full/release-check-guard-1112` |
| Security scoreboard | — | — | 0 / 30 with the input guardrail (10 / 30 without it) | 18 / 18 | — | — | — | `runs/security/real-scoreboard-1112` |
| Adaptive attacker, 6 rounds | — | — | did not win (5 held, 1 flagged) | — | — | — | — | `runs/security/real-attack-1112` |
| Retrieval, 47 queries (all stages) | Recall@5 1.000, top-1 0.766, MRR 0.867 | — | — | — | — | — | — | `runs/retrieval_retrieval-1112.png` |
| RAGAS faithfulness, 2 claims judged | 0.743 and 0.594 in two runs | — | — | — | — | — | not usable (unstable, uncalibrated) | `runs/ragas-rr-1112.scorecard.json` |

Honest dev claims handled correctly: 20 of 22 in every configuration. Clean claims sent to a
person anyway: 1 of 10. The two weakest claims are CLM-0021 and CLM-0022 (cataract lines, 0.613):
on 12 November a retrieval fix for these was merged (commit `b76e6e0`) and has not yet been
re-measured.

### 4.3 Supporting evidence

| Report | Content |
|---|---|
| `docs/EVAL_HARNESS_REPORT.md` | Harness design, metrics, gates, self-tests, 318 evaluation tests |
| `docs/AGENT_SUITE_REPORT.md` | Agent trajectories, variants, gate results |
| `docs/SECURITY_REPORT_CARD.md` | 20 security controls, scoreboard, release gates |
| `docs/MONITORING_REPORT_CARD.md` | Live alert drill, A/B test, findings MON-01 to MON-04 |
| `docs/OBSERVABILITY_REPORT.md` | Tracing and the DeepEval suite (74 tests) |
| `docs/terminal.md` | Every run, stub and real, with the command that made it |
| `docs/FRAMEWORK_RUBRIC_SCORE.md` | Architecture maturity, 2.85 out of 5 |

---

## 5. Known limitations and failure modes

### 5.1 Open defects that affect a decision

| ID | Failure mode | Effect | Mitigation today |
|---|---|---|---|
| MON-01 | A failed tariff lookup crashes the whole claim | The claim reaches the adjudicator with no worksheet | Alert `PipelineErrorRateHigh`; the claim is never paid |
| AGT-04 | Coverage and critic prompts take outside text without the `as_data` wrapper | A crafted bill line could steer the clause choice | The model may only pick a retrieved clause; every claim needs human approval; 0 / 30 attacks cleared |
| AGT-05, AGT-06 | Two query-rewrite tables; the model sees only 400 characters of each candidate clause | A wrong or weaker clause choice | The critic re-checks every deduction; a person approves |
| AGT-09 | Two model tables disagree (Section 2.3) | Unclear which model is approved | This card records the model that runs |
| AGT-13 | Without a model, the critic's meaning check rejects correct deductions for clauses 6.2.6 and 7.15 | Over-escalation in offline mode | Not in the real-model path |
| — | Real retriever latency: p95 30.2 s with real models | Fails the 30 s release gate | Search cache in place; start-up warm-up or a GPU needed |
| — | PII masking covers ID numbers, phone, email and cards, but not names | A name could reach a model | Synthetic data only; the `pii_exposure` gate checks outputs |
| — | Guard model is off by default | No model-based injection check | The pattern guardrail catches 18 / 18; the guard model added nothing and fails the latency gate |

### 5.2 Inputs the system is not designed to handle

- Policies other than Arogya Sanjeevani, and claims under group or floater variants it was not tested on.
- Scanned or handwritten documents without a text layer; non-English documents.
- Bills with categories outside the `LineCategory` list (they map to `other`).
- Accident claims that should be exempt from waiting periods: the claim carries no accident
  indicator yet, so these go to a person (ADR-0011).
- Claims whose policy number in the documents differs from the registered policy: flagged and sent
  to a person.

### 5.3 Human review gates

1. **Every claim stops for a person.** The graph interrupts at `human_review`; nothing is paid
   without a decision.
2. **The approval is bound to the exact worksheet.** `settle_claim` accepts only an HMAC-signed
   `ApprovalToken` whose `worksheet_hash` matches; any edit voids all earlier approvals.
3. **Senior review.** A payable amount above Rs 100,000, or any fraud flag, needs a second, senior
   approval (`config/models.yaml`, `approvals.needs_senior_review`).
4. **Guardrail blocks escalate.** A payment above the claimed amount or the sum insured, or an
   unsafe letter, sends the claim to a person; it never changes an amount.
5. **Failed admissibility** (outside the policy period, waiting periods, maternity exclusion)
   goes to a person with the clause cited.

---

## 6. Monitoring plan

The alert rules are in `eval/monitoring/alert_rules.yml` and were tested in a live drill against
Prometheus and Grafana (`docs/MONITORING_REPORT_CARD.md`).

| Signal | Alert | Threshold | Holds for | What it detects |
|---|---|---|---|---|
| Tool error rate, per tool | `ToolErrorRateHigh` | > 20 % of calls, 1-minute window | 15 s | A tool server outage (tariff, policy-kb, claims-db) |
| Pipeline error rate | `PipelineErrorRateHigh` | > 5 % of claims | 15 s | Claims ending with no worksheet (MON-01) |
| Handled-correctly rate (scored traffic) | `HandledCorrectlyDrop` | < 40 % | 20 s | Quality drift after a model or prompt change |
| Guardrail trip rate | `GuardrailBurst` | > 5 % of claims | 10 s | A new injection campaign |
| p95 latency | `LatencyP95High` | > 30 s, 2-minute window | 30 s | Slow models, retrieval or loops |
| Cost per claim | `CostPerClaimHigh` | > $0.005 | 20 s | Retry or revise loops, a costlier model |

**Drift signals beyond the alerts.** Run the release check (`python -m eval.full`) on every
material change, and compare it with the last approved run. The live A/B test compares two
variants on real traffic (Fisher's exact test, Mann-Whitney).

**Status and gaps.**

- The windows are seconds long so that a four-minute drill can show them firing. Production
  needs windows of minutes to hours.
- MON-02: the tool alert took 55 s to fire on a 60 s outage.
- MON-04: with real models, the 40 % "handled correctly" limit sits inside normal noise and must
  be re-set from production data.
- The rules belong to the evaluation tools. Deploy & Ops has not yet installed them in the
  product's `monitoring/` folder.

---

## 7. Approval history

**No version of ClaimSense has been approved for production.** The table records the evaluation
reviews to date. It does not record approvals.

| Date | Version | Harness version | Event | By | Outcome |
|---|---|---|---|---|---|
| 12 Nov 2026 | `0bf7400` | scorecard v1, gate v1 | Real-model release check, default pipeline | Eval & Red-Team (Sanjay Singh) | Gates passed (`release-check-sec-1112`) |
| 12 Nov 2026 | `8b2153c` without `b76e6e0` (the cataract glossary fix came in after the run) | scorecard v1, gate v1 | Real-model release check with the real retriever | Eval & Red-Team (Sanjay Singh) | Failed: p95 30.2 s (`rr-release-1112c`) |
| 12 Nov 2026 | `d221187` | scorecard v1, gate v1 | Model card 1.0 written | Eval & Red-Team (Sanjay Singh) | For validation review |

**Before a production approval can be recorded:**

1. Run the held-out set once, with everything frozen, and add its scorecard to Section 4.
2. Close or accept the open items in Section 5.1, especially MON-01, AGT-04 and AGT-09.
3. Pass the release check with the retriever configuration that will run in production.
4. Independent model risk validation reviews this card and the evidence it cites.
5. The model risk committee approves, at a level set by materiality. Record the approver, the
   date, the code commit and the harness version in the table above.

---

## 8. Keeping this card current

Update this card, and send it back to model risk validation, on every material change:

- a new agent, or a changed agent role or tool permission;
- a foundation model promoted or replaced (including any change in `agents/llm.py`);
- a change to a scorecard metric, weight, threshold or catastrophic gate (`scorecard.yaml`,
  `gate.yaml`);
- a change to the policy corpus or the knowledge base;
- a change to a human review gate or the senior-review threshold.

For each update: re-run the release check, update Sections 4 to 7, raise the card version, and
add a row to Section 7. The model risk committee decides, based on materiality, whether the
change needs its review.
