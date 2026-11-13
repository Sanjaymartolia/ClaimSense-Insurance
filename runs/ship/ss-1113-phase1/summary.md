# Ship check `ss-1113-phase1`

**Mode:** stub · **Verdict:** REHEARSAL PASSED

| Stage | Blocks? | Result | Exit | Seconds | Outputs | Note |
|---|---|---|---|---|---|---|
| tests: Product tests (CI) | yes | passed | 0 | 176.2 |  |  |
| lint: ruff check (CI) | yes | passed | 0 | 0.2 |  |  |
| format: ruff format --check (CI) | yes | passed | 0 | 0.2 |  |  |
| tool-pins: Tools unchanged since review | yes | passed | 0 | 0.8 |  |  |
| release-gate: Harness self-check + dev and red-team claims + agent suite + combined gate | yes | passed | 0 | 3.2 | runs/full/ss-1113-phase1-full/ |  |
| tool-use: Tool calls, tools, hooks, guardrails (offline) | yes | passed | 0 | 9.2 | runs/agentic/ss-1113-phase1-agentic.* |  |
| deepeval: DeepEval trajectory tests (code checks, no judge) | yes | passed | 0 | 17.2 |  |  |
| deepeval-judge: DeepEval payload judge, GEval + faithfulness (report only; uncalibrated) | no | skipped |  | 0.0 |  | needs real model |
| security: Security scoreboard: each defence against the attacks (report only) | no | passed | 0 | 2.0 | runs/security/ss-1113-phase1-sec/ |  |
| ragas: RAGAS rationale groundedness (report only; uncalibrated, weight 0.00) | no | skipped |  | 0.0 | runs/ss-1113-phase1-ragas.scorecard.json | needs real model |

Logs: `logs/<stage>.log` in this folder.
