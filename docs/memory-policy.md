# Memory policy (L9) — one page

**Owner:** Knowledge & Memory. **Checked against the code:** 14 November 2026.
**Decisions:** [ADR-0005](adr/0005-memory-ownership.md) (where memory lives),
[ADR-0014](adr/0014-reflexion-playbook-lifecycle.md) (lesson lifecycle). Synthetic claims only.

## 1. What is saved, why, when, and who can read it

| | Claim history (long-term) | Lessons (long-term) | Working state (short-term) |
|---|---|---|---|
| **What** | Claim id, policy number, admission date. Per bill line: line id and a 16-character SHA-256 fingerprint of policy number, admission date, description and amount. Per sub-limit clause: rupees paid against it. | Lesson text, when it applies, clause ids, source dev case, status, reviewer id, review note. | The whole claim in progress: documents, diagnosis, plan, worksheet, edit log, approvals. |
| **Why** | To catch a bill that is sent again, and to know how much of a sub-limit earlier claims used. | To reuse an adjudicator's correction on later claims (signature challenge B). | To pause for a person and to resume after a crash. |
| **Where** | claims-db (SQLite, `CLAIMSENSE_CLAIMS_DB`), behind `memory.HistoryStore`. | `playbook.json` (`reflexion/playbook.py`). | LangGraph checkpointer (SQLite, `CLAIMSENSE_CHECKPOINTS`); thread id = case id. |
| **When** | Step 9, the `memory_update` node, only after the claim is settled or repudiated. A blocked settlement writes nothing. | Offline only: Reflexion, or `review_cli propose-from-edits`, files a *proposed* lesson. The graph never writes one. | After every node. |
| **Who writes** | The graph process. No agent holds a write tool for it. | A named reviewer approves, rejects or withdraws. | The graph. |
| **Who reads** | The fraud analyst only (`claim_history` in `TOOL_ACL`), one policy per call. With tool hooks on, only the claim's own policy. | The coverage analyst only: at most 3 approved lessons that share a clause or wording with the claim. A claim run loads only a frozen playbook whose hash matches. The ids it read go to `lessons_used`. | The graph and the case API. API responses never carry diagnosis or bill text (`tests/api`). |

**Short-term context.** Each agent makes one structured model call from the graph state. There is
no chat history, so there is nothing to trim or summarise.

## 2. What is never saved

- Claim history: no diagnosis, procedure or bill description (`tests/memory`), and no patient name.
- Lessons: no unreviewed lesson reaches a prompt; no amounts or ids; no held-out content.
- No user profile and no conversation log.

## 3. How it is corrected or deleted

| Memory | Correct | Delete |
|---|---|---|
| Claim history | Recording a claim twice changes nothing. A wrong record: `delete_history(claim_id)`, then record again. | `delete_history(claim_id)` removes that claim's rows from all three history tables and leaves other claims alone. Operator only: it is not an MCP tool, so no agent can call it. |
| Lessons | Never edited in place. `Playbook.withdraw()` with a note; a frozen playbook cannot change, so a correction is a new playbook, a new freeze and a new hash. A refused lesson is not proposed again. | Withdraw it. The record stays as an audit trail; it is no longer retrieved. |
| Working state | An adjudicator's edit recalculates the worksheet and cancels the earlier approval. | Delete the thread, or the checkpoint file, when the claim is closed. |

**Retention.** Claim history is kept for the policy's life: the duplicate check uses all years, the
sub-limit check only the current policy period. `*.db` and `*.sqlite` files are never committed.

## 4. Memory on and memory off

| Memory | Off | On | Evidence |
|---|---|---|---|
| Claim history: the same bill sent again under a new claim id (22 dev claims) | 0 of 22 flagged | 22 of 22 flagged and sent to senior approval; 0 of 22 false flags on the first submission | `tests/memory/test_memory_on_off.py`: the fraud screen on the real claims-db store, stub mode. End to end on one claim: `test_the_same_bill_sent_again_is_a_duplicate` (`tests/api`); demo step 2. |
| Claim history: a sub-limit partly used by an earlier claim in the same policy year | No flag | A flag that names the clause and the rupees used (Rs 40,000 in the test; Rs 25,000 of clause 4.3 on dev claim CLM-0022). The amount does not change (limit 1). | The same test file; `test_prior_claims_reach_the_claim_history` (`tests/orchestration`) for CLM-0022. |
| Lessons: 60 held-out claims | Exact match 0.883, edit rate 0.117 | The same | `docs/experiments/reflexion/REPORT-SECTION.md` §4.5. The frozen playbook has no approved lesson, so the two runs are equal by construction. |

Run the first two rows again with `pytest tests/memory` (stub mode, no key, a few seconds).

## 5. Limits

1. Earlier sub-limit use raises a flag for a person. It does not reduce the amount: the calculator
   accepts `sub_limits_used`, but the pipeline does not pass it yet.
2. The fingerprint is an exact match. A changed description or amount is not caught. It keeps bill
   text out of the database; it is not strong anonymisation, because descriptions are guessable.
3. Two files hold health data and are not encrypted: the checkpoint database (the whole claim) and
   the `policies` table in claims-db (declared pre-existing diseases; seeded, not written by memory).
4. Deletion is manual. There is no delete route in the case API, no expiry job, and
   `delete_history` writes no audit record.
5. The case API uses stub tools by default: claim history is then in process memory and is lost at
   a restart. `CLAIMSENSE_TOOLS=real` or `mcp` uses the database file.
6. Lesson memory has shown no benefit yet: no lesson passed review on the final gold.
