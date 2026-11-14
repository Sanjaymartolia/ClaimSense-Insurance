"""Memory on and memory off (docs/memory-policy.md, section 4; capstone guide L9).

"On" is the fraud screen reading the real claims-db history; "off" is the same screen with an
empty history. Stub mode, synthetic claims, no model. A flag sends the claim to a person; it never
changes an amount.
"""

from datetime import date
from decimal import Decimal

from claimsense.agents import PastClaim, PolicyInfo, make_stub_services
from claimsense.agents.fraud import FraudAgent
from claimsense.contracts import Claim
from claimsense.reflexion.cases import load_cases

from .test_claim_history import make_claim, sub_limit_worksheet

DUPLICATE = "duplicate bill lines already claimed"
SUB_LIMIT = "sub-limits partly used earlier this policy year"


def no_memory(policy_number: str) -> list[PastClaim]:
    return []


def flags(claim: Claim, policy: PolicyInfo, history, kind: str) -> list[str]:
    services = make_stub_services(policies={policy.policy_number: policy})
    services.claim_history = history
    return [flag for flag in FraudAgent(services).run(claim) if flag.startswith(kind)]


def test_a_bill_sent_again_is_flagged_only_with_claim_history(db):
    cases = load_cases("eval/golden_dev")
    caught_on, caught_off, false_alarms = set(), set(), set()
    for case in cases:
        claim = Claim.model_validate(case.packet["claim"])
        policy = PolicyInfo.model_validate(case.packet["fixture_policy"])
        if flags(claim, policy, db.claim_history, DUPLICATE):
            false_alarms.add(case.case_id)  # a first submission: nothing to match yet

        db.record_history(claim)
        again = claim.model_copy(update={"claim_id": f"{claim.claim_id}-AGAIN"})
        if flags(again, policy, db.claim_history, DUPLICATE):
            caught_on.add(case.case_id)
        if flags(again, policy, no_memory, DUPLICATE):
            caught_off.add(case.case_id)

    assert cases
    assert caught_on == {case.case_id for case in cases}
    assert caught_off == set()
    assert false_alarms == set()


def test_earlier_sub_limit_use_is_flagged_only_with_claim_history(db):
    earlier = make_claim("CLM-T31-001", admitted=date(2026, 5, 10))
    db.record_history(earlier, sub_limit_worksheet(earlier))  # Rs 40,000 paid against the limit
    later = make_claim("CLM-T31-002", admitted=date(2026, 8, 1))
    policy = PolicyInfo(
        policy_number=later.policy_number,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 12, 31),
        first_inception=date(2024, 1, 1),
        sum_insured=Decimal("300000"),
        insured_pseudonym="PT-T31",
    )

    [on] = flags(later, policy, db.claim_history, SUB_LIMIT)
    assert "Rs 40000.00" in on
    assert flags(later, policy, no_memory, SUB_LIMIT) == []
