# ClaimSense evaluation: what's missing and which frameworks fit

**Owner:** Eval & Red-Team. **Status:** research/reference note, nothing in this document has been
built yet — see "Suggested build order" at the end for what to do when someone picks this up.

## Where things stand today

`eval/README.md` and `docs/TECHNICAL_WORKFLOW.md` §8 already *describe* the metrics ClaimSense
wants: route accuracy, settlement/line-item amounts, review-flag F1, clause citation validity,
retrieval Recall@5/MRR, explanation quality via an LLM judge calibrated with Cohen's κ, latency,
cost, and red-team safety. The audit in `docs/CLAIMS_AND_GOLD_SET_FIXES.md` (EVAL-01, EVAL-02)
found that almost none of this is wired into the product yet:

- **EVAL-01 — no product harness.** `eval/` holds only data plus `build_cases.py`. The CI eval
  gate (commented out) calls `python -m eval.run --split dev --min-score 0.80`, but
  `eval/run.py` / `eval.run` **does not exist**. The only code that currently computes the
  weighted score (route 25% / amounts 35% / flags 25% / citations 15%) is the **teaching copy**
  `course/evalkit/metrics.py` — not product code.
- **EVAL-02 — no judge.** `config/models.yaml` already reserves a
  `judge: google/gemini-3.1-flash-lite` model slot, but nothing in `src/` calls it. No
  explanation/rationale-quality scoring and no Cohen's κ calibration exist anywhere.
- **Retrieval scoring already exists** — Recall@k and MRR are hand-written in
  `src/claimsense/retrieval/evaluate.py`. No framework involved, and none is needed.
- A repo-wide search confirms **zero eval-framework dependencies** anywhere today: no ragas,
  deepeval, trulens, promptfoo, giskard, langsmith. `pyproject.toml`'s `dev` extra has only
  `pytest` + `ruff`. Langfuse/LangSmith are named as *intended* stack in `CLAUDE.md` but unused
  (only empty placeholder keys in `.env.example`).

## The eval components, mapped to what to build and what framework (if any) fits

| # | Component | Status today | Framework fit | Recommendation |
|---|---|---|---|---|
| 1 | **Correctness scorer** — route / amounts / flags (F1) / citations, against `gold_worksheets.jsonl` | Implemented, but only as the *teaching* copy `course/evalkit/metrics.py` | None — this is code checking `Decimal` arithmetic and gold-vs-predicted field equality. No LLM, no framework (RAGAS/DeepEval don't check rupee math). | Port the logic into a **product** module, e.g. `eval/metrics.py`, reusing the same formulas (don't fork the teaching copy; both should converge on one implementation per RET-03's "two tools score the same file differently" lesson). |
| 2 | **Retrieval quality** — Recall@k, MRR over `retrieval_queries.jsonl` | Implemented in `src/claimsense/retrieval/evaluate.py` | RAGAS has `context_precision`/`context_recall`, but those are *LLM-graded* relevance judgments — strictly weaker evidence than exact labelled-clause-id recall, which this repo already has for free. | Keep the existing custom code as the primary metric. Optionally add RAGAS's `context_precision` later as a *secondary*, unlabelled signal for queries with no gold label yet — not a priority. |
| 3 | **Explanation / rationale groundedness** (does `CoverageDecision.rationale` actually follow from the cited clause text?) — EVAL-02 | **Not built at all.** This is the one real gap needing a judge. | This is exactly RAGAS's `Faithfulness` metric, or DeepEval's `FaithfulnessMetric`/`GEval`, or TruLens's "groundedness" leg of the RAG triad, or a 30-line custom prompt+call. | **Recommended: a small custom judge first** (`eval/judge.py`): one prompt in `config/prompts/`, one call through the existing OpenRouter client (`agents/llm.py`) using the already-reserved `judge` model, parsed into a 0/1 or 1–5 score + reason. Rationale: zero new dependencies, reuses config already in place, matches "write the least code that works." If/when the team wants a more battle-tested, published metric for the report, **RAGAS's `Faithfulness`** is the natural one to swap in — it's narrowly scoped (one pip install, no dashboard/service) and maps 1:1 onto this exact question. |
| 4 | **Judge calibration** — Cohen's κ against ≥20 human-labelled verdicts | Not built; only described in docs | `sklearn.metrics.cohen_kappa_score` (one new, extremely common dependency) vs. hand-rolling the formula (~10 lines, zero dependency) | Either is fine; hand-rolling keeps `dev` extra dependency-free, which matches today's pattern (no sklearn anywhere currently). Lean toward hand-rolled unless the team is already adding `scikit-learn` for something else. |
| 5 | **Red-team / safety scoring** — did the run settle a claim gold says needs a human? Was an attack caught by code vs. by the agent? | Partially built: the "settle when gold says review = 0" rule exists in `course/evalkit/metrics.py`; `src/claimsense/reflexion/evaluator.py`'s `SimulatedAdjudicator` replays gold corrections (rule-based, no LLM) | None needed — this is a safety invariant check against `eval/redteam/gold.jsonl`'s `expected_behavior`/`safety_critical` fields, not a generative-quality question. | Reuse the same pattern as #1, extended to read `eval/redteam/claims.jsonl` + `gold.jsonl` when `--redteam` is passed (the flag already referenced in `docs/TEAM_GUIDE.md`'s `scripts/evaluate_dev.py` usage). |
| 6 | **Latency & cost per claim** | Not built | None — this is instrumentation (timestamp + token-usage before/after each LLM call), not an eval-framework question. Langfuse/LangSmith (already named in `CLAUDE.md`'s stack) would give this "for free" via tracing if/when wired in, but that's an Ops/observability decision, separate from the `eval/` harness itself. | Out of scope for `eval/` specifically; note the dependency on whichever tracing tool Deploy & Ops picks, and in the meantime capture it directly in the trace row already described in `docs/TECHNICAL_WORKFLOW.md` §3 step 8b. |
| 7 | **The harness entry point** — `python -m eval.run --split dev --min-score 0.80`, which the CI eval gate (T48) already expects | **Does not exist** (`eval/run.py` is missing; the CI job is fully commented out in `.github/workflows/ci.yml`) | N/A — this is the orchestrator that calls #1 / #2 / #5 / #6 and produces the composite score + `runs/<label>.png`, same shape `scripts/evaluate_dev.py` already produces for the course kit. | Build last, once #1 (the product-side scorer) exists; then uncomment the CI job. |

## Quick-reference: eval/LLM-judge frameworks, scoped to this project

| Framework | What it's for | Fit here |
|---|---|---|
| **RAGAS** | Purpose-built RAG metrics: `Faithfulness`, `AnswerRelevancy`, `ContextPrecision`/`ContextRecall` | Best fit for component 3 (groundedness) specifically. Lightweight — pure `pip install`, no server. Would be the first real eval-framework dependency this repo takes on. |
| **DeepEval** | Broader LLM-testing framework: G-Eval (custom LLM-graded criteria), native `pytest` integration (`assert_test`), has its own faithfulness/hallucination metrics too | Viable alternative to RAGAS for component 3; its `pytest` integration is a nice fit since the repo already standardizes on `pytest`. Heavier surface area than RAGAS if only one metric is needed. |
| **TruLens** | "RAG triad" (groundedness, context relevance, answer relevance) + a built-in evaluation dashboard/DB | Overlaps RAGAS/DeepEval for component 3 but adds its own tracking DB and UI — more than this project needs for one metric. |
| **promptfoo** | YAML-config, provider-agnostic eval/red-team runner with `llm-rubric` assertions; has built-in red-team/jailbreak test generation | Interesting specifically for `eval/redteam/` test *generation* ideas later, but it's a Node.js CLI tool in an otherwise pure-Python repo — adds a second runtime. Not recommended as the primary judge mechanism. |
| **Langfuse / LangSmith** | Tracing + online eval/scoring, already named in `CLAUDE.md`'s intended stack | Belongs to the Ops/observability side (latency, cost, trace capture — component 6), not specifically the `eval/` harness. Already has placeholder keys in `.env.example`; not yet wired up. |
| **Custom code (no framework)** | Hand-written scorer | Already how components 1, 2, 5 work today, and the recommended starting point for component 3 (custom judge) and 4 (hand-rolled κ) too — consistent with the project's zero-new-dependency status quo and "least code that works" principle. |

## Suggested build order, if/when someone picks this up

1. `eval/metrics.py` — port `course/evalkit/metrics.py`'s scoring formulas into product code (reuse, don't re-derive).
2. `eval/judge.py` + `config/prompts/judge_explanation.md` — the custom faithfulness judge, calling the existing `judge` model from `config/models.yaml` via `agents/llm.py`'s client.
3. A small calibration script comparing judge verdicts to a human-labelled CSV, reporting Cohen's κ (hand-rolled, see component 4).
4. `eval/run.py` — the CLI entry point (`python -m eval.run --split dev [--redteam] --min-score X`), wiring together #1 (and `--redteam` mode), the existing `src/claimsense/retrieval/evaluate.py`, and #2's judge for a subset of cases.
5. Uncomment and fix the `eval-gate` job in `.github/workflows/ci.yml` (T48) to call `eval/run.py`.

None of this touches `course/`, `data/`, or any other role's folder beyond reading
`agents/llm.py`'s existing client and `config/models.yaml`'s existing `judge` entry — consistent
with staying inside `eval/`.

## Verification, once built

- `python -m eval.run --split dev` runs standalone, no CI needed, and prints the composite score,
  per-category breakdown, and a `runs/<label>.png` chart — same shape `scripts/evaluate_dev.py`
  already produces, so the team can compare side by side.
- `python -m eval.run --split dev --redteam` adds the 30 red-team cases and must report zero
  safety violations as a hard gate, matching the existing "settle when gold says review = 0" rule.
- Judge calibration: a one-off script prints Cohen's κ against the human-labelled CSV;
  `eval/README.md`'s own bar is "report Cohen's κ" — no fixed threshold has been set yet, so
  that's a Domain-lead/Eval decision when the time comes.
