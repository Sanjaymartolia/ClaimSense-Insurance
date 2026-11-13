# ADR-0013: Domain lead reviews the held-out gold with AI assistance (temporary exception to rule 5)

**Status:** closed 2026-11-14 (the review is done; the temporary exception is removed from
CLAUDE.md rule 5, whose location sentence now names `data/claimsense-heldout/`)
**Owner / layers:** @domain-lead (Domain & Product) — L13 eval gold. Agreed by Eval & Red-Team (Sanjay).
**Date:** 2026-11-14

## Context
ADR-0005 step 1 requires the Domain lead to verify the held-out gold before the one held-out run,
because the held-out gold was built on the same demo rules as the dev gold, and the dev gold needed
many fixes (GOLD-01 to GOLD-08, DEC-01 to DEC-04, ADR-0006 to ADR-0011). The held-out set has 60
claims (`eval/heldout/claims.jsonl`, `eval/heldout/gold_worksheets.jsonl`). A manual review of all
60 is not possible in the time left.

CLAUDE.md rule 5 forbids Claude Code from reading or modifying held-out cases. The main risk is
contamination: what is learned from the held-out set must not flow into agent changes.

## Options considered
- **A. Manual review only.** Keeps rule 5 intact; not possible in the time left.
- **B. Skip the review.** The held-out score would measure demo-rule gold, not the policy wording.
- **C. AI-assisted review by the Domain lead, under a temporary, recorded exception.** Chosen.

## Decision
C, with these limits:
1. Scope: the gold and claim files in `eval/heldout/` only. Changes align them with the policy
   wording and with the rulings already applied to the dev gold (ADR-0006 to ADR-0011,
   `docs/CLAIMS_AND_GOLD_SET_FIXES.md`). No new rulings are invented during the review.
2. Agents are frozen. The Domain lead (also Agents & Orchestration owner) states that no agent,
   prompt, model, playbook or scorecard change is made after this review.
3. Every change is logged with its reason (clause or ruling) in `docs/HELDOUT_GOLD_REVIEW.md`, so
   Eval & Red-Team can audit it before the run.
4. Rule 5 in CLAUDE.md is changed only for the review and restored when it ends.
5. Gold is never put into prompts or tools (rule 5's second sentence still applies).

## Consequences
- The held-out result must be reported with a note that its gold was AI-assisted and reviewed by
  the Domain lead, and that the reviewer had seen the agents' behaviour on the dev set.
- Eval & Red-Team audits the change log before the one run.
- This ADR is closed (status and date below), not deleted, when rule 5 is restored.

## Closure (2026-11-14)
- **Done:** all 60 held-out claims and gold worksheets were relabelled to the dev rules. The script
  that did it reproduces all 22 dev gold worksheets exactly. Every change, the checks and seven
  closed decisions are in `docs/HELDOUT_GOLD_REVIEW.md`.
- **Moved:** the set is now in `data/claimsense-heldout/` (Domain lead's choice), with IDs
  renumbered to CLM-1021…1080 so `run_heldout`'s dev-overlap guard passes.
- **No agent was run on the held-out set,** and no agent, prompt, model, playbook or scorecard
  file was changed during the review.
- **Rule 5 is restored** in CLAUDE.md. From here on, only Eval & Red-Team runs and scores the set,
  once.

## Links
ADR-0005 (held-out scoring), `docs/CLAIMS_AND_GOLD_SET_FIXES.md`, `docs/HELDOUT_GOLD_REVIEW.md`.
