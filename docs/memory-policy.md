# Memory policy (L9) — one page. Owner: Knowledge & Memory

| Question | Answer |
|---|---|
| What is saved? | Per policy: claim history, sub-limits used, bill fingerprints (for duplicates). Approved adjudicator lessons. |
| Where does it live? | Claim history: claims-db (`ClaimsDatabase`), behind `memory.HistoryStore`. Lessons: `reflexion/playbook.py`. One claim's working state: the LangGraph checkpointer. See [ADR-0005](adr/0005-memory-ownership.md). |
| What is never saved? | Raw health details beyond what adjudication needs; unreviewed lessons; held-out case content. Claim history holds claim and policy ids, admission date, line ids, hashed fingerprints and sub-limit clause ids only, never diagnosis, procedure or bill text (`tests/memory`). |
| When is it saved? | After the settlement is written (step 9), and when a lesson is approved. |
| Who can read it? | Coverage and fraud analysts (history); coverage analyst (lessons). |
| How is it corrected or deleted? | Recording a claim twice is ignored. A wrong record is corrected with `delete_history(claim_id)`, which removes only that claim's history rows, then recorded again (`tests/memory`). A lesson is withdrawn with `Playbook.withdraw()` and a note, never edited in place; a frozen playbook can't change. |
| How long is it kept? | Synthetic data only. Claim history is kept for the policy's life, because duplicates and sub-limits span claims. Demo and eval databases (`CLAIMSENSE_CLAIMS_DB`, the checkpoint file) are deleted between runs and never committed. |
| Short-term context | Each agent makes one structured LLM call from the graph state, so there is no chat history to trim. The graph state holds the whole claim, diagnosis included, so the checkpoint database counts as health data: synthetic claims only, never logged, never committed, and its thread can be deleted once the claim closes. |
