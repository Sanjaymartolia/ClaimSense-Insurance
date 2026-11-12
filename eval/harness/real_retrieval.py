"""Run the eval with the real retriever instead of the stub clause table.

Every eval tool builds its tools with `make_stub_services()`, whose `policy_search` ignores the
query and returns a fixed clause list per bill-line category. That keeps the default runs fast,
free and deterministic, but it means no eval run ever measured the hybrid retriever (BM25 + dense
+ RRF + cross-encoder) the product ships. `use_real_retrieval` swaps in policy-kb's two callables
(`mcp_servers/policy_kb.py`, the same ones `real_services()` binds) and leaves every other tool a
stub, so a run differs from the default in retrieval only.

Needs `pip install -e ".[retrieval]"` and an index (`python -m claimsense.retrieval.index`). The
first open takes ~30 s (torch and the reranker); later claims reuse it. No API key is needed.
"""

from __future__ import annotations

from typing import Any


class RetrievalUnavailableError(RuntimeError):
    """The real retriever cannot open: say how to fix it, before any claim runs."""


def open_real_retrieval() -> None:
    """Open the shared retriever once and check the two tools are the reviewed ones (L15 pins)."""
    try:
        from claimsense.hooks.pins import ToolPinError, check_pins
        from claimsense.mcp_servers import policy_kb
    except ImportError as e:
        raise RetrievalUnavailableError(
            f'cannot import policy-kb ({e}). Run: pip install -e ".[dev]"'
        ) from e
    try:
        policy_kb.warm_up()
    except ImportError as e:
        raise RetrievalUnavailableError(
            f'retrieval packages missing ({e}). Run: pip install -e ".[retrieval]"'
        ) from e
    except Exception as e:  # noqa: BLE001 - say what failed; StaleIndexError names its own fix
        hint = (
            " Build the index: python -m claimsense.retrieval.index"
            if isinstance(e, FileNotFoundError)
            else ""
        )
        raise RetrievalUnavailableError(f"{type(e).__name__}: {e}{hint}") from e
    try:
        check_pins({"policy_search": policy_kb.policy_search, "get_clause": policy_kb.get_clause})
    except ToolPinError as e:
        raise RetrievalUnavailableError(
            f"{e} Review the change, then: python -m claimsense.hooks.pins --update"
        ) from e


def use_real_retrieval(services: Any) -> None:
    """`prepare=` hook: point this claim's `Services` at the real policy-kb search."""
    from claimsense.mcp_servers import policy_kb

    open_real_retrieval()
    services.policy_search = policy_kb.policy_search
    services.get_clause = policy_kb.get_clause
