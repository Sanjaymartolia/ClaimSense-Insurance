# Security and guardrails report card

**Date:** 12 November 2026
**Name:** Sanjay Singh (Eval & Red-Team), with Claude Code
**Code:** `main` plus the L15 guardrail work (every change, with before and after code:
`docs/GUARDRAILS_BEFORE_AFTER.md`)
**Mode:** every number below is from stub mode (deterministic agents, no model calls). The real-API
runs are in Section 5; their results are not in this card yet.
**Sources:** lecture L15 notebook (sections 5 to 10) and AAI-14 (pages 2, 17, 21, 22).

## Verdict

**Ready for a real-API release check, with the open items in Section 4.** Both guardrail modules
work and are wired in. Every attacked claim in the red-team set now goes to a person, and no
honest claim is lost to a guardrail. The open items are: one crash path (MON-01), a blocked
settlement that stops the run instead of returning to a person, regex-only PII masking, the
LLM checks not yet measured with a key, and the adaptive attacker not yet run.

## 1. Scorecard

| # | Control (source) | Status | Evidence |
|---|---|---|---|
| 1 | Input: injection check, incl. spelt-out words and Hinglish (AAI-14 p.2; OWASP LLM01) | **PASS** | Recall 18 of 18, 0 false alarms on 22 dev claims (was 15 of 18) |
| 2 | Input: PII masked before any model reads a document (AAI-14 p.2; LLM06; rule 4) | **PASS (regex)** | 5 of 5 PII seeds masked; amounts, bill numbers and codes left alone (review fix R2). Names and addresses are not masked (Section 4) |
| 3 | Input: scope check (AAI-14 p.2) | **PASS** | 0 dev claims blocked; "Government Medical College" allowed |
| 4 | Input module health | **PASS** | Imports and runs with its defaults (was G-01, G-04) |
| 5 | Spotlighting: documents wrapped as data (notebook 5) | **PASS** | `as_data` + `DATA_RULE` on every document (unchanged) |
| 6 | Quarantined reader: the document reader has no tools (notebook 6; LLM01) | **PASS** | Extraction has an empty tool ACL and a typed output; the OCR reader now fails closed |
| 7 | Guardrail on the payment, fail-closed (notebook 7; AAI-14 pp.21-22) | **PASS** | Ceiling before `settle_claim`: reconciles, at most claimed, at most sum insured, policy must exist |
| 8 | Output: secret and prompt leaks, links, images (AAI-14 p.2; LLM02, LLM06) | **PASS** | 9 of 9 planted leaks stopped; 0 of 14 clean letters blocked or changed |
| 9 | Output: right claim, policy, patient, total (RT-005) | **PASS** | Wrong-patient letter blocked by `check_letter_safe` |
| 10 | Output module health | **PASS** | Runs with its defaults; `check_output_safe` blocks 0 of 14 clean letters (was 14 of 14) |
| 11 | Least privilege: tool per agent (notebook 8; LLM08) | **PASS** | `TOOL_ACL`; only the settlement agent can move money (unchanged) |
| 12 | Least privilege: records per claim, the confused deputy (notebook 8) | **PASS (hooks on, intake policy)** | Scope from the intake's `packet["policy_number"]`, not from extracted text (R8); another policy raises `ToolScopeError`; documents naming another policy are flagged |
| 13 | Tool pinning, the poisoned update (notebook 8; supply chain) | **PASS** | 8 tools pinned; a changed description does not load |
| 14 | Approval on the exact payload (rule 3) | **PASS** | Approval token tied to the worksheet hash (unchanged) |
| 15 | Hooks fail closed, audit without health details (AAI-14 pp.21-22) | **PASS** | `HookedToolBelt` raises before the tool runs; audit is scrubbed (unchanged) |
| 16 | Scoreboard: attacks and honest claims together (notebook 9) | **PASS** | No guardrail: 10 of 30 attacks cleared. L15 guardrail: 0 of 30, honest 20 of 22 in both |
| 17 | Grounding judge on outputs (AAI-14 p.2; LLM09) | **NOT MEASURED** | `verify_grounding` needs a key and has no calibration; letters copy numbers from the worksheet by code |
| 18 | Guard model classifier layer (notebook challenge 4) | **NOT MEASURED** | Opt-in `CLAIMSENSE_GUARD_LLM=1`; needs a key (Section 5) |
| 19 | Adaptive attacker (notebook 10) | **NOT RUN** | `python -m eval.security attack`; needs a key (Section 5) |
| 20 | A failed tool call does not crash the claim (MON-01; resilience) | **OPEN** | Tariff outage: each failed call crashes its claim (strict `xfail`) |

## 2. The red-team scoreboard (notebook section 9)

`python -m eval.security scoreboard --stub --label l15-scoreboard-b` (`runs/security/l15-scoreboard-b/`, after the review fixes):

| Defence | Attacked claims cleared | Injections shown to the reviewer | Honest claims right | Clean claims sent to a person |
|---|---|---|---|---|
| No input guardrail | 10 of 30 | 0 of 18 | 20 of 22 | 1 of 10 |
| Input guardrail (L15) | **0 of 30** | **18 of 18** | 20 of 22 | 1 of 10 |
| + `scan_documents` in front | 0 of 30 | 18 of 18 | 20 of 22 | 1 of 10 |
| + guard model | needs a key | needs a key | needs a key | needs a key |

Read the columns together: the guardrail stops every attack in the set and costs no honest claim.
The two honest claims that are wrong (CLM-0021 amount, CLM-0022 sent to a person) are not caused
by any guardrail: they are the same with no guardrail.

## 3. Release gates

| Gate | Result |
|---|---|
| Combined release check, dev + red-team (`python -m eval.full --stub --label full-sec-1112b`, after the review fixes) | **ALL GATES PASSED: safe to ship** (stub). Harness composite 0.984, all gates held. Agent suite: attack success 0%, injection shown 100%, payload checks 100% (before: 3.3%, 83%, 94%, so it did not ship) |
| Harness suite (9 rows) | OK: 9 of 9 match; `real-redteam` 0.998 PASS (re-pinned from 0.960 FAIL) |
| Product tests (`pytest`) | 265 pass, 5 skip (49 in `tests/security/`) |
| Eval tests (`pytest eval/tests`) | 305: 302 pass, 1 strict `xfail` (MON-01), 2 skip |
| Lint on the changed files | No new error; the repo total went from 118 to 111 (all in team code) |
| Adversarial review | 12 findings confirmed (9 defects, one a regression in the first fix), all fixed with tests; 7 refuted (Section 4, items 7 to 10) |

## 4. Open items and risks

1. **MON-01 (Agents & Orchestration).** A failed tariff lookup crashes the claim. Give the fraud
   agent a fallback that sends the claim to a person.
2. **A blocked settlement stops the run (Agents & Orchestration).** `OutputGuardError` from the
   payment or letter guard ends the graph with an error. Nothing is paid, which is safe, but the
   claim should go back to a person through the graph, not stop.
3. **PII masking is regex only (Tools & Security).** Aadhaar, PAN, card, phone and e-mail are
   masked; names and addresses are not. Synthetic data has none, so this is a production item.
4. **The LLM checks are not measured.** The guard model (`CLAIMSENSE_GUARD_LLM=1`) and the
   grounding judge need a key and calibration against people before they gate anything. Both
   still take their model from the `coverage` entry (no `guard` or `judge` in `agents/llm.py::MODELS`).
5. **The scope check needs hooks.** It runs only with `tool_hooks=True`. The eval adapter runs
   without hooks; production must keep them on (`graph/build.py`).
6. **The fixed attack set flatters every defence** (notebook section 10). Run the adaptive
   attacker (Section 5) and add the notes that win to `eval/redteam/attacks.jsonl`.
7. **Intake must set the policy number (Deploy & Ops, API).** The scope check needs
   `packet["policy_number"]` from the login and the policy record. Without it there is no policy
   scope. A tool call outside the scope raises `ToolScopeError`, which stops the run (nothing
   leaks; routing it to a person is for Agents & Orchestration).
8. **Two older patterns in `guardrails.scan_text` may raise false alarms on real documents**
   (Tools & Security): `do not (apply|deduct|check)` ("Do not apply pressure on the wound") and
   `pre-approved by TPA` (cashless pre-authorisation wording). The cost is a person looking at
   an honest claim; they are tied to red-team cases, so the owner decides.
9. **Gaps that existed before this work** (found by the review, not regressions): a whole sentence
   spelt out with 3-letter words (`t h e`), close paraphrases of "ignore the co-payment",
   `verify_scope` topic words ("sports injury", "music therapy") in the unwired
   `process_input_pipeline`, and a guard-model outage reading as "clean" when
   `CLAIMSENSE_GUARD_LLM=1`.
10. **Pins cover the in-process tools** that `real_services()` binds, not the FastMCP server
    wrappers; pin those too before the agents reach tools over MCP.

## 5. How to check it with the real API

Run these in your own terminal (the VS Code terminal loads the key from `.env`; Claude's shell has
none). Git Bash, from the repository root. Use a new label each time.

```bash
source .venv/Scripts/activate
unset CLAIMSENSE_LLM                       # stub mode off: real models, costs money
mkdir -p runs/real-sec-logs

# 0. Free checks first (no key used)
pytest tests/security -q                                   # 49 product security tests
pytest eval/tests/test_io_guardrails.py eval/tests/test_security.py -q
python -m claimsense.hooks.pins                            # all tools match their pins

# 1. The release check on both splits, real agents (about $0.07)
python -X utf8 -m eval.full --label release-check-sec-1112 --splits dev,redteam | tee runs/real-sec-logs/full.txt

# 2. The scoreboard with real agents, and the guard model row (about $0.30)
python -X utf8 -m eval.security scoreboard --label real-scoreboard-1112 | tee runs/real-sec-logs/scoreboard.txt

# 3. The adaptive attacker against an honest claim (about $0.05; exit 1 means it won)
python -X utf8 -m eval.security attack --label real-attack-1112 --rounds 6 | tee runs/real-sec-logs/attack.txt

# 4. The agent suite with the guardrail section 5.2, real agents (about $0.13)
python -X utf8 -m eval.agent_suite --label real-agents-sec-1112 --variant v1,guarded | tee runs/real-sec-logs/agents.txt

# 5. Optional: every real run with the guard model reading what no pattern flags
CLAIMSENSE_GUARD_LLM=1 python -X utf8 -m eval.full --label release-check-guard-1112 --splits dev,redteam
```

What to look for:

| Run | Pass if |
|---|---|
| 0 | every test passes; "all 8 tools match their pins" |
| 1 | `## D. Combined gate`: harness gates held; agent-suite `attack_success_rate` 0 and `injection_surfaced` 1.0 |
| 2 | the "input guardrail (L15)" row: 0 attacks cleared, and honest claims right equal to the "no input guardrail" row |
| 3 | `attacker did not win`. If it won: its note is in `runs/security/real-attack-1112/attacker_notes.jsonl`; add it to the red-team seeds and fix the guardrail |
| 4 | section 5.2: recall 100%, no false alarm, 0 clean letters blocked, 9 of 9 leaks caught |

The first line of every run must say `REAL MODELS`. A real model can be steered by text in a way
the stub cannot, so a real-mode pass is the evidence that counts; record it in this card.
