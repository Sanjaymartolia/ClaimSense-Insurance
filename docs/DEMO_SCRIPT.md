# Running the ClaimSense demo

`scripts/demo.py` runs the three demo scenes from the capstone guide (p.10) through the case API.
It explains each step, prints the worksheet, and checks that each scene behaves as promised.

| Scene | Claim | What it shows |
|---|---|---|
| 1 | CLM-0004 | Room rent above the cap: the proportional cut, line by line, with the clause for each deduction. Alice approves and the claim settles. |
| 2 | CLM-9001, then CLM-0004 again | An injected "pre-approved" note is flagged, and the claim still waits for a person. The same bill sent again is flagged as a duplicate from claim history. |
| 3 | CLM-0019 | Alice approves, then senior Bob edits one line. The totals are recalculated, the worksheet hash changes and Alice's approval is cleared. Bob's next approval gets HTTP 403. After both approve again, the claim settles on the new hash. |

## 1. Setup (once)

```bash
cd ClaimSense-Insurance
source .venv/bin/activate              # macOS / Linux
# source .venv/Scripts/activate        # Windows Git Bash
# .\.venv\Scripts\Activate.ps1         # Windows PowerShell

pip install -e ".[dev,agents]"         # stub mode
pip install -e ".[dev,agents,retrieval]"      # add for --tools real
pip install -e ".[dev,agents,retrieval,mcp]"  # add for --tools mcp
```

Each mode needs:

| Mode | Needs |
|---|---|
| `--llm real` | `OPENROUTER_API_KEY` in `.env` or the shell. The script loads `.env` and never prints the key. |
| `--tools real` or `mcp` | The retrieval index in `chroma-data/`. If it is missing, run `python -m claimsense.retrieval.index`. |
| `--tools mcp` | `fastmcp<4` and `langchain-mcp-adapters>=0.3.2` (ADR-0012). With fastmcp 4 the script stops with "CANNOT START". |

The script sets up the rest itself. For real and MCP tools, each run gets a fresh claims database under
`runs/demo/<timestamp>/` (git-ignored) with the 22 dev policies loaded. If
`CLAIMSENSE_APPROVAL_SECRET` is unset, it uses a throwaway secret for that run.

## 2. Commands

Run these from the repository root.

```bash
# Rehearsal: stub models + stub tools (free, same result every time)
python -X utf8 scripts/demo.py

# Live demo: real models + real tools, pausing between steps (costs money)
python -X utf8 scripts/demo.py --llm real --tools real --pause

# Real models + tools over MCP (closest to production)
python -X utf8 scripts/demo.py --llm real --tools mcp --pause

# One scene only (scene 2 settles CLM-0004 quietly first)
python -X utf8 scripts/demo.py --scene 3

# Skip the cost question
python -X utf8 scripts/demo.py --llm real --tools real --yes
```

### Against a running API server (the run also shows in the UI and Grafana)

```bash
# Terminal 1: the server's settings decide the models and tools
export CLAIMSENSE_TOOLS=real
export CLAIMSENSE_APPROVAL_SECRET=<a long random value>
export CLAIMSENSE_REVIEWERS="local-alice=alice:adjudicator,local-bob=bob:senior"
uvicorn claimsense.api.main:app --port 8000

# Terminal 2
python -X utf8 scripts/demo.py --url http://127.0.0.1:8000 --pause
```

To use reviewer tokens other than `local-alice` / `local-bob`, pass `--alice-token` / `--bob-token`.
Before running the demo again on the same server, restart it, because a case id can be started only once.

## 3. What to type while it runs

| Prompt | Type |
|---|---|
| `Continue? [y/N]` (only with `--llm real`, once at the start) | `y` and Enter. Anything else stops the run before any paid call. |
| `[Enter]` (only with `--pause`, 12 times) | Enter. These pauses give you time to explain each step. |
| To stop at any point | Ctrl+C |

The approvals, Bob's edit and the rejected approval (HTTP 403) are built into the script, so you do not type
any decisions, approver ids or amounts.

## 4. Reading the result

The run ends with one line per scene:

```
Scene 1: PASS
Scene 2: PASS
Scene 3: PASS
```

| Exit code | Meaning |
|---|---|
| 0 | Every scene passed |
| 1 | A scene check failed; the FAIL line says which check |
| 2 | The demo could not start (no key, no index, wrong MCP packages, server down, bad token) |

With real models a FAIL can be a real difference, for example the model chose another clause. Read the
FAIL line before treating it as a bug. The script never relaxes a check.

The script prints only what the API returns: ids, amounts, clauses and flags. It never prints diagnoses
or bill descriptions (rule 4).

## 5. Checking the script

```bash
pytest tests/api/test_demo_script.py    # runs every scene in stub mode; also part of `pytest`
```
