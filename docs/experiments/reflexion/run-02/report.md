# Reflexion experiment: 20 development claims

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

Frozen playbook hash: `b566637830ffd4f5204d56d4a894ae83693ef6cdce40f153c1eaa9a7ce3f8e25`

## Run details

mode: REAL MODEL via OpenRouter | executor: local | calculator: reference | tolerance: Rs 1 | approval: CONSOLE

- development cases: 20 from `eval/golden_dev`
- rounding tolerance: Rs 1 (0 = strict; rupee error is exact either way)
- lessons proposed 19, approved 1, rejected 18, withdrawn after ablation 0
- generated 2026-11-07T12:28:31.650327+00:00

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
| LSN-f5250306 | rejected | Dhruvi Ramani | contradicts clause 4.1.1 Note b; encodes the gold demo rule | Verify that procedure category claims are adjudicated under clause 4.1, not its sub-clauses like 4.1.1, as per the Arogya Sanjeevani policy. | When adjudicating procedure category bill lines under the Arogya Sanjeevani policy. | new_india_arogya_sanjeevani:4.1 | CLM-0004 |
| LSN-2e7f10fb | rejected | Dhruvi Ramani | omits the medicines exception in clause 4.1.1 Note b | Check for proportional deduction rules under clause 4.1.1 when room or ICU rates exceed policy limits before applying other expense coverage. | When adjudicating medicine bills under the Arogya Sanjeevani policy with room or ICU rates exceeding allowed limits. | new_india_arogya_sanjeevani:4.1.1 | CLM-0004 |
| LSN-e4fcd015 | rejected | Dhruvi Ramani | vague, cites a non-existent clause id; duplicate line is a fraud finding, not a clause choice | Check the coverage applicability for the 'investigations' category under the Arogya Sanjeevani policy clauses before approving payment. | When adjudicating claim lines categorized as 'investigations' under the Arogya Sanjeevani policy. | Arogya Sanjeevani Investigations Coverage Clause | CLM-0005 |
| LSN-bac41516 | rejected | Dhruvi Ramani | vague, cites a non-existent clause id; duplicate line is a fraud finding, not a clause choice | Always confirm coverage applicability for the 'investigations' bill line category as specified in the Arogya Sanjeevani policy clauses before approving payment. | When adjudicating claims with bill line category 'investigations' under the Arogya Sanjeevani policy. | Arogya Sanjeevani Investigations Coverage Clause | CLM-0009 |
| LSN-31e1e0e0 | rejected | Dhruvi Ramani | vague, cites a non-existent clause id; duplicate line is a fraud finding, not a clause choice | Check the coverage applicability for the 'investigations' category as specified in the Arogya Sanjeevani policy clauses before approving any payment. | When adjudicating claim lines categorized under 'investigations' for Arogya Sanjeevani policy holders. | Arogya Sanjeevani Investigations Coverage Clause | CLM-0010 |
| LSN-68244324 | rejected | Dhruvi Ramani | contradicts clause 4.1.1 Note b; encodes the gold demo rule | Verify that the procedure category claims are adjudicated strictly under clause 4.1 as specified in the Arogya Sanjeevani policy before considering any sub-clauses. | When adjudicating procedure category claims under the Arogya Sanjeevani policy. | new_india_arogya_sanjeevani:4.1 | CLM-0011 |
| LSN-b6b2fc66 | rejected | Dhruvi Ramani | omits the medicines exception in clause 4.1.1 Note b | Check for proportional deduction rules under clause 4.1.1 when room or ICU rates exceed policy limits before applying other expense coverage. | When adjudicating medicine expenses alongside room/ICU charges that exceed policy limits under the Arogya Sanjeevani policy. | new_india_arogya_sanjeevani:4.1.1 | CLM-0011 |
| LSN-ce8639a3 | rejected | Dhruvi Ramani | contradicts clause 4.1.1 Note b; encodes the gold demo rule | Verify that procedure category claims are adjudicated under clause 4.1 as specified in the Arogya Sanjeevani policy before considering any sub-clauses. | When adjudicating procedure category bill lines under the Arogya Sanjeevani policy. | new_india_arogya_sanjeevani:4.1 | CLM-0012 |
| LSN-94d962cc | approved | Dhruvi Ramani | - | Check if room or ICU rates exceed policy limits and apply proportional deduction to all expenses except medicines as per clause 4.1.1 Note b. | When adjudicating medicine bill lines under the Arogya Sanjeevani policy with room or ICU rates exceeding limits. | new_india_arogya_sanjeevani:4.1.1 | CLM-0012 |
| LSN-e0679e78 | rejected | Dhruvi Ramani | contradicts clause 4.1.1 Note b; encodes the gold demo rule | Verify that procedure category claims are adjudicated under clause 4.1, not its sub-clauses like 4.1.1, as per the Arogya Sanjeevani policy. | When adjudicating procedure category bill lines under the Arogya Sanjeevani policy. | new_india_arogya_sanjeevani:4.1 | CLM-0014 |
| LSN-f53d8fe9 | rejected | Dhruvi Ramani | false: investigations are covered under 4.1; invented clause id; duplicate line is a fraud finding | Confirm that the investigations category is excluded from coverage under the Arogya Sanjeevani policy before approving payment (clause related to investigations exclusion). | When adjudicating claims with bill lines categorized as investigations under the Arogya Sanjeevani policy. | investigations_exclusion_clause | CLM-0015 |
| LSN-7e83a7ff | rejected | Dhruvi Ramani | ICU-breach proportional cut awaits a domain ruling; lesson encodes the gold's no-cut reading | For nursing category claims, apply the coverage rules under clause 4.1 rather than any sub-clauses like 4.1.1. | When adjudicating claims with bill line category 'nursing' under the Arogya Sanjeevani policy. | new_india_arogya_sanjeevani:4.1 | CLM-0016 |
| LSN-ec7bd6d7 | rejected | Dhruvi Ramani | ICU-breach proportional cut awaits a domain ruling; lesson encodes the gold's no-cut reading | For investigations under the Arogya Sanjeevani policy, apply clause 4.1 rather than any sub-clauses like 4.1.1 to ensure correct coverage. | When adjudicating claims with bill line category 'investigations' under the Arogya Sanjeevani policy. | new_india_arogya_sanjeevani:4.1 | CLM-0016 |
| LSN-c3b3ef85 | rejected | Dhruvi Ramani | ICU-breach proportional cut awaits a domain ruling; lesson encodes the gold's no-cut reading | For procedure category claims under the Arogya Sanjeevani policy, verify that clause 7.15 is applied as per policy guidelines. | When adjudicating procedure category bill lines under the Arogya Sanjeevani policy. | new_india_arogya_sanjeevani:7.15 | CLM-0018 |
| LSN-944d94bf | rejected | Dhruvi Ramani | admissibility is deterministic code, not a clause choice; exclusion check is AGT-02 | For room category claims under the Arogya Sanjeevani policy, verify and apply clause 7.15 as the governing clause before adjudication. | When adjudicating room category bill lines under the Arogya Sanjeevani policy. | new_india_arogya_sanjeevani:7.15 | CLM-0018 |
| LSN-7397efdb | rejected | Dhruvi Ramani | admissibility is deterministic code, not a clause choice; exclusion check is AGT-02 | For nursing category claims, always apply clause 7.15 as specified in the Arogya Sanjeevani policy. | When adjudicating nursing category bill lines under the Arogya Sanjeevani policy. | new_india_arogya_sanjeevani:7.15 | CLM-0018 |
| LSN-67834e9d | rejected | Dhruvi Ramani | admissibility is deterministic code, not a clause choice; exclusion check is AGT-02 | For medicines category claims, always apply clause 7.15 as specified in the Arogya Sanjeevani policy. | When adjudicating claims under the medicines bill line category in the Arogya Sanjeevani policy. | new_india_arogya_sanjeevani:7.15 | CLM-0018 |
| LSN-5e17eac9 | rejected | Dhruvi Ramani | admissibility is deterministic code, not a clause choice; exclusion check is AGT-02 | For investigations category claims, always apply clause 7.15 of the Arogya Sanjeevani policy as the governing clause. | When adjudicating bill lines categorized under investigations in the Arogya Sanjeevani policy. | new_india_arogya_sanjeevani:7.15 | CLM-0018 |
| LSN-e338d6c8 | rejected | Dhruvi Ramani | vague, applies to everything, invented clause id; admissibility is deterministic code | Verify claim admissibility criteria as specified in the Arogya Sanjeevani policy before approving any claim. | All health insurance claims under the Arogya Sanjeevani policy. | Admissibility Criteria | CLM-0018 |

## Ablation table (leave one lesson out)

| lesson | harmful | error increase Rs | edit-rate increase | text |
|---|---|---|---|---|
| LSN-94d962cc | no | 0.00 | 0.0 | Check if room or ICU rates exceed policy limits and apply proportional deduction to all expenses except medicines as per clause 4.1.1 Note b. |

## Known gold vs calculator rule disagreements (not fixable by any lesson)

- Gold applies the room-rent proportional cut to pharmacy lines (room_linked=true) and not to the procedure line; the calculator does the opposite, following clause 4.1.1 Note (b). CLM-0004, 0011, 0012, 0014. Decision (lead, Nov 2026 walkthrough): the gold is not relabelled for now because a relabel affects every other owner's scores; the mapping stays, the gap is reported.
- Gold deducts an in-bill duplicate line in full (duplicate_line); the fraud agent only checks claim history and a fraud flag never changes an amount. CLM-0005, 0009, 0010, 0015. Decision (lead, Nov 2026 walkthrough): a duplicate stays a fraud flag for the human adjudicator; no clause pays it at zero.
- Gold rounds each cut line to whole rupees; the calculator keeps paise. Cut lines differ by up to Rs 0.50 and count as a miss unless the evaluator is run with a tolerance (--tolerance-rs). Decision (lead, Nov 2026 walkthrough): the tolerance lives in the Reflexion evaluator, the gold is not changed.
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
| CLM-0004 | settled | 80990.23 | 102313 | 21322.77 | yes | 2 | 0 | LSN-94d962cc |
| CLM-0005 | settled | 103940.45 | 96660 | 7280.45 | no | 0 | 0 | LSN-94d962cc |
| CLM-0006 | settled | 71374.45 | 71374 | 0.45 | no | 0 | 0 | LSN-94d962cc |
| CLM-0007 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0008 | settled | 79842.75 | 79843 | 0.25 | no | 0 | 0 | LSN-94d962cc |
| CLM-0009 | settled | 76604.20 | 73664 | 2940.20 | no | 0 | 0 | LSN-94d962cc |
| CLM-0010 | settled | 144884.50 | 141867 | 3017.50 | no | 0 | 0 | LSN-94d962cc |
| CLM-0011 | settled | 57184.61 | 60741 | 3556.39 | yes | 2 | 0 | LSN-94d962cc |
| CLM-0012 | settled | 67575.39 | 78511 | 10935.61 | yes | 2 | 0 | LSN-94d962cc |
| CLM-0013 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0014 | settled | 74629.15 | 85136 | 10506.85 | yes | 2 | 0 | LSN-94d962cc |
| CLM-0015 | settled | 114515.85 | 108088 | 6427.85 | no | 0 | 0 | LSN-94d962cc |
| CLM-0016 | settled | 50372.13 | 59346 | 8973.87 | yes | 2 | 0 | LSN-94d962cc |
| CLM-0017 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0018 | settled | 111406.50 | 0 | 111406.50 | yes | 5 | 0 | LSN-94d962cc |
| CLM-0019 | settled | 255800.80 | 255801 | 0.20 | no | 0 | 0 | LSN-94d962cc |
| CLM-0020 | settled | 78242.95 | 78243 | 0.05 | no | 0 | 0 | LSN-94d962cc |

## Per case: after pass, run 2

| case | status | proposed Rs | gold Rs | abs error Rs | edited | lines edited | critic rejections | lessons used |
|---|---|---|---|---|---|---|---|---|
| CLM-0001 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0002 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0003 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0004 | settled | 80990.23 | 102313 | 21322.77 | yes | 2 | 0 | LSN-94d962cc |
| CLM-0005 | settled | 103940.45 | 96660 | 7280.45 | no | 0 | 0 | LSN-94d962cc |
| CLM-0006 | settled | 71374.45 | 71374 | 0.45 | no | 0 | 0 | LSN-94d962cc |
| CLM-0007 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0008 | settled | 79842.75 | 79843 | 0.25 | no | 0 | 0 | LSN-94d962cc |
| CLM-0009 | settled | 76604.20 | 73664 | 2940.20 | no | 0 | 0 | LSN-94d962cc |
| CLM-0010 | settled | 144884.50 | 141867 | 3017.50 | no | 0 | 0 | LSN-94d962cc |
| CLM-0011 | settled | 57184.61 | 60741 | 3556.39 | yes | 2 | 0 | LSN-94d962cc |
| CLM-0012 | settled | 67575.39 | 78511 | 10935.61 | yes | 2 | 0 | LSN-94d962cc |
| CLM-0013 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0014 | settled | 74629.15 | 85136 | 10506.85 | yes | 2 | 0 | LSN-94d962cc |
| CLM-0015 | settled | 114515.85 | 108088 | 6427.85 | no | 0 | 0 | LSN-94d962cc |
| CLM-0016 | settled | 50372.13 | 59346 | 8973.87 | yes | 2 | 0 | LSN-94d962cc |
| CLM-0017 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0018 | settled | 111406.50 | 0 | 111406.50 | yes | 5 | 0 | LSN-94d962cc |
| CLM-0019 | settled | 255800.80 | 255801 | 0.20 | no | 0 | 0 | LSN-94d962cc |
| CLM-0020 | settled | 78242.95 | 78243 | 0.05 | no | 0 | 0 | LSN-94d962cc |
