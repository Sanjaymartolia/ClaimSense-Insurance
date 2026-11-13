"""Who may review claims through the API (L14).

Reviewers come from the environment, never from a request body:

    CLAIMSENSE_REVIEWERS="<token>=<approver_id>:<adjudicator|senior>,<token>=..."

A request sends ``Authorization: Bearer <token>``. The approver id and level the review gate signs
with come from the token, so a client cannot approve as someone else or above its level. Tokens
are compared in constant time and never logged. This is demo-grade identity for the capstone; a
deployment would swap :class:`ApiIdentityProvider` for single sign-on.
"""

from __future__ import annotations

import hmac
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from claimsense.contracts import ApprovalLevel
from claimsense.mcp_servers.approvals import AuthenticatedApprover


@dataclass(frozen=True)
class Reviewer:
    approver_id: str
    level: ApprovalLevel


def parse_reviewers(spec: str) -> dict[str, Reviewer]:
    """``"<token>=<approver_id>:<level>,..."`` -> ``{token: Reviewer}``.

    A malformed entry raises ``ValueError`` naming its position, never its token."""
    reviewers: dict[str, Reviewer] = {}
    entries = [entry.strip() for entry in spec.split(",") if entry.strip()]
    for n, entry in enumerate(entries, 1):
        token, has_eq, who = entry.partition("=")
        approver_id, has_colon, level = who.partition(":")
        if not (has_eq and has_colon and token.strip() and approver_id.strip()):
            raise ValueError(f"CLAIMSENSE_REVIEWERS entry {n} is not <token>=<approver_id>:<level>")
        try:
            reviewers[token.strip()] = Reviewer(approver_id.strip(), ApprovalLevel(level.strip()))
        except ValueError:
            raise ValueError(
                f"CLAIMSENSE_REVIEWERS entry {n}: level must be adjudicator or senior"
            ) from None
    return reviewers


def find_reviewer(reviewers: Mapping[str, Reviewer], presented: str) -> Reviewer | None:
    """The reviewer holding ``presented``, compared against every token in constant time."""
    found = None
    for known, reviewer in reviewers.items():
        if hmac.compare_digest(known.encode(), presented.encode()):
            found = reviewer
    return found


class ApiIdentityProvider:
    """The review gate's identity: the reviewer who sent this request (`approvals.ReviewGate`)."""

    def __init__(self, reviewer: Reviewer) -> None:
        self.reviewer = reviewer

    def authenticate(self, claim_id: str, level: ApprovalLevel) -> AuthenticatedApprover:
        if level != self.reviewer.level:
            raise PermissionError(f"a {level.value} decision needs a {level.value} reviewer")
        return AuthenticatedApprover(
            approver_id=self.reviewer.approver_id,
            level=level,
            auth_source="api-token",
            authenticated_at=datetime.now(UTC),
        )
