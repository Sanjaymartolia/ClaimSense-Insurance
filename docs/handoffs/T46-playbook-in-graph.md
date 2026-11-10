# T46: use approved lessons in normal claim runs

**For:** Spandan (Agents & Orchestration). **From:** Shashank (Knowledge & Memory).
**Size:** small. One flag, one loader, one test file. No `contracts/` change.

## The problem in one line
Lessons are saved in `playbook.json`, and the graph can already read them, but only Reflexion
passes a playbook. A normal claim run (`scripts/run_one.py`) builds `Team(services)` with no
playbook, so the coverage agent never sees an approved lesson there.

## What already works (do not change)
- `Team(services, playbook=...)` hands the playbook to the coverage agent (`agents/__init__.py:18`).
- The coverage node takes up to 3 APPROVED lessons (`agents/coverage.py:107-112`) and saves their
  ids in `state["lessons_used"]` and the trace (`graph/nodes.py:167, 184`).
- Reflexion already runs the main graph with a playbook (`reflexion/loop.py:43, 54-60`).
- `scripts/run_reflexion_heldout.py:86-90` already refuses a playbook that is not frozen or that
  changed after freezing.
- `memory_update` writes claim history only. The graph never writes lessons. Keep it that way.

## What to change

### 1. One safe loader: `reflexion/playbook.py`
Add `Playbook.load_frozen(path)`. It loads the file and refuses it if it is not frozen, or if
`content_hash() != frozen_hash` (someone edited it after freezing). This is the same check that
`run_reflexion_heldout.py:86-90` does inline. Move that check here so both use one function.

```python
@classmethod
def load_frozen(cls, path) -> "Playbook":
    # load(path); raise ValueError if not frozen, or if content_hash() != frozen_hash
    ...
```

### 2. `scripts/run_one.py`
- Add `--playbook PATH`. With no flag, everything stays as it is today.
- `pb = Playbook.load_frozen(args.playbook) if args.playbook else None`
- Line 188: `team = Team(services)` becomes `team = Team(services, playbook=pb)`.
- Print one line next to the existing `Tools:` line:
  `Playbook: <first 12 chars of hash>, N approved lessons` or `Playbook: none`.

### 3. Leave alone
- `graph/demo.py`: a demo, no playbook needed.
- `eval/harness/claimsense_adapter.py`: Sanjay's file (Eval & Red-Team). Do not add a playbook
  there. Lessons were learned from the dev claims, so using them in the dev eval would inflate the
  dev score. The held-out with/without comparison already goes through `run_reflexion_heldout.py`.

## Rules
- Use a frozen playbook only. Never a PROPOSED, REJECTED or WITHDRAWN lesson (`retrieve()`
  already filters to APPROVED, so don't bypass it).
- Lessons don't change during a run. The graph only reads them.
- No model IDs or prompts in code (they stay in `config/models.yaml`).

## Tests: `tests/orchestration/test_playbook_in_graph.py`
Reuse `services_factory`, `kit_case` and `approve_all` from `tests/orchestration/test_reflexion.py`.
Use stub mode only: no key, no money.

1. `load_frozen` refuses a playbook that was never frozen.
2. `load_frozen` refuses a frozen playbook whose JSON was edited afterwards (change a lesson's text).
3. A stub claim through `LocalRunner` with a frozen playbook whose approved lesson matches the claim
   ends with that lesson's id in `state["lessons_used"]`.
4. The same claim with no playbook ends with `state["lessons_used"] == []`.
5. A PROPOSED or REJECTED lesson that would match never shows up in `lessons_used`.

## Done when
- `pytest tests/orchestration -q` passes, and `ruff check .` and `ruff format --check .` are clean
  for the changed files.
- `python scripts/run_one.py CLM-0004 --playbook docs/experiments/reflexion/run-02/playbook.json`
  prints the `Playbook:` line. That file is frozen, with 1 approved and 18 rejected lessons. The
  coverage step shows `lessons_used` (it can be `[]` if that one lesson doesn't match CLM-0004).
- The same command without `--playbook` prints `Playbook: none` and otherwise behaves as before.
- PR named `T46: load a frozen playbook in run_one`, reviewed by someone from another role.

Questions about where lessons are stored: see `docs/memory-policy.md` and
`docs/adr/0005-memory-ownership.md`, or ask Shashank.
