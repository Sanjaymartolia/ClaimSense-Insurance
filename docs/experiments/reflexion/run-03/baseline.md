# Reflexion baseline (empty playbook), 20 development claims

mode: REAL MODEL via OpenRouter | executor: local | calculator: reference | tolerance: Rs 1 | approval: CONSOLE

## Summary

| metric | value |
|---|---|
| cases | 22 |
| settlement_error_total_rs | 112102.91 |
| settlement_error_mean_rs | 5095.59 |
| exact_match_rate | 0.864 |
| edit_rate | 0.136 |
| critic_rejection_rate | 0.182 |

## Where the error comes from

- exact match: 7 cases
- rounding only (error under Rs 1): 12 cases (CLM-0004, CLM-0005, CLM-0006, CLM-0009, CLM-0010, CLM-0011, CLM-0012, CLM-0014, CLM-0015, CLM-0016, CLM-0019, CLM-0020)
- real disagreement (Rs 1 or more): 3 cases (CLM-0008, CLM-0021, CLM-0022)

## Known gold vs calculator rule disagreements

- Gold rounds each cut line to whole rupees; the calculator keeps paise. Cut lines differ by up to Rs 0.50 and count as a miss unless the evaluator is run with a tolerance (--tolerance-rs). ADR-0007 (GOLD-08): the gold stays in rupees; the eval harness defaults to a Rs 1 tolerance, the Reflexion evaluator keeps it explicit.
- Gold (ADR-0007, GOLD-03) repudiates CLM-0008 under the 24-month specific wait (clause 6.2.18, urinary calculi, first policy); the admissibility check has no 6.2 list yet (AGT-02), so the pipeline pays it.
- Gold (ADR-0007, GOLD-05) caps cataract treatment at clause 4.3 (CLM-0021) and at the part an earlier claim left unused (CLM-0022); the calculator does not apply 4.3 because the claim contract carries no treated eye (calc.adjudication.INFORMATIONAL_SUB_LIMITS).

## Per case

| case | status | proposed Rs | gold Rs | abs error Rs | edited | lines edited | critic rejections | lessons used |
|---|---|---|---|---|---|---|---|---|
| CLM-0001 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0002 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0003 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0004 | settled | 67067.10 | 67067 | 0.10 | no | 0 | 0 | - |
| CLM-0005 | settled | 76886.60 | 76886 | 0.60 | no | 0 | 2 | - |
| CLM-0006 | settled | 59141.58 | 59141 | 0.58 | no | 0 | 0 | - |
| CLM-0007 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0008 | settled | 72198.11 | 0 | 72198.11 | yes | 5 | 0 | - |
| CLM-0009 | settled | 56078.11 | 56078 | 0.11 | no | 0 | 2 | - |
| CLM-0010 | settled | 107538.62 | 107539 | 0.38 | no | 0 | 2 | - |
| CLM-0011 | settled | 44047.63 | 44048 | 0.37 | no | 0 | 0 | - |
| CLM-0012 | settled | 57971.15 | 57971 | 0.15 | no | 0 | 0 | - |
| CLM-0013 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0014 | settled | 62542.71 | 62542 | 0.71 | no | 0 | 0 | - |
| CLM-0015 | settled | 89481.74 | 89481 | 0.74 | no | 0 | 2 | - |
| CLM-0016 | settled | 40825.14 | 40825 | 0.14 | no | 0 | 0 | - |
| CLM-0017 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0018 | repudiated | 0 | 0 | 0 | no | 0 | 0 | - |
| CLM-0019 | settled | 201962.52 | 201962 | 0.52 | no | 0 | 0 | - |
| CLM-0020 | settled | 71833.40 | 71833 | 0.40 | no | 0 | 0 | - |
| CLM-0021 | settled | 59850.00 | 38000 | 21850.00 | yes | 1 | 0 | - |
| CLM-0022 | settled | 32300.00 | 14250 | 18050.00 | yes | 1 | 0 | - |
