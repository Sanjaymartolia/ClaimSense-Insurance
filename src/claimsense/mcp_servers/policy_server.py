"""policy-kb MCP server (READ-ONLY). ClaimSense Role 4 (Tools, Control & Security).

Serves the *actual* New India Assurance "Arogya Sanjeevani" policy wording that ships in the
repository, so the coverage analyst and critic can search clauses and fetch an exact clause by id.

Source of truth (never synthetic placeholders):
    data/knowledge_base/policy_knowledge_base.jsonl   (retrieval corpus, 167 chunks; primary)
    data/processed/policy_clauses_structured.jsonl     (structured clauses; fallback)

Design notes
------------
* Role 3 agents reach this server through ``claimsense.agents.services.Services`` under the
  registry names ``policy_search`` and ``get_clause`` (see ``agents/permissions.TOOL_ACL`` ->
  COVERAGE, CRITIC). The function names here match those registry names exactly.
* Returns the shared contracts ``RetrievedPassage`` / ``Clause`` (``claimsense.contracts``), or a
  structured ``ToolError`` at the MCP boundary - tools never raise to an agent (CLAUDE.md).
* Retrieved clause text is **untrusted reference data**, not instructions. Each source record
  already carries a ``retrieval_warning``; we surface it but never act on clause text.
* ``fastmcp`` is imported lazily inside :func:`main`, so this module (and its tests) import and run
  even when the optional ``[mcp]`` extra is not installed.

Run as a server (needs ``pip install -e ".[mcp]"``)::

    python policy_server.py            # stdio transport for local development
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

# --------------------------------------------------------------------------------------------
# Make the repository's ``claimsense`` package importable without installing it or touching the
# repo. Override with CLAIMSENSE_SRC=/abs/path/to/ClaimSense-Insurance/src.
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


# --------------------------------------------------------------------------------------------
# Configuration / data location (all overridable via environment variables).
# --------------------------------------------------------------------------------------------
def _repo_root() -> Path:
    env = os.environ.get("CLAIMSENSE_REPO")
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    for cand in (here.parent.parent / "ClaimSense-Insurance", here.parent / "ClaimSense-Insurance"):
        if cand.is_dir():
            return cand
    return here.parent.parent / "ClaimSense-Insurance"


def _default_kb_path() -> Path:
    env = os.environ.get("CLAIMSENSE_KB_PATH")
    if env:
        return Path(env)
    return _repo_root() / "data" / "knowledge_base" / "policy_knowledge_base.jsonl"


def _default_structured_path() -> Path:
    env = os.environ.get("CLAIMSENSE_CLAUSES_PATH")
    if env:
        return Path(env)
    return _repo_root() / "data" / "processed" / "policy_clauses_structured.jsonl"


#: Sentinel meaning "the policy wording's effective date is NOT present in the source data".
#: The ``Clause`` contract requires a ``date``; we refuse to invent a real one. Set the true date
#: once the Domain lead verifies the policy version:  CLAIMSENSE_POLICY_EFFECTIVE_DATE=YYYY-MM-DD.
UNKNOWN_EFFECTIVE_DATE = date(1900, 1, 1)


def _configured_effective_date() -> date:
    raw = os.environ.get("CLAIMSENSE_POLICY_EFFECTIVE_DATE")
    if not raw:
        return UNKNOWN_EFFECTIVE_DATE
    try:
        return date.fromisoformat(raw.strip())
    except ValueError:
        return UNKNOWN_EFFECTIVE_DATE


# Bill-line wording -> policy wording, taken from the real 4.1 / 4.1.1 clause text. Used to bias
# search when the coverage analyst passes a bill-line ``category`` (LineCategory value).
CATEGORY_TERMS: dict[str, list[str]] = {
    "room": ["room", "rent", "boarding", "nursing"],
    "icu": ["intensive", "care", "unit", "icu", "iccu"],
    "nursing": ["nursing", "boarding"],
    "doctor_fees": ["surgeon", "anaesthetist", "medical", "practitioner", "consultant", "specialist", "fees"],
    "ot": ["operation", "theatre", "anaesthesia", "surgical", "oxygen"],
    "medicines": ["medicines", "drugs"],
    "consumables": ["excluded", "items", "consumables", "non-payable"],
    "investigations": ["diagnostics", "diagnostic", "imaging", "laboratory", "investigation"],
    "procedure": ["treatment", "surgery", "hospitalization"],
    "other": [],
}

_STOPWORDS = frozenset(
    "a an the is are of to in on for and or by with up per be as at from this that its it "
    "shall under over into out during each any all not no than whichever lower higher".split()
)
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS]


class ToolError(BaseModel):
    """Structured error returned at the MCP boundary instead of raising to an agent."""

    error: str
    code: str = "policy_kb_error"
    retryable: bool = False


@dataclass(frozen=True)
class PolicyClauseRecord:
    """One policy clause exactly as stored in the knowledge base (no interpretation added)."""

    clause_id: str
    clause_number: str
    title: str
    text: str            # pure clause wording (``source_text`` in the KB)
    retrieval_text: str  # retrieval-oriented text (includes parent context)
    document: str
    page_numbers: tuple[int, ...]
    insurer: str
    product: str
    uin: str | None
    authority_level: str
    verification_status: str
    retrieval_warning: str
    topic: str

    def to_clause(self, effective_date: date) -> Clause:
        """Map the real record onto the shared ``Clause`` contract.

        ``effective_date`` is supplied by configuration; it is NOT present in the source data.
        """
        page = self.page_numbers[0] if self.page_numbers else None
        source_url = f"data/policy/new_india/{self.document}" + (f"#page={page}" if page else "")
        return Clause(
            clause_id=self.clause_id,
            policy_name=self.product or "Arogya Sanjeevani Policy",
            insurer=self.insurer or "The New India Assurance Co. Ltd.",
            section=self.clause_number or self.clause_id.split(":")[-1],
            title=self.title or None,
            text=self.text,
            effective_date=effective_date,
            source_url=source_url,
        )


def _coerce_pages(source: dict) -> tuple[int, ...]:
    pages = source.get("page_numbers")
    if isinstance(pages, list):
        return tuple(int(p) for p in pages if isinstance(p, (int, float)))
    single = source.get("page_number")
    return (int(single),) if isinstance(single, (int, float)) else ()


def _record_from_json(obj: dict) -> PolicyClauseRecord | None:
    """Build a record from one KB/processed JSON line, tolerating both file shapes."""
    clause_id = obj.get("clause_id") or obj.get("record_id") or obj.get("chunk_id")
    if not clause_id:
        return None
    source = obj.get("source", {}) if isinstance(obj.get("source"), dict) else {}
    interp = obj.get("proposed_interpretation", {}) if isinstance(obj.get("proposed_interpretation"), dict) else {}
    source_text = obj.get("source_text", "") or ""
    retrieval_text = obj.get("text", "") or source_text
    return PolicyClauseRecord(
        clause_id=str(clause_id),
        clause_number=str(obj.get("clause_number") or obj.get("displayed_number") or ""),
        title=str(obj.get("title") or ""),
        text=source_text or retrieval_text,
        retrieval_text=retrieval_text,
        document=str(source.get("document") or "policy_wording.pdf"),
        page_numbers=_coerce_pages(source),
        insurer=str(source.get("insurer") or ""),
        product=str(source.get("product") or ""),
        uin=source.get("uin_observed_in_policy_pdf") or source.get("uin"),
        authority_level=str(obj.get("authority_level") or "unspecified"),
        verification_status=str(obj.get("verification_status") or "not_human_verified"),
        retrieval_warning=str(obj.get("retrieval_warning") or ""),
        topic=str(interp.get("topic") or ""),
    )


class PolicyKnowledgeBase:
    """In-memory lexical index over the real policy clauses.

    Deterministic weighted term-frequency scoring (no network, no model). It is hybrid-ready: if
    ``rank_bm25`` from the optional ``[retrieval]`` extra is installed it is used for ranking;
    otherwise a dependency-free fallback is used. A cross-encoder reranker can be layered later.
    """

    def __init__(self, records: list[PolicyClauseRecord], effective_date: date | None = None):
        if not records:
            raise ValueError("policy knowledge base is empty")
        self._records = records
        self._by_id = {r.clause_id: r for r in records}
        self._effective_date = effective_date or _configured_effective_date()
        self._corpus_tokens = [_tokens(f"{r.title} {r.retrieval_text}") for r in records]
        self._bm25 = self._try_build_bm25(self._corpus_tokens)

    @staticmethod
    def _try_build_bm25(corpus_tokens: list[list[str]]):
        try:
            from rank_bm25 import BM25Okapi  # type: ignore
        except ModuleNotFoundError:
            return None
        return BM25Okapi([toks or [""] for toks in corpus_tokens])

    # -- loading ---------------------------------------------------------------------------
    @classmethod
    def from_files(
        cls,
        kb_path: Path | str | None = None,
        structured_path: Path | str | None = None,
        effective_date: date | None = None,
    ) -> "PolicyKnowledgeBase":
        kb = Path(kb_path) if kb_path else _default_kb_path()
        records = cls._load_jsonl(kb) if kb.is_file() else []
        if not records:
            structured = Path(structured_path) if structured_path else _default_structured_path()
            if structured.is_file():
                records = cls._load_jsonl(structured)
        if not records:
            raise FileNotFoundError(
                f"no policy clauses found at {kb} (or structured fallback). "
                "Set CLAIMSENSE_KB_PATH to the policy_knowledge_base.jsonl file."
            )
        return cls(records, effective_date=effective_date)

    @staticmethod
    def _load_jsonl(path: Path) -> list[PolicyClauseRecord]:
        out: list[PolicyClauseRecord] = []
        seen: set[str] = set()
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                rec = _record_from_json(obj)
                # one record per clause_id (the KB may chunk a long clause into parts)
                if rec and rec.clause_id not in seen:
                    seen.add(rec.clause_id)
                    out.append(rec)
        return out

    # -- queries ---------------------------------------------------------------------------
    def __len__(self) -> int:
        return len(self._records)

    @property
    def effective_date(self) -> date:
        return self._effective_date

    def get_clause(self, clause_id: str) -> Clause | None:
        """Return the exact clause, or ``None`` when the id is unknown (never invented)."""
        rec = self._by_id.get((clause_id or "").strip())
        return rec.to_clause(self._effective_date) if rec else None

    def search(self, query: str, category: str | None = None, k: int = 5) -> list[RetrievedPassage]:
        """Lexical clause search. Returns up to ``k`` passages, highest score first.

        ``category`` is a ``LineCategory`` value (e.g. ``"room"``) used only to bias ranking with
        wording taken from the real policy text; it never fabricates results.
        """
        q_tokens = _tokens(query or "")
        if category:
            q_tokens = q_tokens + CATEGORY_TERMS.get(category.strip().lower(), [])
        if not q_tokens:
            return []
        k = max(1, min(int(k or 5), len(self._records)))

        if self._bm25 is not None:
            raw = list(self._bm25.get_scores(q_tokens))
            scored = [(raw[i], i) for i in range(len(self._records))]
        else:
            scored = [(self._score(q_tokens, i), i) for i in range(len(self._records))]

        # keep positive scores; deterministic tie-break on clause number then id
        ranked = sorted(
            (s for s in scored if s[0] > 0),
            key=lambda s: (-s[0], self._records[s[1]].clause_number, self._records[s[1]].clause_id),
        )[:k]
        return [
            RetrievedPassage(
                clause=self._records[i].to_clause(self._effective_date),
                score=round(float(score), 6),
                rank=rank,
            )
            for rank, (score, i) in enumerate(ranked, start=1)
        ]

    def _score(self, q_tokens: list[str], idx: int) -> float:
        rec = self._records[idx]
        doc = self._corpus_tokens[idx]
        if not doc:
            return 0.0
        title_tokens = set(_tokens(rec.title))
        counts: dict[str, int] = {}
        for t in doc:
            counts[t] = counts.get(t, 0) + 1
        score = 0.0
        for qt in set(q_tokens):
            if qt in counts:
                # term frequency, normalised by length, with a title boost
                score += counts[qt] / len(doc)
                if qt in title_tokens:
                    score += 0.5
        # small boost when the query covers several distinct clause terms
        coverage = sum(1 for qt in set(q_tokens) if qt in counts)
        return score + 0.01 * coverage


@lru_cache(maxsize=1)
def _kb() -> PolicyKnowledgeBase:
    """Lazily load the knowledge base once per process."""
    return PolicyKnowledgeBase.from_files()


def load_policy_kb(
    kb_path: Path | str | None = None,
    structured_path: Path | str | None = None,
    effective_date: date | None = None,
) -> PolicyKnowledgeBase:
    """Public loader (used by tests and by ``role4_services``)."""
    return PolicyKnowledgeBase.from_files(kb_path, structured_path, effective_date)


# --------------------------------------------------------------------------------------------
# Services-facing callables (names match ``Services.registry()``). These keep the exact
# semantics of the Role 3 stubs: ``policy_search`` returns a list, ``get_clause`` returns
# ``Clause | None``.
# --------------------------------------------------------------------------------------------
def policy_search(query: str, category: str | None = None, k: int = 5) -> list[RetrievedPassage]:
    """[read] Hybrid/lexical search over the real policy clauses."""
    return _kb().search(query, category=category, k=k)


def get_clause(clause_id: str) -> Clause | None:
    """[read] Fetch one clause by id, or ``None`` if the id is not in the wording."""
    return _kb().get_clause(clause_id)


# --------------------------------------------------------------------------------------------
# MCP tool wrappers: return structured ``ToolError`` instead of raising / returning ``None``.
# --------------------------------------------------------------------------------------------
def _tool_policy_search(query: str, category: str | None = None, k: int = 5):
    """[read] Search policy clauses. Returns passages or a structured error."""
    if not query or not query.strip():
        return ToolError(error="query must be a non-empty string", code="empty_query")
    try:
        results = policy_search(query, category=category, k=k)
    except FileNotFoundError as exc:
        return ToolError(error=str(exc), code="kb_missing", retryable=True)
    if not results:
        return ToolError(error="no matching clause", code="no_match")
    return results


def _tool_get_clause(clause_id: str):
    """[read] Fetch one clause by id. Returns the clause or a structured error."""
    if not clause_id or not clause_id.strip():
        return ToolError(error="clause_id must be a non-empty string", code="empty_clause_id")
    try:
        clause = get_clause(clause_id)
    except FileNotFoundError as exc:
        return ToolError(error=str(exc), code="kb_missing", retryable=True)
    if clause is None:
        return ToolError(error=f"clause {clause_id!r} not found in policy wording", code="unknown_clause")
    return clause


def main() -> None:
    """Start the policy-kb MCP server (stdio). Requires the optional ``[mcp]`` extra."""
    from fastmcp import FastMCP  # lazy: optional dependency

    mcp = FastMCP("policy-kb")
    mcp.tool(name="policy_search")(_tool_policy_search)
    mcp.tool(name="get_clause")(_tool_get_clause)
    mcp.run()


if __name__ == "__main__":
    main()
