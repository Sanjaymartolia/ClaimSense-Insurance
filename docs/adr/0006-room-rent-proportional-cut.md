# ADR-0006: Room-rent proportional cut follows Note 4.1.1(b)

**Status:** accepted
**Owner / layers:** @domain-lead (Domain & Product) — L7 calc rule, L13 eval gold
**Date:** 2026-11-11

## Context
GOLD-02 (`docs/CLAIMS_AND_GOLD_SET_FIXES.md`). When room rent breaches its daily cap, the dev gold
cut nursing, **medicines** and diagnostics in proportion but left the **procedure** line uncut. The
reference calculator (`calc/adjudication.py`) and the agents did the opposite, so four dev claims
(CLM-0004, 0011, 0012, 0014) and the 11 red-team cases built on them scored as wrong amounts when
the pipeline was following the policy.

Arogya Sanjeevani policy wording, clause 4.1.1, Note b:

> In case of admission to a room/ICU/ICCU at rates exceeding the aforesaid limits, the
> reimbursement/payment of all other expenses incurred at the Hospital, **with the exception of
> cost of medicines**, shall be effected in the same proportion as the admissible rate per day
> bears to the actual rate per day of Room Rent/ICU/ICCU charges.

The policy wording is primary (`data/README.md`).

## Options considered
- **A. Keep the demo rule** (cut lines flagged `room_linked`, medicines included, procedure
  excluded). Contradicts the note on both counts, and contradicts its own data: every procedure
  line is `room_linked: true`, yet the gold never cut one.
- **B. Follow the note.** Cut every non-room hospital expense (procedure, nursing, diagnostics,
  and so on) by `admissible rate / actual rate`, and do not cut medicines. This matches the
  calculator and the agents already.

## Decision
**B.** On a room or ICU rate breach:
1. The room (or ICU) line is capped at the daily limit × days, cited to the limit clause as before.
2. Every other expense incurred at the hospital, the procedure included, is paid at
   `admissible rate per day / actual rate per day`, reason `room_rent_proportional_reduction`,
   cited to `new_india_arogya_sanjeevani:4.1.1` (the note lives there, not in 4.1).
3. Medicines are exempt. A dev line in category `pharmacy` ("Medicines and consumables") counts as
   medicines in full, because the fixture does not split consumables out.
4. Gold stays in whole rupees, each line rounded half up (GOLD-08 is still open). The relabelled
   totals sit within ₹1 of the calculator's paise figures.

| Claim | Old gold | New gold | Calculator |
|---|---|---|---|
| CLM-0004 | ₹102,313 | ₹80,990 | ₹80,990.23 |
| CLM-0011 | ₹60,741 | ₹57,184 | ₹57,184.61 |
| CLM-0012 | ₹78,511 | ₹67,575 | ₹67,575.39 |
| CLM-0014 | ₹85,136 | ₹74,630 | ₹74,629.15 |

## Consequences
- `eval/golden_dev/gold_worksheets.jsonl`: the four claims are relabelled. The proportional lines
  now cite `4.1.1` instead of `4.1`, and the room-line rows are unchanged.
- `eval/redteam/gold.jsonl`: rebuilt with `build_cases.py`. 11 cases change (CLM-9001, 9004, 9006,
  9007, 9014, 9017, 9019, 9022, 9023, 9024, 9029).
- `data/README.md`: the demo-ruleset bullet now states this rule.
- Not changed: `calc/` (it already follows the note) and the agents.
- **Eval & Red-Team:** composites pinned in `eval/harness/suite.py::ROWS` may move. Re-check with
  `python -m eval.harness.suite --accept-pipeline` and record any new values.
- **Still open, could move these figures again:** DEC-01 (does the ₹5,000 room limit include
  nursing?) and GOLD-03 / DEC-03 (a specific waiting period on the gallbladder claims CLM-0004 and
  CLM-0005).
- Reports and run records written before this date (`docs/experiments/`, `runs/`) keep the old gold
  figures as history. They are not rewritten.

## Links
GOLD-02 and DEC-01 in `docs/CLAIMS_AND_GOLD_SET_FIXES.md`. Test:
`tests/orchestration/test_cases.py::test_gold_room_rent_cut_follows_note_4_1_1_b`.
