# Ship check `er-1114`

**Mode:** stub · **Verdict:** REHEARSAL PASSED

| Stage | Blocks? | Result | Exit | Seconds | Outputs | Note |
|---|---|---|---|---|---|---|
| tests: Product tests (CI) | yes | passed | 0 | 200.6 |  |  |
| lint: ruff check (CI) | yes | passed | 0 | 0.8 |  |  |
| format: ruff format --check (CI) | yes | passed | 0 | 0.5 |  |  |
| tool-pins: Tools unchanged since review | yes | passed | 0 | 0.7 |  |  |
| release-gate: Harness self-check + dev and red-team claims + agent suite + combined gate | yes | passed | 0 | 2.3 | runs/full/er-1114-full/ |  |
| tool-use: Tool calls, tools, hooks, guardrails (offline) | yes | passed | 0 | 5.7 | runs/agentic/er-1114-agentic.* |  |
| deepeval: DeepEval trajectory tests (code checks, no judge) | yes | passed | 0 | 14.2 |  |  |
| deepeval-judge: DeepEval payload judge, GEval + faithfulness (report only; uncalibrated) | no | skipped |  | 0.0 |  | needs real model |
| security: Security scoreboard: each defence against the attacks (report only) | no | passed | 0 | 1.2 | runs/security/er-1114-sec/ |  |
| retrieval: Policy search recall on 47 queries (report only, about 12 min) | no | passed | 0 | 640.1 | runs/retrieval_er-1114.png |  |
| ragas: RAGAS rationale groundedness (report only; uncalibrated, weight 0.00) | no | skipped |  | 0.0 | runs/er-1114-ragas.scorecard.json | needs real model |

Logs: `logs/<stage>.log` in this folder.
