# Ship check `ss-1113-stub`

**Mode:** stub · **Verdict:** DO NOT SHIP

| Stage | Blocks? | Result | Exit | Seconds | Outputs | Note |
|---|---|---|---|---|---|---|
| tests: Product tests (CI) | yes | passed | 0 | 118.8 |  |  |
| lint: ruff check (CI) | yes | failed | 1 | 0.2 |  |  |
| format: ruff format --check (CI) | yes | failed | 1 | 0.1 |  |  |
| tool-pins: Tools unchanged since review | yes | passed | 0 | 0.5 |  |  |
| release-gate: Harness self-check + dev and red-team claims + agent suite + combined gate | yes | passed | 0 | 1.8 | runs/full/ss-1113-stub-full/ |  |
| tool-use: Tool calls, tools, hooks, guardrails (offline) | yes | passed | 0 | 3.0 | runs/agentic/ss-1113-stub-agentic.* |  |
| deepeval: DeepEval trajectory tests | yes | passed | 0 | 8.0 |  |  |
| security: Security scoreboard: each defence against the attacks (report only) | no | passed | 0 | 1.0 | runs/security/ss-1113-stub-sec/ |  |
| retrieval: Policy search recall on 47 queries (report only, about 12 min) | no | passed | 0 | 376.8 | runs/retrieval_ss-1113-stub.png |  |
| ragas: RAGAS rationale groundedness (report only; uncalibrated, weight 0.00) | no | skipped |  | 0.0 | runs/ss-1113-stub-ragas.scorecard.json | needs real model |

Logs: `logs/<stage>.log` in this folder.
