"""Hand-worked cases for the calculator (T15).

Write each expected amount BY HAND from the downloaded policy wording before implementing,
and put the clause number in the test name or comment. Remove the skip marker when you start T15.
"""

import pytest

pytestmark = pytest.mark.skip(reason="T15: add hand-worked cases, then implement calc")


def test_room_rent_limit_is_lower_of_pct_and_cap():
    # e.g. SI 3,00,000 -> 2% = 6,000/day, capped at 5,000/day. Clause: <fill in>
    ...


def test_proportional_cut_on_linked_charges_after_room_breach():
    # Room 7,000/day vs eligible 5,000/day -> ratio 5/7 applied to linked charges. Clause: <fill in>
    ...


def test_co_pay_applies_after_all_other_deductions():
    # Confirm order of operations from the wording. Clause: <fill in>
    ...
