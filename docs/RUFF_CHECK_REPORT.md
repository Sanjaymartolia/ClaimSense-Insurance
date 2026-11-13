# Ruff check report

**Date:** 2026-11-12
**Commit checked:** `141b03b` (`main`, after the merge of 12 November)
**Tool:** ruff 0.17.4, rules from `pyproject.toml` (`select = ["E", "F", "I", "B", "UP", "S"]`,
`line-length = 100`)
**Prepared by:** Sanjay (Eval & Red-Team), with Claude Code

**Update, 13 November 2026:** fixed. `ruff check .` and `ruff format --check .` are both clean.
Long prose lines were reflowed, long strings split into adjacent pieces of the same string (checked
to evaluate to the same value), and ambiguous names renamed. Two LLM prompts, one ASCII diagram and
one pinned tool docstring keep their text and carry `# noqa: E501` instead, so no prompt and no tool
pin changed (`python -m claimsense.hooks.pins`: all 8 match). Product tests, the pinned eval suite
and a fresh-environment run of both CI jobs pass.

## In short (12 November)

- **CI fails on lint.** `ruff check .` finds **88 errors**, and `ruff format --check .` wants to
  reformat **4 files**. CI runs both (`.github/workflows/ci.yml`), so every push to `main` is red
  until they are fixed.
- **All are in product code** (`src/claimsense/`) and one product test file. `eval/` is clean.
- **No error is a live bug.** We read the two kinds that can hide one (F841, B905). Details in
  Section 4.
- **Most are quick.** 64 are long lines. 18 are a variable named `l`. 3 can be fixed by ruff.

## 1. Run it yourself

```bash
source .venv/Scripts/activate
ruff check .                    # the 88 errors
ruff check . --statistics       # count per rule
ruff check src/claimsense/hooks # one folder
ruff format --check .           # the 4 files to reformat
```

## 2. By owner

Owners from the layout table in `CLAUDE.md`. Please fix the files in your own folder.

| Owner | File | Errors | Rules | Needs `ruff format` |
|---|---|---|---|---|
| Tools & Security | `src/claimsense/hooks/hooks.py` | 14 | E501 | |
| Tools & Security | `src/claimsense/guardrails/input_guardrails.py` | 10 | E501 ×7, F841 ×2, F401 | yes |
| Tools & Security | `src/claimsense/guardrails/guardrails.py` | 7 | E501 | |
| Tools & Security | `src/claimsense/guardrails/output_guardrails.py` | 6 | E501 | yes |
| Tools & Security | `src/claimsense/mcp_servers/claims_db.py` | 6 | E501 | yes |
| Tools & Security | `src/claimsense/mcp_servers/tariff.py` | 5 | E501 | |
| Tools & Security | `src/claimsense/calc/adjudication.py` | 4 | E501 ×3, UP035 | yes |
| Tools & Security | `src/claimsense/mcp_servers/policy_kb.py` | 3 | E501 | |
| Tools & Security | `src/claimsense/mcp_servers/approvals.py` | 3 | E501 | |
| Tools & Security | `src/claimsense/mcp_servers/seed_dev_policies.py` | 2 | E501 | |
| Agents & Orchestration | `src/claimsense/agents/services.py` | 6 | E741 ×3, E501 ×3 | |
| Agents & Orchestration | `src/claimsense/agents/coverage.py` | 4 | E741 | |
| Agents & Orchestration | `src/claimsense/agents/settlement.py` | 4 | B905 ×2, E501 ×2 | |
| Agents & Orchestration | `src/claimsense/agents/critic.py` | 3 | E741 | |
| Agents & Orchestration | `src/claimsense/agents/fraud.py` | 3 | E741 | |
| Agents & Orchestration | `src/claimsense/graph/nodes.py` | 2 | E741, E501 | |
| Agents & Orchestration | `src/claimsense/graph/demo.py` | 2 | E741, E501 | |
| Agents & Orchestration | `src/claimsense/agents/extraction.py` | 1 | E501 | |
| Agents & Orchestration | `tests/orchestration/test_pipeline.py` | 3 | E741 | |
| **Total** | 19 files | **88** | | 4 files |

Tools & Security: 60 errors in 10 files. Agents & Orchestration: 28 errors in 9 files.

## 3. By rule, and how to fix each

| Rule | Count | What it means | How to fix |
|---|---|---|---|
| E501 line-too-long | 64 | A line is longer than 100 characters | Split the line. For a long string, use implicit concatenation: `("part one " "part two")`. `ruff format` does not split strings or comments |
| E741 ambiguous-variable-name | 18 | A variable is named `l`, which looks like `1` and `I` | Rename it to `line`, `lesson` or `ln`. Check the whole comprehension or loop |
| F841 unused-variable | 2 | A variable gets a value that is never read | Delete the assignment (Section 4.1) |
| B905 zip-without-explicit-strict | 2 | `zip()` silently stops at the shorter list | Add `strict=True` if the lengths must match, or `strict=False` if a shorter list is intended (Section 4.2) |
| UP035 deprecated-import | 1 | `Mapping` imported from `typing` | `from collections.abc import Mapping` (ruff fixes it) |
| F401 unused-import | 1 | `decimal.InvalidOperation` imported but not used | Delete the import (ruff fixes it) |

Safe automatic fixes (3 errors, review the diff before you commit):

```bash
ruff check src/claimsense/calc/adjudication.py src/claimsense/guardrails/input_guardrails.py --fix
ruff format src/claimsense/calc/adjudication.py src/claimsense/guardrails/input_guardrails.py \
            src/claimsense/guardrails/output_guardrails.py src/claimsense/mcp_servers/claims_db.py
```

Do not run `--unsafe-fixes` on the whole repo. Do not add `# noqa` to make CI green: fix the line.

`calc/` is rule-1 code (every rupee). After any change there, run `pytest tests/calc` before you
push, even for a lint fix.

## 4. The two rules that can hide a bug

### 4.1 F841 in `input_guardrails.py:565` and `:568`: not a bug

`injection_result` gets a value after a clean check, and is never read. The result that the
function returns uses fixed values, which are correct for a clean input. An injection still
raises `InjectionDetectedException` and blocks the input. `except InjectionDetectedException as
exc: raise` only re-raises. Fix: delete `injection_result` and the `try/except` (or drop
`as exc`). Behaviour does not change.

### 4.2 B905 in `settlement.py`: one small edge case

- **Line 77 (`draft_letter`): safe.** `zip(rows, reasons)`. `_plain_reasons` returns the model's
  text only when it has one line per row, else the original reasons (line 109). The lengths always
  match. Add `strict=True`.
- **Line 52 (`repudiate`): small risk.** `zip(reasons, clause_ids + [""] * 9)`. If a claim has
  more than `len(clause_ids) + 9` reasons, the extra reasons are left out of the repudiation letter
  without an error. Suggestion: pad to the length of `reasons`, for example
  `clause_ids + [""] * max(0, len(reasons) - len(clause_ids))`, and use `strict=True`.

## 5. Every location

E741 (variable `l`):

| File | Lines |
|---|---|
| `src/claimsense/agents/coverage.py` | 122, 146, 166, 187 |
| `src/claimsense/agents/critic.py` | 69, 70, 94 |
| `src/claimsense/agents/fraud.py` | 36, 77, 90 |
| `src/claimsense/agents/services.py` | 230, 247, 377 |
| `src/claimsense/graph/demo.py` | 56 |
| `src/claimsense/graph/nodes.py` | 294 |
| `tests/orchestration/test_pipeline.py` | 17, 20, 22 |

E501 (long lines; the longest line in each file in brackets):

| File | Lines |
|---|---|
| `src/claimsense/hooks/hooks.py` | 12, 137, 148, 166, 169, 205, 211, 331, 458, 500, 519, 536, 608, 640 (107) |
| `src/claimsense/guardrails/input_guardrails.py` | 196, 268, 285, 664, 665, 666, 668 (137) |
| `src/claimsense/guardrails/guardrails.py` | 7, 10, 156, 199, 282, 293, 415 (114) |
| `src/claimsense/guardrails/output_guardrails.py` | 139, 148, 235, 626, 627, 628 (147) |
| `src/claimsense/mcp_servers/claims_db.py` | 1, 228, 335, 343, 468, 577 (108) |
| `src/claimsense/mcp_servers/tariff.py` | 19, 85, 90, 217, 248 (103) |
| `src/claimsense/calc/adjudication.py` | 90, 178, 281 (323) |
| `src/claimsense/mcp_servers/policy_kb.py` | 203, 222, 293 (102) |
| `src/claimsense/mcp_servers/approvals.py` | 181, 665, 953 (104) |
| `src/claimsense/agents/services.py` | 292, 293, 298 (106) |
| `src/claimsense/mcp_servers/seed_dev_policies.py` | 30, 174 (104) |
| `src/claimsense/agents/settlement.py` | 97, 98 (101) |
| `src/claimsense/agents/extraction.py` | 162 (101) |
| `src/claimsense/graph/demo.py` | 62 (104) |
| `src/claimsense/graph/nodes.py` | 6 (107) |

Others: `calc/adjudication.py:22` UP035; `guardrails/input_guardrails.py:33` F401, `:565` F841,
`:568` F841; `agents/settlement.py:52` and `:77` B905.

Line numbers are for commit `141b03b`. They move as you edit, so run `ruff check <file>` for the
current list.

## 6. Keep it clean

- Run `ruff check . && ruff format --check .` before each push. That is exactly what CI runs.
- The Claude Code hook (`.claude/settings.json`) runs `ruff format` and `ruff check --fix` after
  each edit, but only if the system `python` has ruff. If it does not, nothing happens and no
  message shows. Install ruff there, or run the commands from `.venv` yourself.
- Small PRs, one owner per folder. A PR that fixes one folder's lint is easy to review.
