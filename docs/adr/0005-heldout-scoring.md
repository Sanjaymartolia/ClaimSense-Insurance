# ADR-0005: How the held-out set is scored

**Status:** proposed
**Owner / layers:** Eval & Red-Team — L13, L15
**Date:** 2026-11-10

## Context
The production-grade number comes from the 60-claim held-out set in `../claimsense-heldout/`,
run once with everything frozen (CLAUDE.md rule 5). **Update 2026-11-14:** the Domain lead has
verified the held-out gold (step 1 below; ADR-0013, `docs/HELDOUT_GOLD_REVIEW.md`), and the set now
lives in `data/claimsense-heldout/`. The dev and red-team scores come from the
evaluation harness (`eval/harness/`): a weighted composite plus six catastrophic gates, policy in
`eval/harness/scorecard.yaml`.

Today the two cannot be compared:

1. The harness refuses the held-out path on purpose (`loader.assert_not_heldout`), so it cannot
   score the held-out set.
2. The only held-out runner, `scripts/run_reflexion_heldout.py`, measures the reflexion playbook
   (with and without it). It does not apply the scorecard or the gates.

So a held-out result would be on a different scale from every dev and red-team number, and the
safety gates would not run on the one result that matters most.

## Options considered
A. **Leave it.** Report the reflexion runner's numbers for held-out. Cheap, but the headline score
   has no safety gates and no shared scale.

B. **Add an explicit, one-shot held-out mode to the harness.** For example,
   `python -m eval.harness.run --heldout <path outside the repo> --i-am-eval-owner`, writing results
   outside the repo. The guard stays the default and still blocks every path that is not passed
   this way. Same scorecard, same gates, same adapter.

C. **Export a scorer.** The reflexion runner imports `eval.harness.scorecard` and the metric
   modules and scores its own outputs. Keeps one held-out entry point; two code paths call the
   scorer.

## Decision
Proposed: **B**. It gives one scale and the gates on the held-out run, and keeps the refusal as the
default. Needs agreement from Eval & Red-Team and a reviewer from Agents & Orchestration, since the
reflexion runner would stop being the held-out entry point.

Before the one run, in this order:
1. Domain lead verifies the held-out gold, and DEC-01 to DEC-04 are ruled (the dev gold still has
   GOLD-02, 03, 05, 06, 08 open; held-out gold built on the same demo rules likely shares them).
2. Agents, prompts, models, scorecard version and playbook are frozen and tagged.
3. Dev and red-team pass every gate.
4. One held-out run. Report composite, gates and per-category, with a chart in `runs/`.

## Consequences
- Eval & Red-Team implements the held-out mode and its tests (the guard must still refuse every
  other path; a test proves it).
- No one else reads the held-out files. Claude Code stays denied by `.claude/settings.json`.
- The scorecard threshold must be settled first: `scorecard.yaml` says 0.85, the commented CI gate
  (T48) says 0.80.

## Links
`docs/EVAL_HARNESS_REPORT.md` §4.2, `eval/harness/loader.py`, `scripts/run_reflexion_heldout.py`,
`docs/EVAL_CHANGES_2026-11-10_SANJAY.md`.
