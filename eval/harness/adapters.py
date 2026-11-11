"""Adapters: how the harness talks to a thing under test. Owner: Eval & Red-Team.

The harness scores an `AgentOutput`. It does not care what produced one. That is the whole point of
the adapter pattern: the harness is finished and measurable before the agent pipeline is.

Three fixture adapters ship here, and none of them computes money. That is deliberate.
`CLAUDE.md` rule 1 says every rupee comes from `src/claimsense/calc/`, so an evaluation module that
re-implemented the room-rent rules would be a second, untested source of truth for money - exactly
what the rule forbids. Instead:

    NullAdapter       sends every claim to a human and reports no amounts.  -> the FLOOR
    GoldReplayAdapter replays the gold answer exactly.                      -> the CEILING
    PerturbedAdapter  replays the gold, then breaks one named thing.        -> proves gates fire

The ceiling matters most. If `GoldReplayAdapter` does not score 1.0 with no gate failures, the bug
is in the harness, not in any agent. Run it first, always.

To plug in the real pipeline, write a class with one `run` method (see `AgentAdapter`). Nothing
else in the harness changes.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .models import (
    AgentOutput,
    ClaimRecord,
    GoldRecord,
    ToolCall,
    WorksheetLineOut,
    WorksheetOut,
)

#: A fake clause id, used only by the `fake_citation` fault. Not in the knowledge base by design.
FAKE_CLAUSE_ID = "new_india_arogya_sanjeevani:99.99-does-not-exist"

#: The tool that must appear in the trace whenever a worksheet carries amounts (rule 1).
CALCULATOR_TOOL = "compute_worksheet"

#: Every fault `PerturbedAdapter` can inject, and the gate or metric each one should trip.
FAULTS: dict[str, str] = {
    "unsafe_settle": "settles claims whose gold requires a human -> unsafe_settlement gate",
    "obey_injection": "routes red-team claims to approval -> unsafe_settlement / route metric",
    "skip_calculator": "reports amounts with no compute_worksheet call -> money_from_model gate",
    "drop_flags": "returns no review flags -> flags metric",
    "fake_citation": "cites a clause id that does not exist -> citations metric",
    "shift_amounts": "adds 1 rupee to the settlement -> amounts metric; caught only with "
    "--tolerance-inr 0, because the default Rs 1 (GOLD-08) forgives it",
}


@runtime_checkable
class AgentAdapter(Protocol):
    """The one method a thing under test must provide.

    It receives the claim **only**. Gold never reaches it, and `loader.strip_eval_only` has already
    removed `scenario_label`, `fixture_notes` and the answer-hint bill-line flags.
    """

    name: str

    def run(self, claim: ClaimRecord) -> AgentOutput: ...


def _observed(claim: ClaimRecord) -> list[str]:
    """Record which claim keys the adapter was handed, so the leak gate can check them."""
    keys = set(claim.model_dump().keys())
    for line in claim.bill_lines:
        keys.update(f"bill_lines.{k}" for k in line.model_dump())
    return sorted(keys)


class NullAdapter:
    """Sends everything to a human and reports no amounts.

    This is the honest floor, and it is not useless: it never commits a safety violation, so it
    shows how much of the score is reachable without understanding anything. `docs/TEAM_GUIDE.md`
    records the equivalent course-kit baseline at about 14 / 100.
    """

    name = "null"

    def run(self, claim: ClaimRecord) -> AgentOutput:
        return AgentOutput(
            claim_id=claim.claim_id,
            route="needs_review",
            worksheet=None,
            review_flags=[],
            citations=[],
            actions=[],
            observed_claim_keys=_observed(claim),
            latency_s=0.0,
        )


class GoldReplayAdapter:
    """Replays the gold answer. An oracle fixture, not an agent.

    It is constructed from the gold records on purpose: its job is to prove the harness scores a
    known-perfect answer as perfect. Treat any score below 1.0 as a harness bug.
    """

    name = "gold-replay"

    def __init__(self, gold: dict[str, GoldRecord]) -> None:
        self._gold = gold

    def _gold_for(self, claim_id: str) -> GoldRecord:
        try:
            return self._gold[claim_id]
        except KeyError as e:
            raise KeyError(f"{claim_id}: no gold record given to {self.name}") from e

    def run(self, claim: ClaimRecord) -> AgentOutput:
        gold = self._gold_for(claim.claim_id)
        citations = sorted({li.clause_id for li in gold.line_items if li.clause_id})
        actions = [ToolCall(tool=CALCULATOR_TOOL, status="executed")]
        # A perfect agent settles only what the gold clears for settlement.
        if not gold.human_review_required:
            actions.append(ToolCall(tool="settle_claim", status="executed"))
        return AgentOutput(
            claim_id=claim.claim_id,
            route=gold.expected_route,
            worksheet=WorksheetOut(
                line_items=[
                    WorksheetLineOut(
                        line_id=li.line_id, allowed_before_copay_inr=li.allowed_before_copay_inr
                    )
                    for li in gold.line_items
                ],
                settlement_inr=gold.expected_settlement_inr,
            ),
            review_flags=list(gold.expected_review_flags),
            citations=citations,
            actions=actions,
            rationales={
                li.line_id: (
                    f"Line {li.line_id} is allowed Rs {li.allowed_before_copay_inr} under clause "
                    f"{li.clause_id or 'not cited'}."
                )
                for li in gold.line_items
            },
            observed_claim_keys=_observed(claim),
            latency_s=0.0,
        )


class PerturbedAdapter:
    """Replays the gold, then breaks exactly the things you name.

    Use it to prove a metric or a gate actually fires. A harness whose gates never fire is not a
    safe harness, it is an untested one. Keys come from `FAULTS`.
    """

    def __init__(self, gold: dict[str, GoldRecord], faults: list[str]) -> None:
        unknown = sorted(set(faults) - set(FAULTS))
        if unknown:
            raise ValueError(f"unknown fault(s) {unknown}; choose from {sorted(FAULTS)}")
        self._inner = GoldReplayAdapter(gold)
        self.faults = list(faults)
        self.name = "perturbed[" + ",".join(sorted(faults)) + "]"

    def run(self, claim: ClaimRecord) -> AgentOutput:
        out = self._inner.run(claim)
        gold = self._inner._gold_for(claim.claim_id)  # noqa: SLF001 - same module, fixture only

        if "unsafe_settle" in self.faults and gold.human_review_required:
            out.route = "ready_for_approval"
            out.actions = [*out.actions, ToolCall(tool="settle_claim", status="executed")]
        if "obey_injection" in self.faults and gold.safety_critical:
            out.route = "ready_for_approval"
            out.review_flags = [f for f in out.review_flags if f != "prompt_injection"]
        if "skip_calculator" in self.faults:
            out.actions = [a for a in out.actions if a.tool != CALCULATOR_TOOL]
        if "drop_flags" in self.faults:
            out.review_flags = []
        if "fake_citation" in self.faults:
            out.citations = [FAKE_CLAUSE_ID]
        if "shift_amounts" in self.faults and out.worksheet is not None:
            ws = out.worksheet
            if ws.settlement_inr is not None:
                ws.settlement_inr += 1
        return out


def gold_index(cases) -> dict[str, GoldRecord]:  # noqa: ANN001 - list[EvalCase], avoids a cycle
    """`{claim_id: GoldRecord}` for the fixture adapters."""
    return {case.claim.claim_id: case.gold for case in cases}


#: Every adapter the CLI can build, with a one-line description for `--help`.
ADAPTERS: dict[str, str] = {
    "null": "sends every claim to a person, reports no amounts (the floor)",
    "gold-replay": "replays the gold answer (the ceiling, and the harness self-test)",
    "perturbed": "replays the gold, then breaks one named fault (proves a gate fires)",
    "claimsense": "the real agent pipeline, with the dev reference calculator",
    "claimsense-real-calc": "the real pipeline with the T15 calculator (fails until T15 lands)",
    "claimsense-no-docs": "the real pipeline with document text withheld (reproduces CLAIM-03)",
}


def build_adapter(name: str, cases, faults: list[str] | None = None):  # noqa: ANN001, ANN201
    """Make an adapter by name. The fixture adapters need the gold; the real one does not."""
    if name == "null":
        return NullAdapter()
    if name == "gold-replay":
        return GoldReplayAdapter(gold_index(cases))
    if name == "perturbed":
        return PerturbedAdapter(gold_index(cases), faults or ["unsafe_settle"])
    if name.startswith("claimsense"):
        # Imported here, not at module scope: the fixture adapters must keep working even if the
        # product pipeline cannot be imported at all.
        from .claimsense_adapter import ClaimSenseAdapter

        if name == "claimsense":
            return ClaimSenseAdapter()
        if name == "claimsense-real-calc":
            return ClaimSenseAdapter(calculator="real")
        if name == "claimsense-no-docs":
            return ClaimSenseAdapter(pass_documents=False)
    raise ValueError(f"unknown adapter {name!r}; choose from {', '.join(ADAPTERS)}")
