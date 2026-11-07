# Reflexion baseline (empty playbook), 20 development claims

mode: REAL MODEL via OpenRouter | executor: local | calculator: reference | tolerance: Rs 1 | approval: CONSOLE

## Summary

| metric | value |
|---|---|
| cases | 20 |
| settlement_error_total_rs | 186368.94 |
| settlement_error_mean_rs | 9318.45 |
| exact_match_rate | 0.5 |
| edit_rate | 0.3 |
| critic_rejection_rate | 0.0 |

## Where the error comes from

- exact match: 6 cases
- rounding only (error under Rs 1): 4 cases (CLM-0006, CLM-0008, CLM-0019, CLM-0020)
- real disagreement (Rs 1 or more): 10 cases (CLM-0004, CLM-0005, CLM-0009, CLM-0010, CLM-0011, CLM-0012, CLM-0014, CLM-0015, CLM-0016, CLM-0018)

## Known gold vs calculator rule disagreements

- Gold applies the room-rent proportional cut to pharmacy lines (room_linked=true) and not to the procedure line; the calculator does the opposite, following clause 4.1.1 Note (b). CLM-0004, 0011, 0012, 0014. Decision (lead, Nov 2026 walkthrough): the gold is not relabelled for now because a relabel affects every other owner's scores; the mapping stays, the gap is reported.
- Gold deducts an in-bill duplicate line in full (duplicate_line); the fraud agent only checks claim history and a fraud flag never changes an amount. CLM-0005, 0009, 0010, 0015. Decision (lead, Nov 2026 walkthrough): a duplicate stays a fraud flag for the human adjudicator; no clause pays it at zero.
- Gold rounds each cut line to whole rupees; the calculator keeps paise. Cut lines differ by up to Rs 0.50 and count as a miss unless the evaluator is run with a tolerance (--tolerance-rs). Decision (lead, Nov 2026 walkthrough): the tolerance lives in the Reflexion evaluator, the gold is not changed.
- Gold (2026-11-04 audit, GOLD-01) repudiates CLM-0018, a caesarean section, under clause 7.15; the coverage analyst's admissibility check has no exclusion rule yet (AGT-02, orchestration owner), so the pipeline still pays it. Admissibility is deterministic code, not a clause choice, so no lesson can fix this.
- Gold (2026-11-04 audit, GOLD-04) caps CLM-0016's ICU day at Rs 10,000 but applies no proportional cut to the other lines because the room rent itself is within its cap; the calculator applies clause 4.1.1 Note (b) to an ICU breach as well, so it cuts investigations and nursing. Both cap the ICU line identically. Needs a domain ruling: does Note (b) follow an ICU breach or only a room-rent breach?

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
| CLM-0016 | settled | 50372.13 | 59346 | 8973.87 | yes | 2 | 0 | - |
| CLM-0017 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0018 | settled | 111406.50 | 0 | 111406.50 | yes | 5 | 0 | - |
| CLM-0019 | settled | 255800.80 | 255801 | 0.20 | no | 0 | 0 | - |
| CLM-0020 | settled | 78242.95 | 78243 | 0.05 | no | 0 | 0 | - |
