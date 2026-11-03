"""Build and open the policy search index (Knowledge & Memory, L5-L6).

Only ``searchable`` chunks are indexed (ADR-0004). BM25 is rebuilt in memory on load, and hits are
joined back to the knowledge base by chunk ID, so Chroma holds just the IDs and embeddings.

Run from the repository root: ``python -m claimsense.retrieval.index``.
"""

import argparse
import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from claimsense.config import load_config
from claimsense.retrieval.search import Embedder, HybridRetriever, Reranker

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_KB = REPO_ROOT / "data/knowledge_base/policy_knowledge_base.jsonl"
DEFAULT_INDEX_DIR = REPO_ROOT / "chroma-data"
COLLECTION = "policy_clauses"
REBUILD_COMMAND = "python -m claimsense.retrieval.index"


class StaleIndexError(RuntimeError):
    """The index is missing or was built from other chunks or another embedding model."""


def load_chunks(path: Path = DEFAULT_KB) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def fingerprint(chunks: Iterable[dict[str, Any]], embedding_model: str) -> str:
    """Hash parsed records, not the file, so LF and CRLF checkouts agree."""
    searchable = sorted(
        (chunk for chunk in chunks if chunk["searchable"]), key=lambda c: c["chunk_id"]
    )
    content = [embedding_model, *([c["chunk_id"], c["text"]] for c in searchable)]
    return hashlib.sha256(json.dumps(content, ensure_ascii=False).encode()).hexdigest()


def persistent_client(index_dir: Path = DEFAULT_INDEX_DIR) -> Any:
    import chromadb  # optional dependency: pip install -e ".[retrieval]"
    from chromadb.config import Settings

    return chromadb.PersistentClient(
        path=str(index_dir), settings=Settings(anonymized_telemetry=False)
    )


def load_embedder(model_name: str) -> Embedder:
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_name)

    def embed(texts: Iterable[str]) -> list[list[float]]:
        vectors = model.encode(list(texts), normalize_embeddings=True, show_progress_bar=False)
        return vectors.tolist()

    return embed


def load_reranker(model_name: str) -> Reranker:
    from sentence_transformers import CrossEncoder

    model = CrossEncoder(model_name)

    def rerank(query: str, texts: Iterable[str]) -> list[float]:
        pairs = [(query, text) for text in texts]
        return model.predict(pairs, show_progress_bar=False).tolist()

    return rerank


def build_index(
    chunks: list[dict[str, Any]], embed: Embedder, embedding_model: str, client: Any
) -> int:
    """Replace the index, so no chunk from an older build can survive."""
    client.get_or_create_collection(COLLECTION)
    client.delete_collection(COLLECTION)
    collection = client.create_collection(
        COLLECTION,
        metadata={"hnsw:space": "cosine", "fingerprint": fingerprint(chunks, embedding_model)},
    )
    searchable = [chunk for chunk in chunks if chunk["searchable"]]
    collection.add(
        ids=[chunk["chunk_id"] for chunk in searchable],
        embeddings=embed([chunk["text"] for chunk in searchable]),
        metadatas=[{"clause_id": chunk["clause_id"]} for chunk in searchable],
    )
    return len(searchable)


def open_collection(client: Any, chunks: list[dict[str, Any]], embedding_model: str) -> Any:
    """Return the index, refusing one that doesn't match the knowledge base and model."""
    collection = client.get_or_create_collection(COLLECTION)
    built_from = (collection.metadata or {}).get("fingerprint")
    if built_from != fingerprint(chunks, embedding_model):
        raise StaleIndexError(f"Search index is missing or out of date. Run: {REBUILD_COMMAND}")
    return collection


def open_retriever(
    kb_path: Path = DEFAULT_KB, index_dir: Path = DEFAULT_INDEX_DIR
) -> HybridRetriever:
    config = load_config()
    chunks = load_chunks(kb_path)
    # Check the index first: a stale one should fail before the models take time to load.
    collection = open_collection(persistent_client(index_dir), chunks, config["embeddings"])
    return HybridRetriever(
        chunks, collection, load_embedder(config["embeddings"]), load_reranker(config["reranker"])
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kb", type=Path, default=DEFAULT_KB)
    parser.add_argument("--index-dir", type=Path, default=DEFAULT_INDEX_DIR)
    args = parser.parse_args()
    model = load_config()["embeddings"]
    client = persistent_client(args.index_dir)
    count = build_index(load_chunks(args.kb), load_embedder(model), model, client)
    print(f"Indexed {count} searchable chunks with {model} in {args.index_dir}.")


if __name__ == "__main__":
    main()
