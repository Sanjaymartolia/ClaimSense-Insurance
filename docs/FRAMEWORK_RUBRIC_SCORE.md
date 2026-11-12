# ClaimSense Framework Rubric Score

## Technical Report

**Project:** ClaimSense, Agentic AI Capstone
**Subject:** The stack and the architecture, scored against the nine-dimension framework rubric.
**Owner role:** Eval and Red-Team
**Date:** 12 November 2026 (Issue 1: 7 November 2026)
**Document status:** Issue 2
**Writing standard:** ASD-STE100 Simplified Technical English
**Source file:** `docs/FRAMEWORK_RUBRIC_SCORE.md`. Edit this file. Then build the DOCX again.

**Result: 2.85 out of 5.** (Issue 1: 2.70.)

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

### 1.6 Issue 2: what changed

The score does not come from the code. A person writes it, and `python -m eval.tools.rubric_score`
only adds it up (Section 8). Issue 1 was written on 7 November 2026. Between then and 12 November
the team connected several subsystems that Issue 1 called unwired, but nobody scored the rubric
again, so the tool printed 2.70 for five days.

Issue 2 scores every dimension again against the code of 12 November. Three auditors proposed
scores with file and line evidence. A separate skeptic then checked each proposal and tried to
refute it, with the honesty rule (Section 1.4) and the ladder rule (Section 2.3) of Issue 1
unchanged. Only a score that the skeptic upheld changed.

| Dim | Issue 1 | Proposed | Upheld | Why |
|---|---|---|---|---|
| D4 | 2 | 3 | **3** | The hybrid retriever is now called by the coverage agent through `real_services()`. |
| D6 | 1 | 2 | 1 | The new limit counts tool calls, not money; nothing in `src/` measures cost; AGT-09 is open. |
| D7 | 3 | 4 | 3 | The guardrails now run, but AGT-04 is still open, and Issue 1 put AGT-04 below level 4. |
| Others | | unchanged | unchanged | Section 5 records what changed in the evidence. |

The result moves from 2.70 to **2.85**.

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
| D2 Ecosystem fit | 10 | 2 | 20 | OpenRouter, Chroma and SQLite are connected. No MCP client exists and the API serves no claims. |
| D3 Compliance and audit | 15 | 2 | 30 | Structured audit in the graph state and the tool hooks. No run IDs, no trace IDs, no log sink. |
| D4 Data vs. orchestration | 15 | 3 | 45 | The coverage agent now searches the hybrid retriever. Only on the opt-in real-tools path. |
| D5 Experimentation | 5 | 4 | 20 | A working harness with adapters, gates and a regression suite. |
| D6 Cost and performance | 10 | 1 | 10 | A cheap model default, a tool-call limit and a search cache. Nothing in the product measures cost. |
| D7 Safety and governance | 15 | 3 | 45 | Guardrails, hooks and an approval gate now run. Coverage and critic prompts take outside text unwrapped. |
| D8 Typed outputs | 10 | 4 | 40 | Pydantic v2 everywhere, with real invariants. No static type checker. |
| D9 Interoperability | 5 | 3 | 15 | One gateway to many vendors, per-role model overrides. MCP servers exist but nothing speaks MCP. |
| **Total** | **100** | | **285** | **285 / 100 = 2.85 out of 5** |

---

## 4. The finding behind the score

One pattern explained most of the low scores in Issue 1.

**ClaimSense does not lack capability. It lacks connections.** On 7 November four large
subsystems were written, and three of them were tested, but no code called any of them. The table
below is the Issue 1 finding. Section 4.1 gives the state on 12 November.

| Subsystem | Size and state (7 November) | Proof that nothing called it (7 November) |
|---|---|---|
| Hybrid retrieval | BM25, dense vectors, RRF, a cross-encoder reranker and query rewriting. 48 tests. | The only files that import `HybridRetriever` are `retrieval/index.py`, `retrieval/evaluate.py`, `retrieval/search.py` itself and `tests/retrieval/`. No file in `agents/`, `graph/` or `mcp_servers/` imports it. |
| Guardrails | `guardrails/guardrails.py` is 17 KB. It holds input screening, output screening, arithmetic checks and scrubbing. | A repository search for `guardrails` outside its own package finds one docstring in `eval/harness/safety_metrics.py` and two labels in `scripts/build_diagram.py`. No code calls it. |
| MCP servers | Five FastMCP files, including `policy_server.py` at 18 KB and `claims_db_server.py` at 17 KB. | A repository search for `mcp_servers` outside that folder returns nothing at all. The wiring in `agents/services.py` `real_services()` is commented out. |
| Hooks | The pre-tool budget check and the post-tool scrub that `docs/TECHNICAL_WORKFLOW.md` describes. | `src/claimsense/hooks/__init__.py` is one line long. The hooks do not exist. |

The calculator was a separate case. On 7 November `calc/adjudication.py` raised
`NotImplementedError` in all five of its functions. It is now written (task T15).

### 4.1 The state on 12 November

| Subsystem | Connected now? | Evidence | What is still missing |
|---|---|---|---|
| Hybrid retrieval | **Yes**, on the real-tools path | `agents/services.py:277-281` binds `policy_kb.policy_search`, which calls the `HybridRetriever`. The coverage agent searches it for every bill line. Measured on 52 claims with real models: composite 0.976 and 0.980, every gate held. | It is opt-in (`scripts/run_one.py --real-tools`); the default is the stub table. AGT-05 and AGT-06 are open. |
| Guardrails | **Yes**, always | `agents/extraction.py:193-195` masks PII and `:61-77` scans for injection. `agents/settlement.py:34-42` runs `payment_guard` and `output_guard` before `settle_claim`, fail-closed. | The coverage and critic prompts do not wrap outside text in `as_data` (AGT-04). |
| MCP servers | **In process only** | `real_services()` imports `policy_kb`, `claims_db`, `tariff` and `approvals` as Python modules. Their tool definitions are pinned (`hooks/pins.py`). | No MCP client exists; `langchain-mcp-adapters` is not imported; compose runs no MCP service. |
| Hooks | **Yes**, on in `run_one.py` | `hooks/hooks.py` `HookedToolBelt`: tool ACL, tool-call budget, claim scope, audit that fails closed. | `build_graph` defaults to `tool_hooks=False`; the API serves no claims. |

**The finding still holds, with a smaller gap.** Most of the work left is again connection work:
make the real path the default, serve claims from the API, and speak MCP. Section 7 shows that
the top four items raise the score from 2.85 to about 3.65.

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

Issue 2 (12 November): `real_services()` now binds the MCP server modules, the SQLite claims
database and the Chroma retriever, so level 2 is stronger. Level 3 is still not met: the API serves
only `/health` (`api/main.py:14-16`), and no code is an MCP client. The servers have FastMCP entry
points over stdio, but the agents import them as Python modules. Score unchanged.

### 5.3 D3 Compliance and audit — score 2, weight 15%

**Matched: "Structured logs".**

The audit trail inside the graph state is good. `graph/state.py:74-81` defines four append-only
fields with reducers: `trace`, `handoffs`, `critic_history` and `edit_log`. Every node writes a
trace line. Each step records a typed `Handoff`. The edit log records the old clause, the new
clause and the reason.

Approval is bound to the work. A token carries `Worksheet.content_hash()`, and any edit voids
every earlier approval.

Issue 2 (12 November): level 2 is stronger. The tool hooks write a typed `AuditRecord` for every
allowed, denied or failed call (`hooks/hooks.py:315-330`, `:523-575`) to the
`claimsense.hooks.audit` logger. Approvals are HMAC-signed with a nonce
(`mcp_servers/approvals.py:309-320`) and, on the real-tools path, persist to SQLite with the
approver and the time. Loggers now exist in `hooks/`, `mcp_servers/` and `guardrails/`. The Issue 1
sentences "the project has no logging at all" and "the live path issues plain tokens" are no
longer true.

**Not 3.** There are still no trace IDs in the product. A search of `src/` for a run id or a trace
id finds none. The thread id is still `claim_id` (`graph/build.py:124`), so two runs of one claim
cannot be told apart. OpenTelemetry spans exist only in `eval/observability/`. Langfuse and
LangSmith appear in no product code. No code configures a log handler, so the `INFO` audit lines
reach no sink in a real run, and the in-memory audit records are not saved.

### 5.4 D4 Data vs. orchestration — score 3, weight 15%

**Matched: "Vector search + context".** Issue 1 scored 2 ("Simple RAG"). Issue 2 scores 3.

Issue 2 (12 November): the key fact of Issue 1, "no agent calls the retriever", is no longer true.
`real_services()` binds `policy_kb.policy_search` and `get_clause` (`agents/services.py:277-281`).
These call the shared `HybridRetriever`: BM25, dense Chroma vectors, RRF, a cross-encoder rerank and
a glossary rewrite. The coverage agent searches it for every bill line and puts the retrieved
clause text into the model prompt as candidates (`agents/coverage.py`). A citation now carries its
page in `source_url` (`mcp_servers/policy_kb.py`), which partly closes AGT-12. The evaluation
measured this path on 52 claims with real models: composite 0.976 and 0.980 in two runs, every gate
held (`docs/terminal.md`).

**Not 4**, because the component is level 4 but the system path is not:

- The real retriever runs only on the opt-in `--real-tools` path of `scripts/run_one.py`. The
  default is still the keyword table `_SEARCH` in `agents/services.py`, and the API serves no
  claims.
- AGT-05 is open: the coverage agent rewrites the query with its own `REWRITE` table before the
  retriever applies its glossary.
- AGT-06 is open: the model sees only the first 400 characters of each candidate clause.
- No product test runs the agents against the real retriever end to end.

The Issue 1 text follows, for the record.

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
expected outcome. There are 318 evaluation tests (12 November 2026). A judge and a Cohen's kappa
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

Issue 2 (12 November): two things changed, and neither moves the score.

- The tool hooks now enforce `max_tool_calls_per_claim` and fail closed (`hooks/hooks.py:140-148`,
  `:539-546`). This limits tool calls, not money: `max_cost_usd_per_claim` is still not enforced,
  on purpose (`hooks/hooks.py:9-12`).
- `policy_kb.policy_search` caches its answers per process (`_cached_hits`). This fixes the
  retrieval latency (p95 per claim 33.7 s to 3.8 s with stub agents), but it is a search cache, not
  a model-response cache, and it runs only on the real-tools path.

Nothing in `src/` counts tokens or cost yet, and AGT-09 is still open. The evaluation tools now
measure cost in every real run (about $0.0013 per claim on 12 November), but that is a
measurement outside the product.

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

Issue 2 (12 November): the level-3 rung is now mostly real. The extraction agent masks PII before
the model reads a document and runs `classify_injection_fast` over every document and bill line
(`agents/extraction.py:61-77`, `:193-195`). `SettlementAgent` runs `payment_guard` and
`output_guard` before `settle_claim`, fail-closed, and a block sends the claim to a person
(`agents/settlement.py:34-42`, `graph/nodes.py:358-397`). `hooks/hooks.py` adds claim scope, a
tool-call budget and an audit that fails closed, and `real_services()` refuses a tool whose
definition changed (`hooks/pins.py`). Measured with real models: 0 of 30 attacked claims cleared,
18 of 18 injections shown to the reviewer (`docs/SECURITY_REPORT_CARD.md`).

**Still not 4, because one level-3 gap that Issue 1 named is open.** The first two bullets below are
fixed; the others are as Issue 1 wrote them, with notes.

- Fixed: `guardrails/` is now called by the extraction and settlement agents.
- Fixed: `hooks/` now holds the pre-tool checks (on in `run_one.py`, off by default in
  `build_graph`).
- Defect AGT-04: `agents/coverage.py` puts bill-line text, the diagnosis and clause text into the
  model prompt **without** the `as_data` wrapper, and so does the critic. Only the extraction agent
  honours the rule that outside text is data. **Still open on 12 November.** The injection scan does
  not cover the diagnosis or the procedure, and its findings become flags only after the coverage
  model has read the text.
- Defect CLAIM-03: the loader passes an empty `documents` map, so 16 of the 30 red-team attacks
  never reach an agent. The defences cannot be exercised by most of the attack suite.
- The `llama-guard-4-12b` model is configured and never called. Issue 2: a guard-model check now
  exists but is off by default (`CLAIMSENSE_GUARD_LLM=1`), and `get_llm("guard")` falls back to the
  coverage model, not Llama Guard.

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

Issue 2 (12 November): unchanged at 3, and the level-3 rung is thinner than Issue 1 said. Every
product agent defaults to one family (`openai/gpt-4.1-mini`); the Gemini judge is used only by the
evaluation. The MCP servers now have pinned tool definitions, but nothing consumes them over the
protocol.

---

## 6. What this score does not say

### 6.1 It is not the evaluation harness score

Two numbers describe this project. They answer different questions, and they must not be mixed.

| Number | Source | Question it answers |
|---|---|---|
| **2.85 out of 5** | This document | Are these the right parts, and how far are they built? |
| **0.984 composite, every gate held, on 52 dev and red-team claims (12 November; 0.220 on 7 November)** | `docs/EVAL_HARNESS_REPORT.md`, `docs/terminal.md` | Do the agents produce correct worksheets today? |

On 7 November the rubric score was the kinder of the two. On 12 November the harness score is the
kinder one: the answers are now mostly right, while several parts are still not connected to the
default product path.

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
| D4 Data vs. orchestration | 15 | 10 | 3 |
| D7 Safety and governance | 15 | 20 | 3 |
| All others | unchanged | unchanged | unchanged |

That gives **2.75**, against 2.85 with the book's weights.

The adjusted number is lower, and the reason matters: compliance and safety are two of the
dimensions where ClaimSense has the most unwired work, so giving them more weight exposes more of
the gap. **A rubric tuned to insurance makes this project look worse, not better.** That is an
argument for doing the connection work in Section 7 before the next review.

---

## 7. What would move the score

Each row gives the points that the work is worth. The list is ordered by value.

| Work | Dimensions it moves | Gain |
|---|---|---|
| **Give every claim run a run id, send the audit log to a sink, and trace from `src/`** | D3 2→4 | **+0.30** |
| Count tokens and USD per claim in `src/`, enforce `max_cost_usd_per_claim`, settle AGT-09, add a model-response cache | D6 1→3 | +0.20 |
| **T37: serve claims from the API with `real_services()` and hooks on; run the MCP servers over the protocol** | D2 2→3, D9 3→4 | +0.15 |
| Make the real retriever the default product path, fix AGT-05 and AGT-06 | D4 3→4 | +0.15 |
| Wrap coverage and critic prompts in `as_data` (AGT-04), scan the diagnosis, close CLAIM-03 | D7 3→4 | +0.15 |
| Raise `MAX_REVISIONS`, let the planner reason | D1 4→5 | +0.15 |
| Add mypy or pyright | D8 4→5 | +0.10 |
| Enable the CI eval gate, run E1 to E4, measure kappa | D5 4→5 | +0.05 |

Issue 1 listed T16 (connect the MCP servers and the retriever) at +0.55. It is half done: the
retriever is connected (D4 2→3, +0.15), but no code speaks MCP and the API serves no claims.

### 7.1 The recommendation

**Connect what is already written, before writing anything new.**

The first four rows of that table are worth +0.80 together, and they take the score from 2.85 to
about **3.65**. Three of them are connection work: a run id and a log sink, the API endpoint, and
the real retriever as the default. Only the cost row needs new code in `src/`.

The run id and the log sink are worth the most (+0.30), because D3 carries 15% and sits at 2.

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

ClaimSense scores **2.85 out of 5** on the nine-dimension framework rubric, with the book's
weights unchanged (Issue 2, 12 November 2026; Issue 1 scored 2.70 on 7 November).

The strong dimensions are the ones that need no integration: the graph topology (D1, score 4), the
type system (D8, score 4) and the evaluation harness (D5, score 4).

Since Issue 1 the retriever, the guardrails and the hooks were connected. Only the retriever moved
a score (D4 2→3): the guardrails left one level-3 gap open (AGT-04), and the hooks limit tool
calls, not cost.

The weak dimensions are now audit (D3 at 2: no run id, no log sink), cost (D6 at 1: nothing in the
product measures it) and integration (D2 at 2: no API endpoint, no MCP client). The top four items
in Section 7 take the project from 2.85 to about 3.65.
