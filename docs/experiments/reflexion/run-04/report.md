# Reflexion experiment: 22 development claims

## Development claims
| metric | before | after |
|---|---|---|
| settlement_error_total_rs | 39904.80 | 39904.80 |
| settlement_error_mean_rs | 1813.85 | 1813.85 |
| exact_match_rate | 0.909 | 0.909 |
| edit_rate | 0.091 | 0.091 |
| critic_rejection_rate | 0.182 | 0.182 |

## Lessons that made results worse (withdrawn)
- none

## Mistakes sent to the engineering backlog (not clause choices, no lesson)
- CLM-0005 CLM-0005-L06 [critic_rejection]: deduction under a claim-level clause is made by the gate or the calculator, not chosen by the analyst; a critic item
- CLM-0005 CLM-0005-L06 [critic_rejection]: deduction under a claim-level clause is made by the gate or the calculator, not chosen by the analyst; a critic item
- CLM-0009 CLM-0009-L06 [critic_rejection]: deduction under a claim-level clause is made by the gate or the calculator, not chosen by the analyst; a critic item
- CLM-0009 CLM-0009-L06 [critic_rejection]: deduction under a claim-level clause is made by the gate or the calculator, not chosen by the analyst; a critic item
- CLM-0010 CLM-0010-L06 [critic_rejection]: deduction under a claim-level clause is made by the gate or the calculator, not chosen by the analyst; a critic item
- CLM-0010 CLM-0010-L06 [critic_rejection]: deduction under a claim-level clause is made by the gate or the calculator, not chosen by the analyst; a critic item
- CLM-0015 CLM-0015-L06 [critic_rejection]: deduction under a claim-level clause is made by the gate or the calculator, not chosen by the analyst; a critic item
- CLM-0015 CLM-0015-L06 [critic_rejection]: deduction under a claim-level clause is made by the gate or the calculator, not chosen by the analyst; a critic item
- CLM-0022 CLM-0022-L01 [adjudicator_edit]: near-duplicate of LSN-2735248b (rejected)

Frozen playbook hash: `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945`

## Run details

mode: REAL MODEL via OpenRouter | executor: local | calculator: reference | tolerance: Rs 1 | approval: CONSOLE

- development cases: 22 from `eval/golden_dev`
- rounding tolerance: Rs 1 (0 = strict; rupee error is exact either way)
- lessons proposed 1, approved 0, rejected 1, withdrawn after ablation 0; 9 mistake(s) triaged to the backlog (not clause choices)
- generated 2026-11-13T21:24:25.901594+00:00

## Baseline: where the error comes from

- exact match: 8 cases
- rounding only (error under Rs 1): 12 cases (CLM-0004, CLM-0005, CLM-0006, CLM-0009, CLM-0010, CLM-0011, CLM-0012, CLM-0014, CLM-0015, CLM-0016, CLM-0019, CLM-0020)
- real disagreement (Rs 1 or more): 2 cases (CLM-0021, CLM-0022)

## Spread across the 2 after-pass run(s)

| metric | min | max |
|---|---|---|
| settlement_error_total_rs | 39904.80 | 39904.80 |
| settlement_error_mean_rs | 1813.85 | 1813.85 |
| exact_match_rate | 0.909 | 0.909 |
| edit_rate | 0.091 | 0.091 |
| critic_rejection_rate | 0.182 | 0.182 |

## After pass, run 1

| metric | before | after |
|---|---|---|
| settlement_error_total_rs | 39904.80 | 39904.80 |
| settlement_error_mean_rs | 1813.85 | 1813.85 |
| exact_match_rate | 0.909 | 0.909 |
| edit_rate | 0.091 | 0.091 |
| critic_rejection_rate | 0.182 | 0.182 |

- exact match: 8 cases
- rounding only (error under Rs 1): 12 cases (CLM-0004, CLM-0005, CLM-0006, CLM-0009, CLM-0010, CLM-0011, CLM-0012, CLM-0014, CLM-0015, CLM-0016, CLM-0019, CLM-0020)
- real disagreement (Rs 1 or more): 2 cases (CLM-0021, CLM-0022)

## After pass, run 2

| metric | before | after |
|---|---|---|
| settlement_error_total_rs | 39904.80 | 39904.80 |
| settlement_error_mean_rs | 1813.85 | 1813.85 |
| exact_match_rate | 0.909 | 0.909 |
| edit_rate | 0.091 | 0.091 |
| critic_rejection_rate | 0.182 | 0.182 |

- exact match: 8 cases
- rounding only (error under Rs 1): 12 cases (CLM-0004, CLM-0005, CLM-0006, CLM-0009, CLM-0010, CLM-0011, CLM-0012, CLM-0014, CLM-0015, CLM-0016, CLM-0019, CLM-0020)
- real disagreement (Rs 1 or more): 2 cases (CLM-0021, CLM-0022)

## All lessons and their review status

| lesson | status | reviewer | note | text | applies when | clauses | from case |
|---|---|---|---|---|---|---|---|
| LSN-2735248b | rejected | Dhruvi Ramani | rejected | For procedure category claims under the Arogya Sanjeevani policy, verify and apply clause 4.3 as specified (clause new_india_arogya_sanjeevani:4.3). | When adjudicating procedure category bill lines under the Arogya Sanjeevani policy. | new_india_arogya_sanjeevani:4.3 | CLM-0021 |

## Ablation table (leave one lesson out)

| lesson | harmful | error increase Rs | edit-rate increase | text |
|---|---|---|---|---|

## Engineering backlog: mistakes that are not clause choices (no lesson proposed)

- CLM-0005 CLM-0005-L06 [critic_rejection]: deduction under a claim-level clause is made by the gate or the calculator, not chosen by the analyst; a critic item
- CLM-0005 CLM-0005-L06 [critic_rejection]: deduction under a claim-level clause is made by the gate or the calculator, not chosen by the analyst; a critic item
- CLM-0009 CLM-0009-L06 [critic_rejection]: deduction under a claim-level clause is made by the gate or the calculator, not chosen by the analyst; a critic item
- CLM-0009 CLM-0009-L06 [critic_rejection]: deduction under a claim-level clause is made by the gate or the calculator, not chosen by the analyst; a critic item
- CLM-0010 CLM-0010-L06 [critic_rejection]: deduction under a claim-level clause is made by the gate or the calculator, not chosen by the analyst; a critic item
- CLM-0010 CLM-0010-L06 [critic_rejection]: deduction under a claim-level clause is made by the gate or the calculator, not chosen by the analyst; a critic item
- CLM-0015 CLM-0015-L06 [critic_rejection]: deduction under a claim-level clause is made by the gate or the calculator, not chosen by the analyst; a critic item
- CLM-0015 CLM-0015-L06 [critic_rejection]: deduction under a claim-level clause is made by the gate or the calculator, not chosen by the analyst; a critic item
- CLM-0022 CLM-0022-L01 [adjudicator_edit]: near-duplicate of LSN-2735248b (rejected)

## Known gold vs calculator rule disagreements (not fixable by any lesson)

- Gold rounds each cut line to whole rupees; the calculator keeps paise. Cut lines differ by up to Rs 0.50 and count as a miss unless the evaluator is run with a tolerance (--tolerance-rs). ADR-0007 (GOLD-08): the gold stays in rupees; the eval harness defaults to a Rs 1 tolerance, the Reflexion evaluator keeps it explicit.
- Gold (ADR-0007, GOLD-05) caps cataract treatment at clause 4.3 (CLM-0021) and at the part an earlier claim left unused (CLM-0022); the calculator does not apply 4.3 because the claim contract carries no treated eye (calc.adjudication.INFORMATIONAL_SUB_LIMITS).

## Per case: baseline

| case | status | proposed Rs | gold Rs | abs error Rs | edited | lines edited | critic rejections | lessons used |
|---|---|---|---|---|---|---|---|---|
| CLM-0001 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0002 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0003 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0004 | settled | 67067.10 | 67067 | 0.10 | no | 0 | 0 | - |
| CLM-0005 | settled | 76886.60 | 76886 | 0.60 | no | 0 | 2 | - |
| CLM-0006 | settled | 59141.58 | 59141 | 0.58 | no | 0 | 0 | - |
| CLM-0007 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0008 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0009 | settled | 56078.11 | 56078 | 0.11 | no | 0 | 2 | - |
| CLM-0010 | settled | 107538.62 | 107539 | 0.38 | no | 0 | 2 | - |
| CLM-0011 | settled | 44047.63 | 44048 | 0.37 | no | 0 | 0 | - |
| CLM-0012 | settled | 57971.15 | 57971 | 0.15 | no | 0 | 0 | - |
| CLM-0013 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0014 | settled | 62542.71 | 62542 | 0.71 | no | 0 | 0 | - |
| CLM-0015 | settled | 89481.74 | 89481 | 0.74 | no | 0 | 2 | - |
| CLM-0016 | settled | 40825.14 | 40825 | 0.14 | no | 0 | 0 | - |
| CLM-0017 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0018 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0019 | settled | 201962.52 | 201962 | 0.52 | no | 0 | 0 | - |
| CLM-0020 | settled | 71833.40 | 71833 | 0.40 | no | 0 | 0 | - |
| CLM-0021 | settled | 59850.00 | 38000 | 21850.00 | yes | 1 | 0 | - |
| CLM-0022 | settled | 32300.00 | 14250 | 18050.00 | yes | 1 | 0 | - |

## Per case: after pass, run 1

| case | status | proposed Rs | gold Rs | abs error Rs | edited | lines edited | critic rejections | lessons used |
|---|---|---|---|---|---|---|---|---|
| CLM-0001 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0002 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0003 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0004 | settled | 67067.10 | 67067 | 0.10 | no | 0 | 0 | - |
| CLM-0005 | settled | 76886.60 | 76886 | 0.60 | no | 0 | 2 | - |
| CLM-0006 | settled | 59141.58 | 59141 | 0.58 | no | 0 | 0 | - |
| CLM-0007 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0008 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0009 | settled | 56078.11 | 56078 | 0.11 | no | 0 | 2 | - |
| CLM-0010 | settled | 107538.62 | 107539 | 0.38 | no | 0 | 2 | - |
| CLM-0011 | settled | 44047.63 | 44048 | 0.37 | no | 0 | 0 | - |
| CLM-0012 | settled | 57971.15 | 57971 | 0.15 | no | 0 | 0 | - |
| CLM-0013 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0014 | settled | 62542.71 | 62542 | 0.71 | no | 0 | 0 | - |
| CLM-0015 | settled | 89481.74 | 89481 | 0.74 | no | 0 | 2 | - |
| CLM-0016 | settled | 40825.14 | 40825 | 0.14 | no | 0 | 0 | - |
| CLM-0017 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0018 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0019 | settled | 201962.52 | 201962 | 0.52 | no | 0 | 0 | - |
| CLM-0020 | settled | 71833.40 | 71833 | 0.40 | no | 0 | 0 | - |
| CLM-0021 | settled | 59850.00 | 38000 | 21850.00 | yes | 1 | 0 | - |
| CLM-0022 | settled | 32300.00 | 14250 | 18050.00 | yes | 1 | 0 | - |

## Per case: after pass, run 2

| case | status | proposed Rs | gold Rs | abs error Rs | edited | lines edited | critic rejections | lessons used |
|---|---|---|---|---|---|---|---|---|
| CLM-0001 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0002 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0003 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0004 | settled | 67067.10 | 67067 | 0.10 | no | 0 | 0 | - |
| CLM-0005 | settled | 76886.60 | 76886 | 0.60 | no | 0 | 2 | - |
| CLM-0006 | settled | 59141.58 | 59141 | 0.58 | no | 0 | 0 | - |
| CLM-0007 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0008 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0009 | settled | 56078.11 | 56078 | 0.11 | no | 0 | 2 | - |
| CLM-0010 | settled | 107538.62 | 107539 | 0.38 | no | 0 | 2 | - |
| CLM-0011 | settled | 44047.63 | 44048 | 0.37 | no | 0 | 0 | - |
| CLM-0012 | settled | 57971.15 | 57971 | 0.15 | no | 0 | 0 | - |
| CLM-0013 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0014 | settled | 62542.71 | 62542 | 0.71 | no | 0 | 0 | - |
| CLM-0015 | settled | 89481.74 | 89481 | 0.74 | no | 0 | 2 | - |
| CLM-0016 | settled | 40825.14 | 40825 | 0.14 | no | 0 | 0 | - |
| CLM-0017 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0018 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0019 | settled | 201962.52 | 201962 | 0.52 | no | 0 | 0 | - |
| CLM-0020 | settled | 71833.40 | 71833 | 0.40 | no | 0 | 0 | - |
| CLM-0021 | settled | 59850.00 | 38000 | 21850.00 | yes | 1 | 0 | - |
| CLM-0022 | settled | 32300.00 | 14250 | 18050.00 | yes | 1 | 0 | - |
