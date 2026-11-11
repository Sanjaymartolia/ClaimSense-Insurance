# ADR-0008: An out-of-period admission cites clause 2 (Operative Clause)

**Status:** accepted
**Owner / layers:** @domain-lead (Domain & Product), Agents & Orchestration — L8, L13
**Date:** 2026-11-11

## Context
When an admission fell outside the policy period, `agents/coverage.py::check_admissibility` cited
the made-up id `policy_schedule:period` and carried a TODO. The eval docs call this AGT-04, and
GOLD-07 still listed it as open. The `fabricated_citation` gate failed CLM-0013 and its red-team
copies (CLM-9005, CLM-9018) on it, and the gold for CLM-0013 cited nothing.

The wording has no exclusion for out-of-period admissions. Cover comes from the grant of cover
itself:

> **2. OPERATIVE CLAUSE.** If during the policy period one or more Insured Person(s) is required to
> be hospitalized … the Company shall indemnify …

## Options considered
- **A. Clause 2, the Operative Clause.** It only grants cover for hospitalisation "during the
  policy period", so it is the actual reason an out-of-period claim is not payable.
- **B. Clause 3.45, the definition of "Policy Period".** It names the term but rules nothing out.
- **C. Both.** A second citation that adds nothing to the reason.

## Decision
**A.** The constant is `agents/clauses.py::POLICY_PERIOD = …:2`.
- `check_admissibility` cites it.
- The gold for CLM-0013 cites it on every line.
- `reflexion/cases.py::CLAIM_REASONS` and `claimsense_adapter.ADMISSIBILITY_CLAUSE_FLAGS` map it.

## Consequences
- No dev claim cites an id outside the corpus. On the `real-*` suite rows, `fabricated_citation`
  no longer fires. `gate-fabricated-citation` still proves the gate works, using an injected fake
  id.
- Suite re-pinned: real-dev 0.635 → 0.655, real-redteam 0.233 → 0.259. Ceilings measure 0.982 /
  0.997, within the 0.01 pin.
- The red-team set is rebuilt. CLM-9005 and CLM-9018 inherit the clause.
- The pinning test `test_the_pipeline_still_cites_the_agt04_policy_schedule_placeholder` is
  replaced by `test_the_pipeline_cites_only_real_clauses`.

## Links
GOLD-07 in `docs/CLAIMS_AND_GOLD_SET_FIXES.md`. Test:
`tests/orchestration/test_cases.py::test_out_of_period_admission_cites_the_operative_clause`.
