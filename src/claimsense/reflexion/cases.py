"""Load the development golden set (`eval/golden_dev/`) into `DevCase` objects (plan, day 4).

The starter-pack JSON predates the shared contracts and does not match them (CLAUDE.md names this
as the open ADR-0002 gap): bill-line categories use different names, there are no source spans,
and the gold worksheet records reason codes rather than clause ids. This module is the one place
where that mapping lives, so nothing in `evaluator.py`, `contracts/` or `eval/` has to change.

Three rules, all checked rather than assumed:
- An unknown category or reason code raises. A silent default here would score the wrong thing.
- The gold `Worksheet` is rebuilt line by line and must pass the contract's own arithmetic
  validators; if the gold file does not add up, loading fails loudly.
- `scenario_label` and `fixture_notes` never enter the packet. They are evaluation-only.

Known disagreements between the demo-rule gold and the reference calculator are listed in
`RULE_DISAGREEMENTS` and reported, not papered over.

Gold-set history this loader follows: the 2026-11-04 audit (`docs/CLAIMS_AND_GOLD_SET_FIXES.md`)
relabelled CLM-0018 (clause 7.15 exclusion, new reason code `maternity_childbirth_exclusion`),
re-filed CLM-0016's ICU line (`icu_daily_cap`) and added `clause_id` to most gold deductions. The
reason-code tables below stay the source of truth for the clause a gold deduction is taken to
cite; the gold's own `clause_id` is coarser (`4.1` for both caps). ADR-0006 (2026-11-11) moved
the proportional cut to Note 4.1.1(b). ADR-0007 added `first_policy_inception_date`,
`history.prior_claims` and the `cataract_sub_limit` / `specific_illness_waiting_period` codes.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from claimsense.agents import PastClaim, PolicyInfo, Services, make_stub_services
from claimsense.agents import clauses as C
from claimsense.contracts import (
    Deduction,
    DeductionReason,
    LineCategory,
    RoomCategory,
    Worksheet,
    WorksheetLine,
)

from .evaluator import DevCase

# ------------------------------------------------------------------ starter pack -> contracts

#: starter-pack `category` -> `contracts.LineCategory`. `pharmacy` lines are described as
#: "Medicines and consumables"; the contract's CONSUMABLES means non-payable disposables, so the
#: payable medicines reading is the right one. `non_payable` is the comfort-kit line.
CATEGORY_MAP: dict[str, LineCategory] = {
    "room_rent": LineCategory.ROOM,
    "icu": LineCategory.ICU,
    "nursing": LineCategory.NURSING,
    "doctor_fees": LineCategory.DOCTOR_FEES,
    "ot": LineCategory.OT,
    "pharmacy": LineCategory.MEDICINES,
    "diagnostics": LineCategory.INVESTIGATIONS,
    "procedure": LineCategory.PROCEDURE,
    "non_payable": LineCategory.CONSUMABLES,
}

#: gold line-level reason code -> (deduction reason, clause id the gold is taken to cite).
#: `duplicate_line` has no policy clause: it is a fraud finding, so it gets a marker id and is
#: left out of the gold clause choices (a human catches it; no clause choice "fixes" it).
#: `sub_limit` is a generic demo-rule code that no gold line carries today. The cataract limit
#: (clause 4.3) has its own code, `cataract_sub_limit`, used by CLM-0021/0022 (GOLD-05, ADR-0007).
LINE_REASONS: dict[str, tuple[DeductionReason, str]] = {
    "room_rent_daily_cap": (DeductionReason.ROOM_RENT_CAP, C.ROOM_RENT_LIMIT),
    "icu_daily_cap": (DeductionReason.ICU_CAP, C.ICU_LIMIT),
    "room_rent_proportional_reduction": (DeductionReason.PROPORTIONAL_CUT, C.OTHER_EXPENSES),
    "non_payable_item_demo_rule": (DeductionReason.NON_PAYABLE, C.NON_PAYABLE_ITEMS),
    "sub_limit": (DeductionReason.SUB_LIMIT, C.OTHER_EXPENSES),
    "cataract_sub_limit": (DeductionReason.SUB_LIMIT, C.CATARACT),
    "duplicate_line": (DeductionReason.OTHER, "fraud:duplicate_line"),
}
NO_CLAUSE_CHOICE = {"duplicate_line"}

#: Clause 7.15, maternity / childbirth exclusion. The gold-set audit of 2026-11-04 (GOLD-01)
#: relabelled CLM-0018 with it; `agents/clauses.py` defines the id, re-exported here for the tests.
MATERNITY_EXCLUSION = C.MATERNITY_EXCLUSION

#: gold claim-level reason code -> deduction applied to every line through the admissibility gate.
#: An out-of-period admission cites clause 2 (`C.POLICY_PERIOD`), like `check_admissibility` (A3).
CLAIM_REASONS: dict[str, tuple[DeductionReason, str]] = {
    "initial_waiting_period_not_elapsed": (
        DeductionReason.WAITING_PERIOD,
        C.INITIAL_WAITING_PERIOD,
    ),
    "pre_existing_disease_waiting_period": (DeductionReason.WAITING_PERIOD, C.PED_WAITING_PERIOD),
    "specific_illness_waiting_period": (DeductionReason.WAITING_PERIOD, C.SPECIFIC_WAITING_PERIOD),
    "admission_or_discharge_outside_policy_period": (DeductionReason.EXCLUSION, C.POLICY_PERIOD),
    "maternity_childbirth_exclusion": (DeductionReason.EXCLUSION, MATERNITY_EXCLUSION),
}
ADMISSIBILITY_GATE = "claim_level_admissibility_gate"

#: Where the demo-rule gold and the reference calculator are known to disagree. Each one shows up
#: as a baseline error that no playbook lesson can remove, so the report must say so.
RULE_DISAGREEMENTS = [
    "Gold deducts an in-bill duplicate line in full (duplicate_line); the fraud agent only "
    "checks claim history and a fraud flag never changes an amount. CLM-0005, 0009, 0010, 0015. "
    "Decision (lead, Nov 2026 walkthrough): a duplicate stays a fraud flag for the human "
    "adjudicator; no clause pays it at zero.",
    "Gold rounds each cut line to whole rupees; the calculator keeps paise. Cut lines differ by up "
    "to Rs 0.50 and count as a miss unless the evaluator is run with a tolerance "
    "(--tolerance-rs). ADR-0007 (GOLD-08): the gold stays in rupees; the eval harness defaults to "
    "a Rs 1 tolerance, the Reflexion evaluator keeps it explicit.",
    "Gold (2026-11-04 audit, GOLD-04) caps CLM-0016's ICU day at Rs 10,000 but applies no "
    "proportional cut to the other lines because the room rent itself is within its cap; the "
    "calculator applies clause 4.1.1 Note (b) to an ICU breach as well, so it cuts investigations "
    "and nursing. Both cap the ICU line identically. Needs a domain ruling: does Note (b) follow "
    "an ICU breach or only a room-rent breach?",
    "Gold (ADR-0007, GOLD-03) repudiates CLM-0008 under the 24-month specific wait (clause "
    "6.2.18, urinary calculi, first policy); the admissibility check has no 6.2 list yet "
    "(AGT-02), so the pipeline pays it.",
    "Gold (ADR-0007, GOLD-05) caps cataract treatment at clause 4.3 (CLM-0021) and at the part an "
    "earlier claim left unused (CLM-0022); the calculator does not apply 4.3 because the claim "
    "contract carries no treated eye (calc.adjudication.INFORMATIONAL_SUB_LIMITS).",
]


# ------------------------------------------------------------------ one fixture -> packet


def _room_category(description: str) -> RoomCategory:
    d = description.lower()
    if "icu" in d:
        return RoomCategory.ICU
    if "private" in d or "single" in d or "deluxe" in d:
        return RoomCategory.SINGLE_PRIVATE
    if "shared" in d or "twin" in d or "semi" in d:
        return RoomCategory.SHARED
    return RoomCategory.GENERAL_WARD


def _category(raw: str, line_id: str) -> LineCategory:
    try:
        return CATEGORY_MAP[raw]
    except KeyError as e:
        raise ValueError(
            f"{line_id}: unmapped bill-line category {raw!r}; add it to CATEGORY_MAP"
        ) from e


def packet_from_fixture(fx: dict[str, Any]) -> dict[str, Any]:
    """`{"claim_id", "claim": {...}, "documents": {}, "fixture_policy": {...}}`.

    `documents` is empty on purpose: the fixture's `synthetic_text` is a placeholder sentence, not
    a bill, so span verification against it would flag every line. The plan allows extraction to
    stay on hand-extracted fixtures. `fixture_policy` is what claims-db would return for this
    policy; the extraction agent ignores it.
    """
    bill_doc = next(
        (d["document_id"] for d in fx.get("documents", []) if d.get("type") == "itemized_bill"),
        f"{fx['claim_id']}-bill",
    )
    room_lines = [b for b in fx["bill_lines"] if b["category"] in ("room_rent", "icu")]
    proc_lines = [b for b in fx["bill_lines"] if b["category"] == "procedure"]
    lines = []
    for b in fx["bill_lines"]:
        cat = _category(b["category"], b["line_id"])
        desc = b["description"]
        lines.append(
            {
                "line_id": b["line_id"],
                "description": desc,
                "category": cat.value,
                "amount": str(b["amount_inr"]),
                "quantity": str(b.get("quantity", 1)),
                "days": int(b["quantity"])
                if cat in (LineCategory.ROOM, LineCategory.ICU)
                else None,
                "source": {"document": bill_doc, "start": 0, "end": len(desc), "text": desc},
            }
        )
    h, p = fx["hospitalisation"], fx["policy"]
    claim = {
        "claim_id": fx["claim_id"],
        "policy_number": p["policy_id"],
        "patient_pseudonym": fx["policyholder"]["synthetic_person_id"],
        "admission_date": h["admission_date"],
        "discharge_date": h["discharge_date"],
        "diagnosis": h["diagnosis"],
        "procedure": proc_lines[0]["description"] if proc_lines else None,
        "room_category": _room_category(room_lines[0]["description"]).value
        if room_lines
        else RoomCategory.GENERAL_WARD.value,
        "sum_insured": str(p["sum_insured_inr"]),
        "bill_lines": lines,
        "bill_total": str(fx["bill_total_inr"]),
    }
    return {
        "claim_id": fx["claim_id"],
        "claim": claim,
        "documents": {},
        "fixture_policy": policy_from_fixture(fx).model_dump(mode="json"),
        "fixture_history": [p.model_dump(mode="json") for p in history_from_fixture(fx)],
    }


def policy_from_fixture(fx: dict[str, Any]) -> PolicyInfo:
    """Waiting periods run from `first_policy_inception_date` (ADR-0007, GOLD-03). Fixtures made
    before that field existed (the held-out set) fall back to the policy start, the old demo
    assumption that every claim is on a first policy."""
    p, h = fx["policy"], fx["hospitalisation"]
    return PolicyInfo(
        policy_number=p["policy_id"],
        period_start=date.fromisoformat(p["policy_start_date"]),
        period_end=date.fromisoformat(p["policy_end_date"]),
        first_inception=date.fromisoformat(
            p.get("first_policy_inception_date", p["policy_start_date"])
        ),
        sum_insured=Decimal(str(p["sum_insured_inr"])),
        insured_pseudonym=fx["policyholder"]["synthetic_person_id"],
        declared_peds=[h["diagnosis"]] if h.get("pre_existing_condition_declared") else [],
        city_tier=fx.get("hospital", {}).get("city_tier", "tier_1"),
    )


def history_from_fixture(fx: dict[str, Any]) -> list[PastClaim]:
    """`history.prior_claims` -> what claims-db would return for this policy (ADR-0007, GOLD-05).
    Each item: {claim_id, admission_date, sub_limits_used_inr: {clause_id: rupees}}. Earlier bills
    are not in the fixture, so there are no fingerprints to match duplicates against."""
    return [
        PastClaim(
            claim_id=pc["claim_id"],
            policy_number=fx["policy"]["policy_id"],
            bill_fingerprints=[],
            sub_limits_used={k: Decimal(str(v)) for k, v in pc["sub_limits_used_inr"].items()},
            admission_date=date.fromisoformat(pc["admission_date"]),
        )
        for pc in fx.get("history", {}).get("prior_claims", [])
    ]


# ------------------------------------------------------------------ one gold record -> Worksheet


def _line_deduction(
    li: dict[str, Any], claim_codes: list[str]
) -> tuple[Deduction | None, str | None]:
    """Returns (deduction or None, gold clause choice or None)."""
    amount = Decimal(str(li["deduction_before_copay_inr"]))
    codes = list(li.get("reason_codes", []))
    if amount == 0:
        return None, C.HOSPITALISATION
    if ADMISSIBILITY_GATE in codes:
        if not claim_codes:
            raise ValueError(
                f"{li['line_id']}: admissibility gate without a claim-level reason code"
            )
        reason, clause = _lookup(CLAIM_REASONS, claim_codes[0], li["line_id"])
        choice = clause
    else:
        reason, clause = _lookup(LINE_REASONS, codes[0], li["line_id"])
        choice = None if codes[0] in NO_CLAUSE_CHOICE else clause
    return Deduction(
        reason=reason,
        amount=amount,
        clause_id=clause,
        explanation=f"gold reason codes: {', '.join(codes)}",
    ), choice


def _lookup(table: dict, code: str, line_id: str) -> tuple[DeductionReason, str]:
    try:
        return table[code]
    except KeyError as e:
        raise ValueError(f"{line_id}: unmapped gold reason code {code!r}") from e


def gold_from_fixture(
    fx: dict[str, Any], gold: dict[str, Any]
) -> tuple[Worksheet, dict[str, str], bool]:
    """Returns (gold worksheet, gold clause choices, gold_admissible). The Worksheet validators
    check that every line and the totals add up; a gold file that does not reconcile fails here."""
    if gold["claim_id"] != fx["claim_id"]:
        raise ValueError(f"gold {gold['claim_id']} paired with claim {fx['claim_id']}")
    amounts = {b["line_id"]: Decimal(str(b["amount_inr"])) for b in fx["bill_lines"]}
    claim_codes = list(gold.get("reason_codes", []))
    lines, choices = [], {}
    for li in gold["line_items"]:
        ded, choice = _line_deduction(li, claim_codes)
        lines.append(
            WorksheetLine(
                line_id=li["line_id"],
                claimed=amounts[li["line_id"]],
                deductions=[ded] if ded else [],
                payable=Decimal(str(li["allowed_before_copay_inr"])),
            )
        )
        if choice:
            choices[li["line_id"]] = choice
    copay = Decimal(str(gold["copay_amount_inr"]))
    ws = Worksheet(
        claim_id=fx["claim_id"],
        version=1,
        lines=lines,
        co_pay=Deduction(
            reason=DeductionReason.CO_PAY,
            amount=copay,
            clause_id=C.CO_PAY,
            explanation="5% co-pay on the admissible amount.",
        )
        if copay > 0
        else None,
        total_claimed=sum(amounts.values(), Decimal(0)),
        total_payable=Decimal(str(gold["expected_settlement_inr"])),
    )
    return ws, choices, gold["expected_admissibility"] == "admissible"


# ------------------------------------------------------------------ the loader


def load_cases(
    directory: str | Path = "eval/golden_dev",
    split: str = "dev",
    claims_file: str = "claims.jsonl",
    gold_file: str = "gold_worksheets.jsonl",
) -> list[DevCase]:
    """Every claim must have exactly one gold record, and vice versa."""
    d = Path(directory)
    claims = [
        json.loads(line) for line in (d / claims_file).read_text().splitlines() if line.strip()
    ]
    golds = {
        g["claim_id"]: g
        for g in (
            json.loads(line) for line in (d / gold_file).read_text().splitlines() if line.strip()
        )
    }
    ids = [c["claim_id"] for c in claims]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate claim ids in " + str(d / claims_file))
    if set(ids) != set(golds):
        raise ValueError(
            f"claims and gold do not pair up: only-claims={sorted(set(ids) - set(golds))} "
            f"only-gold={sorted(set(golds) - set(ids))}"
        )
    cases = []
    for fx in claims:
        ws, choices, admissible = gold_from_fixture(fx, golds[fx["claim_id"]])
        cases.append(
            DevCase(
                case_id=fx["claim_id"],
                packet=packet_from_fixture(fx),
                gold_worksheet=ws,
                gold_clause_choices=choices,
                gold_admissible=admissible,
                split=split,
            )
        )
    return cases


def stub_services_factory(
    calculate: Callable[..., Worksheet] | None = None,
) -> Callable[[DevCase], Services]:
    """A `ServicesFactory` for `local_run_fn` / `langgraph_run_fn`: stub tools, with the policy
    record this case's fixture carries. Pass `calculate=real_calculate` once the team calculator
    (T15) passes its tests; nothing else changes."""

    def factory(case: DevCase) -> Services:
        pol = PolicyInfo.model_validate(case.packet["fixture_policy"])
        past = [PastClaim.model_validate(p) for p in case.packet.get("fixture_history", [])]
        svc = make_stub_services(
            policies={pol.policy_number: pol}, history={pol.policy_number: past} if past else None
        )
        if calculate is not None:
            svc.calculate = calculate
        return svc

    return factory


__all__ = [
    "CATEGORY_MAP",
    "CLAIM_REASONS",
    "LINE_REASONS",
    "RULE_DISAGREEMENTS",
    "gold_from_fixture",
    "history_from_fixture",
    "load_cases",
    "packet_from_fixture",
    "policy_from_fixture",
    "stub_services_factory",
]
