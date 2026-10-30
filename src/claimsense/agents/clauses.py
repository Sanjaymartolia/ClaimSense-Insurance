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

# TODO(day 1): look these up in the knowledge base and replace.
INITIAL_WAITING_PERIOD = P + "TODO-initial-30-day-waiting-period"
PED_WAITING_PERIOD = P + "TODO-pre-existing-disease-waiting-period"
SPECIFIC_WAITING_PERIOD = P + "TODO-24-36-month-specified-illness"
NON_PAYABLE_ITEMS = "excluded_items:TODO-annexure-item"  # List of excluded items PDF

# Note: the wording (4.1.1 Note b) applies the proportional cut to "all other expenses ... with
# the exception of cost of medicines". The data README says "room-linked charges". Agree ONE
# reading with the Domain lead and the calculator owner (T15) before day 3.
