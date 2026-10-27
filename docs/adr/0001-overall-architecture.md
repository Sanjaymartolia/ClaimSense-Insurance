# ADR-0001: Overall architecture

**Status:** proposed
**Owner / layers:** Agents & Orchestration — all
**Date:** 2026-10-29

## Context
The capstone guide (Figure 3) defines a reference architecture for ClaimSense. We need one agreed
shape so six people can build in parallel against shared contracts.

## Decision (proposed)
- Pipeline: extract → admissibility → line items → fraud screen → critic (max 1 revision) →
  approval gate → settlement, orchestrated by a LangGraph supervisor with a SQLite checkpointer.
- Agents: extraction, coverage analyst, fraud analyst, critic, settlement. Only the settlement
  agent has the write tool `settle_claim`.
- MCP servers: policy-kb, adjudication-calc, tariff, claims-db.
- All money in `calc/` (Decimal). Approval tied to `Worksheet.content_hash()`; two levels above
  `approval.senior_threshold_inr` or on a fraud flag.
- Shared types in `src/claimsense/contracts/`.

## Consequences
Contract changes need review from two roles. Every role builds against `contracts/` from Week 2.

## Links
Capstone guide pp. 9–10; Discord playbook.
