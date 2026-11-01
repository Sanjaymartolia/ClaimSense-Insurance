# ADR-0004: Wording conflicts, the missing effective date and two-clause retrieval labels

**Status:** proposed
**Owner / layers:** Knowledge & Memory — L4–L5
**Date:** 2026-11-02

## Context
T09 left three questions open. These are calls for a demo on synthetic claims, not an insurer's
ruling.

1. **Pre-existing disease (PED) wait.** Clause 6.1 says 36 months. The table of benefits on p. 21
   says 4 years. That row (`12.5`) ranked first for query R06 in dense, BM25 and RRF search. The
   wording has no clause saying which part prevails.
2. **Effective date.** T09 and `contracts.policy.Clause.effective_date` ask for one. The wording and
   CIS state none, and the prospectus's only dates are from 2019–2020, on p. 4. Only a stub sets the
   field (`date(2025, 3, 1)` in `agents/services.py`), and nothing reads it.
3. **R01 and R02 labels.** They expect clause 4.1. Clause 4.1 a and b state the room and ICU limits,
   and so do table rows 12.1 and 12.2.

## Options considered
**PED wait**
- A. Delete 12.5. This hides contract text from an audit.
- B. Leave it searchable with a warning. This depends on the model obeying the warning.
- C. Keep it for audit and `get_clause`, and exclude it from search (chosen).

**Effective date**
- A. Put the PDF's date in `effective_date`. This claims something no document says.
- B. Keep the stub's date. It is invented.
- C. Use a claim's `policy_start_date`. That is each policy's period, not the date of the wording.
- D. Make the field optional and store the PDF's date under its own name (chosen).

**Labels**
- A. Replace 4.1 with the table rows. 4.1 is just as correct.
- B. Keep 4.1 only. This scores a correct answer as a miss.
- C. Accept either clause (chosen).
- D. Split 4.1 into parts a–d. In a trial it moved 4.1 from rank 6 to 5 in dense search and left RRF
  unchanged, so it isn't worth doing now. T56 can test it.

## Decision
**Rule:** where a table row and a numbered clause disagree, the clause wins. Where they agree, either
can be cited.

**1. The PED wait is 36 months.**
- Clause 6.1 a and d, the CIS, prospectus p. 12 and capstone guide p. 9 all say 36 months. "4 years"
  appears once across the wording, CIS and prospectus, in row 12.5.
- News reports say IRDAI cut the maximum from 48 to 36 months in 2024, and the moratorium to 60
  months. Clause 8 already says 60 months, so 4 years looks like a leftover. This is an inference;
  the circular itself wasn't checked.
- The 36 months in definition 3.41 is a different thing, a look-back on diagnosis before the policy
  starts. It is not evidence for this call.
- `12.5` stays in the knowledge base verbatim with `searchable: false` and a `conflict` naming 6.1.

**2. No effective date is recorded, because none is known.**
- Each chunk gets `source.document_date` (2025-03-06) and `source.document_date_basis`
  (`pdf_creation_metadata`).
- `Clause.effective_date` should become `date | None = None`. That is a contract change, so it goes
  in its own PR reviewed by two roles and is **not part of this change**.

**3. `clauses` in `retrieval_queries.jsonl` means any of these.** R01 accepts 4.1 or 12.1, and R02
accepts 4.1 or 12.2. The other 10 queries list one clause each.

**Other table rows.**
- Room, ICU, cataract, AYUSH, cumulative bonus, co-pay, pre/post-hospitalisation, the 24-hour rule
  and family eligibility agree with the clauses. Proposer age appears only in the table.
- **Grace period also conflicts.** The table gives 15 days for every mode except yearly. Clauses
  3.21 and 10.16 give 30 days for quarterly and half-yearly, and prospectus p. 11 agrees with them,
  so the clauses win.
- The row sits inside chunk `12` with rows that are correct, so that chunk stays searchable. In a
  trial of 3 grace-period queries, 10.16 and 3.21 took the top two RRF places and `12` ranked 8–9.
  No code or dev claim uses a grace period. Revisit this if a claim scenario starts to.

## Consequences
- **Knowledge & Memory (T10):** index only `searchable` chunks, and test that `get_clause` still
  returns 12.5 with its `conflict`. Definition 3.41 still outranks 6.1 for R06 in BM25 and RRF, so
  check this query once the reranker is in.
- **Agents & Orchestration:** `PED_WAITING_PERIOD` in `agents/clauses.py` can point to 6.1, and the
  36-months-or-4-years TODO in `agents/coverage.py` can close. Its month arithmetic TODO stays open.
- **Eval & Red-Team:** review the R01 and R02 labels. T12 must score a hit as any listed clause.
  Check that held-out gold doesn't rely on 12.5 or a 4-year wait.
- **Domain & Product:** review these calls. All 20 dev claims have no declared PED, so the 36-month
  call changes no dev payout. Row 12.5 in `clause_review.xlsx` needs a note.
- **Contracts (two roles):** make `effective_date` optional, and add `chunk_id` and page numbers to
  `RetrievedPassage`, which has neither today.

## Links
T09, T10. `tests/ingestion/test_policy_knowledge_base.py`. `runs/t09_open_calls.png` (draft labels,
no reranker): dense hits go from 11/12 to 12/12 because of the label change alone, and removing 12.5
improves the rank of 6.1 for R06. News sources:
[Business Standard](https://www.business-standard.com/amp/finance/insurance/new-india-assurance-increases-premiums-on-health-insurance-by-10-124073001522_1.html),
[Asia Insurance Review](https://www.asiainsurancereview.com/News/View-NewsLetter-Article/id/87871/Type/eDaily/Conferences/Gallery).
