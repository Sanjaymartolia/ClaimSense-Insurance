"""Hybrid policy search: BM25 + vectors, RRF, then a cross-encoder reranker (L5-L6).

Retrieved text is data for the agents, never instructions. Queries are not logged, because they can
hold health details. Build the index first: ``python -m claimsense.retrieval.index``.
"""

import re
from collections.abc import Callable, Iterable, Sequence
from typing import Any

from pydantic import BaseModel

RRF_K = 60
CANDIDATES = 50  # chunks taken from each of dense search and BM25
RERANK_POOL = 20  # best fused chunks that the cross-encoder scores

Embedder = Callable[[Sequence[str]], list[list[float]]]
Reranker = Callable[[str, Sequence[str]], list[float]]


class SearchHit(BaseModel):
    chunk_id: str
    clause_id: str
    clause_number: str
    title: str | None
    text: str  # verbatim wording, for citing
    context_text: str  # adds the headings a terse list item needs, such as its waiting period
    page_numbers: list[int]
    document: str
    document_date: str | None  # when the PDF was made, not a policy effective date (ADR-0004)
    score: float  # reranker score: orders one query's hits, not comparable across queries
    rank: int


class FullClause(BaseModel):
    clause_id: str
    clause_number: str
    title: str | None
    text: str
    page_numbers: list[int]
    document: str
    document_date: str | None
    searchable: bool
    conflict: dict[str, str] | None  # set when another clause applies instead (ADR-0004)


def tokenize(text: str) -> list[str]:
    """Lowercase words and numbers for BM25. The wording spells hospitalisation both ways."""
    text = re.sub(r"(?<=\d),(?=\d)", "", text.lower())
    return [token.replace("isation", "ization") for token in re.findall(r"[a-z0-9]+", text)]


def reciprocal_rank_fusion(rankings: Iterable[Sequence[str]], k: int = RRF_K) -> list[str]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for position, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1 / (k + position)
    return sorted(scores, key=lambda item: (-scores[item], item))


def merge_parts(parts: Sequence[str]) -> str:
    """Join a split clause's parts, dropping the text that neighbouring parts share."""
    merged = ""
    for part in parts:
        longest = min(len(merged), len(part))
        overlap = next((n for n in range(longest, 0, -1) if merged.endswith(part[:n])), 0)
        merged += part[overlap:]
    return merged


class HybridRetriever:
    def __init__(
        self,
        chunks: Iterable[dict[str, Any]],
        collection: Any,
        embed: Embedder,
        rerank: Reranker,
    ) -> None:
        from rank_bm25 import BM25Okapi  # optional dependency: pip install -e ".[retrieval]"

        self._all_chunks = list(chunks)
        self._searchable = {c["chunk_id"]: c for c in self._all_chunks if c["searchable"]}
        self._ids = list(self._searchable)
        self._bm25 = BM25Okapi([tokenize(c["text"]) for c in self._searchable.values()])
        self._collection = collection
        self._embed = embed
        self._rerank = rerank

    def dense(self, query: str, n: int = CANDIDATES) -> list[str]:
        result = self._collection.query(
            query_embeddings=self._embed([query]),
            n_results=min(n, self._collection.count()),
            include=[],
        )
        return result["ids"][0]

    def lexical(self, query: str, n: int = CANDIDATES) -> list[str]:
        scores = self._bm25.get_scores(tokenize(query))
        matches = [i for i, score in enumerate(scores) if score > 0]
        matches.sort(key=lambda i: (-scores[i], self._ids[i]))
        return [self._ids[i] for i in matches[:n]]

    def fused(self, query: str, n: int = RERANK_POOL) -> list[str]:
        return reciprocal_rank_fusion([self.dense(query), self.lexical(query)])[:n]

    def clause_ids(self, chunk_ids: Iterable[str]) -> list[str]:
        """Clause IDs in order, with a split clause counted once at its best position."""
        return list(dict.fromkeys(self._searchable[i]["clause_id"] for i in chunk_ids))

    def search(self, query: str, k: int = 5) -> list[SearchHit]:
        if not query.strip() or k < 1:
            return []
        pool = self.fused(query)
        scores = self._rerank(query, [self._searchable[i]["text"] for i in pool])
        hits: dict[str, SearchHit] = {}
        for chunk_id, score in sorted(zip(pool, scores, strict=True), key=lambda p: (-p[1], p[0])):
            chunk = self._searchable[chunk_id]
            if chunk["clause_id"] not in hits:
                hits[chunk["clause_id"]] = _hit(chunk, float(score), rank=len(hits) + 1)
            if len(hits) == k:
                break
        return list(hits.values())

    def get_clause(self, clause_id: str) -> FullClause | None:
        """A whole clause by ID. This also serves clauses that search leaves out."""
        parts = [c for c in self._all_chunks if c["clause_id"] == clause_id]
        if not parts:
            return None
        parts.sort(key=lambda c: c["chunk_index"])
        first = parts[0]
        return FullClause(
            clause_id=clause_id,
            clause_number=first["clause_number"],
            title=first["title"],
            text=merge_parts([part["source_text"] for part in parts]),
            page_numbers=first["source"]["page_numbers"],
            document=first["source"]["document"],
            document_date=first["source"]["document_date"],
            searchable=first["searchable"],
            conflict=first["conflict"],
        )


def _hit(chunk: dict[str, Any], score: float, rank: int) -> SearchHit:
    return SearchHit(
        chunk_id=chunk["chunk_id"],
        clause_id=chunk["clause_id"],
        clause_number=chunk["clause_number"],
        title=chunk["title"],
        text=chunk["source_text"],
        context_text=chunk["text"],
        page_numbers=chunk["source"]["page_numbers"],
        document=chunk["source"]["document"],
        document_date=chunk["source"]["document_date"],
        score=score,
        rank=rank,
    )
