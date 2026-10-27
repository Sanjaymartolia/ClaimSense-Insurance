# Evaluation (L13, L15). Owner: Eval & Red-Team

- `golden_dev/` — ~20 development claims (JSONL), expected worksheets computed by hand.
- Held-out set (60+): stored **outside this repo** in `../claimsense-heldout/`, which Claude Code is
  denied access to (`.claude/settings.json`). The person tuning agents never writes these.
- `redteam/` — 30+ attacks: injected "pre-approved" note, bill total ≠ lines, altered date,
  wrong-patient letter, injection through our own data path.
- Checks: code first (amounts, cited clause exists, DB state, tool calls, forbidden actions),
  judge (different model family) only for explanation quality; calibrate on 20+ human labels,
  report Cohen's kappa.
- Experiments E1–E4 are config files, one harness.
