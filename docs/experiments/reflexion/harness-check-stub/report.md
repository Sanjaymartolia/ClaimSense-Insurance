# Reflexion experiment: 20 development claims

> **HARNESS CHECK ONLY.** Lessons were auto-approved. These numbers must not be reported; re-run with `--approve console`.

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

Frozen playbook hash: `04349f400380f8cd1f5a6118fdb6a9ddf08b5f99797a3303b402e1a340ae80e0`

## Run details

mode: STUB (deterministic, no model) | executor: local | calculator: reference | approval: AUTO (harness check only, NOT for the report)

- development cases: 20 from `eval/golden_dev`
- lessons proposed 3, approved 3, rejected 0, withdrawn after ablation 0
- generated 2026-11-01T13:38:23.115209+00:00

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
| LSN-1c523724 | approved | AUTO-harness-check | auto-approved (harness check) | For procedure lines, check clause new_india_arogya_sanjeevani:4.1 before new_india_arogya_sanjeevani:4.1. | procedure line on the bill | new_india_arogya_sanjeevani:4.1, new_india_arogya_sanjeevani:4.1 | CLM-0004 |
| LSN-2c44a77f | approved | AUTO-harness-check | auto-approved (harness check) | For medicines lines, check clause new_india_arogya_sanjeevani:4.1.1 before new_india_arogya_sanjeevani:4.1. | medicines line on the bill | new_india_arogya_sanjeevani:4.1.1, new_india_arogya_sanjeevani:4.1 | CLM-0004 |
| LSN-579e6248 | approved | AUTO-harness-check | auto-approved (harness check) | For investigations lines, check clause new_india_arogya_sanjeevani:4.1.1 before new_india_arogya_sanjeevani:4.1.1. | investigations line on the bill | new_india_arogya_sanjeevani:4.1.1, new_india_arogya_sanjeevani:4.1.1 | CLM-0004 |

## Ablation table (leave one lesson out)

| lesson | harmful | error increase Rs | edit-rate increase | text |
|---|---|---|---|---|
| LSN-1c523724 | no | 0.00 | 0.0 | For procedure lines, check clause new_india_arogya_sanjeevani:4.1 before new_india_arogya_sanjeevani:4.1. |
| LSN-2c44a77f | no | 0.00 | 0.0 | For medicines lines, check clause new_india_arogya_sanjeevani:4.1.1 before new_india_arogya_sanjeevani:4.1. |
| LSN-579e6248 | no | 0.00 | 0.0 | For investigations lines, check clause new_india_arogya_sanjeevani:4.1.1 before new_india_arogya_sanjeevani:4.1.1. |

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
| CLM-0004 | settled | 80990.23 | 102313 | 21322.77 | yes | 2 | 0 | LSN-2c44a77f, LSN-1c523724, LSN-579e6248 |
| CLM-0005 | settled | 103940.45 | 96660 | 7280.45 | no | 0 | 0 | LSN-2c44a77f, LSN-1c523724, LSN-579e6248 |
| CLM-0006 | settled | 71374.45 | 71374 | 0.45 | no | 0 | 0 | LSN-2c44a77f, LSN-1c523724, LSN-579e6248 |
| CLM-0007 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0008 | settled | 79842.75 | 79843 | 0.25 | no | 0 | 0 | LSN-2c44a77f, LSN-1c523724, LSN-579e6248 |
| CLM-0009 | settled | 76604.20 | 73664 | 2940.20 | no | 0 | 0 | LSN-2c44a77f, LSN-1c523724, LSN-579e6248 |
| CLM-0010 | settled | 144884.50 | 141867 | 3017.50 | no | 0 | 0 | LSN-2c44a77f, LSN-1c523724, LSN-579e6248 |
| CLM-0011 | settled | 57184.61 | 60741 | 3556.39 | yes | 2 | 0 | LSN-2c44a77f, LSN-1c523724, LSN-579e6248 |
| CLM-0012 | settled | 67575.39 | 78511 | 10935.61 | yes | 2 | 0 | LSN-2c44a77f, LSN-1c523724, LSN-579e6248 |
| CLM-0013 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0014 | settled | 74629.15 | 85136 | 10506.85 | yes | 2 | 0 | LSN-2c44a77f, LSN-1c523724, LSN-579e6248 |
| CLM-0015 | settled | 114515.85 | 108088 | 6427.85 | no | 0 | 0 | LSN-2c44a77f, LSN-1c523724, LSN-579e6248 |
| CLM-0016 | settled | 73089.20 | 73089 | 0.20 | no | 0 | 0 | LSN-2c44a77f, LSN-1c523724, LSN-579e6248 |
| CLM-0017 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0018 | settled | 111406.50 | 111406 | 0.50 | no | 0 | 0 | LSN-2c44a77f, LSN-1c523724, LSN-579e6248 |
| CLM-0019 | settled | 255800.80 | 255801 | 0.20 | no | 0 | 0 | LSN-2c44a77f, LSN-1c523724, LSN-579e6248 |
| CLM-0020 | settled | 78242.95 | 78243 | 0.05 | no | 0 | 0 | LSN-2c44a77f, LSN-1c523724, LSN-579e6248 |

## Per case: after pass, run 2

| case | status | proposed Rs | gold Rs | abs error Rs | edited | lines edited | critic rejections | lessons used |
|---|---|---|---|---|---|---|---|---|
| CLM-0001 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0002 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0003 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0004 | settled | 80990.23 | 102313 | 21322.77 | yes | 2 | 0 | LSN-2c44a77f, LSN-1c523724, LSN-579e6248 |
| CLM-0005 | settled | 103940.45 | 96660 | 7280.45 | no | 0 | 0 | LSN-2c44a77f, LSN-1c523724, LSN-579e6248 |
| CLM-0006 | settled | 71374.45 | 71374 | 0.45 | no | 0 | 0 | LSN-2c44a77f, LSN-1c523724, LSN-579e6248 |
| CLM-0007 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0008 | settled | 79842.75 | 79843 | 0.25 | no | 0 | 0 | LSN-2c44a77f, LSN-1c523724, LSN-579e6248 |
| CLM-0009 | settled | 76604.20 | 73664 | 2940.20 | no | 0 | 0 | LSN-2c44a77f, LSN-1c523724, LSN-579e6248 |
| CLM-0010 | settled | 144884.50 | 141867 | 3017.50 | no | 0 | 0 | LSN-2c44a77f, LSN-1c523724, LSN-579e6248 |
| CLM-0011 | settled | 57184.61 | 60741 | 3556.39 | yes | 2 | 0 | LSN-2c44a77f, LSN-1c523724, LSN-579e6248 |
| CLM-0012 | settled | 67575.39 | 78511 | 10935.61 | yes | 2 | 0 | LSN-2c44a77f, LSN-1c523724, LSN-579e6248 |
| CLM-0013 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0014 | settled | 74629.15 | 85136 | 10506.85 | yes | 2 | 0 | LSN-2c44a77f, LSN-1c523724, LSN-579e6248 |
| CLM-0015 | settled | 114515.85 | 108088 | 6427.85 | no | 0 | 0 | LSN-2c44a77f, LSN-1c523724, LSN-579e6248 |
| CLM-0016 | settled | 73089.20 | 73089 | 0.20 | no | 0 | 0 | LSN-2c44a77f, LSN-1c523724, LSN-579e6248 |
| CLM-0017 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0018 | settled | 111406.50 | 111406 | 0.50 | no | 0 | 0 | LSN-2c44a77f, LSN-1c523724, LSN-579e6248 |
| CLM-0019 | settled | 255800.80 | 255801 | 0.20 | no | 0 | 0 | LSN-2c44a77f, LSN-1c523724, LSN-579e6248 |
| CLM-0020 | settled | 78242.95 | 78243 | 0.05 | no | 0 | 0 | LSN-2c44a77f, LSN-1c523724, LSN-579e6248 |
