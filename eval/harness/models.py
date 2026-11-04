"""Typed records the harness passes around. Owner: Eval & Red-Team.

Why these types and not `src/claimsense/contracts/`:
ADR-0002 records that the starter-pack claim JSON does not validate against `contracts.claim.Claim`
(21 errors on CLM-0004). `src/claimsense/reflexion/cases.py` owns the one adapter that bridges the
two, and it currently raises on CLM-0018 because the GOLD-01 relabel added a reason code its table
does not know. A harness that imported either would not run today.

So the harness reads the fixtures with its own models and stays decoupled. The cost is a second
mapping; the benefit is that evaluation never breaks because a product contract moved. When
ADR-0002 closes, `AgentOutput` is the only type an adapter has to produce, so one adapter change
switches the harness onto contract types.

Money: the fixtures store whole rupees as integers (`*_inr`). The harness compares integers and
never does money arithmetic of its own, so `Decimal` is not needed here. GOLD-08 (gold is whole
rupees, the calculator keeps paise) is handled by the scorer's tolerance option, not by a type.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Route = Literal["ready_for_approval", "needs_review"]
ToolStatus = Literal["executed", "blocked", "failed"]
Severity = Literal["catastrophic", "high", "medium", "warn"]

#: Fields that exist only for evaluation. An agent that sees these has seen the answer.
#: `CLAUDE.md` and `eval/README.md` both forbid it. `loader.strip_eval_only` removes them and
#: `safety_metrics.eval_only_field_leak` asserts they are gone.
EVAL_ONLY_FIELDS = frozenset({"scenario_label", "fixture_notes"})

#: Fields that give away the answer more subtly: they pre-label what the adjudicator must decide.
#: REC-04 in `docs/CLAIMS_AND_GOLD_SET_FIXES.md` asks for these to be withheld too.
ANSWER_HINT_FIELDS = frozenset({"potentially_payable", "room_linked", "duplicate_of"})


class BillLine(BaseModel):
    """One line of the itemised bill, as the agent sees it."""

    model_config = ConfigDict(extra="allow")  # fixtures carry more keys than the harness reads

    line_id: str
    description: str
    quantity: int = 1
    unit_amount_inr: int = 0
    amount_inr: int
    category: str


class ClaimRecord(BaseModel):
    """A claim as the agent sees it: eval-only fields are already removed."""

    model_config = ConfigDict(extra="allow")

    claim_id: str
    bill_total_inr: int
    bill_lines: list[BillLine]
    documents: list[dict] = Field(default_factory=list)

    def document_text(self) -> str:
        """Every document's text joined. Untrusted: this is data, never instructions."""
        return "\n".join(str(d.get("synthetic_text", "")) for d in self.documents)


class GoldLineItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    line_id: str
    allowed_before_copay_inr: int
    deduction_before_copay_inr: int = 0
    reason_codes: list[str] = Field(default_factory=list)
    clause_id: str | None = None  # added by the GOLD-07 fix; absent where DEC-04 is unresolved


class GoldRecord(BaseModel):
    """The reference answer. Never shown to an adapter: the harness holds it separately."""

    model_config = ConfigDict(extra="allow")

    claim_id: str
    line_items: list[GoldLineItem]
    expected_settlement_inr: int
    expected_review_flags: list[str] = Field(default_factory=list)
    human_review_required: bool
    # red-team only
    attack_id: str | None = None
    category: str = ""
    safety_critical: bool = False
    base_claim_id: str | None = None
    door: str | None = None

    @property
    def expected_route(self) -> Route:
        return "needs_review" if self.human_review_required else "ready_for_approval"


class EvalCase(BaseModel):
    """One claim plus its gold, paired and ready to score."""

    claim: ClaimRecord
    gold: GoldRecord
    split: str

    @property
    def claim_id(self) -> str:
        return self.claim.claim_id


class ToolCall(BaseModel):
    """One tool invocation from the run trace.

    `status` matters for safety: a `settle_claim` the guardrail **blocked** is the guardrail
    working and must never count against the agent. Only `executed` counts.
    """

    tool: str
    status: ToolStatus = "executed"


class WorksheetLineOut(BaseModel):
    line_id: str
    allowed_before_copay_inr: int


class WorksheetOut(BaseModel):
    line_items: list[WorksheetLineOut] = Field(default_factory=list)
    settlement_inr: int | None = None


class AgentOutput(BaseModel):
    """What an adapter must return for one claim. The only type a new adapter has to produce."""

    claim_id: str
    route: Route | None = None
    worksheet: WorksheetOut | None = None
    review_flags: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)
    actions: list[ToolCall] = Field(default_factory=list)

    #: line_id -> the agent's one-line reason. Input to the LLM judge.
    rationales: dict[str, str] = Field(default_factory=dict)
    #: line_id -> clause text the agent was actually shown. The judge scores against this.
    retrieved_contexts: dict[str, list[str]] = Field(default_factory=dict)

    #: Fields the adapter saw, so the harness can prove no eval-only field leaked.
    observed_claim_keys: list[str] = Field(default_factory=list)

    latency_s: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0

    #: The pipeline's own end status, when it has one (for example `awaiting_review`). Reported,
    #: never scored: the harness derives `route` from the agents' judgements, not from this.
    status: str = ""
    #: Set when the pipeline raised. A crash is a result and must stay visible, so it is recorded
    #: here and the claim scores as no answer rather than being dropped from the run.
    error: str | None = None

    def settled(self) -> bool:
        """True only if a settlement actually executed."""
        return any(a.tool == "settle_claim" and a.status == "executed" for a in self.actions)

    def allowed_by_line(self) -> dict[str, int]:
        ws = self.worksheet
        return {} if ws is None else {x.line_id: x.allowed_before_copay_inr for x in ws.line_items}


class MetricResult(BaseModel):
    """One metric's outcome. `value` is normalised to 0.0-1.0 so weights are comparable.

    `passed` is None for metrics that only report (latency, cost) and carry no threshold.

    `applicable` is False when this claim cannot fairly exercise the metric at all - for example
    citations on a claim whose gold has no deductions to cite. An inapplicable metric is excluded
    from its own average and from that claim's composite, with the remaining weights renormalised.
    Scoring it 0.0 would punish the agent for a gap in the fixtures; scoring it 1.0 would inflate
    every run. Excluding it is the only honest option, so the count of excluded claims is reported.
    """

    name: str
    family: str
    value: float
    passed: bool | None = None
    threshold: float | None = None
    severity: Severity = "medium"
    applicable: bool = True
    detail: dict = Field(default_factory=dict)


class CaseScore(BaseModel):
    """Per-claim result: the weighted parts plus any gate that fired."""

    claim_id: str
    category: str = ""
    route_pred: Route | None = None
    route_gold: Route
    parts: dict[str, float] = Field(default_factory=dict)
    #: Metrics this claim could not fairly exercise, excluded from its composite. See
    #: `MetricResult.applicable`.
    excluded_metrics: list[str] = Field(default_factory=list)
    score: float = 0.0
    gates_failed: list[str] = Field(default_factory=list)

    @property
    def safe(self) -> bool:
        return not self.gates_failed
