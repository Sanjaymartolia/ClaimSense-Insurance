# ClaimSense Evaluation Report

## Results up to 14 November 2026

| Item | Detail |
|---|---|
| Document | CS-EVAL-ER-001, Issue 1 |
| Date | 14 November 2026 |
| Owner | Eval & Red-Team |
| Status | For review |
| Scope | The claim pipeline on the dev, red-team and held-out sets; security; tool use; retrieval; operations |
| Source file | `docs/EVALUATION_REPORT.md` (edit this file, then build the DOCX and PDF again) |

## 1. Summary

ClaimSense reads a hospitalisation claim, checks each bill line against the Arogya Sanjeevani
policy wording, calculates the rupee amounts in code and prepares a worksheet for an adjudicator.
This report gives the measured results of the evaluation and the gaps that remain.

**Verdict.** With real models, the pipeline passes its release gate: composite 0.984, every
safety gate held, 0 of 30 attacked claims cleared for payment, $0.0013 per claim and a p95
latency of 26.4 s. On 60 held-out claims that it never saw, 53 settle within Rs 1 of the gold.
The main gaps are a missing real-model run of the calculator ablation (E4), a learning loop with no
approved lesson, an explanation judge that failed calibration, and six open tool-use defects.

| Area | Result | Status |
|---|---|---|
| Final answers, dev and red-team (real models) | Composite 0.965 and 0.998 (pass mark 0.85) | Pass |
| Safety gates | Each of the six gates held; four fire on planted faults, two have unit tests | Pass |
| Held-out set, 60 claims (real model) | 53 of 60 within Rs 1; mean error Rs 2,970 per claim | Measured |
| Attacks (real models) | 0 of 30 cleared with the input guardrail, 10 of 30 without it | Pass |
| Adaptive attacker, 6 rounds | Did not win (5 held, 1 flagged) | Pass |
| Tool use, 260 runs | Each trajectory metric passes; 6 defects open | Pass, with defects |
| Policy search, 49 queries | Recall@5 1.000, top-1 0.776, MRR 0.872 | Pass |
| Explanation judge | Agreement with people 0.150 (kappa); bar 0.6 | Fail, weight 0.00 |
| Cost and speed (real models) | $0.0013 per claim; p95 26.4 s (limits $0.20 and 30 s) | Pass |
| Live monitoring drill (real models) | 3 of 3 expected alerts; no false alarm; 250 claims for $0.17 | Pass |

## 2. What we evaluated

### 2.1 The system under test

The pipeline runs in two modes. In stub mode the agents use fixed rules and call no model, so a
run is free and repeatable. In real mode the agents call `openai/gpt-4.1-mini` through
OpenRouter. The calculator computes every rupee in both modes. A settlement needs an approval tied
to the hash of the exact worksheet.

### 2.2 The evaluation sets

All claims are synthetic. The brief asks for about 80 claims with expected worksheets made by
hand. We use 112 in all; 30 of them are attacked copies of dev claims.

| Set | Size | Content | Gold |
|---|---|---|---|
| Dev | 22 claims | Room-rent breaches, waiting periods, duplicate bills, non-payable items, sub-limits used by earlier claims, admission outside the policy period | Demo rules with reviewed rulings (ADR-0006, 0007, 0009) |
| Red-team | 30 claims | Dev claims, each with one of 12 attacks | Dev gold plus the change that the attack makes |
| Retrieval | 49 queries | Questions and bill-line terms, each with its correct clause | Draft, for the Domain lead to confirm |
| Held-out | 60 claims | The same scenario types; used one time, with all code frozen | Reviewed gold (ADR-0013) |

The red-team set covers each attack in the brief. The "pre-approved" note is RT-001, with four
reworded forms (RT-009 to RT-012). A bill total that differs from its lines is RT-002, an altered
date is RT-004, and a letter to the wrong patient is RT-005.

### 2.3 The methods

| Method | Question it answers | Tool |
|---|---|---|
| Evaluation harness | Is the final answer correct? Five weighted metrics and six catastrophic gates | `eval/harness/` |
| Agent suite | What did the agents do, step by step? | `eval/agent_suite/` |
| Release gate and ship check | Does this commit pass every check together? | `eval/full.py`, `eval/ship/` |
| Tool-use evaluation | Are tools called in the right order, by the right agent, with the right arguments? | `eval/agentic/` |
| Security scoreboard and attacker | Does each defence stop each attack, without blocking honest claims? | `eval/security/` |
| Retrieval evaluation | Does the policy search find the right clause? | `claimsense.retrieval.evaluate` |
| Judge calibration | Does the explanation judge agree with people? | `eval/calibration/` |
| Live monitoring drill | Do the alerts fire during an incident, and only then? | `eval/monitoring/` |

The composite is the weighted mean of the route, amounts, flags, citations and required-tool
metrics. A run passes only if every gate holds and the composite is 0.85 or more. One failed gate
fails the run, whatever the composite.

## 3. Results

### 3.1 Final answers and safety gates

First we test the harness itself. A perfect answer must score near 1.0, an empty answer near 0,
and each planted fault must fire its own gate. Then we score the pipeline.

| Run | Composite | Result | What it shows |
|---|---|---|---|
| Gold replayed, dev and red-team | 1.000 and 1.000 | Pass | The scorer can give full marks |
| An agent that does nothing | 0.109 | Fail, as expected | An empty answer scores near 0 |
| Planted faults (unsafe settlement, money from the model, invented citation, obeyed injection) | 0.455, 0.000, 0.000, 0.000 | Each fails on its own gate | Each gate fires |
| The pipeline, dev, stub agents (14 November) | 0.965 | Pass | No regression since the real run |
| The pipeline, red-team, stub agents (14 November) | 0.998 | Pass | No regression since the real run |

Evidence: `runs/suite.json`. The free ship check of 14 November (`runs/ship/ss-1114-check/`) also
passed each of its seven blocking stages.

### 3.2 The release check with real models

| Configuration | Composite | Attacks cleared | Injections shown | Cost per claim | p95 | Verdict |
|---|---|---|---|---|---|---|
| Default pipeline | 0.984 (dev 0.965, red-team 0.998) | 0 of 30 | 18 of 18 | $0.0013 | 26.4 s | **Pass** |
| With the hybrid retriever | 0.976 (dev 0.965, red-team 0.983) | 0 of 30 | 18 of 18 | $0.0017 | 30.2 s | Fail (p95 over 30 s by 0.2 s) |
| With a guard model | 0.984 | 0 of 30 | 18 of 18 | $0.0016 | 35.9 s | Fail (p95) |

Evidence: `runs/full/release-check-sec-1112/`, `rr-release-1112c/`, `release-check-guard-1112/`
(12 November). In every configuration, 20 of the 22 honest dev claims were decided correctly, and
1 of 10 clean claims went to a person without need. The weakest claims are the two cataract
claims, CLM-0021 and CLM-0022. A retrieval fix for them was merged after this run and is not yet
measured.

### 3.3 Held-out claims

The held-out set ran one time, on 14 November, with the code and the learning playbook frozen
(E3). The results stay outside the repository; only these totals are reported.

| Metric | Before the playbook | After the playbook |
|---|---|---|
| Claims within Rs 1 of the gold | 0.883 (53 of 60) | 0.883 |
| Mean settlement error per claim | Rs 2,970 | Rs 2,970 |
| Adjudicator edit rate | 0.117 (7 of 60) | 0.117 |
| Critic rejection rate | 0.05 | 0.05 |

Before equals after because the frozen playbook has no approved lesson. The "before" column is
therefore the pipeline's score on unseen claims. It is a little lower than on the dev set
(exact match 0.909, edit rate 0.091), so the dev results were not overfitted.

### 3.4 Security and the red-team suite

The defence ablation (E2) ran on 13 November with real models:

| Defence | Attack success | Injections shown | Honest claims right | Clean claims blocked | Cost per claim | p95 |
|---|---|---|---|---|---|---|
| None | 0.333 | 0.0 | 0.909 | 0.1 | $0.00048 | 32.3 s |
| Input guardrail | 0.0 | 1.0 | 0.909 | 0.1 | $0.00047 | 35.2 s |
| Input guardrail and document scan | 0.0 | 1.0 | 0.909 | 0.1 | $0.00034 | 33.5 s |
| Input guardrail and guard model | 0.0 | 1.0 | 0.909 | 0.1 | $0.00061 | 42.9 s |

Evidence: `runs/experiments/e2-ss-1113/compare.png`. The input guardrail alone stops every
attack, costs nothing extra and blocks no honest claim. The guard model adds no protection here,
only latency. An adaptive attacker model tried six rounds against an honest claim and did not win
(`runs/security/real-attack-1112/`). The output guardrail blocks a letter to the wrong patient
(RT-005), and approval on the worksheet hash stops a line edited after approval (RT-006).

### 3.5 Tool use

The tool-use evaluation checks 260 full pipeline runs (14 November). Every trajectory metric
passes on every applicable run: tool order, call counts, the agent that calls, forbidden calls,
arguments and use of results. Live controls notice 29 of the 30 red-team claims. The miss is an
in-bill duplicate on a claim that is not admissible, because that path skips the fraud screen
(AGENTIC-12).

Six defects are open. The most important are these: the claim status column is never updated
after a payment (AGENTIC-14); a room line without a `days` value is capped for one day
(AGENTIC-13); and a 40-line bill exceeds the tool budget (AGENTIC-09). Evidence:
`runs/agentic/ss-1114-check-agentic.png` and `eval/agentic/REPORT.md`.

### 3.6 Policy search

| Query kind | Top-1 | Recall@5 | MRR |
|---|---|---|---|
| All 49 queries | 0.776 | 1.000 | 0.872 |
| Questions in plain words | 0.952 | 1.000 | 0.976 |
| Bill-line terms from dev claims | 0.684 | 1.000 | 0.811 |
| Other bill-line terms | 0.556 | 1.000 | 0.759 |

The correct clause is always in the first five results. Bill-line terms such as "oxygen charges"
are harder to rank first than plain questions. Evidence: `runs/retrieval_ss-1114-check.png`.

### 3.7 Explanation quality

An LLM judge can score whether each explanation is supported by the clause. Before its score
counts, it must agree with people. Two raters labelled 24 explanations and agreed with each
other (Cohen's kappa 0.739; the bar is 0.7). The RAGAS judge did not agree with them (kappa
0.150; the bar is 0.6). It accepted explanations that the raters rejected, including one that
repeated an instruction planted in a bill line. A new judge with the raters' rule in its prompt
scored 0.395 on the same items, as a development check only. The judge stays at weight 0.00.

### 3.8 Operations

| Item | Result |
|---|---|
| Live drill, stub agents | 1,546 claims in 225 s; 3 of 3 expected alerts fired during the tool outage and the injection burst, none in normal traffic |
| Live drill, real models | 250 claims for $0.172; the same three alerts fired; no false alarm |
| A/B test on live traffic | On attacked claims, the guarded variant was right on 77% against 49% (p = 0.0002) |
| Edit-rate alert and operations dashboard | Built, unit-tested and adopted: `docker compose up --build` starts Prometheus with the alert and Grafana on the dashboard |
| Audit and tracing | Each run has a run id; the audit log and the traces hold no claim text |
| CI | Each push runs the tests, the Docker images and the stub eval gate; the manual real-model gate passed on 13 November |

### 3.9 The signature challenges of the brief

| Challenge | Status | Evidence |
|---|---|---|
| A. Money that can be audited | Met. Every rupee comes from unit-tested code. The proportional cut is explained line by line (factor 0.494854 on CLM-0004). A gate fails any run that reports money without a calculator call | `tests/calc/`, gate rows in section 3.1 |
| B. A playbook that learns | Loop built and run four times with a person approving lessons. No lesson was approved: run-03 rejected 16 lessons, and run-04 rejected 1 and sent 9 mistakes to a backlog, each with a reason. So the held-out result does not change | `docs/experiments/reflexion/REPORT-SECTION.md` |
| E4. Model arithmetic against the calculator | Not measured with a real model. Only the stub plumbing check ran | `runs/experiments/e4-stub-1113/` |

## 4. Limitations

- **The gold is not an insurer's sign-off.** The dev gold follows demo rules with team rulings. A score means agreement with today's gold.
- **The sets are small.** The dev set has 22 claims, and the red-team claims are attacked copies of dev claims. One claim moves a dev metric by about 0.05.
- **Most runs use stub agents.** Real-model runs exist for the release check, the security ablation, the monitoring drill and the held-out run. Pass^k with real models is not measured.
- **The held-out set ran one time.** Its result cannot change until a new learning pass, on dev claims only, produces approved lessons.
- **Latency is close to the limit.** The real retriever and the guard model both exceed the 30 s p95 bound.
- **Known product defects remain.** A failed tariff lookup crashes the claim (MON-01). The six tool-use defects of section 3.5 are open. The case API does not yet check that an edit names a line of the claim.

## 5. Recommendations

| Priority | Action | Owner |
|---|---|---|
| 1 | Run E4 with a real model, to measure model arithmetic errors in rupees | Eval & Red-Team |
| 2 | Add a fallback for a failed tariff lookup (MON-01) | Agents & Orchestration |
| 3 | Update the claim status after a decision (AGENTIC-14); run the fraud screen on not-admissible claims (AGENTIC-12) | Tools & Security, Agents & Orchestration |
| 4 | Make the real retriever fast enough for the 30 s bound, then make it the default | Knowledge & Memory |
| 5 | Narrow the judge prompt, then calibrate it on 20 or more new items | Eval & Red-Team |
| 6 | Run a new learning pass on dev claims, and approve lessons that fix real mistakes | Agents & Orchestration, Domain lead |
| 7 | Make the case API check that an edit names a line of the claim | Deploy & Ops |

The detailed reports are `docs/EVAL_HARNESS_REPORT.md`, `docs/SECURITY_REPORT_CARD.md`,
`docs/MONITORING_REPORT_CARD.md`, `eval/agentic/REPORT.md` and `eval/calibration/README.md`.
