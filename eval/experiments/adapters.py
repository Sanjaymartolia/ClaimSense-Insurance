"""The three E1 architectures as harness adapters. Each returns the same `AgentOutput`, so one
scorer (`eval.harness`) judges all of them.

    C0 fixed         FixedWorkflowAdapter: code order, one model call (clause choice)
    C1 single_agent  SingleAgentAdapter: one model with every read tool, it picks its own calls
    C2 team          ClaimSenseAdapter, unchanged: the product graph

C0 and C1 subclass `ClaimSenseAdapter` to reuse its claim -> packet, policy and history mapping
and its state -> route / flags / worksheet mapping, so only the architecture differs. Rupees
always come from the calculator (rule 1). A model's clause pick is accepted only if it is a
line-level clause the run actually retrieved, as `CoverageAgent.choose_clauses` requires.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field

from eval.harness.claimsense_adapter import (
    ClaimSenseAdapter,
    _observed,
    count_llm_usage,
    coverage_rationales,
)
from eval.harness.models import AgentOutput, ClaimRecord, ToolCall

from .config import ExperimentConfig

SHOWN_CHARS = 400  # as CoverageAgent.CANDIDATE_CHARS


class _Base(ClaimSenseAdapter):
    def __init__(self, cfg: ExperimentConfig) -> None:
        super().__init__(
            calculator=cfg.calculator, pass_documents=cfg.pass_documents, retrieval=cfg.retrieval
        )
        self.cfg = cfg
        self.name = f"{cfg.experiment}-{cfg.condition}[{cfg.architecture}]"

    def _services(self, claim: ClaimRecord) -> Any:
        """The same tool callables `ClaimSenseAdapter.run` builds for the team."""
        imports = self._imports
        policy = self._policy(claim)
        past = self._history(claim)
        services = imports["make_stub_services"](
            policies={policy.policy_number: policy},
            history={policy.policy_number: past} if past else None,
        )
        services.calculate = (
            imports["reference_calculate"]
            if self.calculator == "reference"
            else imports["real_calculate"]
        )
        if self.retrieval == "real":
            from eval.harness.real_retrieval import use_real_retrieval

            use_real_retrieval(services)
        return services

    def _output(
        self,
        claim: ClaimRecord,
        state: dict,
        actions: list[ToolCall],
        rationales: dict[str, str],
        contexts: dict[str, list[str]],
        spent: dict[str, float],
        started: float,
    ) -> AgentOutput:
        choices = dict(state.get("clause_choices") or {})
        citations = set(choices.values())
        adm = state.get("admissibility")
        if adm is not None:
            citations.update(getattr(adm, "clause_ids", []) or [])
        return AgentOutput(
            claim_id=claim.claim_id,
            route=self._route(state),
            worksheet=self._worksheet(state),
            review_flags=self._flags(state),
            citations=sorted(c for c in citations if c),
            actions=actions,
            rationales=rationales,
            retrieved_contexts=contexts,
            observed_claim_keys=_observed(claim),
            latency_s=time.perf_counter() - started,
            status=str(state.get("status", "")),
            prompt_tokens=int(spent["prompt_tokens"]),
            completion_tokens=int(spent["completion_tokens"]),
            cost_usd=float(spent["cost_usd"]),
        )

    def _error(self, claim: ClaimRecord, error: Exception, started: float) -> AgentOutput:
        return AgentOutput(
            claim_id=claim.claim_id,
            review_flags=["pipeline_error"],
            observed_claim_keys=_observed(claim),
            latency_s=time.perf_counter() - started,
            error=f"{type(error).__name__}: {error}",
        )


# ------------------------------------------------------------------------------ C0
class FixedWorkflowAdapter(_Base):
    """C0: admissibility rules, one search per line, one clause-choice prompt, the calculator."""

    def run(self, claim: ClaimRecord) -> AgentOutput:
        from claimsense.contracts import Claim

        started = time.perf_counter()
        services = self._services(claim)
        team = self._imports["Team"](services)
        coverage = team.coverage
        try:
            with count_llm_usage(not self._imports["stub_mode"]()) as spent:
                parsed = Claim.model_validate(self._packet(claim)["claim"])
                adm = coverage.check_admissibility(parsed)
                choices: dict[str, str] = {}
                worksheet = None
                if adm.admissible:
                    choices, _, _ = coverage.choose_clauses(parsed)  # ONE model call
                    worksheet = coverage.adjudicate(parsed, choices)
                elif adm.clause_ids:  # Rs 0 from the calculator, as the team does (ADR-0010)
                    gate = adm.clause_ids[0]
                    worksheet = coverage.adjudicate(
                        parsed, {line.line_id: gate for line in parsed.bill_lines}
                    )
        except Exception as e:  # noqa: BLE001 - one claim must not lose the run
            return self._error(claim, e, started)
        state = {"admissibility": adm, "worksheet": worksheet, "clause_choices": choices}
        rationales, contexts = coverage_rationales(team, choices)
        return self._output(
            claim, state, self._actions(services.tool_log), rationales, contexts, spent, started
        )


# ------------------------------------------------------------------------------ C1
class PolicyNumber(BaseModel):
    policy_number: str


class PolicySearch(BaseModel):
    query: str = Field(description="what to look up in the policy wording")
    category: str | None = Field(None, description="the bill line's category, if any")


class ClauseId(BaseModel):
    clause_id: str


class TariffQuery(BaseModel):
    procedure: str
    city_tier: str = "tier_1"


class Calculate(BaseModel):
    clause_choices: dict[str, str] = Field(description="bill line_id -> clause_id")


TOOL_SCHEMAS: dict[str, type[BaseModel]] = {
    "get_policy": PolicyNumber,
    "claim_history": PolicyNumber,
    "policy_search": PolicySearch,
    "get_clause": ClauseId,
    "tariff_range": TariffQuery,
    "calculate": Calculate,
}

TOOL_HELP = {
    "get_policy": "The policy record: period, first inception, sum insured, declared PEDs.",
    "claim_history": "Earlier claims on this policy, with sub-limits already used.",
    "policy_search": "Search the policy wording. Returns clause ids with their text.",
    "get_clause": "The full text of one clause by id.",
    "tariff_range": "The usual price range of a procedure in a city tier.",
    "calculate": "Run the calculator on your clause choices; returns payable rupees per line.",
}


class LinePick(BaseModel):
    line_id: str
    clause_id: str
    rationale: str = Field(description="one sentence, cite the clause wording")


class FinalDecision(BaseModel):
    choices: list[LinePick]
    admissible: bool = Field(
        description="false if a claim-level rule (period, waiting period, "
        "exclusion) rules the whole claim out"
    )
    gate_clause_id: str | None = Field(None, description="the clause that rules it out, if any")
    needs_review: bool = Field(description="true if a person should look before approval")
    concerns: list[str] = Field(default_factory=list, description="what a person should check")


def _system() -> str:
    from claimsense.agents.llm import DATA_RULE

    return (
        "You adjudicate one Arogya Sanjeevani reimbursement claim on your own. You have tools; "
        "decide which to call and when. For EVERY bill line choose exactly one clause_id that a "
        "tool returned to you. Check the policy record and the wording for claim-level rules "
        "(policy period, waiting periods, exclusions) and say whether the claim is admissible. "
        "Never compute amounts yourself: the calculator does that. Flag anything a person should "
        f"check before approval.\n{DATA_RULE}"
    )


def _brief(claim: Any, documents: dict[str, str]) -> str:
    from claimsense.agents.llm import as_data

    lines = "\n".join(
        f"{b.line_id} | {b.category.value} | {b.description} | Rs {b.amount} | days={b.days}"
        for b in claim.bill_lines
    )
    parts = [
        f"Claim {claim.claim_id}, policy {claim.policy_number}, patient {claim.patient_pseudonym}",
        f"Admitted {claim.admission_date}, discharged {claim.discharge_date}, nights {claim.nights}"
        f", room category {claim.room_category.value}",
        f"Diagnosis: {claim.diagnosis}; procedure: {claim.procedure}",
        f"Bill total Rs {claim.bill_total}\nBILL LINES:\n{lines}",
    ]
    parts += [as_data(name, text) for name, text in documents.items() if text]
    return "\n\n".join(parts)


def _message_cost(message: Any) -> float:
    usage = (getattr(message, "response_metadata", None) or {}).get("token_usage") or {}
    return float(usage.get("cost") or 0.0)


class SingleAgentAdapter(_Base):
    """C1: one model, every read tool bound, its own tool loop, stopped by the budget."""

    max_rounds = 60  # a safety stop; the budget normally ends the loop first

    def _tools(self, services: Any, claim: Any, seen: dict[str, str]) -> dict[str, Callable]:
        def remember(clause: Any) -> str:
            seen[clause.clause_id] = clause.text[:SHOWN_CHARS]
            return f"{clause.clause_id}: {clause.text[:SHOWN_CHARS]}"

        def policy(policy_number: str) -> str:
            p = services.get_policy(policy_number)
            return json.dumps(p.model_dump(mode="json")) if p else "no such policy"

        def history(policy_number: str) -> str:
            past = services.claim_history(policy_number)
            return json.dumps([h.model_dump(mode="json") for h in past]) if past else "none"

        def search(query: str, category: str | None = None) -> str:
            hits = services.policy_search(query, category=category)
            return "\n".join(remember(h.clause) for h in hits) or "no match"

        def clause(clause_id: str) -> str:
            found = services.get_clause(clause_id)
            return remember(found) if found else "no such clause"

        def tariff(procedure: str, city_tier: str = "tier_1") -> str:
            band = services.tariff_range(procedure, city_tier)
            return f"Rs {band[0]} to Rs {band[1]}" if band else "no tariff on file"

        def calculate(clause_choices: dict[str, str]) -> str:
            ws = services.calculate(claim, dict(clause_choices))
            rows = [
                f"{w.line_id}: claimed {w.claimed}, payable {w.payable}"
                + "".join(f"; {d.reason.value} Rs {d.amount} ({d.clause_id})" for d in w.deductions)
                for w in ws.lines
            ]
            return "\n".join([*rows, f"total payable {ws.total_payable}"])

        table = {
            "get_policy": policy,
            "claim_history": history,
            "policy_search": search,
            "get_clause": clause,
            "tariff_range": tariff,
            "calculate": calculate,
        }
        return {name: table[name] for name in self.cfg.tools if name in table}

    def decide(self, llm: Any, claim: Any, documents: dict[str, str], services: Any) -> tuple:
        """(FinalDecision, seen clause texts, executed tool names, stop reason)."""
        from langchain_core.messages import ToolMessage
        from langchain_core.tools import StructuredTool

        seen: dict[str, str] = {}
        funcs = self._tools(services, claim, seen)
        tools = [
            StructuredTool.from_function(
                func=fn, name=name, description=TOOL_HELP[name], args_schema=TOOL_SCHEMAS[name]
            )
            for name, fn in funcs.items()
        ]
        bound = llm.bind_tools(tools)
        messages: list[Any] = [("system", _system()), ("human", _brief(claim, documents))]
        executed: list[str] = []
        cost, stop = 0.0, "answered"
        budget = self.cfg.budget
        for _ in range(self.max_rounds):
            reply = bound.invoke(messages)
            messages.append(reply)
            cost += _message_cost(reply)
            calls = getattr(reply, "tool_calls", None) or []
            if not calls:
                break
            for call in calls:
                if len(executed) >= budget.max_tool_calls_per_claim:
                    stop, result = "tool budget", "not run: the tool-call budget is used up"
                elif cost >= budget.max_cost_usd_per_claim:
                    stop, result = "cost budget", "not run: the cost budget is used up"
                elif call["name"] not in funcs:
                    result = f"unknown tool {call['name']}"
                else:
                    executed.append(call["name"])
                    try:
                        result = funcs[call["name"]](**call["args"])
                    except Exception as e:  # noqa: BLE001 - a tool error is a reply, not a crash
                        result = f"tool error: {type(e).__name__}: {e}"
                messages.append(ToolMessage(content=str(result), tool_call_id=call["id"]))
            if stop != "answered":
                break
        else:
            stop = "round limit"
        messages.append(("human", "Give your final decision for every bill line now."))
        final = llm.with_structured_output(FinalDecision).invoke(messages)
        return final, seen, executed, stop

    def _stub_decision(self, claim: Any, services: Any) -> tuple:
        """No model (stub mode): top line-level search hit per line. Plumbing only."""
        from claimsense.agents import clauses as C

        seen: dict[str, str] = {}
        picks = []
        for line in claim.bill_lines:
            hits = services.policy_search(line.description, category=line.category.value)
            for h in hits:
                seen[h.clause.clause_id] = h.clause.text[:SHOWN_CHARS]
            ids = [h.clause.clause_id for h in hits if h.clause.clause_id not in C.CLAIM_LEVEL]
            picks.append(
                LinePick(line_id=line.line_id, clause_id=ids[0] if ids else "", rationale="")
            )
        final = FinalDecision(choices=picks, admissible=True, needs_review=False)
        return final, seen, ["policy_search"] * len(claim.bill_lines), "stub"

    def run(self, claim: ClaimRecord) -> AgentOutput:
        from claimsense.agents import clauses as C
        from claimsense.agents.coverage import Admissibility
        from claimsense.agents.llm import get_llm
        from claimsense.contracts import Claim

        started = time.perf_counter()
        services = self._services(claim)
        packet = self._packet(claim)
        stub = self._imports["stub_mode"]()
        try:
            with count_llm_usage(not stub) as spent:
                parsed = Claim.model_validate(packet["claim"])
                if stub:
                    final, seen, executed, stop = self._stub_decision(parsed, services)
                else:
                    final, seen, executed, stop = self.decide(
                        get_llm("coverage"), parsed, packet["documents"], services
                    )
                choices, rationales, contexts = validate(final, parsed, seen, C)
                gate = final.gate_clause_id if final.gate_clause_id in C.CLAIM_LEVEL else None
                adm = Admissibility(
                    admissible=final.admissible,
                    needs_review=final.needs_review,
                    reasons=list(final.concerns),
                    clause_ids=[gate] if (gate and not final.admissible) else [],
                )
                applied = (
                    {line.line_id: gate for line in parsed.bill_lines}
                    if (gate and not final.admissible)
                    else choices
                )
                worksheet = services.calculate(parsed, applied)  # rupees from code only
        except Exception as e:  # noqa: BLE001 - one claim must not lose the run
            return self._error(claim, e, started)
        state = {
            "admissibility": adm,
            "worksheet": worksheet,
            "clause_choices": choices,
            "escalation": "agent asked for review" if final.needs_review else None,
            "status": stop,
        }
        # The agent's own calls, then the calculator run that produced the worksheet above.
        actions = [ToolCall(tool=name) for name in [*executed, "calculate"]]
        return self._output(claim, state, actions, rationales, contexts, spent, started)


def validate(final: FinalDecision, claim: Any, seen: dict[str, str], C: Any) -> tuple:
    """(choices, rationales, contexts). A pick must be a line-level clause the agent was shown;
    otherwise the line falls back to clause 4.1 and keeps no rationale, as the team's validation."""
    by_line = {p.line_id: p for p in final.choices}
    choices: dict[str, str] = {}
    rationales: dict[str, str] = {}
    contexts: dict[str, list[str]] = {}
    for line in claim.bill_lines:
        pick = by_line.get(line.line_id)
        if pick and pick.clause_id in seen and pick.clause_id not in C.CLAIM_LEVEL:
            choices[line.line_id] = pick.clause_id
            if pick.rationale.strip():
                rationales[line.line_id] = pick.rationale
                contexts[line.line_id] = [seen[pick.clause_id]]
        else:
            choices[line.line_id] = C.HOSPITALISATION
    return choices, rationales, contexts


# ------------------------------------------------------------------------------ E4
#: The values of `contracts.DeductionReason`, spelled out for the model's answer schema.
DEDUCTION_REASONS = (
    "room_rent_cap",
    "proportional_cut",
    "icu_cap",
    "sub_limit",
    "non_payable",
    "waiting_period",
    "exclusion",
    "co_pay",
    "other",
)


class LlmDeduction(BaseModel):
    reason: str = Field(description="one of: " + ", ".join(DEDUCTION_REASONS))
    amount: float
    clause_id: str


class LlmLine(BaseModel):
    line_id: str
    payable: float = Field(description="rupees payable for this line, after its deductions")
    deductions: list[LlmDeduction] = Field(default_factory=list)


class LlmWorksheet(BaseModel):
    lines: list[LlmLine]
    co_pay: float = Field(description="the co-payment in rupees, taken from the lines' total")
    total_payable: float


ARITHMETIC_SYSTEM = (
    "You compute the rupee amounts of a health insurance claim worksheet yourself. Use only the "
    "rules and the clause chosen for each line below. For each line give the payable amount and "
    "each deduction (reason, amount, clause_id). Then give the co-payment and the total payable."
)


def rules_in_words(claim: Any) -> str:
    """The calculator's rules (`calc.adjudication.PolicyRules`), as text for the model."""
    from claimsense.agents import clauses as C
    from claimsense.calc.adjudication import FULLY_DEDUCTED, PolicyRules

    r = PolicyRules()
    room = min(claim.sum_insured * r.room_rent_pct, r.room_rent_max_per_day)
    icu = min(claim.sum_insured * r.icu_pct, r.icu_max_per_day)
    return "\n".join(
        [
            f"Sum insured Rs {claim.sum_insured}; stay {claim.nights} night(s).",
            f"Room, boarding and nursing together: at most Rs {room} per day "
            f"({r.room_rent_pct:%} of sum insured, max Rs {r.room_rent_max_per_day}); a line's "
            "days come from its days field, else the stay. Clause " + C.ROOM_RENT_LIMIT + ".",
            f"ICU: at most Rs {icu} per day ({r.icu_pct:%} of sum insured, max Rs "
            f"{r.icu_max_per_day}). Clause {C.ICU_LIMIT}.",
            "If the room or ICU rate is above its limit, every other expense except medicines is "
            "paid in the same proportion (proportional deduction).",
            "A line billed twice in the same bill is deducted in full the second time.",
            "These clauses make a line not payable at all: " + ", ".join(sorted(FULLY_DEDUCTED)),
            f"Co-payment: {r.co_pay_rate:%} of the total payable, clause {C.CO_PAY}.",
        ]
    )


class LlmArithmetic:
    """E4's `calculate`: the model computes the worksheet. The real calculator runs alongside on
    the same inputs only to measure the model's arithmetic error; its numbers are never returned.
    In stub mode there is no model, so the calculator's worksheet is returned (error 0)."""

    def __init__(self, calculator: Callable[..., Any]) -> None:
        self.calculator = calculator
        self.log: dict[str, dict[str, Any]] = {}  # claim_id -> the claim's last worksheet

    def __call__(
        self,
        claim: Any,
        clause_choices: dict[str, str],
        version: int = 1,
        fraud_flags: list[str] | None = None,
        **kw: Any,
    ) -> Any:
        from claimsense.agents.llm import get_llm

        truth = self.calculator(
            claim, clause_choices, version=version, fraud_flags=fraud_flags, **kw
        )
        llm = get_llm("coverage")
        if llm is None:
            self.log[claim.claim_id] = arithmetic_error(truth, truth, reconciles=True)
            return truth
        lines = "\n".join(
            f"{b.line_id} | {b.category.value} | {b.description} | Rs {b.amount} | "
            f"days={b.days} | clause {clause_choices.get(b.line_id)}"
            for b in claim.bill_lines
        )
        answer = llm.with_structured_output(LlmWorksheet).invoke(
            [
                ("system", ARITHMETIC_SYSTEM),
                ("human", f"RULES:\n{rules_in_words(claim)}\n\nBILL LINES:\n{lines}"),
            ]
        )
        worksheet, reconciles = to_worksheet(answer, claim, version, fraud_flags)
        self.log[claim.claim_id] = arithmetic_error(worksheet, truth, reconciles)
        return worksheet


def to_worksheet(answer: LlmWorksheet, claim: Any, version: int, fraud_flags: Any) -> tuple:
    """The model's numbers as a Worksheet, unchanged. Built without validation, so numbers that
    do not add up are scored as given; `reconciles` says whether the contract would accept them."""
    from decimal import Decimal

    from claimsense.agents import clauses as C
    from claimsense.contracts import Deduction, DeductionReason, Worksheet, WorksheetLine

    def money(x: float) -> Decimal:
        return Decimal(str(round(float(x), 2)))

    def reason(name: str) -> DeductionReason:
        return DeductionReason(name) if name in DEDUCTION_REASONS else DeductionReason.OTHER

    said = {line.line_id: line for line in answer.lines}
    lines = []
    for b in claim.bill_lines:
        got = said.get(b.line_id)
        deductions = [
            Deduction.model_construct(
                reason=reason(d.reason),
                amount=money(d.amount),
                clause_id=d.clause_id,
                explanation="model arithmetic",
            )
            for d in (got.deductions if got else [])
        ]
        payable = money(got.payable) if got else b.amount
        lines.append(
            WorksheetLine.model_construct(
                line_id=b.line_id, claimed=b.amount, deductions=deductions, payable=payable
            )
        )
    co_pay = Deduction.model_construct(
        reason=DeductionReason.CO_PAY,
        amount=money(answer.co_pay),
        clause_id=C.CO_PAY,
        explanation="model arithmetic",
    )
    worksheet = Worksheet.model_construct(
        claim_id=claim.claim_id,
        version=version,
        lines=lines,
        co_pay=co_pay,
        total_claimed=sum((b.amount for b in claim.bill_lines), Decimal("0")),
        total_payable=money(answer.total_payable),
        fraud_flags=list(fraud_flags or []),
    )
    try:
        Worksheet.model_validate(worksheet.model_dump())
        reconciles = True
    except ValueError:
        reconciles = False
    return worksheet, reconciles


def arithmetic_error(worksheet: Any, truth: Any, reconciles: bool) -> dict[str, Any]:
    """Rupee error of a worksheet against the calculator's on the same clause choices."""
    from decimal import Decimal

    mine = {line.line_id: line.payable for line in worksheet.lines}
    line_error = sum(
        (abs(mine.get(line.line_id, Decimal("0")) - line.payable) for line in truth.lines),
        Decimal("0"),
    )
    return {
        "total_error_rs": float(abs(worksheet.total_payable - truth.total_payable)),
        "line_error_rs": float(line_error),
        "reconciles": reconciles,
    }


def build(cfg: ExperimentConfig) -> ClaimSenseAdapter:
    if cfg.architecture == "fixed":
        return FixedWorkflowAdapter(cfg)
    if cfg.architecture == "single_agent":
        return SingleAgentAdapter(cfg)
    adapter = ClaimSenseAdapter(
        calculator=cfg.calculator, pass_documents=cfg.pass_documents, retrieval=cfg.retrieval
    )
    adapter.name = f"{cfg.experiment}-{cfg.condition}[{cfg.architecture}]"
    if cfg.arithmetic == "llm":
        # The team adapter looks the calculator up here on every claim (calculator="real").
        adapter.arithmetic = LlmArithmetic(adapter._imports["real_calculate"])  # noqa: SLF001
        adapter._imports["real_calculate"] = adapter.arithmetic  # noqa: SLF001
    return adapter
