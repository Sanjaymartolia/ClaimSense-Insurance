# Reflexion experiment: 20 development claims

> **HARNESS CHECK ONLY.** Lessons were auto-approved. These numbers must not be reported; re-run with `--approve console`.

## Development claims
| metric | before | after |
|---|---|---|
| settlement_error_total_rs | 186368.94 | 186368.94 |
| settlement_error_mean_rs | 9318.45 | 9318.45 |
| exact_match_rate | 0.5 | 0.5 |
| edit_rate | 0.3 | 0.3 |
| critic_rejection_rate | 0.0 | 0.0 |

## Lessons that made results worse (withdrawn)
- none

Frozen playbook hash: `b10b6eb16ee8cac166e7af7c2b3bb472a3ddac9bed24ca258de398337943d6d3`

## Run details

mode: STUB (deterministic, no model) | executor: local | calculator: reference | tolerance: Rs 1 | approval: AUTO (harness check only, NOT for the report)

- development cases: 20 from `eval/golden_dev`
- rounding tolerance: Rs 1 (0 = strict; rupee error is exact either way)
- lessons proposed 6, approved 6, rejected 0, withdrawn after ablation 0
- generated 2026-11-07T10:43:30.684905+00:00

## Baseline: where the error comes from

- exact match: 6 cases
- rounding only (error under Rs 1): 4 cases (CLM-0006, CLM-0008, CLM-0019, CLM-0020)
- real disagreement (Rs 1 or more): 10 cases (CLM-0004, CLM-0005, CLM-0009, CLM-0010, CLM-0011, CLM-0012, CLM-0014, CLM-0015, CLM-0016, CLM-0018)

## Spread across the 2 after-pass run(s)

| metric | min | max |
|---|---|---|
| settlement_error_total_rs | 186368.94 | 186368.94 |
| settlement_error_mean_rs | 9318.45 | 9318.45 |
| exact_match_rate | 0.5 | 0.5 |
| edit_rate | 0.3 | 0.3 |
| critic_rejection_rate | 0.0 | 0.0 |

## After pass, run 1

| metric | before | after |
|---|---|---|
| settlement_error_total_rs | 186368.94 | 186368.94 |
| settlement_error_mean_rs | 9318.45 | 9318.45 |
| exact_match_rate | 0.5 | 0.5 |
| edit_rate | 0.3 | 0.3 |
| critic_rejection_rate | 0.0 | 0.0 |

- exact match: 6 cases
- rounding only (error under Rs 1): 4 cases (CLM-0006, CLM-0008, CLM-0019, CLM-0020)
- real disagreement (Rs 1 or more): 10 cases (CLM-0004, CLM-0005, CLM-0009, CLM-0010, CLM-0011, CLM-0012, CLM-0014, CLM-0015, CLM-0016, CLM-0018)

## After pass, run 2

| metric | before | after |
|---|---|---|
| settlement_error_total_rs | 186368.94 | 186368.94 |
| settlement_error_mean_rs | 9318.45 | 9318.45 |
| exact_match_rate | 0.5 | 0.5 |
| edit_rate | 0.3 | 0.3 |
| critic_rejection_rate | 0.0 | 0.0 |

- exact match: 6 cases
- rounding only (error under Rs 1): 4 cases (CLM-0006, CLM-0008, CLM-0019, CLM-0020)
- real disagreement (Rs 1 or more): 10 cases (CLM-0004, CLM-0005, CLM-0009, CLM-0010, CLM-0011, CLM-0012, CLM-0014, CLM-0015, CLM-0016, CLM-0018)

## All lessons and their review status

| lesson | status | reviewer | note | text | applies when | clauses | from case |
|---|---|---|---|---|---|---|---|
| LSN-5fb19c80 | approved | AUTO-harness-check | auto-approved (harness check) | For procedure lines, check clause new_india_arogya_sanjeevani:4.1 before new_india_arogya_sanjeevani:4.1. | procedure line on the bill | new_india_arogya_sanjeevani:4.1, new_india_arogya_sanjeevani:4.1 | CLM-0004 |
| LSN-05148f18 | approved | AUTO-harness-check | auto-approved (harness check) | For medicines lines, check clause new_india_arogya_sanjeevani:4.1.1 before new_india_arogya_sanjeevani:4.1. | medicines line on the bill | new_india_arogya_sanjeevani:4.1.1, new_india_arogya_sanjeevani:4.1 | CLM-0004 |
| LSN-4f4c8530 | approved | AUTO-harness-check | auto-approved (harness check) | For medicines lines, check clause new_india_arogya_sanjeevani:4.1.1 before new_india_arogya_sanjeevani:4.1.1. | medicines line on the bill | new_india_arogya_sanjeevani:4.1.1, new_india_arogya_sanjeevani:4.1.1 | CLM-0011 |
| LSN-f81330a3 | approved | AUTO-harness-check | auto-approved (harness check) | For procedure lines, check clause new_india_arogya_sanjeevani:7.15 before new_india_arogya_sanjeevani:4.1. | procedure line on the bill | new_india_arogya_sanjeevani:7.15, new_india_arogya_sanjeevani:4.1 | CLM-0018 |
| LSN-aaafa599 | approved | AUTO-harness-check | auto-approved (harness check) | For room lines, check clause new_india_arogya_sanjeevani:7.15 before new_india_arogya_sanjeevani:12.1. | room line on the bill | new_india_arogya_sanjeevani:7.15, new_india_arogya_sanjeevani:12.1 | CLM-0018 |
| LSN-e93d88f7 | approved | AUTO-harness-check | auto-approved (harness check) | For medicines lines, check clause new_india_arogya_sanjeevani:7.15 before new_india_arogya_sanjeevani:4.1.1. | medicines line on the bill | new_india_arogya_sanjeevani:7.15, new_india_arogya_sanjeevani:4.1.1 | CLM-0018 |

## Ablation table (leave one lesson out)

| lesson | harmful | error increase Rs | edit-rate increase | text |
|---|---|---|---|---|
| LSN-5fb19c80 | no | 0.00 | 0.0 | For procedure lines, check clause new_india_arogya_sanjeevani:4.1 before new_india_arogya_sanjeevani:4.1. |
| LSN-05148f18 | no | 0.00 | 0.0 | For medicines lines, check clause new_india_arogya_sanjeevani:4.1.1 before new_india_arogya_sanjeevani:4.1. |
| LSN-4f4c8530 | no | 0.00 | 0.0 | For medicines lines, check clause new_india_arogya_sanjeevani:4.1.1 before new_india_arogya_sanjeevani:4.1.1. |
| LSN-f81330a3 | no | 0.00 | 0.0 | For procedure lines, check clause new_india_arogya_sanjeevani:7.15 before new_india_arogya_sanjeevani:4.1. |
| LSN-aaafa599 | no | 0.00 | 0.0 | For room lines, check clause new_india_arogya_sanjeevani:7.15 before new_india_arogya_sanjeevani:12.1. |
| LSN-e93d88f7 | no | 0.00 | 0.0 | For medicines lines, check clause new_india_arogya_sanjeevani:7.15 before new_india_arogya_sanjeevani:4.1.1. |

## Known gold vs calculator rule disagreements (not fixable by any lesson)

- Gold applies the room-rent proportional cut to pharmacy lines (room_linked=true) and not to the procedure line; the calculator does the opposite, following clause 4.1.1 Note (b). CLM-0004, 0011, 0012, 0014. Decision (lead, 6 Nov 2026): the gold is not relabelled for now because a relabel affects every other owner's scores; the mapping stays and the gap is reported.
- Gold deducts an in-bill duplicate line in full (duplicate_line); the fraud agent only checks claim history and a fraud flag never changes an amount. CLM-0005, 0009, 0010, 0015. Decision (lead, 6 Nov 2026): a duplicate stays a fraud flag for the human adjudicator; no clause pays it at zero.
- Gold rounds each cut line to whole rupees; the calculator keeps paise. Cut lines differ by up to Rs 0.50 and count as a miss unless the evaluator is run with a tolerance (--tolerance-rs). Decision (lead, 6 Nov 2026): the tolerance lives in the Reflexion evaluator, the gold is not changed.
- Gold (2026-11-04 audit, GOLD-01) repudiates CLM-0018, a caesarean section, under clause 7.15; the coverage analyst's admissibility check has no exclusion rule yet (AGT-02, orchestration owner), so the pipeline still pays it. Admissibility is deterministic code, not a clause choice, so no lesson can fix this.
- Gold (2026-11-04 audit, GOLD-04) caps CLM-0016's ICU day at Rs 10,000 but applies no proportional cut to the other lines because the room rent itself is within its cap; the calculator applies clause 4.1.1 Note (b) to an ICU breach as well, so it cuts investigations and nursing. Both cap the ICU line identically. Needs a domain ruling: does Note (b) follow an ICU breach or only a room-rent breach?

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
| CLM-0016 | settled | 50372.13 | 59346 | 8973.87 | yes | 2 | 0 | - |
| CLM-0017 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0018 | settled | 111406.50 | 0 | 111406.50 | yes | 5 | 0 | - |
| CLM-0019 | settled | 255800.80 | 255801 | 0.20 | no | 0 | 0 | - |
| CLM-0020 | settled | 78242.95 | 78243 | 0.05 | no | 0 | 0 | - |

## Per case: after pass, run 1

| case | status | proposed Rs | gold Rs | abs error Rs | edited | lines edited | critic rejections | lessons used |
|---|---|---|---|---|---|---|---|---|
| CLM-0001 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0002 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0003 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0004 | settled | 80990.23 | 102313 | 21322.77 | yes | 2 | 0 | LSN-05148f18, LSN-4f4c8530, LSN-aaafa599 |
| CLM-0005 | settled | 103940.45 | 96660 | 7280.45 | no | 0 | 0 | LSN-05148f18, LSN-4f4c8530, LSN-aaafa599 |
| CLM-0006 | settled | 71374.45 | 71374 | 0.45 | no | 0 | 0 | LSN-05148f18, LSN-4f4c8530, LSN-aaafa599 |
| CLM-0007 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0008 | settled | 79842.75 | 79843 | 0.25 | no | 0 | 0 | LSN-05148f18, LSN-4f4c8530, LSN-aaafa599 |
| CLM-0009 | settled | 76604.20 | 73664 | 2940.20 | no | 0 | 0 | LSN-05148f18, LSN-4f4c8530, LSN-aaafa599 |
| CLM-0010 | settled | 144884.50 | 141867 | 3017.50 | no | 0 | 0 | LSN-05148f18, LSN-4f4c8530, LSN-aaafa599 |
| CLM-0011 | settled | 57184.61 | 60741 | 3556.39 | yes | 2 | 0 | LSN-05148f18, LSN-4f4c8530, LSN-aaafa599 |
| CLM-0012 | settled | 67575.39 | 78511 | 10935.61 | yes | 2 | 0 | LSN-05148f18, LSN-4f4c8530, LSN-aaafa599 |
| CLM-0013 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0014 | settled | 74629.15 | 85136 | 10506.85 | yes | 2 | 0 | LSN-05148f18, LSN-4f4c8530, LSN-aaafa599 |
| CLM-0015 | settled | 114515.85 | 108088 | 6427.85 | no | 0 | 0 | LSN-05148f18, LSN-4f4c8530, LSN-aaafa599 |
| CLM-0016 | settled | 50372.13 | 59346 | 8973.87 | yes | 2 | 0 | LSN-05148f18, LSN-4f4c8530, LSN-5fb19c80 |
| CLM-0017 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0018 | settled | 111406.50 | 0 | 111406.50 | yes | 5 | 0 | LSN-05148f18, LSN-4f4c8530, LSN-aaafa599 |
| CLM-0019 | settled | 255800.80 | 255801 | 0.20 | no | 0 | 0 | LSN-05148f18, LSN-4f4c8530, LSN-aaafa599 |
| CLM-0020 | settled | 78242.95 | 78243 | 0.05 | no | 0 | 0 | LSN-05148f18, LSN-4f4c8530, LSN-aaafa599 |

## Per case: after pass, run 2

| case | status | proposed Rs | gold Rs | abs error Rs | edited | lines edited | critic rejections | lessons used |
|---|---|---|---|---|---|---|---|---|
| CLM-0001 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0002 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0003 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0004 | settled | 80990.23 | 102313 | 21322.77 | yes | 2 | 0 | LSN-05148f18, LSN-4f4c8530, LSN-aaafa599 |
| CLM-0005 | settled | 103940.45 | 96660 | 7280.45 | no | 0 | 0 | LSN-05148f18, LSN-4f4c8530, LSN-aaafa599 |
| CLM-0006 | settled | 71374.45 | 71374 | 0.45 | no | 0 | 0 | LSN-05148f18, LSN-4f4c8530, LSN-aaafa599 |
| CLM-0007 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0008 | settled | 79842.75 | 79843 | 0.25 | no | 0 | 0 | LSN-05148f18, LSN-4f4c8530, LSN-aaafa599 |
| CLM-0009 | settled | 76604.20 | 73664 | 2940.20 | no | 0 | 0 | LSN-05148f18, LSN-4f4c8530, LSN-aaafa599 |
| CLM-0010 | settled | 144884.50 | 141867 | 3017.50 | no | 0 | 0 | LSN-05148f18, LSN-4f4c8530, LSN-aaafa599 |
| CLM-0011 | settled | 57184.61 | 60741 | 3556.39 | yes | 2 | 0 | LSN-05148f18, LSN-4f4c8530, LSN-aaafa599 |
| CLM-0012 | settled | 67575.39 | 78511 | 10935.61 | yes | 2 | 0 | LSN-05148f18, LSN-4f4c8530, LSN-aaafa599 |
| CLM-0013 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0014 | settled | 74629.15 | 85136 | 10506.85 | yes | 2 | 0 | LSN-05148f18, LSN-4f4c8530, LSN-aaafa599 |
| CLM-0015 | settled | 114515.85 | 108088 | 6427.85 | no | 0 | 0 | LSN-05148f18, LSN-4f4c8530, LSN-aaafa599 |
| CLM-0016 | settled | 50372.13 | 59346 | 8973.87 | yes | 2 | 0 | LSN-05148f18, LSN-4f4c8530, LSN-5fb19c80 |
| CLM-0017 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0018 | settled | 111406.50 | 0 | 111406.50 | yes | 5 | 0 | LSN-05148f18, LSN-4f4c8530, LSN-aaafa599 |
| CLM-0019 | settled | 255800.80 | 255801 | 0.20 | no | 0 | 0 | LSN-05148f18, LSN-4f4c8530, LSN-aaafa599 |
| CLM-0020 | settled | 78242.95 | 78243 | 0.05 | no | 0 | 0 | LSN-05148f18, LSN-4f4c8530, LSN-aaafa599 |
