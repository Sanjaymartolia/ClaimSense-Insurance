"""Build the retrieval knowledge base directly from the policy wording PDF.

The numbered-clause parser runs in memory against policy_wording.pdf. The structured
JSONL produced by the separate clause-review pipeline is not an input to this builder.
The other policy PDFs are deliberately not chunked (ADR-0003).

This script does not make coverage decisions or verify heuristic interpretations.
It produces provenance-preserving JSONL chunks suitable for later embedding and
indexing into Chroma, FAISS, or another vector store.

Run from the repository root: ``python -m claimsense.ingestion.build_policy_knowledge_base``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from claimsense.ingestion.extract_policy_clauses import (
    DEFAULT_POLICY,
    REPO_ROOT,
    extract_clauses,
    structure_clause,
)
from claimsense.ingestion.extract_policy_clauses import (
    PARSER_VERSION as CLAUSE_PARSER_VERSION,
)

PARSER_VERSION = "1.1.0"
DEFAULT_OUTPUT = "data/knowledge_base/policy_knowledge_base.jsonl"
DEFAULT_MANIFEST = "data/knowledge_base/manifest.json"
DEFAULT_CHUNK_SIZE = 1800
DEFAULT_OVERLAP = 250


def portable_path(path: Path) -> str:
    """Return a repository-relative path when the input lives inside the repo."""
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return Path(path).as_posix()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    return count


def clean_pdf_text(text: str) -> str:
    # Normalize extraction artifacts lightly; preserve original wording and
    # punctuation as returned by pypdf rather than rewriting legal language.
    text = text.replace("\x00", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_text(text: str, max_chars: int, overlap: int) -> list[str]:
    """Split at paragraph/sentence/space boundaries while enforcing a hard cap."""
    if max_chars < 200:
        raise ValueError("--chunk-size must be at least 200 characters")
    if overlap < 0 or overlap >= max_chars:
        raise ValueError("--overlap must be >= 0 and smaller than --chunk-size")
    text = clean_pdf_text(text)
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        if end < len(text):
            # Prefer nearby semantic boundaries in the latter half of the window.
            floor = start + max_chars // 2
            candidates = [
                text.rfind("\n\n", floor, end),
                text.rfind("\n", floor, end),
                text.rfind(". ", floor, end),
                text.rfind("; ", floor, end),
                text.rfind(" ", floor, end),
            ]
            boundary = max(candidates)
            if boundary > start:
                end = min(end, boundary + (1 if text[boundary : boundary + 1] in "\n " else 2))
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return chunks


def clause_records(policy_pdf: Path, chunk_size: int, overlap: int) -> list[dict[str, Any]]:
    """Extract and structure clauses directly from the source policy PDF.

    Raw and structured records are built in memory. The separate structured
    JSONL remains available for review, but is not an input to this builder.
    """
    raw_records, source_metadata = extract_clauses(policy_pdf)
    raw_by_number = {record["clause_number"]: record for record in raw_records}
    records = [structure_clause(record, source_metadata, raw_by_number) for record in raw_records]
    kb: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for record in records:
        rid = str(record.get("record_id") or record.get("clause_id") or "").strip()
        if not rid:
            raise ValueError("Structured clause record missing record_id/clause_id")
        if rid in seen_ids:
            raise ValueError(f"Duplicate clause identifier in structured file: {rid}")
        seen_ids.add(rid)

        source = record.get("source") or {}
        interpretation = record.get("proposed_interpretation") or {}
        raw_text = str(record.get("source_text") or "").strip()
        if not raw_text:
            raise ValueError(f"Clause {rid} has empty source_text")
        pieces = split_text(raw_text, chunk_size, overlap)
        parent = interpretation.get("parent_context") or {}
        waiting = interpretation.get("waiting_period")
        for idx, piece in enumerate(pieces, start=1):
            chunk_id = f"clause::{rid}::part-{idx:03d}"
            parent_source_text = str(parent.get("source_text") or "").strip()
            parent_heading = (
                parent_source_text.splitlines()[0].strip() if parent_source_text else ""
            )
            # Repeating a compact section context makes terse list items
            # retrievable (e.g., a disease name under a waiting-period section).
            # The exact chunk text remains separately available as source_text.
            clause_number = record.get("clause_number")
            context_lines = [
                f"Policy wording clause {clause_number}: {record.get('title') or ''}".strip(),
            ]
            if parent_heading:
                parent_number = parent.get("clause_number") or record.get("parent_clause_number")
                context_lines.append(f"Parent section {parent_number}: {parent_heading}")
            section_context = (waiting or {}).get("section_context_text")
            if section_context:
                # A list item takes its own period only; the parent's conditions stay in
                # proposed_interpretation so they don't drown out the item's name.
                context_lines.append("Waiting-period section context: " + section_context)
            elif parent_source_text and str(clause_number).startswith("6."):
                context_lines.append("Waiting-period section context: " + parent_source_text[:1400])
            retrieval_text = "\n".join(context_lines) + "\nClause source text:\n" + piece
            kb.append(
                {
                    "chunk_id": chunk_id,
                    "record_type": "policy_clause",
                    "text": retrieval_text,
                    "source_text": piece,
                    "title": record.get("title"),
                    "clause_id": rid,
                    "clause_number": record.get("clause_number"),
                    "displayed_number": record.get("displayed_number"),
                    "parent_clause_number": record.get("parent_clause_number"),
                    "hierarchy": record.get("hierarchy") or [],
                    "chunk_index": idx,
                    "chunk_count": len(pieces),
                    "source": {
                        "document": source.get("document") or "policy_wording.pdf",
                        "sha256": source.get("sha256"),
                        "page_number": source.get("page_number"),
                        "page_numbers": source.get("page_numbers") or [],
                        "insurer": source.get("insurer"),
                        "product": source.get("product"),
                        "uin_observed_in_policy_pdf": source.get("uin_observed_in_policy_pdf"),
                    },
                    "proposed_interpretation": {
                        "topic": interpretation.get("topic"),
                        "rule_type": interpretation.get("rule_type"),
                        "applicability_conditions": interpretation.get("applicability_conditions")
                        or [],
                        "exceptions": interpretation.get("exceptions") or [],
                        "numeric_threshold": interpretation.get("numeric_threshold"),
                        "waiting_period": waiting,
                        "interpretation_method": interpretation.get("interpretation_method"),
                        "parent_context": {
                            "clause_number": parent.get("clause_number")
                            or record.get("parent_clause_number"),
                            "source_text": parent.get("source_text"),
                            "page_numbers": parent.get("page_numbers") or [],
                        }
                        if parent
                        else None,
                    },
                    "verification_status": record.get("verification_status", "not_human_verified"),
                    "authority_level": "primary_policy_wording",
                    "retrieval_warning": (
                        "Retrieve as source evidence only. Proposed interpretation is heuristic; "
                        "do not treat it as verified or sufficient for an automated "
                        "coverage decision."
                    ),
                }
            )
    return kb


def build_knowledge_base(
    policy_pdf: Path,
    output_jsonl: Path,
    manifest_path: Path,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> dict[str, Any]:
    if not policy_pdf.is_file():
        raise FileNotFoundError(f"Required source PDF not found: {policy_pdf}")

    policy_records = clause_records(policy_pdf, chunk_size, overlap)

    # Confirm the in-memory extractor is tied to the exact source PDF.
    expected_policy_hash = sha256_file(policy_pdf)
    mismatches = [
        record.get("clause_id")
        for record in policy_records
        if (record.get("source") or {}).get("sha256") != expected_policy_hash
    ]
    if mismatches:
        raise ValueError(
            f"In-memory clause extraction hash differs from policy_wording.pdf "
            f"for {len(mismatches)} chunks."
        )

    # Deterministic order and unique stable IDs are useful for reproducible embedding runs.
    ids = [r["chunk_id"] for r in policy_records]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate chunk_id generated; refusing to write KB")
    written = write_jsonl(output_jsonl, policy_records)

    policy_reader = PdfReader(str(policy_pdf))
    manifest = {
        "knowledge_base_version": "1.1.0",
        "built_by": "src/claimsense/ingestion/build_policy_knowledge_base.py",
        "inputs": {
            "policy_wording": {
                "path": portable_path(policy_pdf),
                "sha256": expected_policy_hash,
                "page_count": len(policy_reader.pages),
                "authority_level": "primary_policy_wording",
            },
        },
        "clause_extraction": {
            "source": "policy_wording.pdf",
            "method": "pypdf extraction and in-memory numbered-clause heuristics",
            "parser": "src/claimsense/ingestion/extract_policy_clauses.py",
            "parser_version": CLAUSE_PARSER_VERSION,
            "derived_record_count": len({record.get("clause_id") for record in policy_records}),
            "verification_status": "heuristic_draft_not_human_verified",
            "intermediate_jsonl_used_as_input": False,
        },
        "outputs": {
            "jsonl_path": portable_path(output_jsonl),
            "record_count": written,
            "policy_clause_chunks": len(policy_records),
            "unique_chunk_ids": len(set(ids)),
        },
        "chunking": {
            "max_chars": chunk_size,
            "overlap_chars": overlap,
            "split_strategy": "paragraph_sentence_whitespace_boundaries",
        },
        "safety_and_provenance": [
            "Source text is retained separately from proposed interpretation.",
            "All chunks require human verification before use as authoritative adjudication rules.",
            "Waiting-period applicability, conditions and exceptions are retained as "
            "source-linked text.",
            "No numeric threshold is inferred by this builder.",
            "excluded_items.pdf is not chunked: it repeats List I of Annexure-A (ADR-0003).",
            "For final decisions, check the policy schedule, endorsements, coverage dates "
            "and version.",
        ],
        "limitations": [
            "PDF text extraction may omit text embedded in images or complex layouts; "
            "inspect empty pages.",
            "Clause-level heuristics may mislabel topics/conditions/exceptions and are not "
            "proof of meaning.",
            "This output is a retrieval corpus, not an embedding index; embeddings and "
            "vector-store schema are downstream steps.",
        ],
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy-pdf", type=Path, default=REPO_ROOT / DEFAULT_POLICY)
    parser.add_argument("--output", type=Path, default=REPO_ROOT / DEFAULT_OUTPUT)
    parser.add_argument("--manifest", type=Path, default=REPO_ROOT / DEFAULT_MANIFEST)
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)
    parser.add_argument("--overlap", type=int, default=DEFAULT_OVERLAP)
    args = parser.parse_args()
    manifest = build_knowledge_base(
        args.policy_pdf,
        args.output,
        args.manifest,
        args.chunk_size,
        args.overlap,
    )
    print(json.dumps(manifest["outputs"], indent=2))
    print(
        "WARNING: this is a retrieval corpus, not verified policy logic or a settlement authority."
    )


if __name__ == "__main__":
    main()
