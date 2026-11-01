# Reflexion experiment: 20 development claims

## Development claims
| metric | before | after |
|---|---|---|
| settlement_error_total_rs | 65989.27 | 65989.27 |
| settlement_error_mean_rs | 3299.46 | 3299.46 |
| exact_match_rate | 0.3 | 0.3 |
| edit_rate | 0.2 | 0.2 |
| critic_rejection_rate | 0.0 | 0.0 |

## Lessons that made results worse (withdrawn)
- none

Frozen playbook hash: `6b4c530d988ac0615a32c258af3968d54475de1bc0dcce98edb2e20de14559b7`

## Run details

mode: REAL MODEL via OpenRouter | executor: local | calculator: reference | approval: CONSOLE

- development cases: 20 from `eval/golden_dev`
- lessons proposed 14, approved 2, rejected 12, withdrawn after ablation 0
- generated 2026-11-01T16:33:10.684908+00:00

## Baseline: where the error comes from

- exact match: 6 cases
- rounding only (error under Rs 1): 6 cases (CLM-0006, CLM-0008, CLM-0016, CLM-0018, CLM-0019, CLM-0020)
- real disagreement (Rs 1 or more): 8 cases (CLM-0004, CLM-0005, CLM-0009, CLM-0010, CLM-0011, CLM-0012, CLM-0014, CLM-0015)

## Spread across the 2 after-pass run(s)

| metric | min | max |
|---|---|---|
| settlement_error_total_rs | 65989.27 | 65989.27 |
| settlement_error_mean_rs | 3299.46 | 3299.46 |
| exact_match_rate | 0.3 | 0.3 |
| edit_rate | 0.2 | 0.2 |
| critic_rejection_rate | 0.0 | 0.0 |

## After pass, run 1

| metric | before | after |
|---|---|---|
| settlement_error_total_rs | 65989.27 | 65989.27 |
| settlement_error_mean_rs | 3299.46 | 3299.46 |
| exact_match_rate | 0.3 | 0.3 |
| edit_rate | 0.2 | 0.2 |
| critic_rejection_rate | 0.0 | 0.0 |

- exact match: 6 cases
- rounding only (error under Rs 1): 6 cases (CLM-0006, CLM-0008, CLM-0016, CLM-0018, CLM-0019, CLM-0020)
- real disagreement (Rs 1 or more): 8 cases (CLM-0004, CLM-0005, CLM-0009, CLM-0010, CLM-0011, CLM-0012, CLM-0014, CLM-0015)

## After pass, run 2

| metric | before | after |
|---|---|---|
| settlement_error_total_rs | 65989.27 | 65989.27 |
| settlement_error_mean_rs | 3299.46 | 3299.46 |
| exact_match_rate | 0.3 | 0.3 |
| edit_rate | 0.2 | 0.2 |
| critic_rejection_rate | 0.0 | 0.0 |

- exact match: 6 cases
- rounding only (error under Rs 1): 6 cases (CLM-0006, CLM-0008, CLM-0016, CLM-0018, CLM-0019, CLM-0020)
- real disagreement (Rs 1 or more): 8 cases (CLM-0004, CLM-0005, CLM-0009, CLM-0010, CLM-0011, CLM-0012, CLM-0014, CLM-0015)

## All lessons and their review status

| lesson | status | reviewer | note | text | applies when | clauses | from case |
|---|---|---|---|---|---|---|---|
| LSN-30d9c04f | rejected | Dhruvi Ramani | contradicts clause 4.1.1 Note b: procedure charges are "other expenses" and are subject to the proportional cut; gold reading not agreed with domain lead | Verify that procedure category claims are adjudicated under clause 4.1, not its sub-clauses like 4.1.1, as per the Arogya Sanjeevani policy. | When adjudicating procedure category bill lines under the Arogya Sanjeevani policy. | new_india_arogya_sanjeevani:4.1 | CLM-0004 |
| LSN-47e092b0 | approved | Dhruvi Ramani | - | Check if room or ICU rates exceed policy limits and apply proportional deduction to all expenses except medicines as per clause 4.1.1 Note b. | When adjudicating medicine bill lines under the Arogya Sanjeevani policy with room or ICU rates exceeding limits. | new_india_arogya_sanjeevani:4.1.1 | CLM-0004 |
| LSN-e90ad757 | rejected | Dhruvi Ramani | not actionable for clause selection: rounding is done by the calculator; the difference is the gold file rounding to whole rupees | Apply proportional deduction exactly as per clause 4.1.1 Note b without rounding amounts prematurely when room/ICU rates exceed limits. | When room or ICU rates exceed policy limits under investigations category. | new_india_arogya_sanjeevani:4.1.1 | CLM-0004 |
| LSN-99d83f2a | rejected | Dhruvi Ramani | vague and cites a non-existent clause id; the mistake was an in-bill duplicate line, a fraud finding, not a clause choice | Always confirm coverage applicability for the investigations category as per the Arogya Sanjeevani policy clauses before processing claims. | When adjudicating claims under the investigations bill line category for the Arogya Sanjeevani policy. | Arogya Sanjeevani Investigations Coverage Clause | CLM-0005 |
| LSN-aadc9136 | rejected | Dhruvi Ramani | vague and cites a non-existent clause id; the mistake was an in-bill duplicate line, a fraud finding, not a clause choice | Always confirm coverage applicability for the 'investigations' bill line category as specified in the Arogya Sanjeevani policy clauses before processing the claim. | When adjudicating claims with bill line category 'investigations' under the Arogya Sanjeevani policy. | Arogya Sanjeevani Investigations Coverage Clause | CLM-0009 |
| LSN-ad720734 | rejected | Dhruvi Ramani | vague and cites a non-existent clause id; the mistake was an in-bill duplicate line, a fraud finding, not a clause choice | Always confirm coverage applicability for the 'investigations' bill line category as specified in the Arogya Sanjeevani policy clauses before processing payment. | When adjudicating claims with bill line category 'investigations' under the Arogya Sanjeevani policy. | None | CLM-0010 |
| LSN-1b0890dc | rejected | Dhruvi Ramani | contradicts clause 4.1.1 Note b: procedure charges are "other expenses" subject to the proportional cut; gold reading not agreed with domain lead | Verify that procedure category claims are adjudicated under clause 4.1 as specified in the Arogya Sanjeevani policy before considering any sub-clauses. | When adjudicating procedure category bill lines under the Arogya Sanjeevani policy. | new_india_arogya_sanjeevani:4.1 | CLM-0011 |
| LSN-d69e9593 | rejected | Dhruvi Ramani | not actionable for clause selection: rounding is done by the calculator; the gold rounds to whole rupees | Apply proportional deductions exactly as specified in clause 4.1.1 Note b without rounding amounts prematurely. | When room or ICU rates exceed policy limits under investigations category. | new_india_arogya_sanjeevani:4.1.1 | CLM-0011 |
| LSN-2a7a2cf8 | rejected | Dhruvi Ramani | contradicts clause 4.1.1 Note b: procedure charges are subject to the proportional cut; gold reading not agreed with domain lead | Verify that procedure category claims are adjudicated under clause 4.1 as specified in the Arogya Sanjeevani policy before considering any sub-clauses. | When adjudicating procedure category bill lines under the Arogya Sanjeevani policy. | new_india_arogya_sanjeevani:4.1 | CLM-0012 |
| LSN-3e9c456b | approved | Dhruvi Ramani | - | When the room or ICU rate exceeds the policy limits, apply proportional deduction to all expenses except medicines as specified in clause 4.1.1 Note b. | Claims involving nursing or room charges where the room or ICU rate exceeds the policy limits under the Arogya Sanjeevani policy. | new_india_arogya_sanjeevani:4.1.1 | CLM-0012 |
| LSN-48602e95 | rejected | Dhruvi Ramani | contradicts clause 4.1.1 Note b: procedure charges are subject to the proportional cut; gold reading not agreed with domain lead | Check that procedure category claims are adjudicated under clause 4.1 before considering any sub-clauses like 4.1.1. | When adjudicating procedure category bill lines under the Arogya Sanjeevani policy. | new_india_arogya_sanjeevani:4.1 | CLM-0014 |
| LSN-e42ab612 | rejected | Dhruvi Ramani | omits the medicines exception in clause 4.1.1 Note b; duplicate of the approved lesson that states it correctly | Check for proportional deduction rules under clause 4.1.1 when room or ICU rates exceed policy limits before applying other expense payments. | When adjudicating medicine bills under the Arogya Sanjeevani policy with room or ICU rates exceeding allowed limits. | new_india_arogya_sanjeevani:4.1.1 | CLM-0014 |
| LSN-9b81c322 | rejected | Dhruvi Ramani | duplicate of an approved lesson (same rule, same clause, nursing lines) | Check that when the room or ICU rate exceeds the policy limits, all other expenses except medicines are proportionally reduced according to clause 4.1.1 Note b. | When the room or ICU rate exceeds the policy limits in nursing bill line categories. | new_india_arogya_sanjeevani:4.1.1 | CLM-0014 |
| LSN-dd440297 | rejected | Dhruvi Ramani | vague and cites a non-existent clause id; duplicate line is a fraud finding, not a clause choice | Always confirm coverage applicability for the 'investigations' bill line category as specified in the Arogya Sanjeevani policy clauses before processing payment. | When adjudicating claims with bill line category 'investigations' under the Arogya Sanjeevani policy. | Arogya Sanjeevani Investigations Coverage Clause | CLM-0015 |

## Ablation table (leave one lesson out)

| lesson | harmful | error increase Rs | edit-rate increase | text |
|---|---|---|---|---|
| LSN-47e092b0 | no | 0.00 | 0.0 | Check if room or ICU rates exceed policy limits and apply proportional deduction to all expenses except medicines as per clause 4.1.1 Note b. |
| LSN-3e9c456b | no | 0.00 | 0.0 | When the room or ICU rate exceeds the policy limits, apply proportional deduction to all expenses except medicines as specified in clause 4.1.1 Note b. |

## Known gold vs calculator rule disagreements (not fixable by any lesson)

- Gold applies the room-rent proportional cut to pharmacy lines (room_linked=true); the calculator exempts medicines, following clause 4.1.1 Note (b). Affects every admissible room_rent_breach case.
- Gold deducts an in-bill duplicate line in full (duplicate_line); the fraud agent only checks claim history and a fraud flag never changes an amount. Affects every admissible duplicate_bill case.
- Gold rounds each cut line to whole rupees; the calculator keeps paise. Cut lines can differ by up to Rs 0.50, which the simulated adjudicator counts as an edit.

## Per case: baseline

| case | status | proposed Rs | gold Rs | abs error Rs | edited | lines edited | critic rejections | lessons used |
|---|---|---|---|---|---|---|---|---|
| CLM-0001 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0002 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0003 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0004 | settled | 80990.23 | 102313 | 21322.77 | yes | 2 | 0 | - |
| CLM-0005 | settled | 103940.45 | 96660 | 7280.45 | no | 0 | 0 | - |
| CLM-0006 | settled | 71374.45 | 71374 | 0.45 | no | 0 | 0 | - |
| CLM-0007 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0008 | settled | 79842.75 | 79843 | 0.25 | no | 0 | 0 | - |
| CLM-0009 | settled | 76604.20 | 73664 | 2940.20 | no | 0 | 0 | - |
| CLM-0010 | settled | 144884.50 | 141867 | 3017.50 | no | 0 | 0 | - |
| CLM-0011 | settled | 57184.61 | 60741 | 3556.39 | yes | 2 | 0 | - |
| CLM-0012 | settled | 67575.39 | 78511 | 10935.61 | yes | 2 | 0 | - |
| CLM-0013 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0014 | settled | 74629.15 | 85136 | 10506.85 | yes | 2 | 0 | - |
| CLM-0015 | settled | 114515.85 | 108088 | 6427.85 | no | 0 | 0 | - |
| CLM-0016 | settled | 73089.20 | 73089 | 0.20 | no | 0 | 0 | - |
| CLM-0017 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0018 | settled | 111406.50 | 111406 | 0.50 | no | 0 | 0 | - |
| CLM-0019 | settled | 255800.80 | 255801 | 0.20 | no | 0 | 0 | - |
| CLM-0020 | settled | 78242.95 | 78243 | 0.05 | no | 0 | 0 | - |

## Per case: after pass, run 1

| case | status | proposed Rs | gold Rs | abs error Rs | edited | lines edited | critic rejections | lessons used |
|---|---|---|---|---|---|---|---|---|
| CLM-0001 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0002 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0003 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0004 | settled | 80990.23 | 102313 | 21322.77 | yes | 2 | 0 | LSN-3e9c456b, LSN-47e092b0 |
| CLM-0005 | settled | 103940.45 | 96660 | 7280.45 | no | 0 | 0 | LSN-3e9c456b, LSN-47e092b0 |
| CLM-0006 | settled | 71374.45 | 71374 | 0.45 | no | 0 | 0 | LSN-3e9c456b, LSN-47e092b0 |
| CLM-0007 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0008 | settled | 79842.75 | 79843 | 0.25 | no | 0 | 0 | LSN-3e9c456b, LSN-47e092b0 |
| CLM-0009 | settled | 76604.20 | 73664 | 2940.20 | no | 0 | 0 | LSN-3e9c456b, LSN-47e092b0 |
| CLM-0010 | settled | 144884.50 | 141867 | 3017.50 | no | 0 | 0 | LSN-3e9c456b, LSN-47e092b0 |
| CLM-0011 | settled | 57184.61 | 60741 | 3556.39 | yes | 2 | 0 | LSN-3e9c456b, LSN-47e092b0 |
| CLM-0012 | settled | 67575.39 | 78511 | 10935.61 | yes | 2 | 0 | LSN-3e9c456b, LSN-47e092b0 |
| CLM-0013 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0014 | settled | 74629.15 | 85136 | 10506.85 | yes | 2 | 0 | LSN-3e9c456b, LSN-47e092b0 |
| CLM-0015 | settled | 114515.85 | 108088 | 6427.85 | no | 0 | 0 | LSN-3e9c456b, LSN-47e092b0 |
| CLM-0016 | settled | 73089.20 | 73089 | 0.20 | no | 0 | 0 | LSN-3e9c456b, LSN-47e092b0 |
| CLM-0017 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0018 | settled | 111406.50 | 111406 | 0.50 | no | 0 | 0 | LSN-3e9c456b, LSN-47e092b0 |
| CLM-0019 | settled | 255800.80 | 255801 | 0.20 | no | 0 | 0 | LSN-3e9c456b, LSN-47e092b0 |
| CLM-0020 | settled | 78242.95 | 78243 | 0.05 | no | 0 | 0 | LSN-3e9c456b, LSN-47e092b0 |

## Per case: after pass, run 2

| case | status | proposed Rs | gold Rs | abs error Rs | edited | lines edited | critic rejections | lessons used |
|---|---|---|---|---|---|---|---|---|
| CLM-0001 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0002 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0003 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0004 | settled | 80990.23 | 102313 | 21322.77 | yes | 2 | 0 | LSN-3e9c456b, LSN-47e092b0 |
| CLM-0005 | settled | 103940.45 | 96660 | 7280.45 | no | 0 | 0 | LSN-3e9c456b, LSN-47e092b0 |
| CLM-0006 | settled | 71374.45 | 71374 | 0.45 | no | 0 | 0 | LSN-3e9c456b, LSN-47e092b0 |
| CLM-0007 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0008 | settled | 79842.75 | 79843 | 0.25 | no | 0 | 0 | LSN-3e9c456b, LSN-47e092b0 |
| CLM-0009 | settled | 76604.20 | 73664 | 2940.20 | no | 0 | 0 | LSN-3e9c456b, LSN-47e092b0 |
| CLM-0010 | settled | 144884.50 | 141867 | 3017.50 | no | 0 | 0 | LSN-3e9c456b, LSN-47e092b0 |
| CLM-0011 | settled | 57184.61 | 60741 | 3556.39 | yes | 2 | 0 | LSN-3e9c456b, LSN-47e092b0 |
| CLM-0012 | settled | 67575.39 | 78511 | 10935.61 | yes | 2 | 0 | LSN-3e9c456b, LSN-47e092b0 |
| CLM-0013 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0014 | settled | 74629.15 | 85136 | 10506.85 | yes | 2 | 0 | LSN-3e9c456b, LSN-47e092b0 |
| CLM-0015 | settled | 114515.85 | 108088 | 6427.85 | no | 0 | 0 | LSN-3e9c456b, LSN-47e092b0 |
| CLM-0016 | settled | 73089.20 | 73089 | 0.20 | no | 0 | 0 | LSN-3e9c456b, LSN-47e092b0 |
| CLM-0017 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0018 | settled | 111406.50 | 111406 | 0.50 | no | 0 | 0 | LSN-3e9c456b, LSN-47e092b0 |
| CLM-0019 | settled | 255800.80 | 255801 | 0.20 | no | 0 | 0 | LSN-3e9c456b, LSN-47e092b0 |
| CLM-0020 | settled | 78242.95 | 78243 | 0.05 | no | 0 | 0 | LSN-3e9c456b, LSN-47e092b0 |
