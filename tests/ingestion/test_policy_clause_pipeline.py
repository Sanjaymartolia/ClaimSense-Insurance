import json
import re
from pathlib import Path

import pytest
from pypdf import PdfReader

from claimsense.ingestion.extract_policy_clauses import (
    extract_clauses,
    structure_clause,
    write_jsonl,
)

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def by_number():
    records, _ = extract_clauses(ROOT / "data/policy/new_india/policy_wording.pdf")
    return {record["clause_number"]: record for record in records}


def _letters_and_digits(text):
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def test_waiting_period_heading_stays_out_of_the_previous_list_item(by_number):
    # Item 20 is on the 24-month list; the 36-month heading printed after it starts the next list.
    assert "36 Months" not in by_number["6.2.20"]["source_text"]
    parent = by_number["6.2"]["source_text"]
    assert "(i) 24 Months waiting period" in parent
    assert "(ii) 36 Months waiting period" in parent


def test_moratorium_is_top_level_clause_8(by_number):
    assert "7.20.1" not in by_number
    assert by_number["8"]["title"].startswith("Moratorium Period")
    assert by_number["8"]["parent_clause_number"] is None


def test_benefit_table_rows_are_separate_clauses(by_number):
    icu = by_number["12.2"]["source_text"]
    assert "Intensive Care Unit" in icu
    for other_row in ("Cataract", "AYUSH", "Pre Existing", "Cumulative", "Co Pay"):
        assert other_row not in icu
    assert "Rs.40,000" in by_number["12.3"]["source_text"]
    assert "Ayurveda" in by_number["12.4"]["source_text"]
    assert "4 years" in by_number["12.5"]["source_text"]
    assert "Increase in the sum insured" in by_number["12.6"]["source_text"]
    assert "5% co pay" in by_number["12.7"]["source_text"]


@pytest.mark.parametrize(
    ("clause", "present", "absent"),
    [
        ("annexure-a.list-i", "BABY FOOD", "List II"),
        ("annexure-a.list-ii", "PATIENT IDENTIFICATION BAND", "List III"),
        ("annexure-a.list-iii", "ORTHOBUNDLE, GYNAEC BUNDLE", "List IV"),
        ("annexure-a.list-iv", "ADMISSION/REGISTRATION CHARGES", "ORTHOBUNDLE"),
        ("annexure-c", "Stapedotomy", "Ombudsman"),
    ],
)
def test_annexures_are_clauses(by_number, clause, present, absent):
    text = by_number[clause]["source_text"]
    assert present in text
    assert absent not in text
    assert not {"S", "No", "No.", "Item"} & set(text.splitlines())


def test_ombudsman_directory_is_not_chunked(by_number):
    assert not any("Ombudsman, " in record["source_text"] for record in by_number.values())


def test_list_i_matches_the_standalone_excluded_items_pdf(by_number):
    # This match is why excluded_items.pdf is not chunked (ADR-0003).
    pages = PdfReader(ROOT / "data/policy/new_india/excluded_items.pdf").pages
    standalone = "\n".join(page.extract_text() for page in pages)
    standalone = standalone.split("S No Item", 1)[1]
    in_wording = by_number["annexure-a.list-i"]["source_text"].split("\n", 1)[1]
    assert _letters_and_digits(in_wording) == _letters_and_digits(standalone)


def test_extracts_numbered_clauses_with_hierarchy_and_source_pages():
    records, metadata = extract_clauses(ROOT / "data/policy/new_india/policy_wording.pdf")
    assert records
    assert metadata["page_count"] == 33
    assert records[0]["clause_number"] == "1"
    assert records[0]["page_number"] == 1
    assert any(record["clause_number"] == "6.2" for record in records)
    assert any(record["clause_number"].startswith("6.2.") for record in records)
    by_number = {record["clause_number"]: record for record in records}
    assert by_number["6.2.1"]["section_context"]["text"].endswith("24 Months waiting period")
    assert by_number["6.2.21"]["section_context"]["text"].endswith("36 Months waiting period")
    assert all(record["source_text"].strip() for record in records)
    assert all(record["source_sha256"] == metadata["source_sha256"] for record in records)


def test_waiting_period_structuring_keeps_conditions_and_exceptions_explicit():
    records, metadata = extract_clauses(ROOT / "data/policy/new_india/policy_wording.pdf")
    by_number = {record["clause_number"]: record for record in records}
    waiting = [
        structure_clause(r, metadata, by_number)
        for r in records
        if r["clause_number"].startswith("6.")
    ]
    assert waiting
    serialized = json.dumps(waiting, ensure_ascii=False).lower()
    assert "duration_text" in serialized
    assert "applies_to_text" in serialized
    assert "section_context_text" in serialized
    assert 'numeric_threshold": null' in serialized
    assert all(item["verification_status"] == "not_human_verified" for item in waiting)
    first_item = next(item for item in waiting if item["clause_number"] == "6.2.1")
    assert first_item["proposed_interpretation"]["waiting_period"]["duration_text"] == ["24 Months"]
    assert any(
        "accident" in value.lower() for value in first_item["proposed_interpretation"]["exceptions"]
    )


def test_jsonl_writer_emits_one_json_object_per_line(tmp_path):
    output = tmp_path / "nested" / "records.jsonl"
    write_jsonl(output, [{"a": 1}, {"b": "हिंदी"}])
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert rows == [{"a": 1}, {"b": "हिंदी"}]
