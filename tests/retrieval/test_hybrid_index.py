"""Real Chroma and BM25 over the real knowledge base, with fake models unless stated."""

import zlib
from pathlib import Path

import pytest

from claimsense.config import load_config
from claimsense.ingestion.build_policy_knowledge_base import clean_pdf_text
from claimsense.ingestion.extract_policy_clauses import extract_clauses
from claimsense.retrieval.evaluate import STAGES, plot_stages, rank_by_stage
from claimsense.retrieval.index import (
    StaleIndexError,
    build_index,
    load_chunks,
    load_embedder,
    load_reranker,
    open_collection,
    persistent_client,
)
from claimsense.retrieval.search import HybridRetriever, tokenize

pytest.importorskip("chromadb")
pytest.importorskip("rank_bm25")

ROOT = Path(__file__).resolve().parents[2]
POLICY_PDF = ROOT / "data/policy/new_india/policy_wording.pdf"
PRODUCT = "new_india_arogya_sanjeevani"
MODEL = "fake-model"
CONFLICTING_ROW = (
    "Only PEDs declared in the Proposal Form and accepted for coverage by the company shall be "
    "covered after a waiting period of 4 years"
)


def fake_embed(texts):
    vectors = []
    for text in texts:
        vector = [0.0] * 64
        for token in tokenize(text):
            vector[zlib.crc32(token.encode()) % 64] += 1.0
        vectors.append(vector)
    return vectors


def fake_rerank(query, texts):
    words = set(tokenize(query))
    return [float(len(words & set(tokenize(text)))) for text in texts]


@pytest.fixture(scope="module")
def chunks():
    return load_chunks()


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    return persistent_client(tmp_path_factory.mktemp("index"))


@pytest.fixture(scope="module")
def collection(chunks, client):
    build_index(chunks, fake_embed, MODEL, client)
    return open_collection(client, chunks, MODEL)


@pytest.fixture(scope="module")
def retriever(chunks, collection):
    return HybridRetriever(chunks, collection, fake_embed, fake_rerank)


def _row_12_5(chunks):
    return next(chunk for chunk in chunks if chunk["clause_number"] == "12.5")


def test_index_holds_every_searchable_chunk_and_not_the_conflicting_row(chunks, collection):
    assert collection.count() == sum(chunk["searchable"] for chunk in chunks) == 180
    assert collection.get(ids=[_row_12_5(chunks)["chunk_id"]])["ids"] == []


def test_no_search_stage_returns_the_conflicting_row(chunks, retriever):
    row_id = _row_12_5(chunks)["chunk_id"]
    assert row_id not in retriever.dense(CONFLICTING_ROW)
    assert row_id not in retriever.lexical(CONFLICTING_ROW)
    assert row_id not in retriever.fused(CONFLICTING_ROW)
    assert "12.5" not in {hit.clause_number for hit in retriever.search(CONFLICTING_ROW, k=20)}


def test_get_clause_still_returns_the_conflicting_row_with_its_conflict(retriever):
    clause = retriever.get_clause(f"{PRODUCT}:12.5")
    assert "4 years" in clause.text
    assert clause.searchable is False
    assert clause.conflict["conflicts_with"] == f"{PRODUCT}:6.1"


def test_get_clause_returns_none_for_an_unknown_id(retriever):
    assert retriever.get_clause(f"{PRODUCT}:99.9") is None


@pytest.mark.parametrize("number", ["5", "9.4", "annexure-c"])
def test_get_clause_merges_parts_back_into_the_original_text(retriever, number):
    records, _ = extract_clauses(POLICY_PDF)
    original = next(record for record in records if record["clause_number"] == number)
    clause = retriever.get_clause(original["clause_id"])
    assert clause.text == clean_pdf_text(original["source_text"])


def test_parts_of_one_clause_come_back_as_one_hit(chunks, retriever):
    query = "Policy wording clause annexure-c day care"
    parts = {chunk["chunk_id"] for chunk in chunks if chunk["clause_number"] == "annexure-c"}
    assert len(parts & set(retriever.fused(query))) > 1

    hits = retriever.search(query, k=20)
    assert [hit.clause_number for hit in hits].count("annexure-c") == 1
    assert len({hit.clause_id for hit in hits}) == len(hits)


def test_hits_carry_provenance_and_the_context_a_list_item_needs(retriever):
    hit = next(
        hit
        for hit in retriever.search("hernia waiting period", k=20)
        if hit.clause_number == "6.2.12"
    )
    assert hit.chunk_id == f"clause::{PRODUCT}:6.2.12::part-001"
    assert hit.document == "policy_wording.pdf"
    assert hit.document_date == "2025-03-06"
    assert hit.page_numbers
    assert "Months waiting period" in hit.context_text
    assert "Months waiting period" not in hit.text


def test_hits_are_ranked_in_score_order_and_respect_k(retriever):
    hits = retriever.search("room rent per day", k=3)
    assert [hit.rank for hit in hits] == [1, 2, 3]
    assert [hit.score for hit in hits] == sorted((hit.score for hit in hits), reverse=True)


def test_search_is_repeatable(retriever):
    query = "cataract limit per eye"
    assert retriever.search(query) == retriever.search(query)


@pytest.mark.parametrize("query", ["", "   ", "\n"])
def test_blank_query_returns_nothing(retriever, query):
    assert retriever.search(query) == []


def test_bm25_leaves_out_chunks_that_match_no_query_word(retriever):
    assert retriever.lexical("zzzzqqqq") == []


def test_clause_ids_keep_the_best_position_of_each_clause(chunks, retriever):
    parts = [chunk["chunk_id"] for chunk in chunks if chunk["clause_number"] == "annexure-c"]
    other = next(chunk for chunk in chunks if chunk["clause_number"] == "4.1")
    ids = [parts[0], other["chunk_id"], parts[1]]
    assert retriever.clause_ids(ids) == [f"{PRODUCT}:annexure-c", f"{PRODUCT}:4.1"]


def test_changed_chunk_makes_the_index_refuse(chunks, collection, client):
    edited = [{**chunks[0], "text": "edited"}, *chunks[1:]]
    with pytest.raises(StaleIndexError, match="python -m claimsense.retrieval.index"):
        open_collection(client, edited, MODEL)


def test_changed_model_makes_the_index_refuse(chunks, collection, client):
    with pytest.raises(StaleIndexError):
        open_collection(client, chunks, "another-model")


def test_missing_index_refuses(chunks, tmp_path):
    with pytest.raises(StaleIndexError):
        open_collection(persistent_client(tmp_path), chunks, MODEL)


def test_rebuild_leaves_no_chunks_from_the_old_index(chunks, tmp_path):
    client = persistent_client(tmp_path)
    build_index(chunks, fake_embed, MODEL, client)
    assert build_index(chunks[:5], fake_embed, MODEL, client) == 5
    assert open_collection(client, chunks[:5], MODEL).count() == 5


def test_rank_by_stage_scores_every_stage_on_any_listed_clause(retriever):
    queries = [{"query": "cataract treatment", "clauses": [f"{PRODUCT}:4.3", f"{PRODUCT}:12.3"]}]
    ranks = rank_by_stage(retriever, queries)
    assert set(ranks) == set(STAGES)
    assert all(len(stage_ranks) == 1 for stage_ranks in ranks.values())
    assert ranks["BM25"][0] is not None


def test_plot_stages_writes_the_chart(tmp_path):
    pytest.importorskip("matplotlib")
    out = tmp_path / "chart.png"
    plot_stages({stage: [1, 2, None] for stage in STAGES}, out)
    assert out.stat().st_size > 0


# Real models. These skip until the models in config/models.yaml are downloaded.


def _downloaded(model):
    hub = pytest.importorskip("huggingface_hub")
    return isinstance(hub.try_to_load_from_cache(model, "config.json"), str)


@pytest.fixture(scope="module")
def real_models():
    pytest.importorskip("sentence_transformers")
    config = load_config()
    if not (_downloaded(config["embeddings"]) and _downloaded(config["reranker"])):
        pytest.skip("search models not downloaded")
    return config["embeddings"], config["reranker"]


@pytest.fixture(scope="module")
def real_retriever(chunks, real_models, tmp_path_factory):
    embedding_model, reranker = real_models
    client = persistent_client(tmp_path_factory.mktemp("real_index"))
    embed = load_embedder(embedding_model)
    build_index(chunks, embed, embedding_model, client)
    collection = open_collection(client, chunks, embedding_model)
    return HybridRetriever(chunks, collection, embed, load_reranker(reranker))


def test_pre_existing_query_finds_clause_6_1_without_the_conflicting_row(real_retriever):
    hits = real_retriever.search("When does cover start for a pre-existing disease?")
    clauses = [hit.clause_number for hit in hits]
    assert "6.1" in clauses
    assert "12.5" not in clauses


def test_reranker_accepts_the_longest_chunk(chunks, real_models):
    longest = max(chunks, key=lambda chunk: len(chunk["text"]))
    assert len(load_reranker(real_models[1])("day care", [longest["text"]])) == 1
