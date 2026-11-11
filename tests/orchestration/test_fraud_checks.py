"""B5 / AGT-03: the fraud analyst catches a line billed twice inside one bill.

A duplicate is a flag for a person, never an amount change (fraud flags route; DEC-04 decides
how a duplicate is deducted). The message starts "duplicate bill lines", the template the eval
adapter maps to the gold `duplicate_bill` flag.
"""

import copy

from claimsense.agents.fraud import FraudAgent
from claimsense.contracts import Claim
from claimsense.reflexion.cases import load_cases, stub_services_factory

from .conftest import room_breach_packet

DUPLICATE_SCENARIOS = {"CLM-0005", "CLM-0009", "CLM-0010", "CLM-0015"}


def _claim(mutate=None) -> Claim:
    raw = copy.deepcopy(room_breach_packet()["claim"])
    if mutate:
        mutate(raw["bill_lines"])
    return Claim.model_validate(raw)


def _dup_flags(services, claim):
    return [f for f in FraudAgent(services).run(claim) if f.startswith("duplicate bill lines")]


def _repeat(lines, i=1, **over):
    lines.append({**lines[i], "line_id": "L9", **over})


def test_a_line_billed_twice_is_flagged_with_both_ids(services):
    flags = _dup_flags(services, _claim(lambda ls: _repeat(ls)))
    assert len(flags) == 1
    assert "L9" in flags[0] and "L2" in flags[0]


def test_case_and_spacing_do_not_hide_a_duplicate(services):
    def mutate(ls):
        _repeat(ls, description="  SURGEON   fees ")

    assert _dup_flags(services, _claim(mutate))


def test_same_description_different_amount_is_not_a_duplicate(services):
    assert not _dup_flags(services, _claim(lambda ls: _repeat(ls, amount="15001.00")))


def test_same_amount_different_description_is_not_a_duplicate(services):
    assert not _dup_flags(services, _claim(lambda ls: _repeat(ls, description="Anaesthetist")))


def test_the_flag_never_changes_an_amount(services):
    claim = _claim(lambda ls: _repeat(ls))
    before = claim.model_dump()
    FraudAgent(services).run(claim)
    assert claim.model_dump() == before


def test_dev_set_duplicates_are_caught_and_nothing_else():
    """Every admissible duplicate-bill dev claim is flagged; no other dev claim is."""
    factory = stub_services_factory()
    flagged = set()
    for case in load_cases("eval/golden_dev"):
        claim = Claim.model_validate(case.packet["claim"])
        if _dup_flags(factory(case), claim):
            flagged.add(case.case_id)
    # CLM-0003 also repeats a line; it fails the 30-day wait, but the check itself still sees it.
    assert flagged == DUPLICATE_SCENARIOS | {"CLM-0003"}
