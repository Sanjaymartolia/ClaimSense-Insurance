"""Claim history and lesson store (Knowledge & Memory, L9).

Memory reuses the stores teammates already built (ADR-0005); this package owns the interface, the
policy (docs/memory-policy.md) and the tests (tests/memory/).

| Memory                                  | Lives in                                       |
|-----------------------------------------|------------------------------------------------|
| Claim history: fingerprints, sub-limits | ``mcp_servers/claims_db.ClaimsDatabase``        |
| Approved adjudicator lessons            | ``reflexion/playbook.Playbook``                |
| One claim's working state               | the LangGraph checkpointer (``graph/build.py``) |
"""

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from claimsense.agents.services import PastClaim
    from claimsense.contracts import Claim, Worksheet

__all__ = ["HistoryStore"]


@runtime_checkable
class HistoryStore(Protocol):
    """What `Services.claim_history` and `Services.record_history` are bound to.

    Stores pseudonymised ids and fingerprints only, never diagnosis or bill text. A wrong record
    is corrected with `delete_history`, then recorded again (docs/memory-policy.md).
    """

    def claim_history(self, policy_number: str) -> "list[PastClaim]": ...

    def record_history(self, claim: "Claim", worksheet: "Worksheet | None" = None) -> None: ...

    def delete_history(self, claim_id: str) -> None: ...
