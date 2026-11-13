# ClaimSense: run commands

**For:** the team, from a Windows PowerShell terminal at the repository root.
**Updated:** 12 November 2026, Sanjay Singh (Eval & Red-Team).
**More detail:** `docs/terminal.md` (what each command prints, exit codes, costs, common errors).

Replace `X` in each label with your initials and the date, for example `ss-1112`. Use a new
`--label` every time: a label that exists is refused or overwritten. Results are saved under
`runs/`.

---

## Part A. Real API commands

These call the models through OpenRouter. **They cost money.**

### A.0 Make sure the terminal is in real mode

```powershell
Remove-Item Env:CLAIMSENSE_LLM -ErrorAction SilentlyContinue        # stub mode off
Remove-Item Env:CLAIMSENSE_GUARD_LLM -ErrorAction SilentlyContinue  # guard model off (it fails the speed gate)
# OPENROUTER_API_KEY must be set; VS Code loads it from .env. Never print or share it.
```

### A.1 Release check: does it ship? (about $0.07, 10 min)

```powershell
python -X utf8 -m eval.full --label release-X --splits dev,redteam --workers 4
```

Exit 0 and `ALL GATES PASSED` means it ships. Output: `runs/full/<label>/`.

### A.2 Release check with the real retriever

```powershell
python -X utf8 -m eval.full --label rr-X --variant real-retrieval --splits dev,redteam
```

Last result (12 November): composite 0.976, every harness gate held, $0.0017 per claim, but
p95 30.2 s, so the 30 s gate failed by 0.2 s.

### A.3 Harness score (is the final answer right?)

```powershell
python -X utf8 -m eval.harness.run --adapter claimsense --split dev,redteam --label harness-X
python -X utf8 -m eval.harness.run --adapter claimsense-real-retrieval --split dev,redteam --label harness-rr-X
```

Output: `runs/<label>.scorecard.json`.

### A.4 RAGAS judge (is the rationale backed by the clause?)

```powershell
python -X utf8 -m eval.harness.run --adapter claimsense-real-retrieval --split dev --judge --judge-limit 5 --label ragas-X
```

Look for `rationale_groundedness`. It is uncalibrated and changes between runs: do not quote it.

### A.5 Agent suite, `v1` against `guarded` (about $0.13)

```powershell
python -X utf8 -m eval.agent_suite --label agents-X --variant v1,guarded
```

Exit 1 means a gate check failed. Output: `runs/agent_suite/<label>/`.

### A.6 Security (L15)

```powershell
python -X utf8 -m eval.security scoreboard --label scoreboard-X        # about 15 min
python -X utf8 -m eval.security attack --label attack-X --rounds 6     # exit 1 = the attacker won
```

If the attacker wins, its note is in `runs/security/<label>/attacker_notes.jsonl`. Add it to
`eval/redteam/attacks.jsonl`.

### A.7 One claim, end to end, with the real tools

```powershell
python -X utf8 scripts/run_one.py --list
python -X utf8 scripts/run_one.py CLM-0004 --real-tools
```

### A.8 DeepEval with the paid judge

```powershell
$env:DEEPEVAL_DISABLE_DOTENV = "1"; $env:DEEPEVAL_TELEMETRY_OPT_OUT = "1"; $env:CLAIMSENSE_DEEPEVAL_JUDGE = "1"
deepeval test run eval/deepeval_suite
Remove-Item Env:CLAIMSENSE_DEEPEVAL_JUDGE
```

---

## Part B. Free commands (no key, no cost)

### B.1 Set up once

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install --no-deps "ragas>=0.4,<0.5"          # Python 3.14 only
python -m claimsense.retrieval.index             # build the search index
```

### B.2 Before every commit (under 5 min)

```powershell
pytest                                           # product tests
pytest eval/tests -q                             # eval tests (318)
python -m eval.harness.suite                     # all 9 rows must match
python -m claimsense.hooks.pins                  # tools unchanged since review
ruff check . ; ruff format --check .
```

### B.3 Stub versions of the checks

```powershell
python -X utf8 -m eval.full --stub --label full-X
python -X utf8 -m eval.agent_suite --stub --label agents-X --variant v1,guarded
python -X utf8 -m eval.agent_suite --stub --label agents-X --show CLM-0004       # one claim's trace
python -X utf8 -m eval.security scoreboard --stub --label sb-X
pytest tests/security -q
```

For a command with no `--stub` flag (such as `eval.harness.run`), run
`$env:CLAIMSENSE_LLM = "stub"` first, and `Remove-Item Env:CLAIMSENSE_LLM` after.

### B.4 Retrieval (needs no key in either mode)

```powershell
python -X utf8 -m claimsense.retrieval.evaluate --label retrieval-X   # 47 queries, about 12 min
pytest tests/retrieval -q
```

### B.5 Framework rubric (a written score, not a run)

```powershell
python -m eval.tools.rubric_score --plan --insurance
pytest eval/tests/test_rubric_report.py -q
```

To change a score, edit sections 3 and 5 of `docs/FRAMEWORK_RUBRIC_SCORE.md`.

---

## Rules

- Never print, paste or commit `OPENROUTER_API_KEY`, and never open `.env` on a shared screen.
- Use synthetic claims only. Never run the held-out set (`data/claimsense-heldout/`) unless you are
  Eval & Red-Team and everything is frozen.
- Do not use `tee` in PowerShell (it writes UTF-16). Every tool saves its own results.
- Add `-X utf8` to any command that prints a table.
