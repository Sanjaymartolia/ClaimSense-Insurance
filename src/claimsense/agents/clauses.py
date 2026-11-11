"""Clause ids the agents refer to by name.

Taken from data/knowledge_base/policy_knowledge_base.jsonl (New India Arogya Sanjeevani,
UIN NIAHLIP25044V022425). TODO(day 1): confirm each id with the Domain lead / clause_review.xlsx,
and fill in the ones marked TODO. The agents never invent ids: the coverage analyst may only pick
from ids that policy-kb returned, and these constants are used for deterministic checks.
"""

P = "new_india_arogya_sanjeevani:"

HOSPITALISATION = P + "4.1"  # 4.1 a (room), b (ICU), c (doctors), d (OT, medicines, diagnostics)
OTHER_EXPENSES = P + "4.1.1"  # (a) cataract covered "subject to the sub limits" + Note b: prop. cut
# Cataract sub-limit itself: 25% SI or 40,000, whichever is lower, per eye per policy year.
# Confirmed with Knowledge & Memory 2026-11-11; table-of-benefits row is 12.3. Not yet used by the
# calculator (calc/adjudication.py PolicyRules note) or by reflexion/cases.py "sub_limit" (4.1.1).
CATARACT = P + "4.3"
ROOM_RENT_LIMIT = P + "12.1"  # table of benefits: 2% SI, max 5,000/day
ICU_LIMIT = P + "12.2"  # 5% SI, max 10,000/day
CO_PAY = P + "9.5"  # 5% on every claim
MATERNITY_EXCLUSION = P + "7.15"  # 7.15 Maternity Expenses (Code - Excl18): childbirth, caesarean
# Operative Clause: cover applies only "if during the policy period" an insured is hospitalised,
# and only for expenses incurred. Cited when the admission falls outside the period (A3, ADR-0008)
# and for an in-bill duplicate line, which is not a second expense (DEC-04, ADR-0009).
OPERATIVE = P + "2"
POLICY_PERIOD = OPERATIVE

# Checked against the knowledge base 2026-11-07 (GOLD-07); still not_human_verified there.
INITIAL_WAITING_PERIOD = P + "6.3"  # First Thirty Days Waiting Period (Code- Excl03)
PED_WAITING_PERIOD = P + "6.1"  # Pre-Existing Diseases (Code- Excl01): 36 months
SPECIFIC_WAITING_PERIOD = P + "6.2"  # Specific Waiting Period (Excl02); list in 6.2.x
NON_PAYABLE_ITEMS = P + "annexure-a.list-i"  # Annexure-A List I: items not covered (ADR-0003)

# Claim-level rulings: each deducts a line in full. Only the admissibility gate applies them (to
# every line, ADR-0010); the coverage analyst may never pick one for a single line.
CLAIM_LEVEL = frozenset(
    {
        POLICY_PERIOD,
        INITIAL_WAITING_PERIOD,
        PED_WAITING_PERIOD,
        SPECIFIC_WAITING_PERIOD,
        MATERNITY_EXCLUSION,
    }
)

# Note: the wording (4.1.1 Note b) applies the proportional cut to "all other expenses ... with
# the exception of cost of medicines". The data README says "room-linked charges". Agree ONE
# reading with the Domain lead and the calculator owner (T15) before day 3.
