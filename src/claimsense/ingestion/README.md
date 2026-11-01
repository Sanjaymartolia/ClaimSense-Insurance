# Ingestion (Knowledge & Memory, L4–L5)

Two modules, run from the repository root:

```bash
python -m claimsense.ingestion.extract_policy_clauses       # --pdf --raw-output --structured-output
python -m claimsense.ingestion.build_policy_knowledge_base  # --policy-pdf --output --manifest --chunk-size --overlap
pytest tests/ingestion
```

| Module | Reads | Writes |
|---|---|---|
| `extract_policy_clauses` | `data/policy/new_india/policy_wording.pdf` | `data/processed/extracted_clauses_raw.jsonl`, `policy_clauses_structured.jsonl` |
| `build_policy_knowledge_base` | `policy_wording.pdf` | `data/knowledge_base/policy_knowledge_base.jsonl`, `manifest.json` |

The builder runs the clause extractor **in memory**. The structured JSONL in `processed/` is a
review/audit artifact and is never an input to the knowledge base.

Only the policy wording is chunked; [ADR-0003](../../../docs/adr/0003-policy-corpus-scope.md) says
why the other PDFs and Annexure-B are not. Beyond the numbered clauses, the parser produces:
- `12.3`–`12.7`: benefit-table rows that print no number (cataract, AYUSH, pre-existing disease,
  cumulative bonus, co-pay). The numbers are generated.
- `annexure-a.list-i` to `list-iv`: the non-payable list, then charges subsumed into room,
  procedure and treatment costs.
- `annexure-c`: the day-care treatment list. It is a two-column table, so a line can hold two
  entries, and every part reports all of the annexure's pages.

Every record is `not_human_verified`. Topic, rule type, conditions and exceptions are
keyword/span heuristics. No numeric threshold is inferred. Do not approve or deny a claim from
these outputs alone.

## `extracted_clauses_raw.jsonl` (one clause per line)
- `clause_id`: product name + clause number, e.g. `new_india_arogya_sanjeevani:6.2.1`.
- `clause_number`: normalised number, including generated hierarchy for list items.
  `displayed_number` is what the PDF prints, which can differ.
- `parent_clause_number`, `hierarchy`: the parent, and the number split into levels.
- `title`: heading or item text after the number.
- `page_number` (start, 1-based), `page_numbers` (all pages with text from this clause).
- `source_document`, `source_sha256`: the exact PDF used.
- `section_context`: nearby heading for list items (e.g. "24 Months waiting period") as
  `{text, page_number}`, or `null`.
- `source_text`, `source_spans`: combined text, and each line with its page.

## `policy_clauses_structured.jsonl`
- `record_id` (= `clause_id`) plus the identification and hierarchy fields above.
- `source`: `document`, `sha256`, `page_number`, `page_numbers`, `insurer`, `product`,
  `uin_observed_in_policy_pdf`.
- `source_text`: retained so the record can be checked against its source.
- `proposed_interpretation`: `topic`, `rule_type`, `applicability_conditions`, `exceptions`,
  `parent_context`, `waiting_period` (`duration_text`, `parent_duration_mentions`,
  `applies_to_text`, `raw_waiting_period_spans`, `section_context_*`, `interpretation_note`),
  `numeric_threshold` (always `null`), `interpretation_method`, `review_flags`.
- `verification_status`: `not_human_verified`.

## `policy_knowledge_base.jsonl`
One retrieval chunk per line with a stable `chunk_id`. `text` is the embedding-facing text: the
clause plus a compact parent/section context, so terse list items stay retrievable. `source_text`
is the raw chunk. Each chunk also carries source document, hash and page metadata, clause
hierarchy, the proposed labels, `authority_level` and a `retrieval_warning`. A waiting-period list
item's `text` carries only its own period; the parent clause's conditions stay in
`proposed_interpretation.parent_context`.

Fields set by [ADR-0004](../../../docs/adr/0004-wording-conflict-and-document-date.md):
- `searchable`, `conflict`: table row `12.5` says 4 years where clause `6.1` says 36 months, so it
  has `searchable: false` and a `conflict` naming the clause that applies. Every other chunk has
  `searchable: true` and `conflict: null`.
- `source.document_date`, `source.document_date_basis`: the PDF's creation date. It is not a policy
  effective date, because no document states one.

Chunking defaults: 1,800 characters, 250 overlap, split at a whitespace boundary or better. Only
clauses over the cap are split (`5`, `9.4`, `annexure-c`). Their parts share a `clause_id`, so
retrieval should merge them.

**Next step (retrieval/):** embed `text` for `searchable` chunks into Chroma, keep the rest as
metadata, and return `chunk_id` + page references with every hit. These records don't yet map to
`contracts.policy.Clause` (see ADR-0002). Never index gold worksheets.
