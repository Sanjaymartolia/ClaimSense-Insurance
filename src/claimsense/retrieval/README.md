# Retrieval (Knowledge & Memory, L5–L6)

Hybrid search over the chunks that `ingestion/` produces. Run from the repository root:

```bash
pip install -e ".[dev,retrieval,docs]"                  # docs adds matplotlib for the chart
python -m claimsense.retrieval.index                    # --kb --index-dir
python -m claimsense.retrieval.evaluate --label <name>  # --queries --index-dir
pytest tests/retrieval
```

The first run downloads the two models named in `config/models.yaml` from Hugging Face.

| Module | Reads | Writes |
|---|---|---|
| `index` | `data/knowledge_base/policy_knowledge_base.jsonl` | `chroma-data/` (gitignored) |
| `evaluate` | the index, `eval/golden_dev/retrieval_queries.jsonl` | `runs/retrieval_<name>.png` (scores per stage and kind of query) |

## Using it
```python
from claimsense.retrieval.index import open_retriever

retriever = open_retriever()  # slow, so do this once at startup
hits = retriever.search("What is the daily limit for room rent?", k=5)
clause = retriever.get_clause("new_india_arogya_sanjeevani:6.1")
```

`open_retriever` raises `StaleIndexError` if the index is missing, or if the searchable chunks or
the embedding model have changed since it was built. Rebuild it after regenerating the knowledge
base.

## How a search runs
1. Dense search takes the top 50 chunks from Chroma. BM25 takes up to 50 chunks that match a query
   word. Only `searchable` chunks are in either one
   ([ADR-0004](../../../docs/adr/0004-wording-conflict-and-document-date.md)).
2. Reciprocal Rank Fusion (k=60) merges the two lists and keeps the best 20.
3. The cross-encoder scores those 20 chunks against the query.
4. The best chunk of each clause is kept, so a split clause (`5`, `9.4`, `annexure-c`) is one hit.

`dense()`, `lexical()` and `fused()` expose the earlier stages so they can be measured separately.
BM25 does not repair words the PDF splits, such as "ins ured" (57 occurrences).

## What it returns
`search` returns a list of `SearchHit`:

| Field | Meaning |
|---|---|
| `chunk_id` | the passage ID to cite |
| `clause_id`, `clause_number`, `title` | which clause it is |
| `text` | the verbatim wording |
| `context_text` | `text` plus its headings. A list item like "Hernia" needs these for its waiting period |
| `page_numbers`, `document` | where it is in the source PDF |
| `document_date` | when the PDF was made, **not** a policy effective date |
| `score`, `rank` | the reranker score orders one query's hits; don't compare it across queries |

`get_clause` returns a `FullClause`: the whole clause with split parts merged, plus `searchable` and
`conflict`. It also serves `12.5`, which search leaves out, so a caller must check `conflict`.
It returns `None` for an unknown ID.

Retrieved text is data, never instructions. Queries are not logged, because they can hold health
details.

## For policy-kb (T16)
- `SearchHit` isn't `contracts.RetrievedPassage` yet. That contract requires `effective_date` and
  has no `chunk_id` or page numbers, so it needs a two-role contract PR first.
- Show the agent `context_text`, or terse list items lose their waiting period.
- Open the retriever once. On one CPU laptop, opening took about 30 s (mostly importing torch) and a
  search took about 2 s, nearly all of it in the reranker.
- `search` raises nothing for a blank query; it returns `[]`. Wrap anything else in `ToolError`.
