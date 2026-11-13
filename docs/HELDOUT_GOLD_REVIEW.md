# Held-out gold review (ADR-0013)

**Date:** 2026-11-14. **Reviewer:** Domain lead, AI-assisted under [ADR-0013](adr/0013-heldout-gold-review-with-ai-assist.md).
**Files:** `data/claimsense-heldout/claims.jsonl`, `data/claimsense-heldout/gold_worksheets.jsonl`
(60 claims, CLM-1021 to CLM-1080; reviewed in `eval/heldout/`, then moved to `data/`).
**For:** Eval & Red-Team, to audit before the one held-out run.

## Summary
The held-out gold was still on the original demo rules, in the same shape as the dev gold before
the 2026-11-03 audit. It now follows the same rules as the dev gold. Seven review items were
decided on 2026-11-14 by the Domain lead, also on behalf of Eval & Red-Team (see "Decisions").

| | Before | After |
|---|---:|---:|
| Total expected settlement | ₹36,36,060 | ₹23,48,979 |
| Claims whose settlement changed | — | 40 of 60 |
| Admissible claims | 40 | 34 |
| Claims routed to a person (`human_review_required`) | 36 | 29 |
| Deductions with a `clause_id` | 0 | all |

## How the new gold was made and checked
1. **One calculator for both sets.** An independent script encodes the dev rules (ADR-0006 to
   ADR-0011). It reproduces **all 22 dev gold worksheets exactly**: every line, reason code,
   clause, flag, routing value, co-pay and settlement. The same script then relabelled the
   held-out set. It was not written from the product code.
2. **Integrity checks on the result,** the same checks the dev set passes. Bill total = sum of
   lines; quantity × unit = amount; ward + ICU days = nights; allowed + deduction = billed, never
   negative; line totals, co-pay and settlement add up; every deduction cites a clause that exists
   in the knowledge base; flags follow reason codes (GOLD-06).
3. **Loads in the product loader.** `reflexion.cases.load_cases(<held-out dir>)` builds all 60
   gold worksheets, and the `Worksheet` validators pass. No claim, policy or patient ID overlaps the
   dev set, so `reflexion.loop.run_heldout`'s overlap guard passes.
4. **Cross-check against `agents/services.py::reference_calculate`** on the gold clause choices.
   This calculator was written separately from the script. On every paid claim it agrees within
   ₹1, except on the 7 cataract claims, where it does not apply clause 4.3 (the GOLD-05 gap, the
   same as dev CLM-0021/0022).

The agents were **not** run on the held-out set during this review.

## What changed, by rule
| Rule | Source | Held-out claims |
|---|---|---|
| Caesarean is excluded: ₹0, every line cites 7.15, flag `maternity_childbirth_exclusion` | 7.15(a); GOLD-01 | CLM-1025, 1047, 1063, 1080 |
| Room, boarding and nursing share one cap; Note 4.1.1(b) cuts every other expense, the procedure included, by the lower of the room and ICU ratios; medicines are never cut | 4.1(a), 12.1, Note 4.1.1(b); ADR-0006, ADR-0009 | every paid claim (the old gold capped room alone, cut medicines and spared the procedure) |
| `first_policy_inception_date` stated on every claim. Cataract and cholecystectomy claims are renewals from 2023-01-01, so their 24-month wait has passed. Every other claim is a first policy from 2026-01-01. | 6.2; ADR-0007 (same pattern as dev). Chosen by the Domain lead, 2026-11-14 | all 60 |
| Ureteroscopy for stones on a first policy: ₹0 under 6.2.18, every line cites 6.2 | 6.2.18; ADR-0007, ADR-0011 (as dev CLM-0008) | CLM-1026, 1048 |
| Cataract: min(25% of SI, ₹40,000) per eye on the whole treatment, applied before the co-pay. The old gold capped the procedure line alone at ₹40,000 under an `illustrative_procedure_sublimit` code. Each now settles at ₹38,000. | 4.3; ADR-0007 | CLM-1036, 1038, 1045, 1060, 1061, 1071, 1078 |
| ICU day re-filed from `procedure` to `icu` and capped at ₹10,000. The ICU day is one of the nights, so ward and nursing go from 3 days to 2 (bill ₹58,792 → ₹52,847). An ICU breach triggers the 4.1.1(b) cut. | 4.1(b); GOLD-04, ADR-0009 (as dev CLM-0016) | CLM-1066 (**claim fixture changed**) |
| A line repeated in the same bill is deducted in full, cites clause 2, and is left out of the rate calculations | 2; ADR-0009 (DEC-04) | CLM-1046, 1051, 1055 |
| Out-of-period admission cites clause 2 alone (no waiting-period code) | 2; ADR-0008, ADR-0011 ruling 1 | CLM-1028, 1030, 1031, 1039, 1052, 1054, 1059 |
| A not-admissible claim: every line cites the first gate's clause (order: 2, 6.3, 6.1, 6.2, 7.15); a duplicate line cites 2 | ADR-0010 | all ₹0 claims |
| Review flags are derived from reason codes; a not-admissible claim carries only its gate's flag. `mixed_boundary_review`, which no rule produces, is removed, and so is `sub_limit` on the angioplasty claims that have no sub-limit. | GOLD-06, ADR-0007 | 43 claims |
| `human_review_required` is true exactly when the claim fails admissibility or has an in-bill duplicate. The 14 `mixed_boundary` claims were routed to a person with no rule behind it. | harness routing (`claimsense_adapter._route`); dev pattern | 7 claims to "no", 6 claims to "yes" |
| Every deduction cites a clause: 4.1, 4.1.1, 4.3, annexure-a.list-i, 2, 6.1/6.2/6.3, 7.15 | GOLD-07 | all |
| Reason code `pre_existing_disease_waiting_period_not_elapsed` renamed to `pre_existing_disease_waiting_period`, the code `reflexion/cases.py::CLAIM_REASONS` maps | vocabulary | CLM-1034, 1068, 1074 |

Not changed: `scenario_label` (evaluation only, as in dev, so a Caesarean can still read
`non_payable_items`), `duplicate_of` (the harness loader strips it as an answer hint), the line
reason codes on claims that were already not admissible (as dev CLM-0001), and the `gold_ruleset`
name. Each gold `note` now ends with a pointer to this file.

IDs are renumbered from CLM-00NN to CLM-10NN (decision 3), together with the line, document and
`duplicate_of` IDs, POL-100NN → POL-110NN, and SYN-PAT-00NN → SYN-PAT-10NN.

## Per claim
| Claim | Diagnosis | Gold before | Gold after | Flags after | Review | Why |
|---|---|---:|---:|---|---|---|
| CLM-1021 | Pneumonia inpatient episode (non-ICU) | ₹0 | ₹0 | waiting_period | yes | flags from reason codes (GOLD-06); clause ids (GOLD-07) |
| CLM-1022 | Coronary angioplasty (single stent) | ₹267,091 | ₹200,578 | room_rent_breach | no | room+nursing cap, Note 4.1.1(b) cut (ADR-0006/0009); flags from reason codes (GOLD-06); clause ids (GOLD-07) |
| CLM-1023 | Coronary angiography | ₹64,062 | ₹51,389 | non_payable_items, room_rent_breach | no (was yes) | room+nursing cap, Note 4.1.1(b) cut (ADR-0006/0009); routing follows rules; flags from reason codes (GOLD-06); clause ids (GOLD-07) |
| CLM-1024 | Appendectomy | ₹0 | ₹0 | waiting_period | yes | flags from reason codes (GOLD-06); clause ids (GOLD-07) |
| CLM-1025 | Caesarean section | ₹97,551 | ₹0 | maternity_childbirth_exclusion | yes (was no) | 7.15 maternity exclusion (GOLD-01); routing follows rules; flags from reason codes (GOLD-06); clause ids (GOLD-07) |
| CLM-1026 | Ureteroscopy with stone removal | ₹84,764 | ₹0 | waiting_period | yes (was no) | 6.2.18 specific wait, first policy (ADR-0007/0011); routing follows rules; flags from reason codes (GOLD-06); clause ids (GOLD-07) |
| CLM-1027 | Coronary angioplasty (single stent) | ₹263,551 | ₹251,289 | room_rent_breach | no | room+nursing cap, Note 4.1.1(b) cut (ADR-0006/0009); flags from reason codes (GOLD-06); clause ids (GOLD-07) |
| CLM-1028 | Pneumonia inpatient episode (non-ICU) | ₹0 | ₹0 | policy_period_inconsistency | yes | clause ids (GOLD-07) |
| CLM-1029 | Pneumonia inpatient episode (non-ICU) | ₹70,249 | ₹57,820 | non_payable_items, room_rent_breach | no | room+nursing cap, Note 4.1.1(b) cut (ADR-0006/0009); flags from reason codes (GOLD-06); clause ids (GOLD-07) |
| CLM-1030 | Hysterectomy | ₹0 | ₹0 | policy_period_inconsistency | yes | clause ids (GOLD-07) |
| CLM-1031 | Pneumonia inpatient episode (non-ICU) | ₹0 | ₹0 | policy_period_inconsistency | yes | clause ids (GOLD-07) |
| CLM-1032 | Pneumonia inpatient episode (non-ICU) | ₹100,085 | ₹82,099 | non_payable_items, room_rent_breach | no | room+nursing cap, Note 4.1.1(b) cut (ADR-0006/0009); flags from reason codes (GOLD-06); clause ids (GOLD-07) |
| CLM-1033 | Dengue inpatient episode (non-ICU) | ₹0 | ₹0 | waiting_period | yes | clause ids (GOLD-07) |
| CLM-1034 | Pneumonia inpatient episode (non-ICU) | ₹0 | ₹0 | waiting_period | yes | clause ids (GOLD-07) |
| CLM-1035 | Appendectomy | ₹0 | ₹0 | waiting_period | yes | flags from reason codes (GOLD-06); clause ids (GOLD-07) |
| CLM-1036 | Cataract surgery (per eye) | ₹79,199 | ₹38,000 | room_rent_breach, sub_limit | no | room+nursing cap, Note 4.1.1(b) cut (ADR-0006/0009); 4.3 cap on whole treatment, renewal (ADR-0007); flags from reason codes (GOLD-06); clause ids (GOLD-07) |
| CLM-1037 | Laparoscopic cholecystectomy | ₹91,696 | ₹65,662 | room_rent_breach | no | room+nursing cap, Note 4.1.1(b) cut (ADR-0006/0009); clause ids (GOLD-07) |
| CLM-1038 | Cataract surgery (per eye) | ₹66,317 | ₹38,000 | room_rent_breach, sub_limit | no | room+nursing cap, Note 4.1.1(b) cut (ADR-0006/0009); 4.3 cap on whole treatment, renewal (ADR-0007); flags from reason codes (GOLD-06); clause ids (GOLD-07) |
| CLM-1039 | Hysterectomy | ₹0 | ₹0 | policy_period_inconsistency | yes | clause ids (GOLD-07) |
| CLM-1040 | Pneumonia inpatient episode (non-ICU) | ₹86,422 | ₹53,663 | room_rent_breach | no | room+nursing cap, Note 4.1.1(b) cut (ADR-0006/0009); clause ids (GOLD-07); largest-remainder rounding (item 2) |
| CLM-1041 | Pneumonia inpatient episode (non-ICU) | ₹76,048 | ₹58,001 | non_payable_items, room_rent_breach | no (was yes) | room+nursing cap, Note 4.1.1(b) cut (ADR-0006/0009); routing follows rules; flags from reason codes (GOLD-06); clause ids (GOLD-07) |
| CLM-1042 | Coronary angiography | ₹70,434 | ₹51,673 | non_payable_items, room_rent_breach | no (was yes) | room+nursing cap, Note 4.1.1(b) cut (ADR-0006/0009); routing follows rules; flags from reason codes (GOLD-06); clause ids (GOLD-07) |
| CLM-1043 | Appendectomy | ₹76,181 | ₹65,338 | room_rent_breach | no | room+nursing cap, Note 4.1.1(b) cut (ADR-0006/0009); flags from reason codes (GOLD-06); clause ids (GOLD-07) |
| CLM-1044 | Appendectomy | ₹82,741 | ₹67,379 | non_payable_items, room_rent_breach | no (was yes) | room+nursing cap, Note 4.1.1(b) cut (ADR-0006/0009); routing follows rules; flags from reason codes (GOLD-06); clause ids (GOLD-07) |
| CLM-1045 | Cataract surgery (per eye) | ₹47,467 | ₹38,000 | non_payable_items, room_rent_breach, sub_limit | no (was yes) | room+nursing cap, Note 4.1.1(b) cut (ADR-0006/0009); 4.3 cap on whole treatment, renewal (ADR-0007); routing follows rules; flags from reason codes (GOLD-06); clause ids (GOLD-07) |
| CLM-1046 | Fracture fixation (long bone) | ₹142,094 | ₹113,978 | duplicate_bill, room_rent_breach | yes | room+nursing cap, Note 4.1.1(b) cut (ADR-0006/0009); duplicate cites clause 2; flags from reason codes (GOLD-06); clause ids (GOLD-07) |
| CLM-1047 | Caesarean section | ₹96,480 | ₹0 | maternity_childbirth_exclusion | yes (was no) | 7.15 maternity exclusion (GOLD-01); routing follows rules; flags from reason codes (GOLD-06); clause ids (GOLD-07) |
| CLM-1048 | Ureteroscopy with stone removal | ₹83,361 | ₹0 | waiting_period | yes (was no) | 6.2.18 specific wait, first policy (ADR-0007/0011); routing follows rules; flags from reason codes (GOLD-06); clause ids (GOLD-07) |
| CLM-1049 | Coronary angiography | ₹78,483 | ₹63,364 | non_payable_items, room_rent_breach | no (was yes) | room+nursing cap, Note 4.1.1(b) cut (ADR-0006/0009); routing follows rules; flags from reason codes (GOLD-06); clause ids (GOLD-07) |
| CLM-1050 | Pneumonia inpatient episode (non-ICU) | ₹75,713 | ₹61,389 | non_payable_items, room_rent_breach | no (was yes) | room+nursing cap, Note 4.1.1(b) cut (ADR-0006/0009); routing follows rules; flags from reason codes (GOLD-06); clause ids (GOLD-07) |
| CLM-1051 | Laparoscopic cholecystectomy | ₹82,035 | ₹77,904 | duplicate_bill, room_rent_breach | yes | room+nursing cap, Note 4.1.1(b) cut (ADR-0006/0009); duplicate cites clause 2; flags from reason codes (GOLD-06); clause ids (GOLD-07) |
| CLM-1052 | Hysterectomy | ₹0 | ₹0 | policy_period_inconsistency | yes | clause ids (GOLD-07) |
| CLM-1053 | Pneumonia inpatient episode (non-ICU) | ₹0 | ₹0 | waiting_period | yes | clause ids (GOLD-07) |
| CLM-1054 | Hysterectomy | ₹0 | ₹0 | policy_period_inconsistency | yes | clause ids (GOLD-07) |
| CLM-1055 | Appendectomy | ₹79,092 | ₹70,868 | duplicate_bill, room_rent_breach | yes | room+nursing cap, Note 4.1.1(b) cut (ADR-0006/0009); duplicate cites clause 2; flags from reason codes (GOLD-06); clause ids (GOLD-07) |
| CLM-1056 | Appendectomy | ₹83,442 | ₹68,818 | non_payable_items, room_rent_breach | no (was yes) | room+nursing cap, Note 4.1.1(b) cut (ADR-0006/0009); routing follows rules; flags from reason codes (GOLD-06); clause ids (GOLD-07) |
| CLM-1057 | Dengue inpatient episode (non-ICU) | ₹0 | ₹0 | waiting_period | yes | clause ids (GOLD-07) |
| CLM-1058 | Coronary angioplasty (single stent) | ₹0 | ₹0 | waiting_period | yes | flags from reason codes (GOLD-06); clause ids (GOLD-07) |
| CLM-1059 | Pneumonia inpatient episode (non-ICU) | ₹0 | ₹0 | policy_period_inconsistency | yes | clause ids (GOLD-07) |
| CLM-1060 | Cataract surgery (per eye) | ₹68,234 | ₹38,000 | non_payable_items, room_rent_breach, sub_limit | no (was yes) | room+nursing cap, Note 4.1.1(b) cut (ADR-0006/0009); 4.3 cap on whole treatment, renewal (ADR-0007); routing follows rules; flags from reason codes (GOLD-06); clause ids (GOLD-07) |
| CLM-1061 | Cataract surgery (per eye) | ₹82,941 | ₹38,000 | room_rent_breach, sub_limit | no | room+nursing cap, Note 4.1.1(b) cut (ADR-0006/0009); 4.3 cap on whole treatment, renewal (ADR-0007); flags from reason codes (GOLD-06); clause ids (GOLD-07) |
| CLM-1062 | Pneumonia inpatient episode (non-ICU) | ₹88,040 | ₹69,066 | room_rent_breach | no | room+nursing cap, Note 4.1.1(b) cut (ADR-0006/0009); flags from reason codes (GOLD-06); clause ids (GOLD-07) |
| CLM-1063 | Caesarean section | ₹86,249 | ₹0 | maternity_childbirth_exclusion | yes (was no) | 7.15 maternity exclusion (GOLD-01); routing follows rules; flags from reason codes (GOLD-06); clause ids (GOLD-07) |
| CLM-1064 | Appendectomy | ₹82,309 | ₹65,810 | non_payable_items, room_rent_breach | no (was yes) | room+nursing cap, Note 4.1.1(b) cut (ADR-0006/0009); routing follows rules; flags from reason codes (GOLD-06); clause ids (GOLD-07) |
| CLM-1065 | Appendectomy | ₹71,941 | ₹53,022 | room_rent_breach | no | room+nursing cap, Note 4.1.1(b) cut (ADR-0006/0009); clause ids (GOLD-07) |
| CLM-1066 | ICU inpatient day (excluding procedure) | ₹55,852 | ₹29,018 | room_rent_breach, sub_limit | no | room+nursing cap, Note 4.1.1(b) cut (ADR-0006/0009); ICU line re-filed and capped (GOLD-04/ADR-0009); flags from reason codes (GOLD-06); clause ids (GOLD-07) |
| CLM-1067 | Pneumonia inpatient episode (non-ICU) | ₹0 | ₹0 | waiting_period | yes | clause ids (GOLD-07) |
| CLM-1068 | Pneumonia inpatient episode (non-ICU) | ₹0 | ₹0 | waiting_period | yes | clause ids (GOLD-07) |
| CLM-1069 | Pneumonia inpatient episode (non-ICU) | ₹80,903 | ₹63,181 | room_rent_breach | no | room+nursing cap, Note 4.1.1(b) cut (ADR-0006/0009); flags from reason codes (GOLD-06); clause ids (GOLD-07) |
| CLM-1070 | Pneumonia inpatient episode (non-ICU) | ₹74,862 | ₹54,216 | room_rent_breach | no | room+nursing cap, Note 4.1.1(b) cut (ADR-0006/0009); clause ids (GOLD-07) |
| CLM-1071 | Cataract surgery (per eye) | ₹86,218 | ₹38,000 | non_payable_items, room_rent_breach, sub_limit | no (was yes) | room+nursing cap, Note 4.1.1(b) cut (ADR-0006/0009); 4.3 cap on whole treatment, renewal (ADR-0007); routing follows rules; flags from reason codes (GOLD-06); clause ids (GOLD-07) |
| CLM-1072 | Appendectomy | ₹77,825 | ₹65,966 | non_payable_items, room_rent_breach | no | room+nursing cap, Note 4.1.1(b) cut (ADR-0006/0009); flags from reason codes (GOLD-06); clause ids (GOLD-07) |
| CLM-1073 | Pneumonia inpatient episode (non-ICU) | ₹100,454 | ₹85,123 | non_payable_items, room_rent_breach | no (was yes) | room+nursing cap, Note 4.1.1(b) cut (ADR-0006/0009); routing follows rules; flags from reason codes (GOLD-06); clause ids (GOLD-07) |
| CLM-1074 | Pneumonia inpatient episode (non-ICU) | ₹0 | ₹0 | waiting_period | yes | clause ids (GOLD-07) |
| CLM-1075 | Pneumonia inpatient episode (non-ICU) | ₹0 | ₹0 | waiting_period | yes | clause ids (GOLD-07) |
| CLM-1076 | Pneumonia inpatient episode (non-ICU) | ₹90,147 | ₹77,548 | non_payable_items, room_rent_breach | no | room+nursing cap, Note 4.1.1(b) cut (ADR-0006/0009); flags from reason codes (GOLD-06); clause ids (GOLD-07) |
| CLM-1077 | Pneumonia inpatient episode (non-ICU) | ₹0 | ₹0 | waiting_period | yes | clause ids (GOLD-07) |
| CLM-1078 | Cataract surgery (per eye) | ₹70,410 | ₹38,000 | room_rent_breach, sub_limit | no | room+nursing cap, Note 4.1.1(b) cut (ADR-0006/0009); 4.3 cap on whole treatment, renewal (ADR-0007); flags from reason codes (GOLD-06); clause ids (GOLD-07) |
| CLM-1079 | Coronary angiography | ₹77,227 | ₹58,817 | non_payable_items, room_rent_breach | no (was yes) | room+nursing cap, Note 4.1.1(b) cut (ADR-0006/0009); routing follows rules; flags from reason codes (GOLD-06); clause ids (GOLD-07) |
| CLM-1080 | Caesarean section | ₹97,890 | ₹0 | maternity_childbirth_exclusion | yes (was no) | 7.15 maternity exclusion (GOLD-01); routing follows rules; flags from reason codes (GOLD-06); clause ids (GOLD-07) |

## Decisions (all closed 2026-11-14)
Decided by the Domain lead. Items 2, 3 and 7 were decided on behalf of Eval & Red-Team (Sanjay),
who agreed to this review.

1. **Cataract cap larger than the procedure line: ruling.** ADR-0007 puts the 4.3 deduction on the
   procedure line. When that line reaches ₹0, the rest falls on the next payable lines in bill
   order, still citing 4.3. This applies on CLM-1061 and CLM-1071, where the other lines alone
   exceed ₹40,000. Line amounts only: the settlement is ₹38,000 under any allocation.
2. **Rounding beyond the ₹1 tolerance: fix the gold, not the tolerance.** With each line rounded
   half up (GOLD-08), CLM-1040 sat ₹1.10 above its paise figure, so an exact pipeline would have
   scored wrong. Its lines are now rounded by largest remainder so they sum to the rounded exact
   total: ₹53,663 against ₹53,662.90. The ₹1 tolerance is unchanged (thresholds are never
   loosened). No other claim was affected.
3. **IDs renumbered.** CLM-0021 and CLM-0022 and POL-10021 and POL-10022 repeated dev IDs.
   `run_heldout` asserts no dev/held-out overlap and would have refused the run. Every held-out ID
   is now in the 10xx range.
4. **30-day boundary: ruling.** 6.3 "within 30 days from the first policy commencement date"
   covers days 1 to 30. A day-31 admission (2026-01-31 from 2026-01-01) is admissible, as in the
   original gold: CLM-1042, 1044, 1050, 1056, 1064. CLM-1060 is a renewal, so 6.3(b) applies anyway.
5. **Known product gaps: accepted, to be reported with the held-out result.** These show as misses,
   not gold errors:
   - The calculator does not apply 4.3 (7 cataract claims; GOLD-05).
   - Cataract claims state no `treated_eye`. This has no effect: none has an earlier claim.
6. **PED fixture corrected.** CLM-1034, 1068 and 1074 stated
   `pre_existing_condition_wait_months_elapsed: 8` on a first policy that began days before
   admission. It is now 0. No agent reads the field, and all three fail the 30-day wait first.
7. **Kept in the repository at `data/claimsense-heldout/`** (Domain lead, 2026-11-14). The
   pre-review copy remains in git history (`c2a1112`).
   - CLAUDE.md rule 5, `data/README.md`, the team guide and the eval docs now name this folder.
   - `.claude/settings.json` denies Claude Code reads of it.
   - `scripts/run_reflexion_heldout.py` accepts exactly this in-repo folder and still refuses any
     other in-repo folder (test:
     `tests/orchestration/test_cases.py::test_day5_heldout_script_accepts_only_the_in_repo_heldout_folder`).
     Results must still be written outside the repository.
   - The harness loader still refuses any held-out path, so the ADR-0005 option B held-out mode is
     needed to score it on the harness scale.
