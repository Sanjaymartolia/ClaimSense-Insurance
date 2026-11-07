"""Clause ids the agents refer to by name.

Taken from data/knowledge_base/policy_knowledge_base.jsonl (New India Arogya Sanjeevani,
UIN NIAHLIP25044V022425). TODO(day 1): confirm each id with the Domain lead / clause_review.xlsx,
and fill in the ones marked TODO. The agents never invent ids: the coverage analyst may only pick
from ids that policy-kb returned, and these constants are used for deterministic checks.
"""

P = "new_india_arogya_sanjeevani:"

HOSPITALISATION = P + "4.1"  # 4.1 a (room), b (ICU), c (doctors), d (OT, medicines, diagnostics)
OTHER_EXPENSES = P + "4.1.1"  # cataract sub-limit (a) + Note b: proportional deduction
ROOM_RENT_LIMIT = P + "12.1"  # table of benefits: 2% SI, max 5,000/day
ICU_LIMIT = P + "12.2"  # 5% SI, max 10,000/day (+ cataract row in the same chunk)
CO_PAY = P + "9.5"  # 5% on every claim
MATERNITY_EXCLUSION = P + "7.15"  # 7.15 Maternity Expenses (Code - Excl18): childbirth, caesarean

# Checked against the knowledge base 2026-11-07 (GOLD-07); still not_human_verified there.
INITIAL_WAITING_PERIOD = P + "6.3"  # First Thirty Days Waiting Period (Code- Excl03)
PED_WAITING_PERIOD = P + "6.1"  # Pre-Existing Diseases (Code- Excl01): 36 months
SPECIFIC_WAITING_PERIOD = P + "6.2"  # Specific Waiting Period (Excl02); list in 6.2.x
NON_PAYABLE_ITEMS = P + "annexure-a.list-i"  # Annexure-A List I: items not covered (ADR-0003)

# Note: the wording (4.1.1 Note b) applies the proportional cut to "all other expenses ... with
# the exception of cost of medicines". The data README says "room-linked charges". Agree ONE
# reading with the Domain lead and the calculator owner (T15) before day 3.
