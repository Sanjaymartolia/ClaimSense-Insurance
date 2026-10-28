# Ingestion (Knowledge & Memory, L4–L5)

Two modules, run from the repository root:

```bash
python -m claimsense.ingestion.extract_policy_clauses       # --pdf --raw-output --structured-output
python -m claimsense.ingestion.build_policy_knowledge_base  # --policy-pdf --excluded-items-pdf --output --manifest --chunk-size --overlap
pytest tests/ingestion
```

| Module | Reads | Writes |
|---|---|---|
| `extract_policy_clauses` | `data/policy/new_india/policy_wording.pdf` | `data/processed/extracted_clauses_raw.jsonl`, `policy_clauses_structured.jsonl` |
| `build_policy_knowledge_base` | `policy_wording.pdf` + `excluded_items.pdf` | `data/knowledge_base/policy_knowledge_base.jsonl`, `manifest.json` |

The builder runs the clause extractor **in memory**. The structured JSONL in `processed/` is a
review/audit artifact and is never an input to the knowledge base.

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
hierarchy, the proposed labels, `authority_level` and a `retrieval_warning`. The excluded-items
PDF is indexed as `record_type: excluded_items_reference`, a supporting reference that never
overrides the wording.

Chunking defaults: 1,800 characters, 250 overlap, split at paragraph, then sentence, then
whitespace boundaries. Pages with no extractable text are flagged. If very little text comes out
overall, the build stops and calls for OCR/layout review.

**Next step (retrieval/):** embed `text` into Chroma, keep the rest as metadata, and return
`chunk_id` + page references with every hit. These records don't yet map to
`contracts.policy.Clause` (see ADR-0002). Never index gold worksheets.
