# ADR-0005: Where memory lives

**Status:** proposed
**Owner / layers:** Knowledge & Memory — L9 (with Tools & Security, Agents & Orchestration)
**Date:** 2026-11-09

## Context
L9 belongs to Knowledge & Memory, and `src/claimsense/memory/` was empty. Teammates have since built
each kind of memory the policy asks for, in their own folders:

- **Claim history** (bill fingerprints, sub-limits used): `ClaimsDatabase.record_history` and
  `claim_history` in `mcp_servers/claims_db.py` (Tools & Security). They store pseudonymised
  ids, dates and hashed fingerprints only.
- **Lessons:** `reflexion/playbook.py` (Agents & Orchestration): proposed → approved / rejected →
  withdrawn, frozen before the held-out run.
- **One claim's working state:** the LangGraph checkpointer (`graph/build.py`). It holds the whole
  claim, diagnosis included, so it can pause for review and resume.

## Options considered
- A. Build a second claim-history store in `memory/`. It would duplicate claims-db's tables, and the
  fraud agent would have two sources to disagree.
- B. Move the claims-db history code into `memory/`. It shares one SQLite connection and lock with
  settlement, so splitting it adds risk for no behaviour change.
- C. Keep the storage where it is. `memory/` owns the interface, the policy and the tests (chosen).

## Decision
- `memory.HistoryStore` is the interface `Services.claim_history` and `Services.record_history` bind
  to. `ClaimsDatabase` implements it.
- Lessons stay in `reflexion/playbook.py`; the checkpointer stays in `graph/`.
- `docs/memory-policy.md` is the policy. `tests/memory/` checks claims-db against it: fingerprints
  round-trip, a resubmitted bill is caught, recording is idempotent, history is per policy, and no
  diagnosis, procedure or bill text reaches the database.

## Consequences
- **Tools & Security (claims-db):**
  1. `record_history` stores a `SUB_LIMIT` deduction's amount (what was cut) as `sub_limits_used`,
     but the fraud agent reads it as what was used. Limit 40,000 on a 50,000 bill stores 10,000,
     not 40,000. Store the line's payable amount instead. `tests/memory` has this as a strict xfail;
     remove the marker when it's fixed.
  2. Add `delete_history(claim_id)` so a wrongly recorded claim can be corrected. `record_history`
     ignores a claim that is already recorded, so a corrected claim can't be re-recorded today.
- **Agents & Orchestration:** `real_services()` already binds `claim_history` and `record_history`
  to claims-db. `fraud.py` says "sub-limits already used this policy year" but sums every year in
  history; filter by the policy period (`PolicyInfo.period_start`, `period_end`).
- **Knowledge & Memory:** keep `docs/memory-policy.md` and `tests/memory/` current. If claim history
  ever moves, the new store must pass `tests/memory/` unchanged.

## Links
T31 (claim history), T46 (lesson store). `docs/memory-policy.md`, `tests/memory/`,
`src/claimsense/memory/__init__.py`, `docs/experiments/reflexion/REPORT-SECTION.md`.
