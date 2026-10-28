# Evaluation (L13, L15). Owner: Eval & Red-Team

- `golden_dev/` — 20 development claims (`claims.jsonl`) and their reference outcomes
  (`gold_worksheets.jsonl`), from the starter pack (ADR-0002). The gold uses the demo ruleset in
  `data/README.md`, which isn't authoritative yet. Re-check it by hand before scoring against it.
  Use these for prompt/tool iteration only. Never feed gold into prompts, tools or the retrieval
  corpus.
- Held-out set (60): stored **outside this repo** in `../claimsense-heldout/`, which Claude Code is
  denied access to (`.claude/settings.json`). The person tuning agents never writes these.
- `redteam/` — `attacks.jsonl` (8 seed cases so far; target 30+): injected "pre-approved" note,
  bill total ≠ lines, duplicate bill, altered date, wrong-patient letter, injection through our
  own data path.
- Freeze code, model, prompt, policy version and playbook before any held-out run.
- Report: rupee absolute error, exact settlement match rate, line-item match rate, clause
  grounding, arithmetic, duplicate detection, human-review routing, false-negative safety flags,
  latency, cost.
- Checks: code first (amounts, cited clause exists, DB state, tool calls, forbidden actions),
  judge (different model family) only for explanation quality; calibrate on 20+ human labels,
  report Cohen's kappa.
- Experiments E1–E4 are config files, one harness.
