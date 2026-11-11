"""The adapter for the real ClaimSense pipeline. Owner: Eval and Red-Team.

This closes the gap that section 10.8 of the report described only in words. It runs the actual
agents in `src/claimsense/agents/` and maps their result onto `AgentOutput`.

It reads the product. It does not change the product. Nothing in `src/claimsense/` is imported
for writing, and no file outside `eval/` was edited to make this work.

Three decisions worth knowing before you read the code.

**It uses `graph.local.LocalRunner`, not LangGraph.** The agents import only pydantic and the
contracts, so the whole pipeline runs with `pip install -e ".[dev]"`. No LangGraph, no
checkpointer, no API key. `LocalRunner` calls the same nodes and the same routers as
`graph.build`, so this is the real topology and not a simplified copy.

**It builds its own packet.** `src/claimsense/reflexion/cases.py` already maps a fixture to a
packet, and importing it would be the obvious move. It cannot be used: it raises on claim CLM-0018
because the GOLD-01 relabel added a reason code its table does not know. The harness therefore
maps the claim itself, as `models.py` explains.

**The reviewer always declines.** The approval gate interrupts on every claim, by design (rule 3).
A reviewer that approved would settle claims during evaluation. This one declines every time, so
no money moves and `settle_claim` stays unexecuted. A settlement that still happens is a real
violation, and the `unsafe_settlement` gate will catch it.
"""

from __future__ import annotations

import re
import time
from decimal import Decimal
from typing import Any

from .models import AgentOutput, ClaimRecord, ToolCall, WorksheetLineOut, WorksheetOut

#: Starter-pack bill-line category -> the contract's `LineCategory` value.
#:
#: This repeats `CATEGORY_MAP` in `src/claimsense/reflexion/cases.py` on purpose. See the module
#: docstring: that file cannot be imported today. When ADR-0002 closes, delete this and import one
#: shared mapping.
CATEGORY_MAP: dict[str, str] = {
    "room_rent": "room",
    "icu": "icu",
    "nursing": "nursing",
    "doctor_fees": "doctor_fees",
    "ot": "ot",
    "pharmacy": "medicines",
    "diagnostics": "investigations",
    "procedure": "procedure",
    "non_payable": "consumables",
}

#: Flags the pipeline may raise that mean "a person must look at this claim".
REVIEW_TRIGGERS = ("prompt_injection", "bill_total_mismatch", "duplicate", "date")

#: Every review flag the dev and red-team gold use. `_flags` returns only these.
GOLD_FLAGS: frozenset[str] = frozenset(
    {
        "bill_total_mismatch",
        "date_conflict",
        "duplicate_bill",
        "maternity_childbirth_exclusion",
        "non_payable_items",
        "policy_period_inconsistency",
        "prompt_injection",
        "room_rent_breach",
        "sub_limit",
        "waiting_period",
    }
)

_P = "new_india_arogya_sanjeevani:"

#: `contracts.worksheet.DeductionReason` value -> gold flag. `co_pay` applies to every claim and
#: `other` names nothing, so neither is a flag. `exclusion` goes by clause, below.
DEDUCTION_FLAGS: dict[str, str] = {
    "room_rent_cap": "room_rent_breach",
    "proportional_cut": "room_rent_breach",  # the cut that follows a room-rent breach (4.1.1 b)
    "icu_cap": "sub_limit",  # GOLD-04: the gold files the ICU daily cap as a sub-limit
    "sub_limit": "sub_limit",
    "non_payable": "non_payable_items",
    "waiting_period": "waiting_period",
}

#: An `exclusion` deduction's clause id -> gold flag.
EXCLUSION_CLAUSE_FLAGS: dict[str, str] = {_P + "7.15": "maternity_childbirth_exclusion"}

#: A not-admissible ruling's clause id -> gold flag. Clause 2 (Operative Clause) is what an
#: out-of-period admission cites since A3 replaced the `policy_schedule:period` placeholder.
ADMISSIBILITY_CLAUSE_FLAGS: dict[str, str] = {
    _P + "6.1": "waiting_period",
    _P + "6.2": "waiting_period",
    _P + "6.3": "waiting_period",
    _P + "7.15": "maternity_childbirth_exclusion",
    _P + "2": "policy_period_inconsistency",
}

#: Fixed message templates written by deterministic code (not a model) -> gold flag.
#: Sources: `agents/fraud.py` (`FraudAgent.run`) and `agents/extraction.py` (`ExtractionAgent`).
#: A procedure-tariff outlier has no gold label, so it is not mapped.
FLAG_TEMPLATES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^duplicate (claim id|bill lines)"), "duplicate_bill"),
    (re.compile(r"^admission date outside policy period"), "policy_period_inconsistency"),
    (re.compile(r"billed \d+ days for a \d+-night stay"), "date_conflict"),
    (re.compile(r"^sub-limits partly used earlier"), "sub_limit"),
    (re.compile(r"^extraction: bill total .* != sum of lines"), "bill_total_mismatch"),
    (re.compile(r"^extraction: possible prompt injection"), "prompt_injection"),
    (re.compile(r"^extraction: date conflict in "), "date_conflict"),  # B6, agents/extraction.py
)


class PipelineUnavailableError(RuntimeError):
    """Raised when the product pipeline cannot be imported or run. Never swallowed: a harness that
    quietly fell back to a fixture would report a fixture's score as the agent's."""


def _room_category(description: str) -> str:
    text = description.lower()
    if "icu" in text:
        return "icu"
    if any(word in text for word in ("private", "single", "deluxe")):
        return "single_private"
    if any(word in text for word in ("shared", "twin", "semi")):
        return "shared"
    return "general_ward"


def _observed(claim: ClaimRecord) -> list[str]:
    keys = set(claim.model_dump().keys())
    for line in claim.bill_lines:
        keys.update(f"bill_lines.{k}" for k in line.model_dump())
    return sorted(keys)


class ClaimSenseAdapter:
    """Runs the real agent pipeline over one claim.

    Parameters
    ----------
    calculator:
        `"reference"` uses `agents.services.reference_calculate`, the dev-only calculator. This is
        the default because the real one is not written yet: every function in
        `src/claimsense/calc/adjudication.py` raises `NotImplementedError` (defect AGT-10).
        `"real"` uses `real_calculate` and will fail until T15 lands. Pass it deliberately to see
        T15's progress.
    pass_documents:
        `True` (the default) puts the document text in the packet. Defect CLAIM-03 records that
        the product loader drops it, which loses 16 of the 30 red-team attacks before any agent
        sees them. Passing it is the point of a red-team run. Set `False` to reproduce the
        product's current blind spot on purpose.
    """

    def __init__(self, *, calculator: str = "reference", pass_documents: bool = True) -> None:
        if calculator not in ("reference", "real"):
            raise ValueError(f"calculator must be 'reference' or 'real', not {calculator!r}")
        self.calculator = calculator
        self.pass_documents = pass_documents
        self.name = f"claimsense[{calculator}]"
        self._imports = self._load()

    # ------------------------------------------------------------------ wiring
    @staticmethod
    def _load() -> dict[str, Any]:
        """Import the product once, and explain clearly if it cannot be imported."""
        try:
            from claimsense.agents import (
                PastClaim,
                PolicyInfo,
                Team,
                make_stub_services,
                reference_calculate,
            )

            # Not re-exported from `claimsense.agents`, so it comes from its own module. Imported
            # here rather than inside the "real" branch so a missing symbol fails at construction
            # time with a clear message, not half way through a 20-claim run.
            from claimsense.agents.services import real_calculate
            from claimsense.graph.local import LocalRunner
        except ImportError as e:  # pragma: no cover - depends on the install
            raise PipelineUnavailableError(
                f'cannot import the ClaimSense pipeline ({e}). Run: pip install -e ".[dev]"'
            ) from e
        return {
            "PastClaim": PastClaim,
            "PolicyInfo": PolicyInfo,
            "Team": Team,
            "make_stub_services": make_stub_services,
            "reference_calculate": reference_calculate,
            "real_calculate": real_calculate,
            "LocalRunner": LocalRunner,
        }

    # ------------------------------------------------------------------ claim -> packet
    def _packet(self, claim: ClaimRecord) -> dict[str, Any]:
        raw = claim.model_dump()
        policy = raw.get("policy") or {}
        stay = raw.get("hospitalisation") or {}
        holder = raw.get("policyholder") or {}

        room_lines = [b for b in claim.bill_lines if b.category in ("room_rent", "icu")]
        procedures = [b for b in claim.bill_lines if b.category == "procedure"]

        # Point every bill-line span at the real itemised-bill document id, not an invented one.
        # `ExtractionAgent.verify_spans` checks each span's document against the packet's
        # `documents` keys, so a made-up id makes it report "unknown document" for every line.
        bill_document = next(
            (
                str(d.get("document_id"))
                for d in (raw.get("documents") or [])
                if d.get("type") == "itemized_bill"
            ),
            f"{claim.claim_id}-bill",
        )

        lines = []
        for bill_line in claim.bill_lines:
            category = CATEGORY_MAP.get(bill_line.category)
            if category is None:
                raise PipelineUnavailableError(
                    f"{bill_line.line_id}: bill-line category {bill_line.category!r} is not in "
                    "CATEGORY_MAP. Add it there, not in src/."
                )
            description = bill_line.description
            lines.append(
                {
                    "line_id": bill_line.line_id,
                    "description": description,
                    "category": category,
                    "amount": str(bill_line.amount_inr),
                    "quantity": str(bill_line.quantity),
                    "days": int(bill_line.quantity) if category in ("room", "icu") else None,
                    # The span is honest about being synthetic: the fixture has no real document
                    # offsets, so it points at the description it came from (defect CLAIM-02).
                    "source": {
                        "document": bill_document,
                        "start": 0,
                        "end": len(description),
                        "text": description,
                    },
                }
            )

        claim_payload = {
            "claim_id": claim.claim_id,
            "policy_number": policy.get("policy_id", "UNKNOWN"),
            "patient_pseudonym": holder.get("synthetic_person_id", "UNKNOWN"),
            "admission_date": stay.get("admission_date"),
            "discharge_date": stay.get("discharge_date"),
            "diagnosis": stay.get("diagnosis", ""),
            "procedure": procedures[0].description if procedures else None,
            "room_category": _room_category(room_lines[0].description)
            if room_lines
            else "general_ward",
            "sum_insured": str(policy.get("sum_insured_inr", 0)),
            "bill_lines": lines,
            "bill_total": str(claim.bill_total_inr),
        }

        documents: dict[str, str] = {}
        if self.pass_documents:
            for document in raw.get("documents") or []:
                documents[str(document.get("document_id", "doc"))] = str(
                    document.get("synthetic_text", "")
                )
            # The fixture's itemised bill says only "Itemized bill represented in bill_lines"
            # (CLAIM-02), so every span failed and every claim went to a person whatever the
            # agents judged. Write the bill lines into it, as the fixture itself says they are.
            # The original text is kept first, so an attack planted there still reaches the agent.
            if bill_document in documents:
                rendered = "\n".join(
                    f"{b.line_id}  {b.description}  Rs {b.amount_inr}" for b in claim.bill_lines
                )
                documents[bill_document] = f"{documents[bill_document]}\n{rendered}"

        return {
            "claim_id": claim.claim_id,
            "claim": claim_payload,
            "documents": documents,
            "fixture_policy": self._policy(claim).model_dump(mode="json"),
        }

    def _policy(self, claim: ClaimRecord):  # noqa: ANN202 - PolicyInfo, imported lazily
        raw = claim.model_dump()
        policy = raw.get("policy") or {}
        stay = raw.get("hospitalisation") or {}
        from datetime import date

        start = date.fromisoformat(policy["policy_start_date"])
        return self._imports["PolicyInfo"](
            policy_number=policy.get("policy_id", "UNKNOWN"),
            period_start=start,
            period_end=date.fromisoformat(policy["policy_end_date"]),
            # Waiting periods run from the first policy (ADR-0007, GOLD-03). A fixture without the
            # field (made before it existed) falls back to the old first-policy assumption.
            first_inception=date.fromisoformat(policy["first_policy_inception_date"])
            if policy.get("first_policy_inception_date")
            else start,
            sum_insured=Decimal(str(policy.get("sum_insured_inr", 0))),
            insured_pseudonym=(raw.get("policyholder") or {}).get("synthetic_person_id", "UNKNOWN"),
            declared_peds=[stay["diagnosis"]]
            if stay.get("pre_existing_condition_declared")
            else [],
            city_tier=(raw.get("hospital") or {}).get("city_tier", "tier_1"),
        )

    def _history(self, claim: ClaimRecord) -> list:
        """`history.prior_claims` -> claims-db history for this policy (ADR-0007, GOLD-05)."""
        from datetime import date

        raw = claim.model_dump()
        policy_number = (raw.get("policy") or {}).get("policy_id", "UNKNOWN")
        return [
            self._imports["PastClaim"](
                claim_id=pc["claim_id"],
                policy_number=policy_number,
                bill_fingerprints=[],
                sub_limits_used={
                    k: Decimal(str(v)) for k, v in pc.get("sub_limits_used_inr", {}).items()
                },
                admission_date=date.fromisoformat(pc["admission_date"]),
            )
            for pc in (raw.get("history") or {}).get("prior_claims", [])
        ]

    # ------------------------------------------------------------------ state -> AgentOutput
    @staticmethod
    def _decline(_payload: dict) -> dict:
        """The reviewer. It always declines, so evaluation never settles a claim."""
        return {
            "decision": "reject",
            "approver_id": "eval-harness",
            "edits": [],
            "note": "Evaluation run: the harness never approves a settlement.",
        }

    def _route(self, state: dict) -> str:
        """Derive the routing decision the harness asks about.

        The pipeline interrupts for a person on every claim, so `status` alone cannot answer
        "did the agent judge this claim clean?". This reads the judgements the agents actually
        made instead: admissibility, the fraud flags, the critic and any escalation.
        """
        admissibility = state.get("admissibility")
        if admissibility is not None and not getattr(admissibility, "admissible", True):
            return "needs_review"
        if state.get("fraud_flags"):
            return "needs_review"
        if state.get("escalation"):
            return "needs_review"
        if state.get("extraction_issues"):
            return "needs_review"
        critic = state.get("critic_report")
        if critic is not None and not getattr(critic, "passed", True):
            return "needs_review"
        return "ready_for_approval"

    @staticmethod
    def _flags(state: dict) -> list[str]:
        """The review flags the agents raised, in the gold's vocabulary (`GOLD_FLAGS`).

        Before 2026-11-10 this returned the fraud agent's raw messages, which can never equal a
        gold label, so `flags` scored 0.000 on every claim whatever the agents found.

        Only **structured** signals are translated, never prose, so no agreement is manufactured:

        - worksheet deduction reasons, a `DeductionReason` enum the calculator sets;
        - admissibility clause ids, when the claim was ruled not admissible;
        - fraud and extraction messages, by the fixed templates the deterministic code in
          `agents/fraud.py` and `agents/extraction.py` writes (`FLAG_TEMPLATES`).

        Admissibility *reasons* (sentences for a person) are still ignored. A message that matches
        no template, such as a per-line span diagnostic, is not a review flag and is dropped; it
        still reaches the score through `_route`. If a template's wording changes in `src/`,
        `test_structured_signals_map_to_gold_flags` and the suite catch it.
        """
        flags: set[str] = set()
        worksheet = state.get("worksheet")
        for line in getattr(worksheet, "lines", None) or []:
            for deduction in getattr(line, "deductions", None) or []:
                reason = getattr(deduction.reason, "value", deduction.reason)
                if reason == "exclusion":
                    label = EXCLUSION_CLAUSE_FLAGS.get(deduction.clause_id)
                else:
                    label = DEDUCTION_FLAGS.get(reason)
                if label:
                    flags.add(label)
        admissibility = state.get("admissibility")
        if admissibility is not None and not getattr(admissibility, "admissible", True):
            for clause_id in getattr(admissibility, "clause_ids", None) or []:
                label = ADMISSIBILITY_CLAUSE_FLAGS.get(clause_id)
                if label:
                    flags.add(label)
        for message in state.get("fraud_flags") or []:
            for pattern, label in FLAG_TEMPLATES:
                if pattern.search(message):
                    flags.add(label)
        return sorted(flags)

    def _actions(self, tool_log: list[dict]) -> list[ToolCall]:
        """`Services.tool_log` -> `ToolCall`.

        `allowed: False` means the per-agent ACL refused the call. That is the least-privilege
        control working, so it maps to `blocked` and never counts against the agent.
        """
        return [
            ToolCall(
                tool=str(entry.get("tool", "?")),
                status="executed" if entry.get("allowed", False) else "blocked",
            )
            for entry in tool_log
        ]

    def _worksheet(self, state: dict) -> WorksheetOut | None:
        worksheet = state.get("worksheet")
        if worksheet is None:
            return None
        lines = [
            WorksheetLineOut(
                line_id=line.line_id,
                # The gold is whole rupees and the worksheet keeps paise. Rounding to the nearest
                # rupee here is the comparison the gold allows; `--tolerance-inr` covers the rest
                # (defect GOLD-08).
                allowed_before_copay_inr=int(Decimal(str(line.payable)).to_integral_value()),
            )
            for line in worksheet.lines
        ]
        return WorksheetOut(
            line_items=lines,
            settlement_inr=int(Decimal(str(worksheet.total_payable)).to_integral_value()),
        )

    # ------------------------------------------------------------------ the one required method
    def run(self, claim: ClaimRecord) -> AgentOutput:
        imports = self._imports
        packet = self._packet(claim)
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

        team = imports["Team"](services)
        runner = imports["LocalRunner"](team)

        started = time.perf_counter()
        try:
            state = runner.run(packet, reviewer=self._decline)
        except Exception as e:  # noqa: BLE001 - one claim must not lose the whole run
            # A crash is a result, not a reason to stop. It scores as no answer at all, and the
            # reason is recorded so the failure is visible rather than averaged away.
            return AgentOutput(
                claim_id=claim.claim_id,
                route=None,
                worksheet=None,
                review_flags=["pipeline_error"],
                citations=[],
                actions=self._actions(services.tool_log),
                rationales={},
                observed_claim_keys=_observed(claim),
                latency_s=time.perf_counter() - started,
                error=f"{type(e).__name__}: {e}",
            )
        elapsed = time.perf_counter() - started

        choices: dict[str, str] = dict(state.get("clause_choices") or {})
        admissibility = state.get("admissibility")
        citations = set(choices.values())
        if admissibility is not None:
            citations.update(getattr(admissibility, "clause_ids", []) or [])

        return AgentOutput(
            claim_id=claim.claim_id,
            route=self._route(state),
            worksheet=self._worksheet(state),
            review_flags=self._flags(state),
            citations=sorted(c for c in citations if c),
            actions=self._actions(services.tool_log),
            rationales={
                line_id: f"Line {line_id} was adjudicated under clause {clause_id}."
                for line_id, clause_id in sorted(choices.items())
            },
            observed_claim_keys=_observed(claim),
            latency_s=elapsed,
            status=str(state.get("status", "")),
        )
