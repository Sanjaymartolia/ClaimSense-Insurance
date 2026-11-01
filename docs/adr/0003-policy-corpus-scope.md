# ADR-0003: Which policy documents the retrieval corpus chunks

**Status:** proposed
**Owner / layers:** Knowledge & Memory — L4–L5
**Date:** 2026-11-01

## Context
`data/policy/new_india/` holds six PDFs. The first knowledge base chunked `policy_wording.pdf` up to
Annexure-A, plus `excluded_items.pdf` as a supporting reference. That left out Lists II–IV of
Annexure-A, which clause 4.7 points to, and Annexure-C. Chunks retrieved for an adjudication decision
must come from the document that governs it.

## Options considered
A. Keep the wording's clauses plus `excluded_items.pdf`. Lists II–IV stay missing.
B. Add the annexures and keep `excluded_items.pdf`. The same 68-item list then exists twice and can
   take several of the top 5 results for a single consumables query.
C. Chunk only the wording, annexures included (chosen).
D. Also chunk the CIS and prospectus. They repeat the same limits with lower authority, so retrieval
   could return a summary in place of the clause it summarises.

## Decision
| Source | Chunked? | Why |
|---|---|---|
| `policy_wording.pdf` clauses 1–12 | yes | the contract |
| Annexure-A Lists I–IV | yes | part of the wording; decide how bill items are treated |
| Annexure-C day-care list | yes | decides whether the 24-hour hospitalisation limit applies |
| Annexure-B ombudsman addresses | no | no claim rule |
| `excluded_items.pdf` | no | same items as List I; a test keeps that checked |
| `customer_information_sheet.pdf` | no | summary; states that the Policy Document prevails |
| `prospectus.pdf` | no | customer FAQ; does not override the wording |
| `proposal_form.pdf`, `claim_form.pdf` | no | blank forms |

All six PDFs stay in the repo. Tariffs remain a table served by the tariff tool, and claims and gold
worksheets are never indexed.

## Consequences
- Every chunk is `record_type: policy_clause`. `excluded_items_reference` chunks no longer exist.
- Clause ID changes: `7.20.1` becomes `8`; `12.3`–`12.7` and the annexure IDs are new.
- Retrieval label R09 now expects `annexure-a.list-i`. Eval & Red-Team reviews this change.
- Domain & Product: `clause_review.xlsx` is out of date for the changed clauses.
- Eval & Red-Team: check that held-out gold cites neither `7.20.1` nor `excluded-items::` IDs.
- Agents & Orchestration: `NON_PAYABLE_ITEMS` in `agents/clauses.py` can point to `annexure-a.list-i`.

## Links
T09. `tests/ingestion/test_policy_clause_pipeline.py` holds the List I check.
