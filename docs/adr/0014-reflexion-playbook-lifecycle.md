# ADR-0014: The Reflexion playbook: how a lesson is made, approved, used and frozen

**Status:** accepted
**Owner / layers:** Dhruvi Ramani (Agents & Orchestration, Reflexion part) — L12; touches L9 (memory
ownership, ADR-0005) and L14 (the edit path)
**Date:** 2026-11-13

## Context
Signature challenge B asks for "a playbook that learns from adjudicators": a Reflexion loop on
development claims fed by adjudicator edits and critic rejections, one short lesson per mistake
naming its clause and when it applies, a person approving every lesson, retrieval of only relevant
lessons, withdrawal, and a before/after measurement of settlement error and edit rate. The brief's
step 9 says adjudicator corrections "become candidate lessons, used only after review", and the L12
row says to freeze the playbook before the held-out run.

Three reviewed runs (`run-01` to `run-03`) exist, but two questions from the team had no answer in
code: *how is the playbook used outside the experiment scripts?* and *how does a live edit become a
lesson?* A fourth point, the reflector's noise (16 of 16 proposals rejected in `run-03`, 14 of them
not clause choices), made the human gate expensive.

## Options considered
- **A. The graph writes lessons** when an adjudicator edits a line (`apply_edits` → PROPOSED).
  Fast to demo, but a graph node would then write to long-term memory that ADR-0005 keeps outside
  the graph, and a live run could change the playbook a frozen hash vouches for.
- **B. The graph only leaves the edits** (`edit_log`, already in the claim state); an offline command
  turns them into PROPOSED lessons, and a normal run can only *read* a frozen playbook.
- **C. Keep everything in the experiment scripts** and document that production never reads lessons.
  Honest, but it leaves step 9 and "the coverage analyst retrieves only relevant lessons" unmet in
  the product.

## Decision
Option B.

1. **The evaluator is code.** A mistake is an adjudicator edit, a critic rejection, or a `Decimal`
   difference from the gold beyond `--tolerance-rs`. No model scores anything.
2. **Triage before reflection** (`reflexion/triage.py`). Only a clause-choice mistake goes to the
   reflector and the reviewer: it names a line, and the expected clause is one the analyst could
   have picked (not a claim-level ruling of the admissibility gate, ADR-0010; not the same clause as
   the gold, which is a calculator or gold gap; not a critic arithmetic issue; not a deduction made
   under clause 2 by the calculator, REF-17). Everything else is written to an engineering backlog
   in the report, with the reason.
3. **The reflector never invents a clause.** A draft's clause ids are filtered against the agents'
   registry (`agents/clauses.py`); a draft left with none is dropped (REF-08). Lessons quoting
   amounts or ids are blocked on the stub path as well as the real one.
4. **A refused lesson stays refused.** `Playbook.propose` treats a near-duplicate of a REJECTED or
   WITHDRAWN lesson like a duplicate of an approved one: it is not shown to the reviewer again, and
   the backlog names the lesson it duplicates.
5. **Only a frozen, unchanged playbook reaches a claim run** (`Playbook.load_frozen`, T46). The hash
   in the file must equal the SHA-256 of its approved lessons; `run_one.py --playbook` and the
   held-out script use the same loader. The coverage analyst reads at most three approved lessons
   that share a clause or wording with the claim, and the ids it read are in `lessons_used`.
6. **Live edits become lessons offline, never automatically.** `run_one.py --edits-out` appends the
   run's `edit_log` (ids, clauses, category, the adjudicator's reason; no patient text) to a
   JSON-lines file. `review_cli propose-from-edits` triages, reflects and files PROPOSED lessons into
   a new, unfrozen playbook. `review_cli review` is the gate. A new freeze gives a new hash, which
   is a new deploy.
7. **Freeze precedes held-out.** The experiment ends with `freeze()`; the held-out script refuses an
   unfrozen, changed or leaky playbook. After the held-out numbers are seen, nothing changes.

## Consequences
- The graph (`graph/nodes.py`) is untouched: it reads lessons through `Team(playbook=...)` and leaves
  edits in `edit_log`, as before. ADR-0005 holds.
- `scripts/run_one.py` gains `--playbook` and `--edits-out`; the console reviewer accepts `edit`.
- `learn()` and `experiment()` take `known_clause_ids` and a `triage` sink; `Report`, `report.md`
  and `report.json` gain the backlog. Old callers are unchanged (keyword arguments, defaults).
- The eval harness still runs without a playbook on purpose: lessons learned from dev claims would
  inflate the dev score. The with/without comparison is the held-out run (E3).
- Tests: `tests/orchestration/test_playbook_in_graph.py`, `test_reflexion_triage.py`.
- A rerun of the experiment on the final gold (`run-04`) is needed before the held-out run, because
  triage changes what the reviewer sees.

## Links
`docs/handoffs/T46-playbook-in-graph.md`, `docs/experiments/reflexion/REPORT-SECTION.md` §10,
`docs/REFLEXION_WORK_LOG.md` REF-18 to REF-21, ADR-0005 (memory ownership), ADR-0010.
