# ClaimSense Framework Rubric Score

## Technical Report

**Project:** ClaimSense, Agentic AI Capstone
**Subject:** The stack and the architecture, scored against the nine-dimension framework rubric.
**Owner role:** Eval and Red-Team
**Date:** 7 November 2026
**Document status:** Issue 1
**Writing standard:** ASD-STE100 Simplified Technical English
**Source file:** `docs/FRAMEWORK_RUBRIC_SCORE.md`. Edit this file. Then build the DOCX again.

**Result: 2.70 out of 5.**

---

## 1. About this document

### 1.1 Purpose

This document scores ClaimSense against the framework rubric in `docs/rubric_1.png` and
`docs/rubric_2.png`. The rubric has nine dimensions. Each one has a weight and a score from 0 to
5. The weighted scores give one number.

### 1.2 Scope

This document scores the **stack and the architecture**. It asks whether the project is built from
the right parts, and how far those parts are finished.

It does not score the answers that the agents give. The evaluation harness does that, and
`docs/EVAL_HARNESS_REPORT.md` holds its results. Section 6 explains why the two numbers are
different and must not be confused.

### 1.3 Source of the rubric

The rubric is Table 3.2 of *Building AI Agents for Finance*. The weights are the book's weights,
unchanged.

The book gives a tip: raise the weights of D3 and D7 for a regulated unit. Insurance is regulated,
so the tip applies to ClaimSense. The weights are **not** changed here, for one reason: an
unchanged rubric gives a number that you can compare with any other project scored on the same
table. Section 6.3 shows what the adjusted weights would give.

### 1.4 The honesty rule

**This rubric rewards architecture. ClaimSense's architecture is well ahead of its
implementation.** The project holds several large subsystems that are written, and in some cases
well tested, but that no code calls.

Every score in this document therefore describes the **working** state. Design that is written but
not connected does not earn points. It is recorded in Section 7 instead, with the score it would
earn once it is connected.

A rubric that credits intentions is not a measurement. It is a wish.

### 1.5 Terms

| Term | Meaning in this document |
|---|---|
| Dimension | One of the nine things the rubric measures. D1 to D9. |
| Level descriptor | The words the rubric gives for a score, such as "Some loops, branches" for D1 level 3. |
| Unwired | Code that exists and may be tested, but that no other code calls. |
| Weighted score | The score multiplied by the weight of the dimension. |

---

## 2. The rubric and the method

### 2.1 The nine dimensions

| Dim | Weight | 0 | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|---|---|
| D1 Task complexity fit | 15% | No multi-step | Simple chains only | Sequential tasks | Some loops, branches | Full DAGs, branches | Advanced reasoning, self-correction |
| D2 Ecosystem fit | 10% | Standalone only | Minimal integrations | Common tools | Platform integration | Multi-platform | Enterprise-ready ecosystem |
| D3 Compliance and audit | 15% | No logs | Basic logs | Structured logs | Trace IDs | Full traceability | Compliance-ready audit trails |
| D4 Data vs. orchestration | 15% | No data handling | Basic retrieval | Simple RAG | Vector search + context | Advanced RAG patterns | Hybrid (graphs + RAG) |
| D5 Experimentation | 5% | No testing tools | Manual testing | Basic test utilities | Test frameworks | A/B testing support | Full experimentation platform |
| D6 Cost and performance | 10% | High cost, slow | Moderate cost/speed | Good balance | Optimized paths | Caching + batching | Advanced optimization |
| D7 Safety and governance | 15% | No guardrails | Basic filtering | Content filtering | Input/output validation | Policy enforcement | Multi-layer safety + compliance |
| D8 Typed outputs | 10% | Plain text only | JSON strings | Basic validation | Schema validation | Pydantic models | Full type system + inference |
| D9 Interoperability | 5% | Locked in | Limited portability | Standard formats | Multi-provider | Protocol support | Full vendor neutrality |

The weights add up to 100.

### 2.2 The method

Score each dimension from 0 to 5. Multiply each score by its weight. Add the results. Divide by
100. The answer is a number between 0.0 and 5.0.

### 2.3 How a level was chosen

A dimension is a ladder. A score of 4 claims that levels 1 to 4 are all true.

Where a dimension has a strong upper rung and a hollow lower rung, this document scores the
**hollow** rung. D7 is the clearest example. ClaimSense has real policy enforcement, which is
level 4, but its input and output validation layer, which is level 3, is not connected. The score
is 3, not 4. A ladder with a missing step does not carry weight.

---

## 3. The scorecard

| Dim | Weight | Score | Weighted | One-line reason |
|---|---|---|---|---|
| D1 Task complexity fit | 15 | 4 | 60 | A real graph with branches and cycles, and a critic that corrects itself once. |
| D2 Ecosystem fit | 10 | 2 | 20 | OpenRouter and Chroma are connected. The MCP layer is not. |
| D3 Compliance and audit | 15 | 2 | 30 | A structured audit trail inside the graph state. No logging, no run IDs, no tracing. |
| D4 Data vs. orchestration | 15 | 2 | 30 | An advanced retriever exists and is tested. No agent calls it. |
| D5 Experimentation | 5 | 4 | 20 | A working harness with adapters, gates and a regression suite. |
| D6 Cost and performance | 10 | 1 | 10 | A cheap model default and a free offline mode. Nothing measures or limits cost. |
| D7 Safety and governance | 15 | 3 | 45 | Least privilege and a human approval gate work. The guardrail module is not connected. |
| D8 Typed outputs | 10 | 4 | 40 | Pydantic v2 everywhere, with real invariants. No static type checker. |
| D9 Interoperability | 5 | 3 | 15 | Three model families through one gateway. The protocol layer is not connected. |
| **Total** | **100** | | **270** | **270 / 100 = 2.70 out of 5** |

---

## 4. The finding behind the score

One pattern explains most of the low scores.

**ClaimSense does not lack capability. It lacks connections.** Four large subsystems are written,
and three of them are tested, but no code calls any of them.

| Subsystem | Size and state | Proof that nothing calls it |
|---|---|---|
| Hybrid retrieval | BM25, dense vectors, RRF, a cross-encoder reranker and query rewriting. 48 tests. | The only files that import `HybridRetriever` are `retrieval/index.py`, `retrieval/evaluate.py`, `retrieval/search.py` itself and `tests/retrieval/`. No file in `agents/`, `graph/` or `mcp_servers/` imports it. |
| Guardrails | `guardrails/guardrails.py` is 17 KB. It holds input screening, output screening, arithmetic checks and scrubbing. | A repository search for `guardrails` outside its own package finds one docstring in `eval/harness/safety_metrics.py` and two labels in `scripts/build_diagram.py`. No code calls it. |
| MCP servers | Five FastMCP files, including `policy_server.py` at 18 KB and `claims_db_server.py` at 17 KB. | A repository search for `mcp_servers` outside that folder returns nothing at all. The wiring in `agents/services.py` `real_services()` is commented out. |
| Hooks | The pre-tool budget check and the post-tool scrub that `docs/TECHNICAL_WORKFLOW.md` describes. | `src/claimsense/hooks/__init__.py` is one line long. The hooks do not exist. |

The calculator is a separate case. `calc/adjudication.py` raises `NotImplementedError` in all five
of its functions, and its tests are skipped. It is not unwired. It is unwritten. This is task T15.

**This finding is good news.** Connecting work is cheaper than inventing work, and Section 7 shows
that connection alone raises the score from 2.70 to about 3.90.

---

## 5. Evidence for each score

### 5.1 D1 Task complexity fit — score 4, weight 15%

**Matched: "Full DAGs, branches".**

The graph is real. `graph/nodes.py` defines 14 nodes. `graph/build.py` defines 11 fixed edges and
four conditional routers. The routers make true branches: after admissibility, after the critic
(pass, revise or escalate), and after a review (apply edits, senior review, settle, repudiate or
end).

Cycles exist. `revise` returns to `coverage`, and `apply_edits` returns to `critic`.

The critic corrects the system. It recomputes the worksheet with the calculator tool and checks
every deduction against its clause. Its feedback returns to the coverage agent.

The Reflexion loop in `reflexion/loop.py` is substantial. It holds `learn`, a leave-one-out
`ablate`, a `freeze` step, and assertions that refuse a held-out leak.

**Not 5, for three reasons.** `MAX_REVISIONS = 1` in `graph/state.py:15`, so the system corrects
itself once and then stops. The planner in `graph/planner.py` fills a fixed template and does no
reasoning. Without an API key the critic's meaning check falls back to a keyword table, and defect
AGT-13 records that this table rejects correct deductions for clauses 6.2.6 and 7.15.

### 5.2 D2 Ecosystem fit — score 2, weight 10%

**Matched: "Common tools".**

Two integrations work. The agents reach models through OpenRouter in `agents/llm.py`. The
retrieval layer uses Chroma. `docker-compose.yml` starts the API, Chroma, Prometheus and Grafana.

**Not 3.** The integration story of this project is MCP, and no code imports an MCP server. The
`langchain-mcp-adapters` package is declared in `pyproject.toml` and never used. The API serves
one endpoint, `/health`. The monitoring folder holds one `prometheus.yml` and no dashboards. The
compose file says that the MCP servers arrive in tasks T16 to T18.

Note of 11 November 2026: `eval/monitoring/` now holds six alert rules and a Grafana dashboard,
tested against a live Prometheus and Grafana. They are an evaluation tool. The product does not
use them yet, so this score does not change.

### 5.3 D3 Compliance and audit — score 2, weight 15%

**Matched: "Structured logs".**

The audit trail inside the graph state is good. `graph/state.py:74-81` defines four append-only
fields with reducers: `trace`, `handoffs`, `critic_history` and `edit_log`. Every node writes a
trace line. Each step records a typed `Handoff`. The edit log records the old clause, the new
clause and the reason.

Approval is bound to the work. A token carries `Worksheet.content_hash()`, and any edit voids
every earlier approval.

**Not 3.** There are no trace IDs. A search of `src/` for `import logging` or `getLogger` returns
nothing: the project has no logging at all. The only identifier is `claim_id`, used as a thread
id, so two runs of the same claim cannot be told apart. Langfuse and LangSmith appear as empty
keys in `.env.example` and in no code. `mcp_servers/approval_security.py` holds HMAC signing,
nonces and single-use records, and nothing imports it, so the live path issues plain tokens.

### 5.4 D4 Data vs. orchestration — score 2, weight 15%

**Matched: "Simple RAG".** This dimension has the widest gap in the report.

The corpus is real. The ingestion pipeline turns the policy PDF into 181 committed chunks, and
`get_clause` returns whole clauses.

The retriever is genuinely advanced. `retrieval/search.py` combines BM25 and dense vectors with
Reciprocal Rank Fusion, reranks a pool of 20 with a cross-encoder, and rewrites bill-line queries
through a glossary. `tests/retrieval/` defines 48 test functions, of which 24 need Chroma and skip when it is
absent. **On its own, this component scores 4.**

**Not 4, because the system is not the component.** No agent calls the retriever. The live data
layer for the agents is a keyword dictionary with three entries, `_SEARCH` in
`agents/services.py`, beside a nine-entry `_CLAUSE_TEXT`. The agents answer from a lookup table.

Three defects make the gap wider. AGT-05: the coverage agent has its own rewrite table that
fights the retriever's glossary. AGT-06: candidate clause text is cut at 400 characters, which
removes the operative words. AGT-12: the shared contract cannot carry a chunk id or page numbers,
so a citation loses its page.

### 5.5 D5 Experimentation — score 4, weight 5%

**Matched: "A/B testing support".**

The evaluation harness works and is used. `eval/harness/` holds 12 modules. It defines an adapter
protocol, with a floor adapter, a ceiling adapter, a fault-injecting adapter with six named
faults, and an adapter for the real pipeline. `scorecard.yaml` separates weighted metrics from six
catastrophic gates. `suite.py` runs nine configurations in one command and checks each against its
expected outcome. There are 292 evaluation tests (12 November 2026). A judge and a Cohen's kappa
calibration module exist. The agent suite compares variants side by side, and live monitoring runs
an A/B test on live traffic with Fisher's exact and Mann-Whitney tests.

Comparison is supported in practice. You can run two adapters and compare two labelled
scorecards, and the Reflexion loop can ablate one lesson at a time.

**Not 5.** `pyproject.toml` sets `testpaths = ["tests"]`, so a plain `pytest` in CI does not run
the harness tests at all. The CI evaluation gate is still commented out, and its threshold of 0.80
disagrees with the scorecard's 0.85. The judge is disabled and carries a weight of zero.
Experiments E1 to E4 have not run. Kappa has not been measured.

### 5.6 D6 Cost and performance — score 1, weight 10%

**Matched: "Moderate cost/speed".** This is the lowest score in the report.

Three things help. `agents/llm.py` defaults most roles to a cheap model and reserves a strong one
for reflection. `temperature=0` keeps runs repeatable. Stub mode runs the whole pipeline offline
and free.

**Not 2.** Nothing in the product measures or limits cost.

- There is **no response caching in the product**. The only `SQLiteCache` is in the teaching kit,
  `course/claimsense_hw/llm.py`. The product's `lru_cache` caches the client object, not answers.
- No code in `src/` counts tokens or cost. The fields exist only in the evaluation tools. Those
  tools measured real-model runs on 10 and 11 November 2026: about $0.0007 to $0.0008 per claim and
  a P95 of about 10 s. This is a measurement outside the product, so it does not move the score.
- `config/models.yaml` declares `max_tool_calls_per_claim: 40` and `max_cost_usd_per_claim: 0.20`.
  Nothing enforces either, because the budget hook is the empty `hooks/` folder.
- Defect AGT-09 means the model tiering contradicts itself. `agents/llm.py:16` sets coverage to
  `openai/gpt-4.1-mini`; `config/models.yaml:8` sets it to `openai/gpt-4o-mini`. You cannot call
  this a balance when you cannot say which model runs.
- There is no batching and no concurrency.

### 5.7 D7 Safety and governance — score 3, weight 15%

**Matched: "Input/output validation".**

Several real controls run in the live path. `agents/extraction.py` verifies every source span and
scans for injected instructions. The Pydantic contracts validate every object. The critic
recomputes the arithmetic. The stub `settle_claim` checks the approval token on the server side.

Two controls are stronger than the matched level. `agents/permissions.py` gives each agent a tool
allow-list, re-checks it inside `ToolBelt.call`, logs every allowed and denied call, and holds a
module-level assertion that `settle_claim` can never reach a non-settlement agent. The approval
gate interrupts the graph for a person, binds the token to the worksheet hash, and voids all
approvals when a line is edited. These are level-4 mechanisms and they work.

**Not 4, because the level-3 rung below them is hollow.**

- `guardrails/guardrails.py` is a complete 17 KB module with input screening, output screening and
  scrubbing. **No code calls it.**
- `hooks/` is empty, so there is no pre-tool check and no post-tool scrub.
- Defect AGT-04: `agents/coverage.py` puts bill-line text, the diagnosis and clause text into the
  model prompt **without** the `as_data` wrapper. Only the extraction agent honours the rule that
  outside text is data.
- Defect CLAIM-03: the loader passes an empty `documents` map, so 16 of the 30 red-team attacks
  never reach an agent. The defences cannot be exercised by most of the attack suite.
- The `llama-guard-4-12b` model is configured and never called.

### 5.8 D8 Typed outputs — score 4, weight 10%

**Matched: "Pydantic models". This is the cleanest match in the rubric.**

The contracts package holds six modules and about 300 lines of Pydantic v2. The models carry
real invariants, not just field types: `contracts/claim.py` and `contracts/worksheet.py` use
`model_validator(mode="after")` to check that lines and totals reconcile. All money is `Decimal`,
quantized to paise. The graph state is a `TypedDict` with `Annotated` reducers. Enumerations type
the agent names, line categories, deduction reasons and approval levels.

Model output is constrained, not merely parsed. Extraction uses `with_structured_output(Claim)`
and retries with the validation error fed back. The coverage agent may only choose a clause id
from the candidates it was given, and a fallback is logged.

**Not 5.** There is no static type checking anywhere: no mypy, no pyright, no `py.typed` marker,
and ruff selects no annotation rules. `ClaimState` is `total=False`, so every read is a guarded
`.get()` rather than a guarantee. The `Services` fields are `Callable[..., X]`, which types almost
nothing, and one line carries a `# type: ignore`.

### 5.9 D9 Interoperability — score 3, weight 5%

**Matched: "Multi-provider".**

This is real and in use. OpenRouter is a single gateway to many vendors, and
`config/models.yaml` deliberately mixes three families: OpenAI for the agents, Google Gemini for
the judge, and Meta Llama Guard for the guard role. Every model id can be overridden by an
environment variable. The data formats are plain JSONL, CSV and YAML. The evaluation harness is
deliberately decoupled from the product through an adapter protocol.

**Not 4.** MCP is the declared protocol layer and no code calls it. Defect AGT-09 is confirmed:
the model table in `agents/llm.py:14-21` hard-codes defaults that disagree with
`config/models.yaml`, and `config.model_for()` has **no callers inside `src/claimsense/`** at all.
`config/prompts/` is empty, so every prompt is an inline string. Chroma is the only vector store
and has no abstraction layer. LangGraph is woven through the graph layer.

---

## 6. What this score does not say

### 6.1 It is not the evaluation harness score

Two numbers describe this project. They answer different questions, and they must not be mixed.

| Number | Source | Question it answers |
|---|---|---|
| **2.70 out of 5** | This document | Are these the right parts, and how far are they built? |
| **0.220 composite, with a safety gate failing on 10 of 20 claims** | `docs/EVAL_HARNESS_REPORT.md` | Do the agents produce correct worksheets today? |

The rubric score is the kinder of the two. That is expected: this rubric rewards architecture, and
the architecture is the strongest part of ClaimSense.

### 6.2 It rewards structure, not correctness

A dimension can score well while the output is wrong. D8 scores 4 because the types are excellent.
The types do not make the amounts right; the harness shows the amounts are not right yet.

### 6.3 The weights are the book's, not the domain's

The book advises raising D3 and D7 for a regulated unit. One way to do that, keeping the sum at
100, is to raise D3 and D7 to 20% each and lower D1 and D4 to 10% each.

| Dim | Book weight | Insurance weight | Score |
|---|---|---|---|
| D1 Task complexity fit | 15 | 10 | 4 |
| D3 Compliance and audit | 15 | 20 | 2 |
| D4 Data vs. orchestration | 15 | 10 | 2 |
| D7 Safety and governance | 15 | 20 | 3 |
| All others | unchanged | unchanged | unchanged |

That gives **2.65**, against 2.70 with the book's weights.

The adjusted number is lower, and the reason matters: compliance and safety are two of the
dimensions where ClaimSense has the most unwired work, so giving them more weight exposes more of
the gap. **A rubric tuned to insurance makes this project look worse, not better.** That is an
argument for doing the connection work in Section 7 before the next review.

---

## 7. What would move the score

Each row gives the points that the work is worth. The list is ordered by value.

| Work | Dimensions it moves | Gain |
|---|---|---|
| **T16: connect the MCP servers and the hybrid retriever to the agents** | D4 2→4, D2 2→4, D9 3→4 | **+0.55** |
| Wire `hooks/`, add a run id, connect Langfuse | D3 2→4 | +0.30 |
| Add response caching and cost instrumentation to `src/` | D6 1→3 | +0.20 |
| Call `guardrails.py`, fix AGT-04 and fix CLAIM-03 | D7 3→4 | +0.15 |
| Raise `MAX_REVISIONS`, let the planner reason | D1 4→5 | +0.15 |
| Add mypy or pyright | D8 4→5 | +0.10 |
| Enable the CI eval gate, run E1 to E4, measure kappa | D5 4→5 | +0.05 |

### 7.1 The recommendation

**Connect what is already written, before writing anything new.**

The first four rows of that table are all connection work. Together they are worth +1.20, and they
take the score from 2.70 to about **3.90**. None of them invents a capability. Every one of them
turns an existing, tested subsystem into a working part of the product.

T16 alone is worth +0.55, because it moves three dimensions at once. It is the single most
valuable task in the project by this measure.

---

## 8. How to run this

The score in this document is a judgement, not a program. You cannot compute it from the code.
What you **can** run is a reader that prints it, and the tests that prove its arithmetic.

### 8.1 Print the scorecard

    python -m eval.tools.rubric_score

The tool reads the scores from this document's Section 3. It then recomputes the total itself. It
does not copy the total printed here, so if the two ever disagree, one of them is wrong and the
tests in Section 8.3 fail.

Two more views:

    python -m eval.tools.rubric_score --plan        # also: what would move the score
    python -m eval.tools.rubric_score --insurance   # also: the regulated-domain weighting
    python -m eval.tools.rubric_score --json        # machine-readable

### 8.2 Read the evidence

The table is a summary. Section 5 holds the evidence, with the file paths that prove each score.
Read Section 5 before you argue with a number.

### 8.3 Check the arithmetic

    pytest eval/tests/test_rubric_report.py -q

Fourteen tests run. They check that the nine dimensions are present, that the weights are the
book's weights, that the weights add up to 100, that every weighted cell equals its score times
its weight, that the stated total equals the recomputed sum, and that the Section 7 gains add up
to the improvement this report claims.

These tests exist because writing this report produced exactly that class of error: an early
draft of Section 6.3 used weights that added up to 105, and its total was wrong by 0.06. A reader
would not have caught it.

### 8.4 Rebuild the DOCX

**CAUTION: Do not edit the DOCX by hand. This Markdown file is the source. A hand edit is lost at
the next build.**

    python -m eval.tools.build_report_docx         --source docs/FRAMEWORK_RUBRIC_SCORE.md         --target docs/ClaimSense_Framework_Rubric_Score.docx

Run every command from the root of the repository.

### 8.5 What this does not run

This rubric scores the architecture. It does not run the agents and it does not score their
answers. To do that, use the evaluation harness:

    python -m eval.harness.suite

Section 6.1 explains why the two numbers are different.

---

## 9. Summary

ClaimSense scores **2.70 out of 5** on the nine-dimension framework rubric, with the book's
weights unchanged.

The strong dimensions are the ones that need no integration: the graph topology (D1, score 4), the
type system (D8, score 4) and the evaluation harness (D5, score 4).

The weak dimensions are all the same problem. Retrieval, guardrails, MCP and the hooks are written
but unconnected, which holds D4, D3 and D2 at 2 and D6 at 1.

The work that raises this score is connection work, not invention. Doing it takes the project from
2.70 to about 3.90 without one new feature.
