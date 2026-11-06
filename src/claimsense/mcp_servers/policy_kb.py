"""policy-kb MCP server (READ-ONLY). ClaimSense Role 4 (Tools, Control & Security).

Single policy search/lookup service for the ClaimSense agents, backed by **Role 2's hybrid
retriever** (``claimsense.retrieval``: BM25 + dense + RRF + cross-encoder reranker). This module is
the proposed replacement for the ``policy_kb`` stub that ships in the repository at
``src/claimsense/mcp_servers/policy_kb.py`` and for the earlier Role 4 ``policy_server.py`` that
carried its own independent keyword index. There is exactly one search engine now: Shashank's
``HybridRetriever``. The old keyword implementation is intentionally dropped (see "Stale index").

Two integration paths, one implementation
------------------------------------------
* Path A - direct Python service: Role 3 wires the plain callables into
  ``claimsense.agents.services.Services`` (registry names ``policy_search`` / ``get_clause``, used
  by the COVERAGE and CRITIC agents per ``agents/permissions.TOOL_ACL``)::

      from claimsense.mcp_servers.policy_kb import policy_search, get_clause

* Path B - MCP: the same callables are exposed through FastMCP wrappers in :func:`main`.

Both paths share one process-wide ``HybridRetriever`` and the same conversion logic, so they can
never drift apart.

Contract mapping (verified against ``claimsense.retrieval.search`` and ``claimsense.contracts``)
------------------------------------------------------------------------------------------------
``SearchHit``/``FullClause`` carry neither ``policy_name`` nor ``insurer``, which the shared
``Clause`` contract requires. Those two policy-level values are read from the knowledge-base
``source`` metadata (``product`` -> ``policy_name``, ``insurer`` -> ``insurer``) via Role 2's own
``load_chunks`` loader - not invented. This KB ships a single policy product (confirmed in
``data/knowledge_base/manifest.json`` and in every record's ``source``), so they are treated as
constants; a multi-policy KB would need a per-clause map.

* ``Clause.text`` is set from ``SearchHit.context_text`` (NOT ``SearchHit.text``). The context adds
  the headings a terse list item needs - e.g. a disease name under its waiting-period heading -
  without which the clause's meaning is lost (retrieval README, "For policy-kb (T16)"). A full
  clause fetched by id uses ``FullClause.text`` (its parts already merged).
* ``score`` / ``rank`` are copied straight from the ``SearchHit``.
* ``section`` <- ``clause_number`` (the number as printed in the wording); ``title`` <- ``title``;
  ``clause_id`` <- ``clause_id`` (e.g. ``new_india_arogya_sanjeevani:12.1``, the real KB id).
* ``source_url`` is built from the hit's ``document`` + first page number.

Effective date
--------------
The ``Clause`` contract requires an ``effective_date``, but no source document states a policy
effective date (ADR-0004: ``source.document_date`` is only the PDF's creation date, never a policy
effective date, and is deliberately *not* used here). We reuse the established Role 4 handling:
``CLAIMSENSE_POLICY_EFFECTIVE_DATE`` (ISO ``YYYY-MM-DD``) when set, otherwise the explicit
:data:`UNKNOWN_EFFECTIVE_DATE` sentinel (``1900-01-01``) that is obviously not a real date. The same
configured date is used for both search results and exact lookups. We do not assume 2020-04-01
merely because Arogya Sanjeevani launched then; the wording version here is not verified.

Conflict handling
-----------------
``FullClause.conflict`` is set when another clause applies instead (ADR-0004; e.g. table row 12.5
contradicts clause 6.1). The shared ``Clause`` contract has no field for it and must not be
changed, so a conflicted clause is still returned in full (never discarded, never silently treated
as a single verified rule) and a WARNING is logged with the clause id and the conflict payload.
**Callers that receive the plain ``Clause`` currently do NOT see the conflict flag** - surfacing it
to agents needs a two-role contract PR to add a field to ``Clause``/``RetrievedPassage``. Until
then the log is the signal. (``policy_search`` is unaffected: only ``searchable`` chunks are
retrieved and the conflicting row is non-searchable.)

Stale index
-----------
Role 2's ``open_retriever`` raises ``StaleIndexError`` when the index is missing or was built from
other chunks/another embedding model. We **fail loudly** rather than fall back to a second engine:
reinstating the old keyword index would recreate exactly the duplicate policy server this task
removes. The failure is logged once and cached, so a broken 30-second open is not retried on every
request; fix the index (``python -m claimsense.retrieval.index``) and restart the process. At the
MCP boundary this surfaces as a structured ``ToolError`` (``code="stale_index"``); the plain Python
functions propagate the exception rather than lying with an empty result.

Security
--------
Retrieved policy wording is untrusted *reference data*, never instructions for an agent. Queries
and clause text are never logged (they can hold health details); only non-sensitive metadata
(error messages, clause ids, conflict payloads) is logged.

Run as a server (needs ``pip install -e ".[mcp]"`` and ``.[retrieval]``)::

    python -m claimsense.mcp_servers.policy_kb     # in-package
    python policy_kb.py                            # standalone, stdio transport
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING


# --------------------------------------------------------------------------------------------
# Make the repository's ``claimsense`` package importable when this file is run from outside the
# installed package (as the standalone Role 4 deliverable). It is a no-op once the module lives at
# ``src/claimsense/mcp_servers/policy_kb.py``, because ``import claimsense`` then succeeds first.
# Override the search root with CLAIMSENSE_SRC=/abs/path/to/ClaimSense-Insurance/src.
# --------------------------------------------------------------------------------------------
def _ensure_claimsense_on_path() -> None:
    try:
        import claimsense  # noqa: F401

        return
    except ModuleNotFoundError:
        pass
    env = os.environ.get("CLAIMSENSE_SRC")
    here = Path(__file__).resolve()
    candidates = [Path(env)] if env else []
    candidates += [
        here.parent.parent / "ClaimSense-Insurance" / "src",
        here.parent / "ClaimSense-Insurance" / "src",
    ]
    for cand in candidates:
        if (cand / "claimsense").is_dir():
            sys.path.insert(0, str(cand))
            return


_ensure_claimsense_on_path()

from pydantic import BaseModel  # noqa: E402

from claimsense.contracts import Clause, RetrievedPassage  # noqa: E402

if TYPE_CHECKING:  # import only for type checking; the real import is lazy (optional heavy deps)
    from claimsense.retrieval.search import FullClause, HybridRetriever, SearchHit

logger = logging.getLogger("claimsense.mcp_servers.policy_kb")


# --------------------------------------------------------------------------------------------
# Effective-date configuration (reused from the earlier Role 4 policy_server; see module docstring)
# --------------------------------------------------------------------------------------------
#: Sentinel meaning "the policy wording's effective date is NOT present in the source data". The
#: ``Clause`` contract needs a real ``date``; we refuse to invent one. Set the true date once the
#: domain lead verifies the policy version:  CLAIMSENSE_POLICY_EFFECTIVE_DATE=YYYY-MM-DD.
UNKNOWN_EFFECTIVE_DATE = date(1900, 1, 1)

#: Relative citation prefix for ``Clause.source_url``. The knowledge base stores only the PDF file
#: name in ``source.document``; the directory is the one recorded in the KB manifest
#: (``inputs.policy_wording.path = data/policy/new_india/policy_wording.pdf``). This is a repo-
#: relative reference for provenance, not a path opened at runtime, so it is machine-independent.
POLICY_SOURCE_DIR = "data/policy/new_india"

#: Verified policy-level metadata, used only as a fallback if a record's ``source`` omits it. These
#: are the values every record in this single-policy KB carries today (not invented placeholders).
_FALLBACK_INSURER = "The New India Assurance Co. Ltd."
_FALLBACK_PRODUCT = "Arogya Sanjeevani Policy"


def _configured_effective_date() -> date:
    """Policy effective date from ``CLAIMSENSE_POLICY_EFFECTIVE_DATE``, else the unknown sentinel.

    Deterministic within a process (reads an environment variable that does not change), so search
    and exact-lookup results stay consistent. An unset or malformed value yields
    :data:`UNKNOWN_EFFECTIVE_DATE` rather than a guessed real date.
    """
    raw = os.environ.get("CLAIMSENSE_POLICY_EFFECTIVE_DATE")
    if not raw:
        return UNKNOWN_EFFECTIVE_DATE
    try:
        return date.fromisoformat(raw.strip())
    except ValueError:
        return UNKNOWN_EFFECTIVE_DATE


class ToolError(BaseModel):
    """Structured error returned at the MCP boundary instead of raising to an agent."""

    error: str
    code: str = "policy_kb_error"
    retryable: bool = False


# --------------------------------------------------------------------------------------------
# Process-wide retriever + policy metadata, opened once (the open costs ~30 s, mostly importing
# torch and loading the reranker). Thread-safe double-checked init; a failed open is cached so a
# broken index is not re-opened on every request (fix it and restart - see module docstring).
# --------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class _PolicyMeta:
    """Policy-level fields the retriever's models drop but the ``Clause`` contract needs."""

    insurer: str
    product: str


@dataclass(frozen=True)
class _Engine:
    retriever: "HybridRetriever"
    meta: _PolicyMeta


_ENGINE: _Engine | None = None
_ENGINE_ERROR: Exception | None = None
_ENGINE_LOCK = threading.Lock()


def _derive_policy_meta(chunks: list[dict]) -> _PolicyMeta:
    """Read insurer/product from the KB ``source`` metadata (uniform across this single-policy KB)."""
    for chunk in chunks:
        source = chunk.get("source") if isinstance(chunk, dict) else None
        if isinstance(source, dict) and source.get("insurer") and source.get("product"):
            return _PolicyMeta(insurer=str(source["insurer"]), product=str(source["product"]))
    return _PolicyMeta(insurer=_FALLBACK_INSURER, product=_FALLBACK_PRODUCT)


def _build_engine() -> _Engine:
    # Lazy imports: the retrieval stack pulls in optional, heavy dependencies (chromadb, torch,
    # sentence-transformers, rank-bm25) that must not be required merely to import this module.
    from claimsense.retrieval.index import load_chunks, open_retriever

    retriever = open_retriever()  # may raise StaleIndexError / FileNotFoundError / ImportError
    meta = _derive_policy_meta(load_chunks())  # same default KB the retriever was opened from
    return _Engine(retriever=retriever, meta=meta)


def _engine() -> _Engine:
    """Return the shared engine, opening it once. Re-raises a cached open failure without retrying."""
    global _ENGINE, _ENGINE_ERROR
    if _ENGINE is not None:
        return _ENGINE
    with _ENGINE_LOCK:
        if _ENGINE is not None:
            return _ENGINE
        if _ENGINE_ERROR is not None:
            raise _ENGINE_ERROR
        try:
            _ENGINE = _build_engine()
        except Exception as exc:  # cache once; do not re-open a broken index on every call
            _ENGINE_ERROR = exc
            logger.warning("policy-kb retriever could not be opened: %s", exc)
            raise
    return _ENGINE


def warm_up() -> None:
    """Open the retriever ahead of the first request (~30 s), so searches don't pay that latency.

    Role 3 or the server entry point can call this at start-up. Raises the underlying error (e.g.
    ``StaleIndexError``) if the index cannot be opened; that failure is cached, not retried.
    """
    _engine()


# --------------------------------------------------------------------------------------------
# SearchHit / FullClause -> shared contracts
# --------------------------------------------------------------------------------------------
def _source_url(document: str, page_numbers: list[int]) -> str:
    page = page_numbers[0] if page_numbers else None
    base = f"{POLICY_SOURCE_DIR}/{document}"
    return f"{base}#page={page}" if page else base


def _clause_from_hit(hit: "SearchHit", meta: _PolicyMeta, effective_date: date) -> Clause:
    return Clause(
        clause_id=hit.clause_id,
        policy_name=meta.product,
        insurer=meta.insurer,
        section=hit.clause_number,
        title=hit.title,
        text=hit.context_text,  # context, not verbatim hit.text - keeps headings/waiting periods
        effective_date=effective_date,
        source_url=_source_url(hit.document, hit.page_numbers),
    )


def _clause_from_full(full: "FullClause", meta: _PolicyMeta, effective_date: date) -> Clause:
    return Clause(
        clause_id=full.clause_id,
        policy_name=meta.product,
        insurer=meta.insurer,
        section=full.clause_number,
        title=full.title,
        text=full.text,  # the whole clause, with its split parts already merged by the retriever
        effective_date=effective_date,
        source_url=_source_url(full.document, full.page_numbers),
    )


# --------------------------------------------------------------------------------------------
# Public plain-Python service callables (names/signatures match Services.registry + TOOL_ACL).
# Role 3 binds these directly; they return the shared contracts and do not return ToolError.
# --------------------------------------------------------------------------------------------
def policy_search(query: str, category: str | None = None, k: int = 5) -> list[RetrievedPassage]:
    """[read] Hybrid search over the policy wording, via Role 2's ``HybridRetriever``.

    ``category`` is accepted for interface parity with the Role 3 stub but is intentionally unused:
    the hybrid retriever performs its own bill-line query rewriting and ranking and takes no
    category. A blank query yields ``[]`` (the retriever's own behaviour). Raises ``StaleIndexError``
    when the index needs rebuilding rather than returning an empty list.
    """
    engine = _engine()
    effective_date = _configured_effective_date()
    hits = engine.retriever.search(query, k=k)
    return [
        RetrievedPassage(
            clause=_clause_from_hit(hit, engine.meta, effective_date),
            score=hit.score,
            rank=hit.rank,
        )
        for hit in hits
    ]


def get_clause(clause_id: str) -> Clause | None:
    """[read] Fetch one exact clause by id, or ``None`` if the id is not in the wording.

    Uses Role 2's exact lookup (``HybridRetriever.get_clause``). A conflicted clause (ADR-0004) is
    still returned in full; the conflict is logged as a WARNING because the shared ``Clause``
    contract cannot carry it (see module docstring).
    """
    engine = _engine()
    full = engine.retriever.get_clause((clause_id or "").strip())
    if full is None:
        return None
    if full.conflict:
        logger.warning(
            "policy-kb clause %s has a wording conflict %s; the shared Clause contract cannot "
            "carry it, so the caller receives the clause text WITHOUT the conflict flag.",
            full.clause_id,
            full.conflict,
        )
    return _clause_from_full(full, engine.meta, _configured_effective_date())


# --------------------------------------------------------------------------------------------
# MCP tool wrappers: never raise to an agent and never return a bare None - convert every outcome
# into a shared contract or a structured ``ToolError``. This is the only layer that knows ToolError.
# --------------------------------------------------------------------------------------------
def _tool_policy_search(query: str, category: str | None = None, k: int = 5):
    """[read] Search policy clauses. Returns a list of ``RetrievedPassage`` or a ``ToolError``."""
    from claimsense.retrieval.index import StaleIndexError

    if not query or not query.strip():
        return ToolError(error="query must be a non-empty string", code="empty_query")
    try:
        results = policy_search(query, category=category, k=k)
    except StaleIndexError as exc:
        return ToolError(error=str(exc), code="stale_index", retryable=False)
    except (FileNotFoundError, ImportError) as exc:
        return ToolError(error=str(exc), code="kb_unavailable", retryable=False)
    except Exception as exc:  # defensive: an agent must never see a raw crash
        return ToolError(error=f"policy search failed: {exc}")
    if not results:
        return ToolError(error="no matching clause", code="no_match")
    return results


def _tool_get_clause(clause_id: str):
    """[read] Fetch one clause by id. Returns a ``Clause`` or a ``ToolError``."""
    from claimsense.retrieval.index import StaleIndexError

    if not clause_id or not clause_id.strip():
        return ToolError(error="clause_id must be a non-empty string", code="empty_clause_id")
    try:
        clause = get_clause(clause_id)
    except StaleIndexError as exc:
        return ToolError(error=str(exc), code="stale_index", retryable=False)
    except (FileNotFoundError, ImportError) as exc:
        return ToolError(error=str(exc), code="kb_unavailable", retryable=False)
    except Exception as exc:  # defensive: an agent must never see a raw crash
        return ToolError(error=f"get_clause failed: {exc}")
    if clause is None:
        return ToolError(
            error=f"clause {clause_id!r} not found in policy wording", code="unknown_clause"
        )
    return clause


def main() -> None:
    """Start the policy-kb MCP server over stdio. FastMCP is imported here, never at module load."""
    from fastmcp import FastMCP  # optional dependency: pip install -e ".[mcp]"

    try:
        warm_up()  # pay the ~30 s open once at start-up; a stale index is reported per call below
    except Exception as exc:
        logger.warning("policy-kb starting with an unusable retriever; tools will error: %s", exc)

    mcp = FastMCP("policy-kb")
    mcp.tool(name="policy_search")(_tool_policy_search)
    mcp.tool(name="get_clause")(_tool_get_clause)
    mcp.run()


if __name__ == "__main__":
    main()
