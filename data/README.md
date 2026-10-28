# Data (Domain & Product)

Synthetic starter pack v0.1.0 (`manifest.json`). Every person, policy ID, claim ID, hospital, bill
and tariff range is **synthetic**: use it for development and evaluation only, never for real
insurance decisions or medical pricing. Placement decisions: [ADR-0002](../docs/adr/0002-starter-data-pack.md).

| Path | What |
|---|---|
| `policy/new_india/` | Six New India Assurance PDFs for Arogya Sanjeevani (wording, CIS, prospectus, proposal form, excluded items, claim form) + `manifest.json` with SHA-256 per file |
| `tariffs/synthetic_tariffs.csv` | 30 procedures × 3 city tiers = 90 synthetic reference ranges |
| `processed/` | Clause-extraction output (`extracted_clauses_raw.jsonl`, `policy_clauses_structured.jsonl`) and the human review sheet `clause_review.xlsx` |
| `knowledge_base/` | Retrieval corpus built from the two source PDFs + its manifest |

Dev claims, gold worksheets and red-team cases live in [`eval/`](../eval/README.md). The 60
held-out claims live **outside this repo** in `../claimsense-heldout/`.

## Policy documents
The proposal form shows UIN `NIAHLIP25044V022425`. Treat it as an observed identifier, not proof
that every document is the same version. Before encoding rules, cross-check the UIN, effective
dates and wording across the policy wording, CIS, prospectus and excluded-items list. The policy
wording is primary: the CIS and prospectus never override it, and the proposal and claim forms are
workflow templates, not coverage contracts.

## Caveats
1. Claims are synthetic test fixtures, not interpretations of a real policy.
2. Gold outcomes use the simplified demo ruleset below. Review them against the exact policy
   wording, schedule and endorsements before relying on them.
3. Room-rent proportional deductions, waiting periods, sub-limits, co-pay, admissibility and
   non-payable items vary by policy version. Do not assume the demo rules are universally valid.
4. Tariff ranges are synthetic (Option A), not official, negotiated or reimbursement rates. Use
   them only to flag unusual prices for human review, never to decide coverage.
5. Money in the JSON is integer INR. In code, use `Decimal` (rule 1 in `CLAUDE.md`).

## Demo ruleset used to generate the gold labels
- Policy period 2026-01-01 → 2026-12-31.
- Initial waiting period: 30 days from policy start. Earlier admissions are `needs_review` / not
  admissible.
- Pre-existing disease waiting period: 36 months. A declared PED inside it is not payable.
- Room cap: min(2% of sum insured, ₹5,000/day). ICU cap: min(5% of sum insured, ₹10,000/day).
- Cataract sub-limit: min(25% of sum insured, ₹40,000 per eye).
- Co-pay: 5% of the otherwise payable amount.
- `non_payable` line items are excluded.
- When room charges exceed the daily cap, room-linked charges are reduced by the same ratio. The
  gold worksheet records the proportional-cut factor.

These rules are illustrative and must be verified against the policy wording before real use.

## Regenerating derived files
```bash
pip install -e ".[dev]"
python -m claimsense.ingestion.extract_policy_clauses       # -> processed/
python -m claimsense.ingestion.build_policy_knowledge_base  # -> knowledge_base/
```
See [`src/claimsense/ingestion/README.md`](../src/claimsense/ingestion/README.md) for the field reference.
