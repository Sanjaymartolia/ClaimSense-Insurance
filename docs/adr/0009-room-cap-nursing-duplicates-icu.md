# ADR-0009: Nursing inside the room cap, duplicates deducted, ICU breach cuts (DEC-01, DEC-04, CLM-0016)

**Status:** accepted
**Owner / layers:** @domain-lead (Domain & Product) — L7 calc rules, L13 eval gold. Calculator
owners must act: Agents & Orchestration (`agents/services.py::reference_calculate`, done) and
Tools & Security (`calc/adjudication.py`).
**Date:** 2026-11-11

## Context
Three questions from the 2026-11-03 audit were still open:
- **DEC-01:** does the ₹5,000/day room limit include nursing?
- **DEC-04:** how is an in-bill duplicate line deducted?
- **CLM-0016:** does an ICU breach trigger the Note 4.1.1(b) cut, and is its ICU day one of the 6
  nights?

The gold, the reference calculator and `calc/adjudication.py` all followed the demo ruleset, which
caps the room line alone. On duplicates, the gold paid the line at ₹0 with no clause, while the
code paid it.

Wording relied on:
- **4.1(a)**: "Room Rent, Boarding, Nursing Expenses … up to 2% of the sum insured subject to
  maximum of Rs.5000/- per day."
- **12.1** (table of benefits): the same, "**all inclusive**".
- **Note 4.1.1(b)**: "In case of admission to a room/**ICU/ICCU** at rates exceeding the aforesaid
  limits, … all other expenses …, with the exception of cost of medicines, shall be effected in the
  same proportion as the admissible rate per day bears to the actual rate per day …"
- **2, the Operative Clause**: the Company indemnifies medically necessary expenses *incurred*.

## Decision

### DEC-01: reading A, nursing inside the all-inclusive room cap
- **Ward rate per day** = (room + boarding + nursing) ÷ ward days, where ward days come from the
  room line's days.
- **Room ratio** = min(1, cap ÷ ward rate), with cap = min(2% of sum insured, ₹5,000).
- When the ward rate exceeds the cap, the room and nursing lines are each paid × room ratio. That
  caps them together at cap × days. Both carry reason `room_rent_daily_cap`, clause 12.1 (the gold
  coarsely files it as 4.1, as before).
- The same ratio drives the Note 4.1.1(b) cut on the other expenses. Medicines are never cut.

### DEC-04: deduct the duplicate, citing clause 2
- A line with the same category, description (case and spacing ignored) and amount as an earlier
  line in the same bill is deducted in full. Reason `other`, clause `…:2`, because a repeat is not
  a second expense incurred.
- It is left out of every rate calculation, so a repeated nursing line can't create a false
  breach.
- The fraud flag (B5) still sends the claim to a person, who can restore a genuine repeat, such as
  two identical visits, through the edit path.
- One rule, one helper: `agents/services.py::in_bill_duplicates`, used by the fraud agent and the
  calculators.
- **This deliberately ends "fraud flags never change amounts" for this one case.** The
  deduction is a calculator rule, not a flag, and a person still approves it.

### CLM-0016: an ICU breach cuts too; the ICU day is one of the 6 nights
- **ICU breach.** An ICU rate above min(5% SI, ₹10,000)/day caps the ICU line and triggers the
  Note 4.1.1(b) cut on the other expenses. When both room and ICU breach, the lower ratio applies.
  **Implementation reading:** ward room and nursing that are already inside their own cap are not
  cut again by the ICU ratio.
- **The overlapping day.** The fixture now bills 5 ward nights and 5 days of ward nursing, plus the
  ICU day: 6 nights in all, matching the 2026-07-17 → 2026-07-23 stay. ICU charges are
  all-inclusive, so ICU-day nursing is not billed separately.

## Worked example (hand-checked): CLM-0004
SI ₹10,00,000, so the cap is ₹5,000/day. 3 nights.

**Ward rate.** Room 24,000 + nursing 6,312 = 30,312, ÷ 3 = ₹10,104/day.

**Room ratio** = 5,000 / 10,104 = 0.49485.

| Line | Billed | Paid |
|---|---|---|
| Room + nursing | 30,312 | 15,000 (= 5,000 × 3) |
| Procedure | 74,726 | 36,979 |
| Diagnostics | 7,573 | 3,748 |
| Medicines (not cut) | 14,871 | 14,871 |
| **Total before co-pay** | | **70,598** |

Co-pay 5% = 3,530. **Settlement ₹67,067**, against ₹80,990 under ADR-0006.

## Consequences
**Dev gold.** All 14 paid dev claims are recomputed by an independent script (ADR-0007 style). Every
one except the two cataract claims is now a room breach and carries `room_rent_breach`:

| Claim | Before | After |
|---|---|---|
| CLM-0004 | ₹80,990 | ₹67,067 |
| CLM-0005 | ₹96,660 | ₹76,886 |
| CLM-0006 | ₹71,374 | ₹59,141 |
| CLM-0009 | ₹73,664 | ₹56,078 |
| CLM-0010 | ₹141,867 | ₹107,539 |
| CLM-0011 | ₹57,184 | ₹44,048 |
| CLM-0012 | ₹67,575 | ₹57,971 |
| CLM-0014 | ₹74,630 | ₹62,542 |
| CLM-0015 | ₹108,088 | ₹89,481 |
| CLM-0016 | ₹59,346 | ₹40,825 |
| CLM-0019 | ₹255,801 | ₹201,962 |
| CLM-0020 | ₹78,243 | ₹71,833 |
| CLM-0021, CLM-0022 | unchanged | unchanged |

Duplicate lines now cite clause 2, in the dev gold and in `build_cases.py`. The red team is rebuilt.

**Cross-check.** The gold script and `reference_calculate` were written separately. They agree
within ₹1 on every dev claim except the three documented gaps (CLM-0008, CLM-0021, CLM-0022).

**Suite.**

| Row | Before | After | Why |
|---|---|---|---|
| ceiling-dev | 0.982 | 1.000 | duplicate lines now have a citation |
| ceiling-redteam | 0.997 | 1.000 | same |
| floor-dev | 0.119 | 0.109 | gold relabel |
| real-dev | 0.728 | 0.772 | gold relabel and calculator change |
| real-redteam | 0.698 | 0.731 | same |

**Superseded.** ADR-0006's settlement table is superseded; its cut rule stands. The
`RULE_DISAGREEMENTS` entries for duplicates and the ICU cut are removed.

**Still to do.**
- **Tools & Security:** apply the same three rules in `calc/adjudication.py`, with hand-worked tests
  first.
- **Eval & Red-Team:** the course kit's `rules.py` is still on the old demo rules.

## Links
DEC-01, DEC-04, GOLD-04 and AGT-03 in `docs/CLAIMS_AND_GOLD_SET_FIXES.md`; ADR-0006; ADR-0008
(clause 2).

Tests:
- `tests/orchestration/test_reference_calculator.py` (hand-worked)
- `tests/orchestration/test_cases.py`
- `tests/test_dataset_integrity.py`
