# Reflexion experiment: 20 development claims

## Development claims
| metric | before | after |
|---|---|---|
| settlement_error_total_rs | 112102.91 | 112102.91 |
| settlement_error_mean_rs | 5095.59 | 5095.59 |
| exact_match_rate | 0.864 | 0.864 |
| edit_rate | 0.136 | 0.136 |
| critic_rejection_rate | 0.182 | 0.182 |

## Lessons that made results worse (withdrawn)
- none

Frozen playbook hash: `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945`

## Run details

mode: REAL MODEL via OpenRouter | executor: local | calculator: reference | tolerance: Rs 1 | approval: CONSOLE

- development cases: 22 from `eval/golden_dev`
- rounding tolerance: Rs 1 (0 = strict; rupee error is exact either way)
- lessons proposed 16, approved 0, rejected 16, withdrawn after ablation 0
- generated 2026-11-11T20:55:14.539451+00:00

## Baseline: where the error comes from

- exact match: 7 cases
- rounding only (error under Rs 1): 12 cases (CLM-0004, CLM-0005, CLM-0006, CLM-0009, CLM-0010, CLM-0011, CLM-0012, CLM-0014, CLM-0015, CLM-0016, CLM-0019, CLM-0020)
- real disagreement (Rs 1 or more): 3 cases (CLM-0008, CLM-0021, CLM-0022)

## Spread across the 2 after-pass run(s)

| metric | min | max |
|---|---|---|
| settlement_error_total_rs | 112102.91 | 112102.91 |
| settlement_error_mean_rs | 5095.59 | 5095.59 |
| exact_match_rate | 0.864 | 0.864 |
| edit_rate | 0.136 | 0.136 |
| critic_rejection_rate | 0.182 | 0.182 |

## After pass, run 1

| metric | before | after |
|---|---|---|
| settlement_error_total_rs | 112102.91 | 112102.91 |
| settlement_error_mean_rs | 5095.59 | 5095.59 |
| exact_match_rate | 0.864 | 0.864 |
| edit_rate | 0.136 | 0.136 |
| critic_rejection_rate | 0.182 | 0.182 |

- exact match: 7 cases
- rounding only (error under Rs 1): 12 cases (CLM-0004, CLM-0005, CLM-0006, CLM-0009, CLM-0010, CLM-0011, CLM-0012, CLM-0014, CLM-0015, CLM-0016, CLM-0019, CLM-0020)
- real disagreement (Rs 1 or more): 3 cases (CLM-0008, CLM-0021, CLM-0022)

## After pass, run 2

| metric | before | after |
|---|---|---|
| settlement_error_total_rs | 112102.91 | 112102.91 |
| settlement_error_mean_rs | 5095.59 | 5095.59 |
| exact_match_rate | 0.864 | 0.864 |
| edit_rate | 0.136 | 0.136 |
| critic_rejection_rate | 0.182 | 0.182 |

- exact match: 7 cases
- rounding only (error under Rs 1): 12 cases (CLM-0004, CLM-0005, CLM-0006, CLM-0009, CLM-0010, CLM-0011, CLM-0012, CLM-0014, CLM-0015, CLM-0016, CLM-0019, CLM-0020)
- real disagreement (Rs 1 or more): 3 cases (CLM-0008, CLM-0021, CLM-0022)

## All lessons and their review status

| lesson | status | reviewer | note | text | applies when | clauses | from case |
|---|---|---|---|---|---|---|---|
| LSN-347a7fbf | rejected | Dhruvi Ramani | duplicate-line deduction is made by the calculator under clause 2 (DEC-04), not a clause choice; lesson is vague | Verify that the clause explicitly permits the specific type of deduction before applying it (new_india_arogya_sanjeevani:2). | When processing deductions under the investigations category for Arogya Sanjeevani policy claims. | new_india_arogya_sanjeevani:2 | CLM-0005 |
| LSN-72f035ed | rejected | Dhruvi Ramani | duplicate of rejected lesson; duplicate-line deduction is calculator rule under clause 2 (DEC-04), not a clause choice | Verify that the clause explicitly permits the specific deduction type before applying it (new_india_arogya_sanjeevani:2). | When processing deductions under the investigations category for Arogya Sanjeevani policy claims. | new_india_arogya_sanjeevani:2 | CLM-0005 |
| LSN-dcdd3e06 | rejected | Dhruvi Ramani | specific waiting period is admissibility code (6.2 list missing, AGT-02), not a clause choice; lesson would misapply 6.2 to every procedure line | Check that procedure category claims are adjudicated under clause 6.2, which specifies the applicable waiting period, rather than clause 4.1. | When adjudicating procedure category claims under the Arogya Sanjeevani policy. | new_india_arogya_sanjeevani:6.2 | CLM-0008 |
| LSN-ea2aeb53 | rejected | Dhruvi Ramani | 6.2 waiting period is admissibility code, not a per-line clause; would wrongly cite 6.2 on every room line | Verify the correct clause governing the room category before adjudication, specifically apply clause 6.2 for room-related claims under the Arogya Sanjeevani policy. | When adjudicating room category bill lines under the Arogya Sanjeevani policy. | new_india_arogya_sanjeevani:6.2 | CLM-0008 |
| LSN-40d021e6 | rejected | Dhruvi Ramani | 6.2 waiting period is admissibility code, not a per-line clause; would wrongly cite 6.2 on every nursing line | Check that nursing bill lines are adjudicated under clause 6.2 as specified in the Arogya Sanjeevani policy. | When adjudicating nursing bill line categories under the Arogya Sanjeevani policy. | new_india_arogya_sanjeevani:6.2 | CLM-0008 |
| LSN-c3f47b16 | rejected | Dhruvi Ramani | 6.2 waiting period is admissibility code, not a per-line clause; would wrongly cite 6.2 on every medicines line | Check for specified illness waiting periods under clause 6.2 before approving medicines claims. | When adjudicating medicines category claims under the Arogya Sanjeevani policy. | new_india_arogya_sanjeevani:6.2 | CLM-0008 |
| LSN-f5989787 | rejected | Dhruvi Ramani | 6.2 waiting period is admissibility code, not a per-line clause; would wrongly cite 6.2 on every investigations line | Check the applicable clause for investigations category claims and apply clause 6.2 for specified illness waiting periods under the Arogya Sanjeevani policy. | When adjudicating investigations category claims under the Arogya Sanjeevani policy. | new_india_arogya_sanjeevani:6.2 | CLM-0008 |
| LSN-e48b3e25 | rejected | Dhruvi Ramani | vague, applies to everything, invented clause id; admissibility is deterministic code | Verify claim admissibility criteria as specified in the Arogya Sanjeevani policy before approving any claim. | All health insurance claims under the Arogya Sanjeevani policy. | Admissibility Criteria | CLM-0008 |
| LSN-ddf29848 | rejected | Dhruvi Ramani | duplicate-line deduction is a calculator rule under clause 2 (DEC-04), not a clause choice; vague | Verify that the clause explicitly permits deductions of the 'other' type before applying them (new_india_arogya_sanjeevani:2). | When processing investigations category bill lines under the Arogya Sanjeevani policy. | new_india_arogya_sanjeevani:2 | CLM-0009 |
| LSN-8801151d | rejected | Dhruvi Ramani | duplicate of rejected lesson; duplicate-line deduction is a calculator rule under clause 2 (DEC-04), not a clause choice | Verify that the clause explicitly permits deductions of the 'other' type before applying them (new_india_arogya_sanjeevani:2). | When processing investigations category bill lines under the Arogya Sanjeevani policy. | new_india_arogya_sanjeevani:2 | CLM-0009 |
| LSN-2e80cde1 | rejected | Dhruvi Ramani | duplicate-line deduction is a calculator rule under clause 2 (DEC-04), not a clause choice; vague | Verify that the clause explicitly supports the type of deduction being applied before deducting any amount (new_india_arogya_sanjeevani:2). | When processing investigations category claims under the Arogya Sanjeevani policy. | new_india_arogya_sanjeevani:2 | CLM-0010 |
| LSN-7a0d86b4 | rejected | Dhruvi Ramani | duplicate of rejected lesson; duplicate-line deduction is a calculator rule under clause 2 (DEC-04), not a clause choice | Verify that the clause explicitly permits the specific type of deduction before applying it (new_india_arogya_sanjeevani:2). | When processing deductions under the investigations category for Arogya Sanjeevani policy claims. | new_india_arogya_sanjeevani:2 | CLM-0010 |
| LSN-83788bbf | rejected | Dhruvi Ramani | duplicate-line deduction is a calculator rule under clause 2 (DEC-04), not a clause choice; vague | Verify that the clause explicitly permits the specific type of deduction before applying it (Arogya Sanjeevani clause 2). | When processing deductions under the investigations category for Arogya Sanjeevani policy claims. | new_india_arogya_sanjeevani:2 | CLM-0015 |
| LSN-62b49014 | rejected | Dhruvi Ramani | duplicate of rejected lesson; duplicate-line deduction is a calculator rule under clause 2 (DEC-04), not a clause choice | Verify that the clause explicitly supports the type of deduction being applied before deducting any amount (new_india_arogya_sanjeevani:2). | When processing deductions under the investigations category for Arogya Sanjeevani policy claims. | new_india_arogya_sanjeevani:2 | CLM-0015 |
| LSN-580262d9 | rejected | Dhruvi Ramani | too broad: 4.3 is the cataract sub-limit, not every procedure; and 4.3 is informational in the calculator, so the lesson cannot change the amount | For procedure category claims under the Arogya Sanjeevani policy, verify and apply clause 4.3 as the governing clause. | When adjudicating procedure category bill lines under the Arogya Sanjeevani policy. | new_india_arogya_sanjeevani:4.3 | CLM-0021 |
| LSN-ee794076 | rejected | Dhruvi Ramani | too broad: 4.3 is the cataract sub-limit, not every procedure; 4.3 is informational in the calculator, so the lesson cannot  change the amount | For procedure category claims under the Arogya Sanjeevani policy, verify and apply clause 4.3 as the governing clause, not clause 4.1. | When adjudicating procedure category bill lines under the Arogya Sanjeevani policy. | new_india_arogya_sanjeevani:4.3 | CLM-0022 |

## Ablation table (leave one lesson out)

| lesson | harmful | error increase Rs | edit-rate increase | text |
|---|---|---|---|---|

## Known gold vs calculator rule disagreements (not fixable by any lesson)

- Gold rounds each cut line to whole rupees; the calculator keeps paise. Cut lines differ by up to Rs 0.50 and count as a miss unless the evaluator is run with a tolerance (--tolerance-rs). ADR-0007 (GOLD-08): the gold stays in rupees; the eval harness defaults to a Rs 1 tolerance, the Reflexion evaluator keeps it explicit.
- Gold (ADR-0007, GOLD-03) repudiates CLM-0008 under the 24-month specific wait (clause 6.2.18, urinary calculi, first policy); the admissibility check has no 6.2 list yet (AGT-02), so the pipeline pays it.
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
| CLM-0008 | settled | 72198.11 | 0 | 72198.11 | yes | 5 | 0 | - |
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
| CLM-0008 | settled | 72198.11 | 0 | 72198.11 | yes | 5 | 0 | - |
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
| CLM-0008 | settled | 72198.11 | 0 | 72198.11 | yes | 5 | 0 | - |
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
