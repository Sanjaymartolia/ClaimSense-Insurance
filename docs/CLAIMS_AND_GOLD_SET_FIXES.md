# Claims and Gold Set Fixes

**Audit date:** 2026-11-03. **Code audited:** `shashank/t11-query-rewrite` (`94d31a8`) merged with `origin/main` (`c6ecb69`). Rechecked at `688109b`, which only adds `guardrails.py`, `claims_db_server.py`, `approval_gate.py` and `approval_security.py`.
**Owners of the fixes:** see each item. Nothing in `eval/`, `agents/` or `calc/` was changed by this audit.

**2026-11-04 update:** GOLD-01, GOLD-04 and part of GOLD-07 are fixed in `eval/golden_dev/` (see
each item below and `eval/README.md`). GOLD-02, GOLD-03, GOLD-05, GOLD-06, GOLD-08 and DEC-01 to
DEC-04 are unchanged and still need a ruling. The GOLD-01 fix also surfaced a new, small gap:
`src/claimsense/reflexion/cases.py::CLAIM_REASONS` has no entry for the new
`maternity_childbirth_exclusion` reason code, so `load_cases()` now raises on CLM-0018 until
Agents & Orchestration adds one (plus a clause-7.15 constant in `agents/clauses.py`). Not fixed
here because both files are outside `eval/`.

**2026-11-11 update:** GOLD-02 is fixed by [ADR-0006](adr/0006-room-rent-proportional-cut.md),
which applies the room-rent cut per Note 4.1.1(b). GOLD-03, GOLD-05, GOLD-06, GOLD-08, DEC-02 and
DEC-03 are fixed by [ADR-0007](adr/0007-gold-set-rulings-2026-11-11.md); the dev set is now 22
claims. DEC-01, DEC-04 and the CLM-0016 ICU questions are decided by
[ADR-0009](adr/0009-room-cap-nursing-duplicates-icu.md). Since 2026-11-12, both calculators
(`agents/services.py::reference_calculate` and `calc/adjudication.py`) apply ADR-0009 and agree
with each other on every paid dev claim.

## Summary
**The JSONL files are well formed, and the gold's arithmetic is right. The problem is the rules behind the gold.** The gold was generated from a demo ruleset (`data/README.md`) that disagrees with the policy wording in several places. A wrong answer can therefore score as correct: the real-model run paid CLM-0018, a Caesarean the policy excludes, at ₹111,406.50, and that counted as a ₹0.50 rounding difference.

This doesn't block agent building, because no agent code reads these files. It does block trusting any score measured against them.

| Priority | Fix first | IDs |
|---|---|---|
| Critical | Wrong payouts in gold and the agent gaps that hide them | ~~GOLD-01~~ (fixed 2026-11-04), ~~GOLD-02~~ (fixed 2026-11-11), ~~GOLD-03~~ (fixed 2026-11-11), AGT-01, AGT-02, DEC-01 |
| High | Missing test cases, unverified labels, no evaluation harness | ~~GOLD-04~~ (fixed 2026-11-04), ~~GOLD-05~~ (fixed 2026-11-11), ~~GOLD-07~~ (partially fixed 2026-11-04), CLAIM-01, CLAIM-03, RET-01, RET-02, EVAL-01, AGT-03 to AGT-07, AGT-10, AGT-11, AGT-12, AGT-14, DEC-02, DEC-04 |
| Medium | Consistency and accuracy | ~~GOLD-06~~, ~~GOLD-08~~ (fixed 2026-11-11), CLAIM-02, CLAIM-04, RET-03, RET-04, RET-05, EVAL-02, AGT-08, AGT-09, AGT-13, DEC-03, REC-01 to REC-04 |
| Low | Tidying | REC-05, REC-06, REC-07 |

See the "2026-11-04 update" note above for exactly what changed and the one new follow-up it created.

### How this was verified
- A read-only script parsed every row and recalculated the gold from `data/README.md`.
- Each code finding was reproduced in a scratch copy of the merged code, using the stub LLM, so no model was called.
- `eval/redteam/build_cases.py` was re-run in a scratch folder.
- Clause text was read from `data/knowledge_base/policy_knowledge_base.jsonl`.

**Not checked:** `../claimsense-heldout/`. It is off-limits under `CLAUDE.md` rule 5, so nothing here says whether the held-out gold has the same errors. See REC-01.

### What passed
| Check | Files | Result |
|---|---|---|
| Valid JSON on every line, no BOM, no blank lines | all 6 eval JSONL files | Passed: 159 rows, none malformed |
| Unique IDs | all 6 | Passed |
| Claims and gold pair up, with matching line IDs | dev and red team | Passed |
| Bill total equals the sum of the lines | dev | Passed, 20 of 20 |
| `quantity × unit = amount`; room and nursing quantity equals nights | dev and red team | Passed |
| Allowed + deduction = billed; line totals, co-pay and settlement add up | dev and red team | Passed |
| Gold matches its own demo rules | dev and red team | Passed, except the ICU line in GOLD-04 |
| Red-team rebuild matches the committed files | `eval/redteam/` | Passed: parsed rows identical; Windows line endings only differ in the working copy |
| Red-team settlement equals its base claim, and no base claim ID leaks | `eval/redteam/` | Passed, 30 of 30 |
| Retrieval labels point at real, searchable clauses | `retrieval_queries.jsonl` | Passed, 47 of 47 |
| Exact duplicate bills | dev | None found |

The four deliberate red-team bill-total mismatches (CLM-9019 to CLM-9022) are expected, not errors.

---

# Part 1: Confirmed issues
Each item was reproduced from the data or code.

## Gold worksheet data

### GOLD-01: CLM-0018 pays a Caesarean the policy excludes — **Fixed 2026-11-04**
- **Priority:** Critical
- **Where:** `eval/golden_dev/gold_worksheets.jsonl`, CLM-0018. Two red-team cases inherit it.
- **Issue:** Gold says `admissible` and pays ₹111,406. Clause 7.15 excludes treatment traceable to childbirth, "including complicated deliveries and caesarean sections", except ectopic pregnancy. The claim shows no ectopic pregnancy.
- **Expected:** ₹0, with an exclusion reason citing clause 7.15.
- **Fix:** Relabel the claim, add an exclusion reason code, and map that code in `CLAIM_REASONS` in `src/claimsense/reflexion/cases.py` (on `main`). Rerun `python eval/redteam/build_cases.py`.
- **Done:** Relabelled to `not_admissible_under_demo_exclusion_rule`, reason code `maternity_childbirth_exclusion`, every line's deduction cites `new_india_arogya_sanjeevani:7.15`, settlement ₹0. Red-team rebuilt.
- **Still open:** `CLAIM_REASONS` in `src/claimsense/reflexion/cases.py` has no entry for `maternity_childbirth_exclusion` yet, so `load_cases()` raises on CLM-0018. That file and `agents/clauses.py` (needs a 7.15 constant) are outside `eval/`, owned by Agents & Orchestration — not changed here.
- **Depends on:** Domain lead sign-off on this relabel (not yet obtained — applied here directly from clause 7.15's text, which this audit already read as unambiguous; still worth a second look); AGT-02, so the pipeline can reach the same answer.

### GOLD-02: The room-rent cut is applied to the wrong lines — **Fixed 2026-11-11**
- **Priority:** Critical
- **Where:** `gold_worksheets.jsonl`, CLM-0004, 0011, 0012 and 0014; 11 red-team cases; the rule wording in `data/README.md`.
- **Issue:** Gold cuts medicines and leaves the procedure line uncut. Note 4.1.1(b) cuts "all other expenses incurred at the Hospital, with the exception of cost of medicines". The data also contradicts itself: all 20 procedure lines have `room_linked: true`, and `data/README.md` says room-linked charges are cut, yet gold never cuts them.
- **Expected** (reference calculator, which follows the note):

  | Claim | Gold | Following the note | Difference |
  |---|---|---|---|
  | CLM-0004 | ₹102,313 | ₹80,990.23 | ₹21,322.77 |
  | CLM-0011 | ₹60,741 | ₹57,184.61 | ₹3,556.39 |
  | CLM-0012 | ₹78,511 | ₹67,575.39 | ₹10,935.61 |
  | CLM-0014 | ₹85,136 | ₹74,629.15 | ₹10,506.85 |

- **Fix:** Agree one reading in an ADR, correct `data/README.md`, relabel the four claims and rebuild the red-team set. These figures may change again with DEC-01 and GOLD-03.
- **Depends on:** Domain lead and T15 owners. `docs/experiments/reflexion/README.md` on `main` already lists this as an open finding.
- **Done:** The Domain lead ruled for the note in [ADR-0006](adr/0006-room-rent-proportional-cut.md). The four claims are relabelled: procedure, nursing and diagnostics are cut and cite `4.1.1`, and medicines are paid in full. New gold: ₹80,990, ₹57,184, ₹67,575 and ₹74,630, each within ₹1 of the calculator (GOLD-08 rounding). `data/README.md` is corrected. The red team is rebuilt (11 cases changed). Test: `tests/orchestration/test_cases.py::test_gold_room_rent_cut_follows_note_4_1_1_b`.
- **Still open:** DEC-01 (nursing inside the room limit?) can still move these four figures.

### GOLD-03: Gold ignores the 24-month specific waiting period — **Fixed 2026-11-11**
- **Priority:** Critical
- **Where:** `gold_worksheets.jsonl`, CLM-0008 (certain if DEC-02 confirms the first-policy date), CLM-0004 and CLM-0005 (conditional); 8 red-team cases. The demo ruleset in `data/README.md` has no such rule.
- **Issue:** Every claim has `specific_illness_waiting_months: 24` and a policy start of 2026-01-01. Gold applies the 30-day wait from that date, so it treats the date as the first policy, but it never applies clause 6.2. CLM-0008 ("Ureteroscopy with stone removal", admitted 2026-03-16) is labelled `normal_admissible` and pays ₹79,843, although 6.2.18 lists calculi in the urinary system under the 24-month wait. CLM-0004 and CLM-0005 are gallbladder removals. Clause 6.2.18 also lists the gall bladder, but those claims don't state the cause.
- **Expected:** CLM-0008 pays ₹0 or goes to review if this is the first policy. CLM-0004 and CLM-0005 need a stated cause (DEC-03).
- **Fix:** Add the rule to the ruleset, relabel the claims, and add a clear specific-wait test case.
- **Depends on:** CLAIM-01, DEC-02, DEC-03, AGT-02.
- **Done (ADR-0007):** Every claim states `policy.first_policy_inception_date`. CLM-0008 is a first policy, so it pays ₹0 under 6.2.18 (`specific_illness_waiting_period`). CLM-0004 and 0005 are renewals from 2023-01-01, so the wait has passed and DEC-03 no longer matters. The agent gap (no 6.2 check, AGT-02) is listed in `KNOWN_UNIMPLEMENTED_EXCLUSIONS`.

### GOLD-04: CLM-0016 pays an ICU day above the ICU limit — **Partially fixed 2026-11-04**
- **Priority:** High
- **Where:** `claims.jsonl` and `gold_worksheets.jsonl`, CLM-0016; 2 red-team cases.
- **Issue:** "ICU inpatient day (excluding procedure)" is ₹24,466 for one day, and gold pays it in full. Clause 4.1(b) and the demo ruleset both limit ICU to ₹10,000 a day at this sum insured. The line is filed as `procedure`, so no ICU rule runs. The claim also bills 6 ward nights plus an ICU day for a 6-night stay.
- **Expected:** The line is category `icu`, capped at ₹10,000, with Note 4.1.1(b) applied to the other charges.
- **Fix:** Re-file the line, resolve the overlapping day, recalculate.
- **Done:** `claims.jsonl` L01 category changed `procedure` → `icu`. Gold: L01 now allowed ₹10,000 / deducted ₹14,466, reason `icu_daily_cap`, clause `new_india_arogya_sanjeevani:4.1`. Room rent was already within its ₹5,000/day cap (no breach), so no proportional cut applies to the other lines under Note 4.1.1(b). Settlement ₹73,089 → ₹59,346. Red-team rebuilt. This also gives CLM-0016 a real sub-limit deduction, closing its half of GOLD-05.
- **Done ([ADR-0009](adr/0009-room-cap-nursing-duplicates-icu.md)):** The ICU day is one of the 6 nights, so the fixture now bills 5 ward nights and 5 days of ward nursing. An ICU breach also triggers the Note 4.1.1(b) cut. Settlement ₹40,825.
- **Depends on:** Domain lead, specifically for the overlapping-day question above; the calculator's ICU rule (T15).

### GOLD-05: The `sub_limit` scenario tests no sub-limit — **Fixed 2026-11-11**
- **Priority:** High
- **Where:** `gold_worksheets.jsonl`, CLM-0016 and CLM-0019; 4 red-team cases.
- **Issue:** Both claims have the flag `sub_limit`, but no gold line uses a `sub_limit` reason code. Cataract, the only sub-limit in the demo rules, appears in no dev claim. `history.sub_limit_used_inr` is 0 and `prior_claims` is empty on all 20. Capstone guide p.10 requires "sub-limits partly used by earlier claims".
- **Expected:** At least one claim where a sub-limit changes the amount, and one where an earlier claim used part of it.
- **Fix:** Add cataract claims, including a partly used limit. Relabel CLM-0016 and CLM-0019.
- **Depends on:** T22, T39; prior-claim mapping in `policy_from_fixture`, which currently raises if `prior_claims` is present.
- **Done (ADR-0007):** Added CLM-0021 (cataract, capped at clause 4.3, ₹38,000) and CLM-0022 (₹25,000 of 4.3 used by an earlier claim on the same eye, ₹14,250). `prior_claims` is mapped by `history_from_fixture`. CLM-0019 is relabelled `normal_admissible` with no flag. The calculator still doesn't apply 4.3, because the contract has no eye field.

### GOLD-06: Review flags don't match reason codes — **Fixed 2026-11-11**
- **Priority:** Medium
- **Where:** `gold_worksheets.jsonl`; `eval/redteam/gold.jsonl`.
- **Issue:** CLM-0001, 0002, 0003 and 0017 fail on the waiting period but have no `waiting_period` flag. CLM-0008 and 0020 deduct a non-payable line but have no `non_payable_items` flag. Five red-team cases inherit the second problem. `docs/TEAM_GUIDE.md` notes that flags follow the scenario rather than every rule.
- **Expected:** A flag for every rule that fired, or a documented rule that flags name only the main scenario. Flag scoring can't be trusted until one of these is chosen.
- **Fix:** Generate flags from the reason codes.
- **Depends on:** T39, T41.
- **Done (ADR-0007):** Flags are derived from reason codes, and a not-admissible claim carries only its gate's flag. Enforced by `tests/test_dataset_integrity.py::test_gold_flags_follow_reason_codes` (also REC-02, in part).

### GOLD-07: Gold has no clause IDs — **Partially fixed 2026-11-04**
- **Priority:** High
- **Where:** `gold_worksheets.jsonl`; `gold_from_fixture` in `src/claimsense/reflexion/cases.py` (on `main`).
- **Issue:** No gold row contains a clause ID, but `eval/README.md` lists clause grounding as a metric. The loader infers `gold_clause_choices` from reason codes through the constants in `agents/clauses.py`, four of which are placeholders (AGT-01). Lines with no deduction default to `C.HOSPITALISATION`.
- **Expected:** Each deduction in the gold cites the clause a person chose.
- **Fix:** Add `clause_id` to each deduction during T39.
- **Done:** Added a `clause_id` field directly on every gold deduction where the mapping is unambiguous from this document and ADR-0004/AGT-01: `initial_waiting_period_not_elapsed` → `6.3` (all 6 claims), `room_rent_daily_cap`/`room_rent_proportional_reduction` → `4.1` (CLM-0004, 0011, 0012, 0014), `non_payable_item_demo_rule` → `annexure-a.list-i` (CLM-0006, 0008, 0020), `icu_daily_cap` → `4.1` (CLM-0016), `maternity_childbirth_exclusion` → `7.15` (CLM-0018). This field is informational in the gold file itself; `gold_from_fixture` still derives its own clause choice from `CLAIM_REASONS`/`LINE_REASONS` in `cases.py`, which is unchanged here.
- **Still open:** `duplicate_line` deductions (CLM-0005, 0009, 0010, 0015) have no `clause_id` — that is DEC-04, not a lookup gap. CLM-0013's `admission_or_discharge_outside_policy_period` gate ~~also has none~~ cites clause 2, the Operative Clause, since 2026-11-11 ([ADR-0008](adr/0008-policy-period-clause.md)). AGT-01's four placeholder constants in `agents/clauses.py` are also still unresolved (outside `eval/`).
- **Depends on:** AGT-01; RET-02; DEC-04 (duplicate lines); a confirmed policy-period clause (CLM-0013).

### GOLD-08: Gold uses whole rupees, the calculator uses paise — **Fixed 2026-11-11**
- **Priority:** Medium
- **Where:** `gold_worksheets.jsonl`; `Money` in `src/claimsense/contracts/claim.py`; the evaluator on `main`.
- **Issue:** Six dev claims differ from the pipeline only by rounding, and cut lines can differ by up to ₹0.50, which the simulated adjudicator counts as an edit.
- **Expected:** Rounding never counts as a mistake.
- **Fix:** Relabel gold to paise, or add a tolerance. `docs/experiments/reflexion/README.md` names Spandan's evaluator as the place for a tolerance.
- **Depends on:** Eval & Red-Team, Spandan.
- **Done (ADR-0007):** The gold stays in rupees, and the eval harness CLIs default `--tolerance-inr` to 1. The Reflexion scripts keep their explicit `--tolerance-rs`.

## Claim fixture data

### CLAIM-01: Waiting periods can't be decided from the fixture
- **Priority:** High
- **Where:** `eval/golden_dev/claims.jsonl`; `policy_from_fixture` in `reflexion/cases.py` (on `main`); the TODO at `src/claimsense/agents/coverage.py:76`.
- **Issue:** No claim has a first-policy date, continuous-coverage period or accident indicator. Clause 6.2 runs from "inception of the first policy" and exempts accidents, and clause 6.3 stops applying after 12 months of continuous coverage. The loader sets `first_inception` to the policy start, which assumes every patient is on a first policy.
- **Expected:** These facts are stated per claim, not assumed.
- **Fix:** Add `first_policy_inception_date` and an accident field, and map them in the loader. An accident field on `contracts.Claim` needs a two-role PR.
- **Depends on:** DEC-02; the contract PR.

### CLAIM-02: Raw fixtures don't validate against the claim contract
- **Priority:** Medium
- **Where:** `claims.jsonl`; `Claim` in `src/claimsense/contracts/claim.py`.
- **Issue:** `Claim.model_validate` on CLM-0004 gives 21 errors (ADR-0002). `packet_from_fixture` on `main` maps fixtures correctly and has tests, but it invents each source span (`start: 0`, `end: len(description)`).
- **Expected:** One supported route from fixture to contract, with honest spans.
- **Fix:** Keep the adapter as the single mapping and record that decision, closing ADR-0002. Don't add a second mapping.
- **Depends on:** Eval & Red-Team, Agents & Orchestration.

### CLAIM-03: Document text never reaches the agents, so 16 of 30 attacks are lost
- **Priority:** High
- **Where:** `documents` in `claims.jsonl` and `eval/redteam/claims.jsonl`; `packet_from_fixture` on `main`.
- **Issue:** Dev documents are one-line placeholders, such as "Fictional discharge summary for Appendectomy". The loader returns `documents: {}` on purpose, so `verify_spans` and `find_injections` in `agents/extraction.py` have nothing to check. Tested on the red-team set, none of the 12 discharge-summary and itemised-bill attacks and none of the 4 RT-004 date attacks reach the packet. Only the 6 bill-line attacks do among the injection cases.
- **Expected:** Every attack reaches the agent it is meant to test.
- **Fix:** Write realistic synthetic documents, and pass them through for red-team runs.
- **Depends on:** T39; extraction work. Guide p.10 asks for claim packets that are generated and then edited by hand.

### CLAIM-04: Bill-line categories don't describe the lines
- **Priority:** Medium
- **Where:** `category` in `claims.jsonl`; `CATEGORY_MAP` in `reflexion/cases.py` (on `main`).
- **Issue:**
  - Six `procedure` lines aren't procedures: 5 "Pneumonia inpatient episode" and 1 ICU day.
  - "Medicines and consumables" combines two things the policy may treat differently, because List I of Annexure-A covers many consumables. The loader treats the whole line as medicines.
  - No claim has an `icu`, `doctor_fees` or `ot` line, so those calculator paths have no dev test.
- **Expected:** Categories match what was billed, and medicines are billed separately from consumables.
- **Fix:** Split the lines and add the missing categories.
- **Depends on:** DEC-01; T39. Changing descriptions also means updating `bill_line_dev` rows in `retrieval_queries.jsonl`.

### Missing edge cases
All counts are from the 20 dev claims. The set needs these before T39 is complete.

| Edge case | Dev claims today | Why it matters |
|---|---|---|
| Declared pre-existing disease | 0 | Clause 6.1 and the 36-month call in ADR-0004 are untested |
| Specific waiting period, clearly tested | 0 (GOLD-03) | Clause 6.2 |
| Cataract or other sub-limit | 0 | Clause 4.3; guide p.10 |
| Sub-limit partly used by an earlier claim | 0 | Guide p.10; the fraud agent's used-limit check has no data |
| Duplicate across claims (`prior_claims`) | 0 | The fraud agent only checks history, so it has no dev test |
| Real `icu` line | 0 | ICU cap and Note 4.1.1(b) on ICU |
| Maternity or other section 7 exclusion labelled correctly | 0 (GOLD-01) | Section 7 |
| Accident exemption | 0 | Clauses 6.2 and 6.3 |
| Admission on the 30-day boundary | 0 | The nearest are 2026-01-24 and 2026-03-13 |
| Stay crossing the policy end date | 0 | Only one out-of-period claim exists, at the start |
| Sum insured small enough for 2% to set the room cap | 0 | The lowest sum insured is ₹300,000, so the cap is always ₹5,000 |
| Bill above the sum insured | 0 | No test of the overall limit |
| Same-day or day-care stay | 0 | The shortest stay is 3 nights; Annexure-C is untested |
| Patient mismatch | 0 | `check_admissibility` has this path; RT-005 has no test |

**Already covered:** room charged exactly at the cap (CLM-0009, 0010, 0013, 0016) and settlements above the ₹100,000 senior threshold (CLM-0004, 0010, 0015, 0018, 0019).

**Weak cases:** CLM-0001, 0002, 0003 and 0017 are labelled with other scenarios, but the 30-day wait sets them to ₹0, so they don't test their named rule in rupees. Only 4 of the 6 `room_rent_breach` claims exercise the room cut. Five groups of claims share a scenario and diagnosis, and four claims share the admission date 2026-01-24. These are near-duplicates rather than errors.

## Retrieval evaluation

### RET-01: "Any listed clause" overstates search quality
- **Priority:** High
- **Where:** `clauses` in `eval/golden_dev/retrieval_queries.jsonl`; `first_hit_rank` in `src/claimsense/retrieval/evaluate.py`.
- **Issue:** Finding any one listed clause counts as a hit. That suits R01, where 4.1 and 12.1 state the same limit. It doesn't suit R32, where 4.1 covers treatment and 6.2.6 sets the waiting period. R31, R32 and R35 score as hits while missing a clause the agent needs. Recall@5 is 0.915 (43 of 47) with any-of, and 0.851 (40 of 47) if every listed clause must be in the top 5. The stricter figure comes from a one-off run, so it isn't on a chart yet.
- **Expected:** Labels separate "same fact stated twice" from "different facts, all needed".
- **Fix:** Group the labels (any-of within a group, all groups required), and report both scores with a chart.
- **Depends on:** Eval & Red-Team review; change it before the Domain lead verifies the labels.

### RET-02: All 47 labels are unverified drafts
- **Priority:** High
- **Where:** `status` in `retrieval_queries.jsonl`.
- **Issue:** All 47 rows are `draft_domain_lead_to_verify`. "Appendectomy", "angioplasty", "pneumonia", "cholecystectomy", "ureteroscopy" and "comfort" appear nowhere in the policy text, so R27, R28, R30, R33, R34 and R35 rest on inference.
- **Expected:** A person verifies each row.
- **Fix:** Domain lead reviews these six first and marks rows verified.
- **Depends on:** RET-01.

### RET-03: Two tools score the same file differently
- **Priority:** Medium
- **Where:** `src/claimsense/retrieval/evaluate.py`; `course/scripts/evaluate_dev.py`.
- **Issue:** The product tool counts a row as a hit if any listed clause is found. `retrieval_only` in the course kit counts the share of all listed clauses found. The same label `recall` therefore means different things, and multi-clause rows are affected.
- **Expected:** One definition per metric name.
- **Fix:** Rename one metric. Follow RET-01 if labels gain groups. `course/` changes need Eval & Red-Team review.
- **Depends on:** RET-01.

### RET-04: Labels cover few clauses
- **Priority:** Medium
- **Where:** `retrieval_queries.jsonl`.
- **Issue:** The labels use 26 of 172 searchable clauses, and 22 of 47 rows include clause 4.1. Section 7 (exclusions) has 1 of 23 clauses covered, section 6 has 8 of 26, section 9 has 1 of 11, section 3 has 1 of 60 and section 10 has 0 of 26.
- **Expected:** The clauses that decide money are all measured, especially exclusions and waiting periods.
- **Fix:** Add exclusion and waiting-period queries before T56. Keep them out of the rewrite glossary unless they come from dev claim terms.
- **Depends on:** Domain lead.

### RET-05: Search has no way to say "nothing relevant"
- **Priority:** Medium
- **Where:** `HybridRetriever.search` in `src/claimsense/retrieval/search.py`; `retrieval_queries.jsonl`.
- **Issue:** `search` has no score threshold. "best biryani in Hyderabad" returns 3.6, 3.7 and 3.28 with scores near -11. No label row tests a query with no answer.
- **Expected:** The behaviour is measured and known to callers.
- **Fix:** Add negative queries, then decide on a threshold with data. Agents must treat every result as a candidate meanwhile.
- **Depends on:** T56.

## Answer evaluation

### EVAL-01: The product has no evaluation harness
- **Priority:** High
- **Where:** `eval/`; `.github/workflows/ci.yml`.
- **Issue:** `eval/` holds data and `build_cases.py` only. The commented CI gate runs `python -m eval.run`, which doesn't exist. Of the metrics in `eval/README.md`, only rupee error and exact settlement match are reported by product code (the reflexion runner on `main`, which also reports edit rate and critic rejections). The other scoring code is the teaching copy in `course/evalkit/metrics.py`.
- **Expected:** A harness scoring amounts, line items, clause grounding, flags, routing, latency and cost (T41).
- **Fix:** Build T41 on the relabelled gold.
- **Depends on:** T22, T39.

### EVAL-02: Explanations and rationales aren't scored
- **Priority:** Medium
- **Where:** `config/models.yaml` (`judge`); `LineChoice.rationale` in `agents/coverage.py`.
- **Issue:** The `judge` model is configured, but nothing in `src/` uses it. Nothing checks whether a rationale matches the cited clause. The critic checks only the deduction reason.
- **Expected:** Explanation quality is measured by a judge calibrated on human labels, as `eval/README.md` describes.
- **Fix:** Add this to T41.
- **Depends on:** EVAL-01; AGT-04.

## Agents integration

### AGT-01: Four clause constants are placeholders
- **Priority:** Critical
- **Where:** `src/claimsense/agents/clauses.py:18-21`; `FULLY_DEDUCTED` at `src/claimsense/agents/services.py:117`.
- **Issue:** `INITIAL_WAITING_PERIOD`, `PED_WAITING_PERIOD`, `SPECIFIC_WAITING_PERIOD` and `NON_PAYABLE_ITEMS` aren't real clause IDs. With real search, a non-payable clause isn't recognised: on the worked example the pipeline pays ₹45,328.58 instead of ₹43,428.58, and the critic passes it.
- **Expected:** `6.3`, `6.1`, `6.2` and `annexure-a.list-i`, prefixed as usual. `NON_PAYABLE_ITEMS` needs the product prefix too.
- **Fix:** Replace the values and test against the knowledge base.
- **Depends on:** Nothing. Owner: Agents & Orchestration.

### AGT-02: Exclusions and specific waiting periods never deduct
- **Priority:** Critical
- **Where:** `check_admissibility` at `src/claimsense/agents/coverage.py:66`; `FULLY_DEDUCTED`; `reference_calculate`.
- **Issue:** `check_admissibility` has no rule for clause 6.2 or section 7. CLM-0018 and CLM-0008 both come back `admissible`. Choosing 7.15, 6.2.6 or 6.3 for every line of CLM-0018 still pays ₹112,272.90 with no deductions, because `FULLY_DEDUCTED` holds only the four placeholders. Search can return list items like `6.2.6`, which a single `6.2` ID can't match.
- **Expected:** Choosing an exclusion or an unserved waiting-period clause deducts the line, or the claim fails admissibility.
- **Fix:** Decide the mapping with T15's owners, for example by clause prefix, and cover it with hand-worked tests.
- **Depends on:** AGT-01, CLAIM-01, T15.
- **Done since:**
  - Maternity: `coverage.py` excludes childbirth under 7.15 (GOLD-01).
  - `FULLY_DEDUCTED` holds the real waiting-period, 7.15 and clause-2 ids.
  - **ADR-0010 (2026-11-12):** a not-admissible claim gets its ₹0 worksheet from the calculator,
    with every line under the gate's clause. `clauses.CLAIM_LEVEL` keeps those clauses out of
    per-line choices.
- **Still open:** admissibility has no 6.2 specific-waiting check (CLM-0008, DEC-02), and `6.2.x`
  list items still don't match `6.2`.

### AGT-03: Duplicate lines inside one bill aren't caught — **Flag fixed 2026-11-11 (B5); deduction waits on DEC-04**
- **Priority:** High
- **Where:** `src/claimsense/agents/fraud.py:31-36`.
- **Issue:** The fraud agent compares lines only with earlier claims. CLM-0009 gives no flags and pays the duplicate line (₹3,095). This affects CLM-0005, 0009, 0010 and 0015. Gold deducts these lines and looks right. Fraud flags never change amounts by design, and every `Deduction` must cite a clause, but no clause covers duplicates.
- **Expected:** An in-bill duplicate is flagged and doesn't get paid.
- **Fix:** Add the check, and settle DEC-04 on how a duplicate is deducted.
- **Depends on:** DEC-04; T27.
- **Done (B5):** `fraud.py` step 1b flags a line with the same category, description (case and spacing ignored) and amount as an earlier line in the same bill: `duplicate bill lines within this bill: L06 repeats L05`. The claim goes to a person. CLM-0005, 0009, 0010, 0015 and red-team RT-003 are now caught, with no flag on any other dev claim. Test: `tests/orchestration/test_fraud_checks.py`.
- **Done (ADR-0009):** The reference calculator deducts the duplicate (clause 2), so the amounts now match the gold. `calc/adjudication.py` still has to follow.

### AGT-04: Untrusted bill text isn't marked as data in the coverage prompt
- **Priority:** High
- **Where:** `_ask_model` at `src/claimsense/agents/coverage.py:147`.
- **Issue:** `SYSTEM` tells the model that text in `<document>` tags is data, but `_ask_model` puts `line.description`, diagnosis, procedure and clause text in the prompt without those tags. Only `agents/extraction.py` calls `as_data`. `wrap_as_data` in `guardrails.py` delegates to it, but nothing calls that. The 6 bill-line red-team attacks reach this prompt. This weakens `CLAUDE.md` rule 2, although the calculator and approval gate still protect the money.
- **Expected:** All outside text is wrapped as data.
- **Fix:** Use `as_data` for each bill line and candidate.
- **Depends on:** Guardrails owner, if `wrap_as_data` should be used instead of `as_data`.

### AGT-05: `REWRITE` in `coverage.py` conflicts with real search
- **Priority:** High
- **Where:** `src/claimsense/agents/coverage.py:40`, applied at lines 96-99.
- **Issue:** `REWRITE` replaces the bill wording before search, and search has its own glossary that keeps the original. "Medicines and consumables" is sent as "medicines and excluded items consumables non-payable". Clause 4.1 then leaves the top 5 and List I (non-payable) rises to rank 2. "Pharmacy" also loses 4.1.
- **Expected:** Search receives the original bill wording.
- **Fix:** Delete `REWRITE` when wiring in real search.
- **Depends on:** Real search on the agents' branch.

### AGT-06: The model sees only the first 400 characters of each candidate
- **Priority:** High
- **Where:** `src/claimsense/agents/coverage.py:150`.
- **Issue:** `p.clause.text[:400]` cuts off the operative text. In clause 4.1's context text, "Room Rent" is visible, but "Surgeon" starts at character 616 and "operation theatre" at 796.
- **Expected:** The model sees enough text to choose correctly.
- **Fix:** Remove or raise the cut, and watch prompt size, because a chunk's context text can reach 1,902 characters.
- **Depends on:** Nothing.

### AGT-07: An empty search result crashes coverage
- **Priority:** High
- **Where:** `src/claimsense/agents/coverage.py:129` and `:142-143`.
- **Issue:** `ps[0]` raises `IndexError` when search returns no candidates. Real search returns `[]` for a blank query, and `BillLine.description` allows blank text. The stub always returned something, so this has never appeared.
- **Expected:** The line goes to human review, and the claim doesn't crash.
- **Fix:** Handle the empty case and add a test.
- **Depends on:** Nothing.

### AGT-08: The 36-month wait is calculated as 1,080 days
- **Priority:** Medium
- **Where:** `src/claimsense/agents/coverage.py:81`.
- **Issue:** `timedelta(days=36 * 30)` ends on 2026-12-16 for a first policy of 2024-01-01, while 36 months ends on 2027-01-01. The code has a TODO, and no dev claim tests it.
- **Expected:** Exact month arithmetic. The 36-month answer itself is settled in ADR-0004, so that part of the TODO can close.
- **Fix:** Use month arithmetic, with a boundary test.
- **Depends on:** Pre-existing-disease dev case.

### AGT-09: Model IDs and prompts aren't in `config/`
- **Priority:** Medium
- **Where:** `MODELS` at `src/claimsense/agents/llm.py:14`; `config/models.yaml`; `config/prompts/`.
- **Issue:** `CLAUDE.md` says prompts and model IDs live only in `config/models.yaml`. Agents use hard-coded defaults that disagree with it: coverage is `openai/gpt-4.1-mini` in code and `openai/gpt-4o-mini` in the YAML. `model_for` in `config.py` has no callers. `config/prompts/` is empty, and prompts are inline strings.
- **Expected:** Agents read `model_for(role)` and versioned prompts.
- **Fix:** Move them when the agent prompts settle.
- **Depends on:** Nothing.

### AGT-10: The T15 calculator isn't implemented
- **Priority:** High
- **Where:** `src/claimsense/calc/adjudication.py`; `real_calculate` in `agents/services.py`; `tests/calc/test_adjudication.py`.
- **Issue:** All five functions raise `NotImplementedError`, and the three calculator tests are skipped. `real_services()` therefore can't produce a worksheet. The dev-only `reference_calculate` is doing this job today.
- **Expected:** Hand-worked tests pass (due 2026-11-13 on the tracker).
- **Fix:** Implement T15 after settling DEC-01 and GOLD-02.
- **Depends on:** Domain lead and Eval, who write the hand-worked cases.

### AGT-11: The `policy-kb` MCP tools are stubs
- **Priority:** High
- **Where:** `src/claimsense/mcp_servers/policy_kb.py`.
- **Issue:** `search_wording` and `get_clause` both return a "not implemented" `ToolError`. The search they need now exists. See AGT-14 for the second server on `main`.
- **Expected:** Both call `HybridRetriever` and return structured errors.
- **Fix:** Implement T16. See `docs/RAG_ARCHITECTURE_AND_IMPLEMENTATION.md`.
- **Depends on:** AGT-12. Owner: Tools & Security.

### AGT-12: The policy contract can't carry what search returns
- **Priority:** High
- **Where:** `Clause` and `RetrievedPassage` in `src/claimsense/contracts/policy.py`.
- **Issue:** `Clause.effective_date` is required, but no document states one (ADR-0004). `RetrievedPassage` has no `chunk_id` or page numbers, so citations lose their page reference.
- **Expected:** `effective_date` is optional, and passages carry `chunk_id` and pages.
- **Fix:** Open a contract PR reviewed by two roles.
- **Depends on:** Reviewers from two roles.

### AGT-13: `get_clause` omits the headings that give list items meaning
- **Priority:** Medium
- **Where:** `FullClause` and `HybridRetriever.get_clause` in `src/claimsense/retrieval/search.py`; `CriticAgent._supports` in `src/claimsense/agents/critic.py`.
- **Issue:** `get_clause` for `6.2.6` returns just "6. Hysterectomy". The critic's keyword check therefore fails for 6.2.6, 6.2.18 and 7.15, and a correct deduction would be rejected. `SearchHit.context_text` has the headings, but `FullClause` has no equivalent.
- **Expected:** The critic receives the heading context.
- **Fix:** Add `context_text` to `FullClause`. Until then, use the interim adapter in the RAG handoff.
- **Depends on:** Nothing. Owner: Knowledge & Memory.

### AGT-14: `policy_server.py` bypasses hybrid search and breaks ADR-0004
- **Priority:** High
- **Where:** `src/claimsense/mcp_servers/policy_server.py` (on `main`, commit `c6ecb69`), `PolicyKnowledgeBase`, `_load_jsonl`, `_repo_root`.
- **Issue:** This second `policy-kb` server was written before hybrid search reached `main`. Tested on a scratch copy of `main` merged with the RAG branches:
  - **Wrong default path.** It looks in `src/claimsense/ClaimSense-Insurance/data/...`. Without `CLAIMSENSE_KB_PATH` or `CLAIMSENSE_REPO`, the tools return `kb_missing` and `policy_search` raises `FileNotFoundError`.
  - **Keyword only.** It has no vectors, RRF, reranker or glossary. Recall@5 on the 47 draft labels is 0.745, against 0.915 for `HybridRetriever`. For `bill_line_dev` it is 0.529, or 0.765 with the line's category, against 0.824.
  - **Empty results.** "Appendectomy", "RMO visit" and "Pharmacy" return nothing, which crashes coverage (AGT-07).
  - **Split clauses cut short.** `_load_jsonl` keeps the first chunk per clause, so `get_clause` returns 1,799 of 9,956 characters for `annexure-c`, 1,798 of 2,708 for `5` and 1,791 of 1,891 for `9.4`.
  - **Row `12.5` is served.** It ignores `searchable`, and the row ranks first for pre-existing disease queries, against ADR-0004.
  - **Not connected.** No code or test uses it. `load_policy_kb` mentions a `role4_services` module that doesn't exist.
- **Expected:** One `policy-kb` server that serves `HybridRetriever`, honours `searchable`, returns whole clauses and finds its data by default.
- **Fix:** One option is to keep this file's tool names, contract mapping and `ToolError` wrappers, replace its search with `HybridRetriever`, and remove the `policy_kb.py` stub. Add tests. `Clause.text` also has the same missing-headings problem as AGT-13.
- **Depends on:** Tools & Security to decide; AGT-12.

---

# Part 2: Decisions needed
These need a person's ruling. The wording and the current behaviour were checked, but the answer isn't a code question.

### DEC-01: Does the ₹5,000 room limit include nursing? — **Decided 2026-11-11 (ADR-0009): yes, reading A**
- **Priority:** Critical
- **Where:** Clause 4.1(a), table row 12.1; `gold_worksheets.jsonl`; `reference_calculate`; T15.
- **Issue:** Clause 4.1(a) limits "Room Rent, Boarding, Nursing Expenses" to ₹5,000 a day, and row 12.1 adds "all inclusive". Gold and the reference calculator cap room rent alone. All 14 paid claims exceed ₹5,000 once nursing is added, so 10 more become room breaches: CLM-0005, 0006, 0008, 0009, 0010, 0015, 0016, 0018, 0019 and 0020. For example, CLM-0020 is ₹4,000 + ₹1,525 = ₹5,525. No ADR or experiment report discusses this reading.
- **Recommendation:** Treat nursing as inside the cap unless the Domain lead finds a reason not to, because that is the plain wording. This would change nearly every paid amount, so decide it first.
- **Depends on:** Domain lead and T15 owners, before 2026-11-13.
- **Decided:** [ADR-0009](adr/0009-room-cap-nursing-duplicates-icu.md). Room, boarding and nursing share one cap. The Note 4.1.1(b) ratio is cap ÷ (room + nursing per day). The gold is relabelled and `reference_calculate` is updated. `calc/adjudication.py` (Tools & Security) still has to follow.

### DEC-02: Is 2026-01-01 the first policy date? — **Decided 2026-11-11 (ADR-0007)**
- **Priority:** High
- **Where:** `claims.jsonl`; `policy_from_fixture` on `main`.
- **Issue:** If yes, clause 6.2's waits apply to all 20 claims. If some are renewals, the 30-day ₹0 outcomes may change as well.
- **Recommendation:** State it per claim (CLAIM-01), with a mix of first policies and renewals.
- **Depends on:** Domain lead.

### DEC-03: Was the gallbladder removal for gallstones? — **Moot 2026-11-11 (ADR-0007: renewals past the wait)**
- **Priority:** Medium
- **Where:** CLM-0004, CLM-0005.
- **Issue:** Clause 6.2.18 depends on calculi, and these claims don't state the cause.
- **Recommendation:** State the cause in the synthetic claim, or send it to review.
- **Depends on:** Domain lead.

### DEC-04: How should a duplicate line be deducted? — **Decided 2026-11-11 (ADR-0009)**
- **Priority:** High
- **Where:** `Deduction` in `contracts/worksheet.py`; `fraud.py`; `LINE_REASONS` in `reflexion/cases.py` on `main`.
- **Issue:** Gold pays ₹0, `Deduction.clause_id` is required, no clause applies, and the loader's marker `fraud:duplicate_line` would fail the critic against real `get_clause`.
- **Recommendation:** Make it an explicit non-clause reason, or have a person remove the line and record that.
- **Depends on:** Domain lead, Agents & Orchestration. A contract change needs two roles.
- **Decided:** [ADR-0009](adr/0009-room-cap-nursing-duplicates-icu.md). The duplicate is deducted in full, reason `other`, citing clause 2 (Operative Clause: only expenses incurred are indemnified). It is excluded from every rate calculation. The B5 flag still sends the claim to a person, who can restore a genuine repeat. No contract change.

---

# Part 3: Recommendations
These are improvements, not defects.

| ID | Priority | Recommendation | Where | Depends on |
|---|---|---|---|---|
| REC-01 | Medium | Eval & Red-Team should check the held-out gold for GOLD-01 to GOLD-07. It came from the same starter pack (ADR-0002). | `../claimsense-heldout/` | Eval only |
| REC-02 | Medium | Turn the checks in "What passed" into tests. `tests/test_dataset_integrity.py` checks only claim IDs, count and `synthetic`. Add reason-versus-flag and clause-existence checks. | `tests/test_dataset_integrity.py` | T41 |
| REC-03 | Medium | Rebuild red-team gold after any dev relabel, because 19 of 30 cases sit on a claim with a disputed amount. | `eval/redteam/build_cases.py` | GOLD-01 to GOLD-04 |
| REC-04 | Medium | Don't pass `potentially_payable` or `room_linked` to agents, because they give away answers. The product loader already omits them, but `HIDDEN` in `course/claimsense_hw/tools.py` strips only `scenario_label` and `fixture_notes`. | `course/claimsense_hw/tools.py` | Eval review |
| REC-05 | Low | Move the 3 `bill_line_dev` queries that aren't in dev claims (OT charges, RMO visit, Pharmacy) to their own kind, or define the kind to include them. They came from the worked example and `REWRITE`. | `retrieval_queries.jsonl` | Eval review |
| REC-06 | Low | Add `encoding="utf-8"` to `read_text()` in `load_cases`. The files are ASCII today, so this is harmless until a relabel adds a ₹ or similar. | `reflexion/cases.py` on `main` | None |
| REC-07 | Low | Update stale counts: `CLAUDE.md:52`, `docs/TEAM_GUIDE.md` (12 queries, 167 chunks) and `course/README.md`, `course/RUBRIC.md` (167). Current values are 47 queries and 181 chunks. Rebuild the guide with `python scripts/build_team_guide.py`. | Listed files | Merge of the RAG branches |

## Suggested order
1. **This week:** The Domain lead and T15 owners settle DEC-01, GOLD-02 and DEC-02 in an ADR, because T15's tests depend on them. Agents & Orchestration fixes AGT-01, AGT-05, AGT-06 and AGT-07 while wiring in search.
2. **Next:** Implement T15 and T16, and open the contract PR (AGT-10, AGT-11, AGT-12).
3. **For T22 and T39:** Eval & Red-Team relabels the gold, adds the missing edge cases and rebuilds the red-team set. They should also check the held-out set.
4. **Then:** Rerun the reflexion baseline and treat earlier scores as measured against the old gold.
