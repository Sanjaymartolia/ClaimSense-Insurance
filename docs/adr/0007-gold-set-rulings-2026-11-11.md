# ADR-0007: Gold-set rulings for GOLD-03, GOLD-05, GOLD-06 and GOLD-08

**Status:** accepted
**Owner / layers:** @domain-lead (Domain & Product) — L13 eval gold; Eval & Red-Team reviews
**Date:** 2026-11-11

## Context
The 2026-11-03 audit (`docs/CLAIMS_AND_GOLD_SET_FIXES.md`) left four gold defects open because each
needed a ruling. ADR-0006 settled GOLD-02 earlier the same day. This ADR records the other four.

## Decision

### GOLD-03, DEC-02, DEC-03: waiting periods run from a stated first-policy date
Clause 6.2 runs "after the date of inception of the first policy". Every dev claim now states
`policy.first_policy_inception_date`.
- Most claims are first policies, with inception equal to `policy_start_date` (2026-01-01). That
  keeps the 30-day results on CLM-0001/0002/0003/0007/0017 as they were.
- **CLM-0008**, ureteroscopy for stones on a first policy, falls under clause 6.2.18 ("calculi in
  urinary system"), a 24-month wait. It is now not admissible: settlement ₹0, reason
  `specific_illness_waiting_period`, every line cites `…:6.2`, and it goes to human review.
- **CLM-0004 and CLM-0005**, gallbladder removals, are renewals first insured on **2023-01-01**.
  The 24-month wait has passed, so whether the cause was gallstones (DEC-03) no longer matters.
  They keep their room-rent and duplicate scenarios.
- The loaders (`reflexion/cases.py::policy_from_fixture`, `claimsense_adapter._policy`) read the
  field. A fixture without it (the held-out set predates it) falls back to the policy start, which
  was the old assumption.

### GOLD-05: real cataract sub-limit cases
Two claims are added. Both are renewals from 2023-01-01, so the 24-month cataract wait (6.2.9) has
passed.
- **CLM-0021**: right eye, sum insured ₹500,000, bill ₹63,000. Clause 4.3 caps "medical expenses
  incurred for treatment of Cataract" at min(25% of SI, ₹40,000) = ₹40,000 per eye per policy year.
  That limit covers the whole treatment, room and diagnostics included. A deduction of ₹23,000 sits
  on the procedure line (reason `cataract_sub_limit`, clause `…:4.3`). The co-pay is applied after
  the cap: 5% of ₹40,000 = ₹2,000. **Settlement ₹38,000.**
- **CLM-0022**: left eye, sum insured ₹300,000, bill ₹34,000. An earlier claim this policy year on
  the **same eye** used ₹25,000 of 4.3 (`history.prior_claims`), leaving ₹15,000. Deduction
  ₹19,000, co-pay ₹750. **Settlement ₹14,250.** `human_review_required: false`: using up a
  sub-limit is arithmetic, not a fraud signal.
- Fixture fields: `hospitalisation.treated_eye`, and `history.prior_claims[]` =
  `{claim_id, admission_date, treated_eye, sub_limits_used_inr: {clause_id: rupees}}`. These reach
  claims-db history through `reflexion/cases.py::history_from_fixture` and the eval adapter.
- **CLM-0019** (angioplasty) had a `sub_limit` flag but no sub-limit. Its relabel:
  `normal_admissible`, no flags.
- The red-team bases are unchanged, so the red-team set stays at 30.

### GOLD-06: a flag for every rule that changed money
`expected_review_flags` are derived from reason codes. On an admissible claim, every line-level code
maps to a flag. On a not-admissible claim, only the claim-level gate's code maps, because the
claim pays ₹0 whatever its lines say.

Code → flag: initial, specific and PED waits → `waiting_period`; outside the period →
`policy_period_inconsistency`; maternity → `maternity_childbirth_exclusion`; room cap and
proportional cut → `room_rent_breach`; ICU cap and `cataract_sub_limit` → `sub_limit` (ICU filed
as a sub-limit since GOLD-04); non-payable → `non_payable_items`; `duplicate_line` →
`duplicate_bill`.

**Judgement call:** CLM-0003 loses `duplicate_bill`, because it fails the 30-day wait and its
duplicate line changes no money. The duplicate still shows in its line reason codes.
`tests/test_dataset_integrity.py::test_gold_flags_follow_reason_codes` enforces the rule.

### GOLD-08: ₹1 tolerance, gold stays in rupees
The gold keeps whole rupees, with each line rounded half up. The eval harness CLIs
(`eval/harness/run.py`, `suite.py`, `eval/full.py`) now default `--tolerance-inr` to 1. Library
functions keep a default of 0, and the Reflexion scripts keep an explicit `--tolerance-rs`, so
held-out comparisons stay like for like. The `shift_amounts` fault (+₹1) is now caught only with
`--tolerance-inr 0`.

## Consequences
- The dev set grows to **22 claims**. Count pins are updated in `tests/` and `eval/tests/`.
- New known agent misses: CLM-0008 (admissibility has no 6.2 list, AGT-02; listed in
  `KNOWN_UNIMPLEMENTED_EXCLUSIONS`), and CLM-0021/0022 (the calculator doesn't apply 4.3 because
  the claim contract has no treated eye: `calc.adjudication.INFORMATIONAL_SUB_LIMITS`). Both are
  in `RULE_DISAGREEMENTS`.
- Suite composites re-pinned: floor-dev 0.130 → 0.119, real-dev 0.549 → 0.635, real-redteam
  0.203 → 0.233. Every gate row is unchanged.
- **Not updated:** `course/claimsense_hw/rules.py`, the teaching copy of the demo rules, still
  encodes the pre-ADR-0006 rules, so `course/tests` fails on the relabelled claims. That is a
  `course/` change, which Eval & Red-Team must review.
- Still open: DEC-01 (nursing inside the room limit) and DEC-04 (how a duplicate is deducted).

## Links
`docs/CLAIMS_AND_GOLD_SET_FIXES.md` (GOLD-03, 05, 06, 08; DEC-02, 03), ADR-0006, `data/README.md`.
