"""Graph nodes and routers. Each node: state -> partial update (L8). The supervisor is this code.

Pipeline (brief, step 2):
  plan → extract → admissibility ─┬─ coverage → fraud → critic ─┬─ human_review ─┬─ settle → memory
                                  │                ▲  (fail, r<1)│                │  (senior needed)
                                  │                └── revise ◄──┤                ├─ senior_review → settle
                                  │                              └ escalate → human_review
                                  └─ (not admissible) → human_review → repudiate → memory
  human/senior "edit" → apply_edits → critic → human_review   (old approvals are void)
"""  # noqa: E501 - an ASCII diagram: its alignment is content

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Any

from claimsense.agents import Team
from claimsense.contracts import AgentName, ApprovalDecision, ApprovalLevel, Handoff

from . import planner
from .state import ClaimState, Status


def _default_interrupt(payload: dict) -> Any:
    from langgraph.types import interrupt  # lazy: unit tests inject their own

    return interrupt(payload)


def registered_policy(s: ClaimState) -> str | None:
    """The policy number the intake system filed this claim under (`packet["policy_number"]`,
    set from the login and the policy record, never from document text). None if absent."""
    value = (s.get("packet") or {}).get("policy_number")
    return str(value) if value else None


def _handoff(state: ClaimState, to: AgentName, step: str, summary: str, refs: list[str]) -> Handoff:
    return Handoff(
        sender=AgentName.SUPERVISOR,
        recipient=to,
        claim_id=state["claim_id"],
        step=step,
        summary=summary,
        artifact_refs=refs,
    )


class Nodes:
    def __init__(
        self,
        team: Team,
        interrupt_fn: Callable[[dict], Any] | None = None,
        *,
        identity_provider: Any = None,
        approval_store: Any = None,
        tool_hooks: bool = False,
        hook_options: dict[str, Any] | None = None,
    ):
        """identity_provider / approval_store go to approvals.ReviewGate. With no store the gate
        signs into approvals.default_store() (in-memory, fine for stubs). With real_services() the
        store must be claims_db.get_db().approval_store: use build.production_review_kwargs().

        tool_hooks=True installs hooks.install_hooks on the team once per claim, with a fresh
        BudgetState. hook_options: BudgetState fields (per_claim, per_agent, per_tool,
        max_repeats) plus an optional "audit" AuditLog. Hooks are (re)installed by the first node
        that runs for a claim id, so they survive LangGraph pauses; after a process restart the
        resumed claim gets a fresh budget. One claim per Team at a time (hooks.install_hooks)."""
        # lazy: approvals imports graph.state, so a module-level import would be circular
        from claimsense.mcp_servers.approvals import ReviewGate

        self.team = team
        self.interrupt = interrupt_fn or _default_interrupt
        self.gate = ReviewGate(
            self.interrupt, identity_provider, store=approval_store, render_plan=planner.render
        )
        self.tool_hooks = tool_hooks
        self.hook_options = dict(hook_options or {})
        self.hook_guard: Any = None  # hooks.HookGuard for the claim currently hooked
        self._hooked_claim: str | None = None

    # ------------------------------------------------------------------ tool hooks
    def ensure_hooks(self, claim_id: str) -> None:
        """Install hooks with a fresh budget the first time a node runs for `claim_id`."""
        if not self.tool_hooks or self._hooked_claim == claim_id:
            return
        from claimsense.hooks.hooks import BudgetState, install_hooks  # lazy: off in unit tests

        self.restore_hooks()
        opts = dict(self.hook_options)
        audit = opts.pop("audit", None)
        self.hook_guard = install_hooks(
            self.team, budget=BudgetState(**opts), audit=audit, claim_id=claim_id
        )
        self._hooked_claim = claim_id

    def restore_hooks(self) -> None:
        """Put the team's plain belts back (end of a local run, or before the next claim)."""
        if self.hook_guard is not None:
            self.hook_guard.restore()
        self.hook_guard, self._hooked_claim = None, None

    def _hooked(self, fn: Callable[[ClaimState], dict]) -> Callable[[ClaimState], dict]:
        def run(s: ClaimState) -> dict:
            self.ensure_hooks(s["claim_id"])
            registered = registered_policy(s)
            if self.hook_guard is not None and registered:
                # L15 least privilege: every tool may touch only the policy the intake system
                # registered for this claim. Never the policy number the model read from the
                # documents: injected text could set that one, and the check would then pass.
                self.hook_guard.scope_to(policy_number=registered)
            return fn(s)

        run.__name__ = fn.__name__
        return run

    # ------------------------------------------------------------------ nodes
    def plan(self, s: ClaimState) -> dict:
        p = planner.make_plan(s["claim_id"])
        return {"plan": p, "trace": [planner.render(p)]}

    def extract(self, s: ClaimState) -> dict:
        claim, issues = self.team.extraction.run(s["packet"])
        registered = registered_policy(s)
        if registered and claim.policy_number != registered:
            # The documents name another policy than the one the claim was filed under: a
            # person decides (and with hooks on, no tool may read that other policy).
            issues = [*issues, "policy number in the documents differs from the registered policy"]
        return {
            "claim": claim,
            "extraction_issues": issues,
            "plan": planner.mark(s["plan"], "extract", "done"),
            "handoffs": [
                _handoff(
                    s,
                    AgentName.EXTRACTION,
                    "extract",
                    "Extract typed fields and every bill line with spans.",
                    ["packet"],
                )
            ],
            "trace": [f"extract: {len(claim.bill_lines)} lines, {len(issues)} issues"],
        }

    def admissibility(self, s: ClaimState) -> dict:
        adm = self.team.coverage.check_admissibility(s["claim"])
        plan = planner.mark(s["plan"], "admissibility", "done" if adm.admissible else "failed")
        plan = planner.monitor_after_admissibility(plan, adm.admissible)
        # B4: a not-admissible claim goes straight to review and skips the fraud node, which is
        # where extraction issues normally become flags (fraud.py step 5). Carry them here, in the
        # same "extraction: ..." form, so the reviewer still sees an injection or a bad span.
        carried = (
            {"fraud_flags": [f"extraction: {i}" for i in s.get("extraction_issues") or []]}
            if not adm.admissible
            else {}
        )
        # ADR-0010 (AGT-02): a not-admissible claim still gets its worksheet from the calculator,
        # every line deducted under the gate's clause, so the Rs 0 comes from code (rule 1). It is
        # not stored as clause_choices: an adjudicator override must run real clause selection.
        # The repudiation review never shows it (Nodes._review hides it).
        if not adm.admissible and adm.clause_ids:
            gate = adm.clause_ids[0]
            ws = self.team.coverage.adjudicate(
                s["claim"],
                {line.line_id: gate for line in s["claim"].bill_lines},
                fraud_flags=carried["fraud_flags"],
            )
            carried["worksheet"] = ws
        return {
            **carried,
            "admissibility": adm,
            "plan": plan,
            "handoffs": [
                _handoff(
                    s,
                    AgentName.COVERAGE,
                    "admissibility",
                    "Policy active, waiting periods served, no exclusion?",
                    ["claim"],
                )
            ],
            "trace": [
                f"admissibility: {'ok' if adm.admissible else 'NOT admissible'} {adm.clause_ids}",
                planner.render(plan),
            ],
        }

    def coverage(self, s: ClaimState) -> dict:
        revising = s.get("revisions", 0) > 0 and s.get("critic_report") is not None
        feedback = s["critic_report"].feedback() if revising else None
        choices, lesson_ids, notes = self.team.coverage.choose_clauses(
            s["claim"],
            critic_feedback=feedback,
            locked=s.get("locked_choices"),
            previous=s.get("clause_choices"),
        )
        prev = s.get("worksheet")
        ws = self.team.coverage.adjudicate(
            s["claim"],
            choices,
            version=(prev.version + 1) if prev else 1,
            fraud_flags=s.get("fraud_flags", []),
        )
        return {
            "clause_choices": choices,
            "lessons_used": lesson_ids,
            "coverage_notes": notes,
            "worksheet": ws,
            "approvals": [],
            "plan": planner.mark(s["plan"], "adjudicate_lines", "done"),
            "handoffs": [
                _handoff(
                    s,
                    AgentName.COVERAGE,
                    "adjudicate_lines",
                    "Pick a clause per line; calculator computes rupees."
                    + (" Fix the critic's issues." if revising else ""),
                    ["claim", "critic_report"] if revising else ["claim"],
                )
            ],
            "trace": [
                f"coverage{' (revision)' if revising else ''}: worksheet v{ws.version} "
                f"payable Rs {ws.total_payable}; lessons {lesson_ids}"
            ],
        }

    def fraud(self, s: ClaimState) -> dict:
        flags = self.team.fraud.run(s["claim"], s.get("extraction_issues"))
        # Worksheet is immutable once hashed; rebuild it through the calculator with the flags.
        ws = self.team.coverage.adjudicate(
            s["claim"], s["clause_choices"], version=s["worksheet"].version, fraud_flags=flags
        )
        return {
            "fraud_flags": flags,
            "worksheet": ws,
            "plan": planner.mark(s["plan"], "fraud_screen", "done"),
            "handoffs": [
                _handoff(
                    s,
                    AgentName.FRAUD,
                    "fraud_screen",
                    "Duplicates, used sub-limits, tariff outliers, dates.",
                    ["claim"],
                )
            ],
            "trace": [f"fraud: {len(flags)} flag(s)"],
        }

    def critic(self, s: ClaimState) -> dict:
        rep = self.team.critic.review(s["claim"], s["clause_choices"], s["worksheet"])
        return {
            "critic_report": rep,
            "critic_history": [rep],
            "plan": planner.mark(s["plan"], "review", "done" if rep.passed else "failed"),
            "handoffs": [
                _handoff(
                    s,
                    AgentName.CRITIC,
                    "review",
                    "Rerun calculator; check each deduction's clause.",
                    ["worksheet", "clause_choices"],
                )
            ],
            "trace": [f"critic: {'pass' if rep.passed else 'FAIL ' + str(len(rep.issues))}"],
        }

    def revise(self, s: ClaimState) -> dict:
        return {
            "revisions": s.get("revisions", 0) + 1,
            "trace": [
                f"critic → coverage, revision {s.get('revisions', 0) + 1}/{s['max_revisions']}"
            ],
        }

    def escalate(self, s: ClaimState) -> dict:
        why = "critic still fails after the allowed revision: " + "; ".join(
            s["critic_report"].feedback()
        )
        return {"escalation": why, "trace": ["escalate: revision limit reached"]}

    def _review(self, s: ClaimState, level: ApprovalLevel) -> dict:
        """The gate builds the payload, pauses (⏸ interrupt), and on APPROVE issues a signed token
        into its store: a settlement approval bound to the worksheet, or, for a not-admissible
        claim, a repudiation approval bound to the admissibility hash. Plan and trace are ours."""
        ws, adm = s.get("worksheet"), s["admissibility"]
        # The gate picks the token type from the worksheet; a repudiation must never get a
        # settlement token, so hide any stale worksheet when the claim is not admissible.
        upd = self.gate.review(s if adm.admissible else {**s, "worksheet": None}, level)
        d = upd["review_decision"]
        if d == ApprovalDecision.APPROVE:
            v = ws.version if ws and adm.admissible else "-"
            return {
                **upd,
                "plan": planner.mark(s["plan"], "approve", "done"),
                "trace": [f"{level.value} approved v{v}"],
            }
        if d == ApprovalDecision.EDIT:
            n = len(upd["pending_edits"])
            return {**upd, "trace": [f"{level.value} edited {n} line(s)"]}
        return {**upd, "trace": [f"{level.value} rejected"]}

    def human_review(self, s: ClaimState) -> dict:
        return self._review(s, ApprovalLevel.ADJUDICATOR)

    def senior_review(self, s: ClaimState) -> dict:
        return self._review(s, ApprovalLevel.SENIOR)

    def apply_edits(self, s: ClaimState) -> dict:
        """Re-entry point: an edit changes the worksheet, so every earlier approval is void."""
        adm = s["admissibility"]
        if not adm.admissible:  # adjudicator overrides the inadmissibility finding
            adm = adm.model_copy(
                update={"admissible": True, "reasons": adm.reasons + ["overridden by adjudicator"]}
            )
        claim, locked = s["claim"], dict(s.get("locked_choices") or {})
        lines = []
        for line in claim.bill_lines:
            e = next((e for e in s.get("pending_edits", []) if e.line_id == line.line_id), None)
            if e and e.amount is not None:
                line = line.model_copy(update={"amount": Decimal(e.amount)})
            if e and e.clause_id:
                locked[line.line_id] = e.clause_id
            lines.append(line)
        delta = sum((b.amount for b in lines), Decimal(0)) - claim.lines_total()
        claim = claim.model_copy(
            update={"bill_lines": lines, "bill_total": claim.bill_total + delta}
        )
        choices = {**(s.get("clause_choices") or {}), **locked}
        if not s.get("clause_choices"):  # came from the repudiation path: run coverage first
            choices, _, _ = self.team.coverage.choose_clauses(claim, locked=locked)
        prev = s.get("worksheet")
        # B7: re-run the fraud screen on the edited claim. An override of a not-admissible ruling
        # never passed the fraud node, and an edited amount can create a new finding (e.g. a
        # tariff outlier); stale or missing flags would let one approval settle it.
        flags = self.team.fraud.run(claim, s.get("extraction_issues"))
        ws = self.team.coverage.adjudicate(
            claim,
            choices,
            version=(prev.version + 1) if prev else 1,
            fraud_flags=flags,
        )
        return {
            "fraud_flags": flags,
            "claim": claim,
            "admissibility": adm,
            "locked_choices": locked,
            "clause_choices": choices,
            "worksheet": ws,
            "approvals": [],
            "pending_edits": [],
            "human_edited": True,
            "trace": [
                f"edit → worksheet v{ws.version}, payable Rs {ws.total_payable}; "
                f"earlier approvals void"
            ],
        }

    def _guard_blocked(self, s: ClaimState, step: str, error: Exception) -> dict:
        """L15: the payment or letter guard refused (fail-closed). Nothing was paid or sent; the
        claim is escalated to a person with the reason, and the approvals are void."""
        return {
            "status": Status.ESCALATED,
            "escalation": f"{step} blocked by a guardrail: {error}",
            "approvals": [],
            "trace": [f"{step} blocked: {error}"],
        }

    def settle(self, s: ClaimState) -> dict:
        from claimsense.agents.settlement import OutputGuardError

        try:
            receipt, letter = self.team.settlement.settle(
                s["claim"],
                s["worksheet"],
                s.get("approvals", []),
                needs_senior=needs_senior(s, self.team),
            )
        except OutputGuardError as e:
            return self._guard_blocked(s, "settle", e)
        return {
            "settlement": receipt,
            "letter": letter,
            "status": Status.SETTLED,
            "plan": planner.mark(s["plan"], "settle", "done"),
            "handoffs": [
                _handoff(
                    s,
                    AgentName.SETTLEMENT,
                    "settle",
                    "Settle with the approval token; letter with a reason per deduction.",
                    ["worksheet", "approvals"],
                )
            ],
            "trace": [f"settled Rs {s['worksheet'].total_payable}"],
        }

    def repudiate(self, s: ClaimState) -> dict:
        from claimsense.agents.settlement import OutputGuardError

        adm = s["admissibility"]
        try:
            receipt, letter = self.team.settlement.repudiate(
                s["claim"], adm.reasons, adm.clause_ids, s.get("approvals", [])
            )
        except OutputGuardError as e:
            return self._guard_blocked(s, "repudiate", e)
        return {
            "settlement": receipt,
            "letter": letter,
            "status": Status.REPUDIATED,
            "plan": planner.mark(s["plan"], "repudiate", "done"),
            "trace": ["repudiated"],
        }

    def memory_update(self, s: ClaimState) -> dict:
        # Claim history (used sub-limits, bills seen). Edits stay in edit_log for Reflexion; they
        # become lessons only after review (reflexion/), never automatically.
        if s.get("status") not in (Status.SETTLED, Status.REPUDIATED):
            # A guard blocked the settlement: nothing was paid, so no sub-limit was used.
            return {"trace": ["memory: not updated (settlement blocked)"]}
        self.team.services.record_history(s["claim"], s.get("worksheet"))
        return {
            "plan": planner.mark(s["plan"], "update_memory", "done"),
            "trace": ["memory: claim history updated"],
        }

    def table(self) -> dict[str, Callable]:
        if not self.tool_hooks:
            return {n: getattr(self, n) for n in NODE_NAMES}
        return {n: self._hooked(getattr(self, n)) for n in NODE_NAMES}


NODE_NAMES = [
    "plan",
    "extract",
    "admissibility",
    "coverage",
    "fraud",
    "critic",
    "revise",
    "escalate",
    "human_review",
    "senior_review",
    "apply_edits",
    "settle",
    "repudiate",
    "memory_update",
]


# ---------------------------------------------------------------------- routers
def needs_senior(s: ClaimState, team: Team) -> bool:
    """One rule with claims_db/approvals: payable > threshold, or any fraud flag."""
    from claimsense.mcp_servers.approvals import needs_senior_review

    if not s["admissibility"].admissible:
        return False
    return needs_senior_review(
        s.get("worksheet"), s.get("fraud_flags"), threshold=team.services.senior_threshold
    )


def after_admissibility(s: ClaimState) -> str:
    return "coverage" if s["admissibility"].admissible else "human_review"


def after_critic(s: ClaimState) -> str:
    if s["critic_report"].passed:
        return "human_review"
    if s.get("human_edited"):
        return "human_review"  # never let an agent overrule a human edit; show the issues instead
    if s.get("revisions", 0) < s["max_revisions"]:
        return "revise"
    return "escalate"


def make_after_review(team: Team) -> Callable[[ClaimState], str]:
    def route(s: ClaimState) -> str:
        d = s.get("review_decision")
        if d == ApprovalDecision.EDIT:
            return "apply_edits"
        if d == ApprovalDecision.REJECT:
            return "end"
        if not s["admissibility"].admissible:
            return "repudiate"
        has_senior = any(
            a.level == ApprovalLevel.SENIOR and a.is_valid_for(s["worksheet"])
            for a in s.get("approvals", [])
        )
        if needs_senior(s, team) and not has_senior:
            return "senior_review"
        return "settle"

    return route
