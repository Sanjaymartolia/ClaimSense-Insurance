# ClaimSense kit report — <your name>, <role>

*About two pages. Every claim needs a number, a file name, or a plot from `runs/` next to it.*

## The short version

| | dev score (20 claims) | red-team (30 claims, `--redteam`) |
|---|---|---|
| shipped baseline | | |
| final | | |

Model `…` (from `config/models.yaml`), `RETRIEVAL_MODE=…`, `CHUNK_STRATEGY=…`, total cost $….

![all runs](runs/log.png)

## What each change was worth

| Change | Dev score after | Tokens / claim | Kept? |
|---|---|---|---|
| baseline | | | — |
| TODO 4 — tool loop | | | |
| TODO 2 — BM25 + RRF + supporting list | | | |
| TODO 3 — verify | | | |
| TODO 6 — branches, memory, approval | | | |
| TODO 5 — injection | | | |
| TODO 1 — clause chunks | | | |

*Two short paragraphs: the change that mattered most and why you think so; one thing that
did not work and what you think went wrong.*

## 1. Search
*Recall from `--retrieval-only` for: shipped, chunking change, BM25/hybrid — one at a time,
with the plot. Your choice for the supporting excluded-items list, and why.*

## 2. Grounding
*How you split and check statements; the cut-off and what happens below it; what it did on
CLM-0016 and CLM-0019 (sub-limits); extra tokens and seconds; keep it on?*

## 3. Tools and safety
*How the loop stops. One trace where a second tool call depended on the first. Both red-team
doors before and after TODO 5, and what a reworded attack would still get past you.*

## 4. Flow
*Paste `draw()` output. Your branches in 2–3 sentences. A two-turn conversation showing
memory. One settlement blocked → approved → executed (paste the terminal output).*

| | agent routed to a human | agent said ready |
|---|---|---|
| **gold: needs a human** | correct | missed — the dangerous one |
| **gold: no human needed** | wasted an adjudicator's time | correct |

## 5. Bugs I caught with a failing test
*Name each test in `tests/test_my_bugs.py`: what broke, how the test shows it.*

## Data problems I found
*Anything in the gold or the policy data that looks wrong (do not edit it — report it).*

## How to reproduce
```bash
python scripts/build_index.py --force --strategy …
RETRIEVAL_MODE=… python scripts/evaluate_dev.py --label final --redteam
```
*Which AI tools you used and for what.*
