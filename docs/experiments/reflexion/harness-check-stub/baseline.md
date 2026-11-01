# Reflexion baseline (empty playbook), 20 development claims

mode: STUB (deterministic, no model) | executor: local | calculator: reference | approval: CONSOLE

## Summary

| metric | value |
|---|---|
| cases | 20 |
| settlement_error_total_rs | 65989.27 |
| settlement_error_mean_rs | 3299.46 |
| exact_match_rate | 0.3 |
| edit_rate | 0.2 |
| critic_rejection_rate | 0.0 |

## Where the error comes from

- exact match: 6 cases
- rounding only (error under Rs 1): 6 cases (CLM-0006, CLM-0008, CLM-0016, CLM-0018, CLM-0019, CLM-0020)
- real disagreement (Rs 1 or more): 8 cases (CLM-0004, CLM-0005, CLM-0009, CLM-0010, CLM-0011, CLM-0012, CLM-0014, CLM-0015)

## Known gold vs calculator rule disagreements

- Gold applies the room-rent proportional cut to pharmacy lines (room_linked=true); the calculator exempts medicines, following clause 4.1.1 Note (b). Affects every admissible room_rent_breach case.
- Gold deducts an in-bill duplicate line in full (duplicate_line); the fraud agent only checks claim history and a fraud flag never changes an amount. Affects every admissible duplicate_bill case.
- Gold rounds each cut line to whole rupees; the calculator keeps paise. Cut lines can differ by up to Rs 0.50, which the simulated adjudicator counts as an edit.

## Per case

| case | status | proposed Rs | gold Rs | abs error Rs | edited | lines edited | critic rejections | lessons used |
|---|---|---|---|---|---|---|---|---|
| CLM-0001 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0002 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0003 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0004 | settled | 80990.23 | 102313 | 21322.77 | yes | 2 | 0 | - |
| CLM-0005 | settled | 103940.45 | 96660 | 7280.45 | no | 0 | 0 | - |
| CLM-0006 | settled | 71374.45 | 71374 | 0.45 | no | 0 | 0 | - |
| CLM-0007 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0008 | settled | 79842.75 | 79843 | 0.25 | no | 0 | 0 | - |
| CLM-0009 | settled | 76604.20 | 73664 | 2940.20 | no | 0 | 0 | - |
| CLM-0010 | settled | 144884.50 | 141867 | 3017.50 | no | 0 | 0 | - |
| CLM-0011 | settled | 57184.61 | 60741 | 3556.39 | yes | 2 | 0 | - |
| CLM-0012 | settled | 67575.39 | 78511 | 10935.61 | yes | 2 | 0 | - |
| CLM-0013 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0014 | settled | 74629.15 | 85136 | 10506.85 | yes | 2 | 0 | - |
| CLM-0015 | settled | 114515.85 | 108088 | 6427.85 | no | 0 | 0 | - |
| CLM-0016 | settled | 73089.20 | 73089 | 0.20 | no | 0 | 0 | - |
| CLM-0017 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0018 | settled | 111406.50 | 111406 | 0.50 | no | 0 | 0 | - |
| CLM-0019 | settled | 255800.80 | 255801 | 0.20 | no | 0 | 0 | - |
| CLM-0020 | settled | 78242.95 | 78243 | 0.05 | no | 0 | 0 | - |
