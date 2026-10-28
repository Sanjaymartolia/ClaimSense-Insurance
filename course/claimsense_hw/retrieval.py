"""Searching the policy (Lecture 6).

Whatever this returns is all the agent knows. If the right clause is missing, no
prompt can save the answer. `dense` (search by meaning) already works; TODO 2 adds
the rest. Measure every change with the free, no-LLM command:

    python scripts/evaluate_dev.py --retrieval-only --label <name>
"""

import json
from dataclasses import dataclass

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

from . import config, kb


@dataclass
class Hit:
    chunk_id: str
    doc_id: str
    title: str
    text: str
    score: float
    metadata: dict


def _collection():
    client = chromadb.PersistentClient(path=str(config.INDEX_DIR))
    embed = SentenceTransformerEmbeddingFunction(model_name=config.EMBED_MODEL)
    return client.get_or_create_collection("policy", embedding_function=embed)


def build_index(strategy=None, force=False):
    """Embed every chunk into Chroma and save the chunks for keyword search."""
    chunks_file = config.INDEX_DIR / "chunks.json"
    if chunks_file.exists() and not force:
        return
    chunks = kb.chunk_documents(strategy)  # first: if this fails, the old index survives
    config.INDEX_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(config.INDEX_DIR))
    if "policy" in [c.name if hasattr(c, "name") else c for c in client.list_collections()]:
        client.delete_collection("policy")  # start clean: old chunks would linger otherwise
    col = _collection()
    col.add(
        ids=[c.chunk_id for c in chunks],
        documents=[c.text for c in chunks],
        metadatas=[{"doc_id": c.doc_id, "title": c.title, **c.metadata} for c in chunks],
    )
    chunks_file.write_text(json.dumps([c.__dict__ for c in chunks]), encoding="utf-8")
    print(f"indexed {len(chunks)} chunks ({strategy or config.CHUNK_STRATEGY})")


class Retriever:
    def __init__(self, mode=None, top_k=None):
        self.mode = mode or config.RETRIEVAL_MODE
        self.top_k = top_k or config.TOP_K
        chunks_file = config.INDEX_DIR / "chunks.json"
        if not chunks_file.exists():
            raise FileNotFoundError("no index yet: run  python scripts/build_index.py --force")
        self.chunks = [kb.Chunk(**c) for c in json.loads(chunks_file.read_text("utf-8"))]
        self.collection = _collection()

    def dense(self, query, k):
        res = self.collection.query(query_texts=[query], n_results=min(k, len(self.chunks)))
        return [
            Hit(cid, m["doc_id"], m["title"], text, 1 / (1 + dist), m)
            for cid, text, m, dist in zip(
                res["ids"][0],
                res["documents"][0],
                res["metadatas"][0],
                res["distances"][0],
                strict=True,
            )
        ]

    def lexical(self, query, k):
        """TODO 2a — keyword search (BM25). Lecture 6, "Hybrid search"."""
        # Hint: rank_bm25.BM25Okapi needs a list of token lists, one per chunk in
        #       self.chunks. Score the query, keep the top k, return Hits like dense().
        # Think: does "room-rent" split the same way as "room rent"? Does "Rs.5000/-"
        #        match a query that says 5000? Lower-case and split on non-letters/digits.
        raise NotImplementedError("TODO 2a")

    def rrf(self, *rankings, k=None):
        """TODO 2b — merge ranked lists by POSITION, not score. Lecture 6, "RRF".

        A chunk ranked 1st in one list and 3rd in the other scores
        1/(k+1) + 1/(k+3), with k = config.RRF_K. Scores from dense and BM25 are on
        different scales, so never add the raw scores.
        """
        # Hint: a dict chunk_id -> summed score, plus chunk_id -> Hit to return.
        raise NotImplementedError("TODO 2b")

    def hybrid(self, query, k):
        """TODO 2c — run dense and lexical, merge with rrf()."""
        # Then compare, and write the numbers down (the run log plots them for you):
        #   RETRIEVAL_MODE=dense  python scripts/evaluate_dev.py --retrieval-only --label dense
        #   RETRIEVAL_MODE=hybrid python scripts/evaluate_dev.py --retrieval-only --label hybrid
        # 167 clauses is tiny. "It gained 0.02 so I left it off" is a good, honest answer.
        raise NotImplementedError("TODO 2c")

    def postprocess(self, hits):
        """TODO 2d — the supporting list must never outrank the wording. Lecture 5.

        `excluded_items_reference` chunks (config.SUPPORTING_RECORD_TYPE) come from a
        supporting list, not the contract. Pick one, and defend it in the report:
          * drop them;
          * push them below every policy_clause hit;
          * keep them for context but never let them be cited (see graph._clean_citations).
        """
        return hits

    def search(self, query, k=None):
        k = k or self.top_k
        hits = {"dense": self.dense, "hybrid": self.hybrid}[self.mode](query, config.CANDIDATE_K)
        return self.postprocess(hits)[:k]


_RETRIEVER = None


def get_retriever():
    """Load the index once per process."""
    global _RETRIEVER
    if _RETRIEVER is None:
        _RETRIEVER = Retriever()
    return _RETRIEVER


def format_context(hits):
    """One identifier per passage — the id the model must cite."""
    return (
        "\n\n".join(
            f"[clause: {h.doc_id}] ({h.metadata.get('record_type')})\n{h.title}\n{h.text.strip()}"
            for h in hits
        )
        or "(nothing retrieved)"
    )
