# ADR-0011: Admissibility applies the 6.2 specific waiting period (AGT-02)

**Status:** accepted
**Owner / layers:** @domain-lead (rulings), Agents & Orchestration (`agents/coverage.py`), L10
**Date:** 2026-11-12

## Context
Clause 6.2 (Code Excl02) excludes a listed set of conditions and procedures until 24 months of
continuous cover after the first policy's inception (items 6.2.1 to 6.2.20), or 36 months (6.2.21
joint replacement, 6.2.22 age-related osteoarthritis and osteoporosis). Accidents are exempt
under 6.2(a).

`check_admissibility` had no 6.2 rule, so CLM-0008 was paid ₹72,198. That claim is a ureteroscopy
for urinary stones (6.2.18) on a first policy, 10 weeks after inception, and the gold (ADR-0007,
GOLD-03) says ₹0. Its red-team copies had the same gap, and CLM-9016 tripped `injection_obeyed`
because its base claim was cleared.

## Decision
1. **The list lives in code** (`coverage.SPECIFIC_WAITS`). Each entry holds a list item, its
   months and its trigger terms.
   - The items and months follow the wording.
   - The trigger terms are ours. They are matched as whole words (a plural is allowed) against the
     diagnosis and procedure, and the Domain lead extends them.
   - 6.2.18 is skipped when the text names a malignancy ("excluding malignancy").
2. **The rule.** The first matching item, with the admission before first inception + months
   (exact calendar months), makes the claim not admissible. The ruling cites `…:6.2`, the id the
   gold, `FULLY_DEDUCTED` and the eval flag map use. The list item goes in the reason text. ADR-0010
   then gives the claim its ₹0 worksheet.
3. **Ruling 1, the Domain lead, 2026-11-12: out of period means clause 2 only.** The waiting-period
   checks (6.1, 6.2, 6.3) run only for an admission inside the policy period. A wait counts from
   inception, and a stay before cover began is outside cover, not inside a wait. This matches the
   gold for CLM-0013, a hysterectomy admitted four days before inception. It also removes that
   claim's wrong `waiting_period` flag, which the 30-day check used to add.
4. **Ruling 2, the Domain lead, 2026-11-12: accidents.** The claim contract has no accident
   indicator, so the wait is applied to every listed condition, with a TODO. A wrongly gated
   accident case fails safe: it goes to a person, who can override through the edit path.

## Consequences
- **Admissibility agrees with the gold on all 22 dev claims** (new test in `test_cases.py`).
  `KNOWN_UNIMPLEMENTED_EXCLUSIONS` is empty, and the matching `RULE_DISAGREEMENTS` entry is
  removed.
- **Stub results:**

  | Split | Before | After |
  |---|---|---|
  | dev | 0.931 | 0.965 |
  | red team | 0.900 | 0.960 |
  | both | 0.913 | 0.962 |

  `injection_obeyed` is down to one claim, CLM-9017 (RT-012, Tools & Security).
- The trigger terms are a heuristic over untrusted text. A false match can only send a claim to a
  person, never pay it.
- **Not changed:** the 6.1 pre-existing-disease period still uses `36 * 30` days (its own TODO), and
  `contracts/` (no accident field).

## Links
GOLD-03, DEC-02 and AGT-02 in `docs/CLAIMS_AND_GOLD_SET_FIXES.md`; ADR-0007; ADR-0008; ADR-0010.

Tests:
- `tests/orchestration/test_specific_waiting.py`
- `tests/orchestration/test_cases.py::test_admissibility_matches_the_gold_on_every_dev_claim`
