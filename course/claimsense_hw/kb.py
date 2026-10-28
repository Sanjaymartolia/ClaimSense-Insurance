"""Reading the policy and cutting it into pieces (Lecture 5).

The policy wording was already parsed into numbered clauses by the ingestion pipeline
(`data/knowledge_base/policy_knowledge_base.jsonl`, one record per clause chunk). Each
record carries `clause_id` (what you cite), `title`, `source_text`, `record_type`
(`policy_clause`, or `excluded_items_reference` for the supporting exclusions list),
and page numbers.

What we SHIP ignores all that structure: it glues the text together and cuts every
600 characters, like the HW2 starter. TODO 1 is to stop doing that.
"""

import json
from dataclasses import dataclass, field

from . import config


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str  # the citation: a clause_id, or the excluded-items chunk id
    title: str
    text: str
    metadata: dict = field(default_factory=dict)


def load_records():
    with open(config.KB_FILE, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _doc_id(record):
    return record.get("clause_id") or record["chunk_id"]


def split_fixed(records, size, overlap):
    """Glue everything together and cut every `size` characters.

    Each piece is labelled with the clause it STARTED in, so a piece that starts at
    the end of 4.1 (room rent) and runs into 4.2 (AYUSH) is labelled 4.1. Some
    pieces are mislabelled; some are half one clause and half another.
    Returns (record, text) pairs.
    """
    full, bounds = "", []
    for r in records:
        bounds.append((len(full), r))
        full += (r.get("source_text") or r.get("text") or "") + "\n\n"
    out, pos = [], 0
    while pos < len(full):
        owner = next(r for start, r in reversed(bounds) if start <= pos)
        if full[pos : pos + size].strip():
            out.append((owner, full[pos : pos + size]))
        pos += size - overlap
    return out


def split_clauses(records, size, overlap):
    """TODO 1 — one piece per clause instead. Lecture 5, "Splitting Documents".

    Goal: every piece belongs to exactly one clause, so nothing is mislabelled.
    Return the same thing split_fixed returns: (record, text) pairs.
    """
    # Hint 1: the records are ALREADY clause-sized (the ingestion step capped them at
    #         1,800 characters). Start with: one piece per record, text = source_text.
    # Hint 2: a list item like "6.2.9 Cataract and age related eye ailments" says
    #         nothing about waiting periods on its own. Try putting the record's
    #         `title` (or its parent clause) on the front of the text. Measure that
    #         change SEPARATELY from hint 1, or you won't know which one helped.
    # Hint 3: rebuild after any change, or nothing changes:
    #         python scripts/build_index.py --force --strategy clauses
    raise NotImplementedError("TODO 1 — see the comments above")


def chunk_documents(strategy=None, size=None, overlap=None):
    strategy = strategy or config.CHUNK_STRATEGY
    splitter = {"fixed": split_fixed, "clauses": split_clauses}[strategy]
    pairs = splitter(load_records(), size or config.CHUNK_SIZE, overlap or config.CHUNK_OVERLAP)
    return [
        Chunk(
            chunk_id=f"{_doc_id(r)}#{i}",
            doc_id=_doc_id(r),
            title=r.get("title") or "",
            text=text,
            metadata={
                "record_type": r["record_type"],
                "pages": ",".join(map(str, r["source"]["page_numbers"])),
            },
        )
        for i, (r, text) in enumerate(pairs)
    ]
