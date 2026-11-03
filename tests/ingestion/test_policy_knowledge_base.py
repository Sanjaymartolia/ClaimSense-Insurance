import json
from pathlib import Path

import pytest

from claimsense.ingestion.build_policy_knowledge_base import (
    build_knowledge_base,
    clause_records,
    split_text,
)
from claimsense.ingestion.extract_policy_clauses import extract_clauses

ROOT = Path(__file__).resolve().parents[2]
POLICY_PDF = ROOT / "data/policy/new_india/policy_wording.pdf"
COMMITTED_KB = ROOT / "data/knowledge_base/policy_knowledge_base.jsonl"
RETRIEVAL_QUERIES = ROOT / "eval/golden_dev/retrieval_queries.jsonl"
PRODUCT = "new_india_arogya_sanjeevani"


@pytest.fixture(scope="module")
def chunks():
    return clause_records(POLICY_PDF, chunk_size=1800, overlap=250)


def _first_chunk(chunks, clause_number):
    return next(chunk for chunk in chunks if chunk["clause_number"] == clause_number)


def _read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_split_text_respects_size_and_keeps_content():
    text = ("First paragraph. " * 60) + "\n\n" + ("Second paragraph. " * 60)
    chunks = split_text(text, max_chars=500, overlap=50)
    assert len(chunks) > 1
    assert all(len(chunk) <= 500 for chunk in chunks)
    assert "First paragraph." in " ".join(chunks)
    assert "Second paragraph." in " ".join(chunks)


def test_policy_chunks_are_extracted_directly_from_pdf(chunks):
    waiting = _first_chunk(chunks, "6.2.1")
    assert waiting["source"]["document"] == "policy_wording.pdf"
    assert waiting["source"]["sha256"]
    assert waiting["source"]["page_numbers"]
    assert waiting["verification_status"] == "not_human_verified"
    assert waiting["proposed_interpretation"]["waiting_period"]["duration_text"]
    assert waiting["proposed_interpretation"]["numeric_threshold"] is None
    assert waiting["proposed_interpretation"]["exceptions"]
    assert "waiting-period section context" in waiting["text"].lower()


def test_waiting_list_items_embed_only_their_own_period(chunks):
    item_24 = _first_chunk(chunks, "6.2.1")["text"]
    assert "24 Months waiting period" in item_24
    assert "36 Months waiting period" not in item_24

    item_36 = _first_chunk(chunks, "6.2.21")["text"]
    assert "36 Months waiting period" in item_36
    assert "24 Months waiting period" not in item_36


def test_waiting_list_items_are_not_buried_in_parent_text(chunks):
    item = _first_chunk(chunks, "6.2.1")
    assert len(item["text"]) < 300
    parent_text = item["proposed_interpretation"]["parent_context"]["source_text"]
    assert "Expenses related to the treatment" in parent_text


def test_every_chunk_comes_from_the_wording_and_respects_the_cap(chunks):
    assert {chunk["source"]["document"] for chunk in chunks} == {"policy_wording.pdf"}
    assert all(len(chunk["source_text"]) <= 1800 for chunk in chunks)


def test_long_annexure_parts_share_one_clause_id(chunks):
    parts = [chunk for chunk in chunks if chunk["clause_number"] == "annexure-c"]
    assert len(parts) > 1
    assert {part["clause_id"] for part in parts} == {"new_india_arogya_sanjeevani:annexure-c"}
    assert all(part["chunk_count"] == len(parts) for part in parts)


def test_overlap_keeps_every_annexure_line_whole_in_some_part(chunks):
    records, _ = extract_clauses(POLICY_PDF)
    annexure = next(record for record in records if record["clause_number"] == "annexure-c")
    parts = [chunk["source_text"] for chunk in chunks if chunk["clause_number"] == "annexure-c"]
    for line in annexure["source_text"].splitlines():
        assert any(line in part for part in parts), line


def test_builder_uses_only_the_policy_wording(tmp_path):
    output = tmp_path / "policy_knowledge_base.jsonl"
    manifest_path = tmp_path / "manifest.json"
    manifest = build_knowledge_base(
        POLICY_PDF,
        output,
        manifest_path,
        chunk_size=1800,
        overlap=250,
    )

    assert output.is_file()
    assert manifest_path.is_file()
    assert set(manifest["inputs"]) == {"policy_wording"}
    assert manifest["clause_extraction"]["source"] == "policy_wording.pdf"
    assert manifest["clause_extraction"]["intermediate_jsonl_used_as_input"] is False

    records = _read_jsonl(output)
    assert len(records) == manifest["outputs"]["record_count"]
    assert len({record["chunk_id"] for record in records}) == len(records)
    assert all(record["verification_status"] == "not_human_verified" for record in records)
    assert {record["record_type"] for record in records} == {"policy_clause"}
    assert all(record["source"]["page_numbers"] for record in records)

    waiting = [r for r in records if r["proposed_interpretation"]["topic"] == "waiting_period"]
    assert waiting
    assert all(r["proposed_interpretation"]["numeric_threshold"] is None for r in waiting)
    assert all(
        isinstance(r["proposed_interpretation"]["applicability_conditions"], list) for r in waiting
    )
    assert all(isinstance(r["proposed_interpretation"]["exceptions"], list) for r in waiting)


def test_builder_rejects_missing_source_pdf(tmp_path):
    missing = tmp_path / "does_not_exist.pdf"
    with pytest.raises(FileNotFoundError, match="Required source PDF not found"):
        build_knowledge_base(missing, tmp_path / "kb.jsonl", tmp_path / "manifest.json")


def test_committed_knowledge_base_matches_a_fresh_build(tmp_path):
    output = tmp_path / "kb.jsonl"
    build_knowledge_base(POLICY_PDF, output, tmp_path / "manifest.json")
    assert _read_jsonl(output) == _read_jsonl(COMMITTED_KB)


def test_retrieval_labels_point_at_searchable_clauses():
    clause_ids = {
        record["clause_id"] for record in _read_jsonl(COMMITTED_KB) if record["searchable"]
    }
    for query in _read_jsonl(RETRIEVAL_QUERIES):
        assert set(query["clauses"]) <= clause_ids, query["qid"]


def test_limit_queries_accept_the_clause_and_the_table_row_stating_it(chunks):
    labels = {query["qid"]: query["clauses"] for query in _read_jsonl(RETRIEVAL_QUERIES)}
    limits = {"R01": ("12.1", "Rs.5000/-"), "R02": ("12.2", "Rs.10,000/-")}
    for qid, (table_row, limit) in limits.items():
        assert labels[qid] == [f"{PRODUCT}:4.1", f"{PRODUCT}:{table_row}"]
        assert limit in _first_chunk(chunks, "4.1")["source_text"]
        assert limit in _first_chunk(chunks, table_row)["source_text"]


def test_table_row_contradicting_its_clause_is_kept_but_not_searchable(chunks):
    row = _first_chunk(chunks, "12.5")
    assert "4 years" in row["source_text"]
    assert row["searchable"] is False
    assert row["conflict"]["conflicts_with"] == f"{PRODUCT}:6.1"
    assert "ADR-0004" in row["conflict"]["decision"]
    assert "36 months" in _first_chunk(chunks, "6.1")["source_text"]


def test_only_the_conflicting_row_leaves_search(chunks):
    others = [chunk for chunk in chunks if chunk["clause_number"] != "12.5"]
    assert all(chunk["searchable"] is True for chunk in others)
    assert all(chunk["conflict"] is None for chunk in others)
    assert not any("4 years" in chunk["source_text"] for chunk in others)


def test_chunks_carry_the_pdf_date_without_claiming_an_effective_date(chunks):
    for chunk in chunks:
        assert chunk["source"]["document_date"] == "2025-03-06"
        assert chunk["source"]["document_date_basis"] == "pdf_creation_metadata"
        assert "effective_date" not in chunk["source"]


def test_manifest_counts_searchable_chunks(tmp_path):
    manifest = build_knowledge_base(POLICY_PDF, tmp_path / "kb.jsonl", tmp_path / "manifest.json")
    outputs = manifest["outputs"]
    assert outputs["searchable_chunks"] == outputs["record_count"] - 1
