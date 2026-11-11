# ADR-0010: The calculator runs after the admissibility gate (AGT-02, short circuit)

**Status:** accepted
**Owner / layers:** Agents & Orchestration (`graph/nodes.py`, `agents/`), L8/L10. Tools & Security
must follow in `calc/adjudication.py` (one line, below).
**Date:** 2026-11-12

## Context
A claim that failed admissibility went straight to a person with no worksheet. The gold expects
a worksheet for it: every line is deducted and cites the gate's clause, and the settlement is ₹0.
The harness keeps the calculator required on every claim (decision of 10 November 2026, Section
9.8 of `docs/EVAL_HARNESS_REPORT.md`), so these claims scored 0 on `amounts` and on
`required_tool_coverage`. Seven dev claims and their red-team copies lost half their score this
way, and the release check stayed below its 0.85 threshold (0.788).

## Options considered
- **A. Change the harness** so that the calculator is not required on a not-admissible claim.
  This was rejected on 10 November: no worksheet is not the same as ₹0, and the adjudicator gets
  nothing to audit.
- **B. Compute the ₹0 worksheet in the node.** This was rejected because it breaks rule 1 (money
  from code, not from the orchestration).
- **C. The admissibility node calls the calculator** with the gate's clause on every line. The
  calculator deducts each line in full.

## Decision
**C.**
1. When admissibility fails and names a clause, the node calls `coverage.adjudicate` (the
   calculator, through the coverage tool belt, so hooks, the tool log and traces see it). It
   passes the first gate clause on every line.
   - The checks run in this order: policy period (2), initial wait (6.3), pre-existing disease
     (6.1), maternity (7.15).
   - With no clause (policy not found, patient mismatch), there is still no worksheet.
2. The worksheet is stored, but the gate clause is **not** stored as `clause_choices`. An
   adjudicator override still runs real clause selection.
3. The repudiation review still shows no worksheet, and the repudiation approval is still bound
   to the admissibility finding. Nothing about routing or approvals changes.
4. Full-deduction clauses in the reference calculator: 6.1, 6.2, 6.3 → `waiting_period`;
   7.15 → `exclusion`; 2 → `other`.
   - An in-bill duplicate still comes first and cites clause 2 (ADR-0009), as the gold has it.
5. **Guard:** these claim-level clauses (`clauses.CLAIM_LEVEL`) are never a valid per-line choice
   for the coverage analyst. Clause 2 is searchable in the knowledge base, and choosing it would
   now zero a line. A model pick falls back to the first line-level candidate, with a note. An
   adjudicator's locked choice still wins.

## Consequences
- **Stub results (52 claims):** composite 0.788 → 0.913.

  | Split | Before | After |
  |---|---|---|
  | dev | 0.772 | 0.931 (passes) |
  | red team | 0.800 | 0.900 |

  `required_tool_coverage` is 1.000 on both splits. On the dev split alone, `python -m eval.full
  --stub --splits dev` now ships.
- The release check still fails on `injection_obeyed` (CLM-9016, CLM-9017: RT-012, owned by
  Tools & Security) and on the matching agent-suite thresholds.
- `memory_update` now records a ₹0 worksheet for a repudiated claim instead of none.
- **Tools & Security:** add `C.POLICY_PERIOD: DeductionReason.OTHER` to
  `calc/adjudication.py::FULLY_DEDUCTED`, with a hand-worked test. 7.15 and the waiting periods
  are already there. Until then, with `real_services()` an out-of-period claim gets a non-zero
  worksheet. It is still repudiated and never shown, so nothing is paid, but the worksheet is
  wrong.
- **AGT-02's other half,** the 6.2 specific-waiting check (CLM-0008), is done by
  [ADR-0011](0011-specific-waiting-period-check.md).

## Links
AGT-02 in `docs/CLAIMS_AND_GOLD_SET_FIXES.md`; ADR-0008 (clause 2); ADR-0009 (duplicates).

Tests:
- `tests/orchestration/test_gate_worksheet.py`
- `tests/orchestration/test_reference_calculator.py::test_claim_level_gate_clauses_deduct_every_line_in_full`
- `eval/tests/test_claimsense_adapter.py::test_a_gated_claim_gets_a_zero_worksheet_from_the_calculator`
