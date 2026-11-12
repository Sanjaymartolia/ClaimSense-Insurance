"""policy-kb caches search results per process (12 Nov 2026).

The cross-encoder re-ranker costs ~1.5-3 s per search on a laptop CPU, and only 17 of the 188
searches over the 52 dev and red-team claims are distinct, so a real-retriever eval run spent most
of its time re-ranking the same queries (p95 64-90 s per claim). No retrieval extras needed: the
retriever here is a fake that counts its calls.
"""

from __future__ import annotations

import pytest

from claimsense.mcp_servers import policy_kb
from claimsense.retrieval.search import SearchHit


class CountingRetriever:
    def __init__(self) -> None:
        self.calls = 0

    def search(self, query: str, k: int = 5, category: str | None = None) -> list[SearchHit]:
        self.calls += 1
        return [
            SearchHit(
                chunk_id=f"c{n}",
                clause_id=f"new_india_arogya_sanjeevani:{n}",
                clause_number=str(n),
                title=None,
                text=f"{query} {category}",
                context_text=f"heading {n}",
                page_numbers=[1],
                document="policy_wording.pdf",
                document_date=None,
                score=1.0 - n / 10,
                rank=n,
            )
            for n in range(1, k + 1)
        ]


@pytest.fixture
def retriever(monkeypatch):
    fake = CountingRetriever()
    meta = policy_kb._PolicyMeta(insurer="Insurer", product="Product")
    monkeypatch.setattr(policy_kb, "_ENGINE", policy_kb._Engine(retriever=fake, meta=meta))
    policy_kb._cached_hits.cache_clear()
    yield fake
    policy_kb._cached_hits.cache_clear()  # never leak the fake's hits into another test


def test_a_repeated_search_does_not_rerun_the_retriever(retriever):
    first = policy_kb.policy_search("pharmacy", category="medicines")
    again = policy_kb.policy_search("pharmacy", category="medicines")
    assert retriever.calls == 1
    assert [p.model_dump() for p in again] == [p.model_dump() for p in first]


def test_a_different_query_category_or_k_is_searched(retriever):
    policy_kb.policy_search("pharmacy", category="medicines")
    policy_kb.policy_search("pharmacy", category="consumables")
    policy_kb.policy_search("ot charges", category="medicines")
    assert len(policy_kb.policy_search("pharmacy", category="medicines", k=2)) == 2
    assert retriever.calls == 4


def test_a_caller_cannot_change_what_the_next_caller_gets(retriever):
    first = policy_kb.policy_search("pharmacy", category="medicines")
    first[0].clause.text = "tampered"
    first.clear()
    again = policy_kb.policy_search("pharmacy", category="medicines")
    assert again[0].clause.text == "heading 1"
