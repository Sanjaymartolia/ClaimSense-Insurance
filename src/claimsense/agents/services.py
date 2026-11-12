"""The tools the agents use, behind one injectable object.

`Services` is the seam between your code and your teammates' code:

| field            | real implementation (owner)                         | stub here            |
|------------------|-----------------------------------------------------|----------------------|
| policy_search    | policy-kb MCP: hybrid search + rerank (Knowledge)   | keyword table        |
| get_clause       | policy-kb MCP (Knowledge)                           | small dict           |
| calculate        | claimsense.calc.adjudicate (Tools & Security, T15)  | reference_calculate  |
| tariff_range     | tariff MCP (Tools & Security)                       | dict                 |
| get_policy       | claims-db MCP (Tools & Security)                    | dict                 |
| claim_history    | claims-db / memory store (Knowledge & Memory)       | in-memory list       |
| settle_claim     | claims-db MCP, behind the approval gate (T&S)       | verifies tokens      |
| record_history   | memory store (Knowledge & Memory)                   | in-memory list       |

Day 3 job: write `real_services()` by swapping stub callables for MCP client calls. Nothing in
graph/ or agents/ should change when you do.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from pydantic import BaseModel, Field

from claimsense.contracts import (
    ApprovalLevel,
    ApprovalToken,
    Claim,
    Clause,
    Deduction,
    DeductionReason,
    LineCategory,
    RetrievedPassage,
    Worksheet,
    WorksheetLine,
)

from . import clauses as C

PAISE = Decimal("0.01")


def rupees(x: Decimal) -> Decimal:
    return x.quantize(PAISE, rounding=ROUND_HALF_UP)


class PolicyInfo(BaseModel):
    policy_number: str
    period_start: date
    period_end: date
    first_inception: date  # waiting periods run from here, not from this year's renewal
    sum_insured: Decimal
    insured_pseudonym: str
    declared_peds: list[str] = Field(default_factory=list)
    city_tier: str = "tier_1"


class PastClaim(BaseModel):
    claim_id: str
    policy_number: str
    bill_fingerprints: list[str]
    sub_limits_used: dict[str, Decimal] = Field(default_factory=dict)  # e.g. {"cataract": 30000}
    admission_date: date


def in_bill_duplicates(claim: Claim) -> dict[str, str]:
    """{repeat line_id: first line_id} for lines billed twice inside one bill: same category, same
    description (case and spacing ignored), same amount (B5 / DEC-04, ADR-0009). The fraud agent
    flags them and the calculators deduct them, so both must use this one rule."""
    first_seen: dict[tuple, str] = {}
    repeats: dict[str, str] = {}
    for line in claim.bill_lines:
        key = (line.category, " ".join(line.description.lower().split()), line.amount)
        if key in first_seen:
            repeats[line.line_id] = first_seen[key]
        else:
            first_seen[key] = line.line_id
    return repeats


def line_fingerprint(claim: Claim, line_desc: str, amount: Decimal) -> str:
    """Stable id for 'the same bill line submitted again' (duplicate-bill check)."""
    key = f"{claim.policy_number}|{claim.admission_date}|{line_desc.strip().lower()}|{amount}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


@dataclass
class Services:
    policy_search: Callable[..., list[RetrievedPassage]]
    get_clause: Callable[..., Clause | None]
    calculate: Callable[..., Worksheet]
    tariff_range: Callable[..., tuple[Decimal, Decimal] | None]
    get_policy: Callable[..., PolicyInfo | None]
    claim_history: Callable[..., list[PastClaim]]
    settle_claim: Callable[..., dict[str, Any]]
    record_repudiation: Callable[..., dict[str, Any]]
    record_history: Callable[..., None]
    senior_threshold: Decimal = Decimal("100000")  # TODO: agree with the domain lead
    tool_log: list = field(default_factory=list)

    def registry(self) -> dict[str, Callable[..., Any]]:
        return {
            "policy_search": self.policy_search,
            "get_clause": self.get_clause,
            "calculate": self.calculate,
            "tariff_range": self.tariff_range,
            "get_policy": self.get_policy,
            "claim_history": self.claim_history,
            "settle_claim": self.settle_claim,
            "record_repudiation": self.record_repudiation,
        }


# --------------------------------------------------------------------------------------------
# Reference calculator: DEV ONLY, so the graph runs before T15 lands. Implements the demo ruleset
# from data/README.md as amended by ADR-0006/0009. Delete once claimsense.calc.adjudicate passes
# its tests.
# --------------------------------------------------------------------------------------------

#: Room, boarding and nursing share one all-inclusive daily cap (clause 4.1(a), row 12.1; DEC-01).
ROOM_TIER = {LineCategory.ROOM, LineCategory.NURSING}
#: "All other expenses" that Note 4.1.1(b) cuts after a room or ICU breach. Medicines never are.
LINKED = {
    LineCategory.DOCTOR_FEES,
    LineCategory.OT,
    LineCategory.INVESTIGATIONS,
    LineCategory.PROCEDURE,
    LineCategory.OTHER,
}
FULLY_DEDUCTED = {
    C.NON_PAYABLE_ITEMS: DeductionReason.NON_PAYABLE,
    C.INITIAL_WAITING_PERIOD: DeductionReason.WAITING_PERIOD,
    C.PED_WAITING_PERIOD: DeductionReason.WAITING_PERIOD,
    C.SPECIFIC_WAITING_PERIOD: DeductionReason.WAITING_PERIOD,
    # Claim-level rulings the admissibility gate applies to every line (ADR-0010).
    C.MATERNITY_EXCLUSION: DeductionReason.EXCLUSION,
    C.POLICY_PERIOD: DeductionReason.OTHER,
}


def reference_calculate(
    claim: Claim, clause_choices: dict[str, str], version: int = 1, fraud_flags=None, **_
) -> Worksheet:
    si = claim.sum_insured
    room_cap = min(si * Decimal("0.02"), Decimal("5000"))
    icu_cap = min(si * Decimal("0.05"), Decimal("10000"))
    repeats = in_bill_duplicates(claim)  # DEC-04: never counted towards any rate
    counted = [x for x in claim.bill_lines if x.line_id not in repeats]

    # DEC-01: room + nursing per ward day against one cap. Ward days come from the room line(s).
    ward_days = sum(
        (Decimal(x.days or claim.nights or 1) for x in counted if x.category == LineCategory.ROOM),
        Decimal(0),
    )
    ward_total = sum((x.amount for x in counted if x.category in ROOM_TIER), Decimal(0))
    room_ratio = Decimal("1")
    if ward_days and ward_total / ward_days > room_cap:
        room_ratio = room_cap / (ward_total / ward_days)
    ratio = room_ratio  # Note 4.1.1(b): the lower of the room and ICU ratios (CLM-0016 ruling)
    for line in counted:
        days = Decimal(line.days or claim.nights or 1)
        if line.category == LineCategory.ICU and line.amount / days > icu_cap:
            ratio = min(ratio, icu_cap / (line.amount / days))

    out: list[WorksheetLine] = []
    for line in claim.bill_lines:
        chosen = clause_choices.get(line.line_id, C.HOSPITALISATION)
        deds: list[Deduction] = []
        days = Decimal(line.days or claim.nights or 1)
        if line.line_id in repeats:
            deds.append(
                Deduction(
                    reason=DeductionReason.OTHER,
                    amount=line.amount,
                    clause_id=C.OPERATIVE,
                    explanation=f"Repeats {repeats[line.line_id]} in the same bill: only "
                    "expenses incurred are indemnified. A person can restore it if genuine.",
                )
            )
        elif chosen in FULLY_DEDUCTED:
            deds.append(
                Deduction(
                    reason=FULLY_DEDUCTED[chosen],
                    amount=line.amount,
                    clause_id=chosen,
                    explanation="Not payable under this clause.",
                )
            )
        elif line.category in ROOM_TIER and room_ratio < 1:
            amt = rupees(line.amount * (1 - room_ratio))
            deds.append(
                Deduction(
                    reason=DeductionReason.ROOM_RENT_CAP,
                    amount=amt,
                    clause_id=C.ROOM_RENT_LIMIT,
                    explanation=f"Room, boarding and nursing capped together at Rs "
                    f"{rupees(room_cap)}/day x {ward_days}; factor {room_ratio:.4f}.",
                )
            )
        elif line.category == LineCategory.ICU and line.amount > icu_cap * days:
            amt = rupees(line.amount - icu_cap * days)
            deds.append(
                Deduction(
                    reason=DeductionReason.ICU_CAP,
                    amount=amt,
                    clause_id=C.ICU_LIMIT,
                    explanation=f"ICU capped at Rs {rupees(icu_cap)}/day x {days}.",
                )
            )
        elif line.category in LINKED and ratio < 1:
            amt = rupees(line.amount * (1 - ratio))
            deds.append(
                Deduction(
                    reason=DeductionReason.PROPORTIONAL_CUT,
                    amount=amt,
                    clause_id=C.OTHER_EXPENSES,
                    explanation=f"Proportional cut, factor {ratio:.4f}.",
                )
            )
        payable = line.amount - sum((d.amount for d in deds), Decimal("0"))
        out.append(
            WorksheetLine(
                line_id=line.line_id, claimed=line.amount, deductions=deds, payable=payable
            )
        )

    gross = sum((l.payable for l in out), Decimal("0"))
    co = rupees(gross * Decimal("0.05"))
    co_pay = (
        Deduction(
            reason=DeductionReason.CO_PAY,
            amount=co,
            clause_id=C.CO_PAY,
            explanation="5% co-pay on the admissible amount.",
        )
        if co > 0
        else None
    )
    return Worksheet(
        claim_id=claim.claim_id,
        version=version,
        lines=out,
        co_pay=co_pay,
        total_claimed=sum((l.claimed for l in out), Decimal("0")),
        total_payable=gross - co,
        fraud_flags=list(fraud_flags or []),
    )


def real_calculate(
    claim: Claim, clause_choices: dict[str, str], version: int = 1, fraud_flags=None, **_
) -> Worksheet:
    """Adapter onto the team calculator (T15). Swap it into Services.calculate on day 3."""
    from claimsense.calc.adjudication import PolicyRules, adjudicate

    ws = adjudicate(claim, clause_choices, PolicyRules())
    # version / flags don't change any amount, so copying them on is safe
    return ws.model_copy(update={"version": version, "fraud_flags": list(fraud_flags or [])})


def real_services(*, check: bool = True) -> Services:
    """Services bound to the teammates' plain-Python tool callables (no stubs left).

    Imports are lazy so the stub path and the unit tests never need retrieval or MCP deps.
    settle_claim / record_repudiation verify approvals against claims_db.get_db().approval_store,
    so the review gate must issue tokens into that same store (see graph/build.py).

    L15 tool pinning: with check=True (the default) a tool whose name, description or arguments
    changed since review does not load (`hooks.pins`, `config/tool_pins.json`).
    """
    from claimsense.mcp_servers import approvals, claims_db, policy_kb, tariff

    services = Services(
        policy_search=policy_kb.policy_search,
        get_clause=policy_kb.get_clause,
        calculate=real_calculate,
        tariff_range=tariff.tariff_range,
        get_policy=claims_db.get_policy,
        claim_history=claims_db.claim_history,
        settle_claim=claims_db.settle_claim,
        record_repudiation=claims_db.record_repudiation,
        record_history=claims_db.record_history,
        senior_threshold=approvals.senior_threshold_inr(),
    )
    if check:
        from claimsense.hooks.pins import check_pins

        check_pins(services.registry())
    return services


# --------------------------------------------------------------------------------------------
# Stub services
# --------------------------------------------------------------------------------------------

_CLAUSE_TEXT = {
    C.HOSPITALISATION: "4.1 Hospitalization ... room rent, ICU, surgeon fees, OT, medicines, diagnostics",
    C.OTHER_EXPENSES: "4.1.1 Note b: if room/ICU rate exceeds the limits, all other expenses except "
    "medicines are paid in the same proportion (proportional deduction).",
    C.ROOM_RENT_LIMIT: "Room rent, boarding, nursing up to 2% of sum insured, max Rs 5000 per day.",
    C.ICU_LIMIT: "ICU charges up to 5% of sum insured, max Rs 10,000 per day.",
    C.CO_PAY: "9.5 Co-payment of 5% on each and every claim.",
    C.NON_PAYABLE_ITEMS: "List of excluded items: consumables such as gloves, masks are not payable.",
    C.INITIAL_WAITING_PERIOD: "30-day initial waiting period from first policy inception.",
    C.PED_WAITING_PERIOD: "Pre-existing disease waiting period.",
    C.SPECIFIC_WAITING_PERIOD: "Specified illness waiting period of 24/36 months.",
    C.POLICY_PERIOD: "2 Operative clause: if during the policy period an insured person is "
    "hospitalized, the Company shall indemnify medically necessary expenses.",
}


def stub_clause(clause_id: str, text: str) -> Clause:
    """A Clause with placeholder metadata, for stubs and tests only."""
    return Clause(
        clause_id=clause_id,
        policy_name="Arogya Sanjeevani",
        insurer="The New India Assurance Co. Ltd.",
        section=clause_id.split(":")[-1],
        text=text,
        effective_date=date(2025, 3, 1),
        source_url="data/policy/new_india/policy_wording.pdf",
    )


_SEARCH = {
    LineCategory.ROOM: [C.ROOM_RENT_LIMIT, C.HOSPITALISATION],
    LineCategory.ICU: [C.ICU_LIMIT, C.HOSPITALISATION],
    LineCategory.CONSUMABLES: [C.NON_PAYABLE_ITEMS, C.HOSPITALISATION],
}


def make_stub_services(
    policies: dict[str, PolicyInfo] | None = None,
    history: dict[str, list[PastClaim]] | None = None,
    tariffs: dict[str, tuple[Decimal, Decimal]] | None = None,
) -> Services:
    policies = dict(policies or {})
    history = {k: list(v) for k, v in (history or {}).items()}
    tariffs = dict(tariffs or {})
    settled: list[dict] = []

    def policy_search(query: str, category: str | None = None, k: int = 5):
        ids = _SEARCH.get(
            LineCategory(category) if category else None, [C.HOSPITALISATION, C.OTHER_EXPENSES]
        )
        return [
            RetrievedPassage(clause=stub_clause(i, _CLAUSE_TEXT[i]), score=1.0 - n / 10, rank=n + 1)
            for n, i in enumerate(ids[:k])
        ]

    def get_clause(clause_id: str):
        text = _CLAUSE_TEXT.get(clause_id)
        return stub_clause(clause_id, text) if text else None

    def settle_claim(
        claim_id: str, worksheet: Worksheet, approvals: list[ApprovalToken], needs_senior: bool
    ):
        # The real tool (T&S) must do exactly these checks server-side.
        if not any(
            a.level == ApprovalLevel.ADJUDICATOR and a.is_valid_for(worksheet) for a in approvals
        ):
            raise PermissionError("no valid adjudicator approval for this worksheet version")
        if needs_senior and not any(
            a.level == ApprovalLevel.SENIOR and a.is_valid_for(worksheet) for a in approvals
        ):
            raise PermissionError("senior approval required")
        rec = {
            "claim_id": claim_id,
            "amount": str(worksheet.total_payable),
            "worksheet_hash": worksheet.content_hash(),
        }
        settled.append(rec)
        return {"status": "settled", **rec}

    def record_repudiation(claim_id: str, reasons: list[str], approvals: list[ApprovalToken]):
        if not approvals:
            raise PermissionError("repudiation needs an adjudicator decision")
        settled.append({"claim_id": claim_id, "repudiated": reasons})
        return {"status": "repudiated", "claim_id": claim_id}

    def record_history(claim: Claim, worksheet: Worksheet | None):
        fps = [line_fingerprint(claim, l.description, l.amount) for l in claim.bill_lines]
        history.setdefault(claim.policy_number, []).append(
            PastClaim(
                claim_id=claim.claim_id,
                policy_number=claim.policy_number,
                bill_fingerprints=fps,
                admission_date=claim.admission_date,
            )
        )

    svc = Services(
        policy_search=policy_search,
        get_clause=get_clause,
        calculate=reference_calculate,
        tariff_range=lambda procedure, city_tier="tier_1": tariffs.get(procedure),
        get_policy=lambda policy_number: policies.get(policy_number),
        claim_history=lambda policy_number: list(history.get(policy_number, [])),
        settle_claim=settle_claim,
        record_repudiation=record_repudiation,
        record_history=record_history,
    )
    svc.settled = settled  # type: ignore[attr-defined]  (handy in tests)
    return svc
