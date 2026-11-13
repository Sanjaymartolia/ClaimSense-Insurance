"""Run one claim through the real nodes and routers, with hooks on and every tool call recorded."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from claimsense.agents import PolicyInfo, Team, make_stub_services
from claimsense.agents.services import real_calculate
from claimsense.contracts import ApprovalDecision, ApprovalLevel, ApprovalToken
from claimsense.graph.local import LocalRunner
from claimsense.hooks.hooks import AuditLog
from claimsense.mcp_servers.approvals import DemoIdentityProvider, InMemoryApprovalStore

from .recorder import Recorder

MODES = ("approve", "reject", "edit", "senior_reject")


class Reviewer:
    """A scripted adjudicator. It sees only the review payload, never gold."""

    def __init__(self, mode: str, recorder: Recorder):
        if mode not in MODES:
            raise ValueError(f"unknown reviewer mode {mode!r}")
        self.mode = mode
        self.recorder = recorder
        self.reviews: list[dict[str, Any]] = []
        self.edited = False

    def _edit_first_line(self, payload: dict) -> dict:
        self.edited = True
        line = payload["worksheet"]["lines"][0]
        return {
            "decision": ApprovalDecision.EDIT,
            "approver_id": "eval-reviewer",
            "edits": [
                {
                    "line_id": line["line_id"],
                    "amount": str(Decimal(line["claimed"]) - 1),
                    "reason": "evaluation edit",
                }
            ],
        }

    def __call__(self, payload: dict) -> dict:
        reply = {"decision": ApprovalDecision.APPROVE, "approver_id": "eval-reviewer"}
        if self.mode == "reject":
            reply["decision"] = ApprovalDecision.REJECT
        elif self.mode == "senior_reject" and payload["level"] == ApprovalLevel.SENIOR.value:
            reply["decision"] = ApprovalDecision.REJECT
        elif self.mode == "edit" and not self.edited and payload["kind"] == "worksheet":
            reply = self._edit_first_line(payload)
        self.reviews.append(
            {
                "at_event": len(self.recorder.events),
                "level": payload["level"],
                "kind": payload["kind"],
                "hash": payload["worksheet_hash"],
                "decision": ApprovalDecision(reply["decision"]).value,
            }
        )
        return reply


@dataclass
class Run:
    claim_id: str
    scenario: str
    n_lines: int
    has_procedure: bool
    events: list[dict[str, Any]]
    reviews: list[dict[str, Any]]
    state: dict[str, Any]
    audit: list[Any]
    error: str | None = None
    stale_token_refused: bool | None = None
    tags: dict[str, Any] = field(default_factory=dict)


def _stale_refused(settle: Callable[..., Any], run: Run) -> bool | None:
    """Present an approval for the pre-edit hash against the final worksheet."""
    worksheet = run.state.get("worksheet")
    edits = [r for r in run.reviews if r["decision"] == "edit"]
    if not edits or worksheet is None:
        return None
    token = ApprovalToken(
        claim_id=run.claim_id,
        worksheet_hash=edits[0]["hash"],
        level=ApprovalLevel.ADJUDICATOR,
        approver_id="eval-reviewer",
        decided_at=datetime.now(UTC),
    )
    try:
        settle(claim_id=run.claim_id, worksheet=worksheet, approvals=[token], needs_senior=False)
    except PermissionError:
        return True
    return False


def run_packet(
    packet: dict,
    policy: PolicyInfo,
    mode: str = "approve",
    scenario: str | None = None,
    fail_on: str | None = None,
    hook_options: dict | None = None,
    configure: Callable[[Team], None] | None = None,
) -> Run:
    services = make_stub_services(policies={policy.policy_number: policy})
    services.calculate = real_calculate
    recorder = Recorder(fail_on=fail_on)
    recorder.install(services)
    team = Team(services)
    if configure is not None:
        configure(team)

    audit = AuditLog()
    reviewer = Reviewer(mode, recorder)
    runner = LocalRunner(
        team,
        identity_provider=DemoIdentityProvider(),
        approval_store=InMemoryApprovalStore(),
        tool_hooks=True,
        hook_options={**(hook_options or {}), "audit": audit},
    )
    error, state = None, {}
    try:
        state = dict(runner.run(packet, reviewer))
    except Exception as exc:  # noqa: BLE001 - a crash is a recorded outcome of the case
        error = type(exc).__name__

    claim = packet["claim"]
    run = Run(
        claim_id=packet["claim_id"],
        scenario=scenario or mode,
        n_lines=len(claim["bill_lines"]),
        has_procedure=bool(claim.get("procedure")),
        events=recorder.events,
        reviews=reviewer.reviews,
        state=state,
        audit=audit.records,
        error=error,
    )
    run.stale_token_refused = _stale_refused(services.settle_claim.original, run)
    return run
