# How the code and report are reviewed

*Public on purpose: it is the specification. Read it before you start.*

A reviewer (a teammate from another role, or a model run three times, middle score taken)
reads `REPORT.md` and your code. **Marks only for what it can see and quote.** "I added
BM25" with no code and no number scores zero. **Saying something did not work still earns
marks**, if you measured it and show the plot.

## 1. Search — Lectures 5, 6 — 25 marks (TODO 1, 2)
- **0–8** Search left as shipped, or changed with nothing measured.
- **9–17** BM25 + RRF work, compared with dense using `--retrieval-only` recall and the
  `runs/log.png` plot. The supporting list never outranks the wording; you say which of
  the three options you chose and why.
- **18–25** Plus: chunking measured *separately* from search; one setting (`TOP_K`,
  `RRF_K` or `CHUNK_SIZE`) tried at 2–3 values with the plot; an honest note on how much
  this can gain on 167 clauses.

## 2. Grounding — Lecture 6 — 20 marks (TODO 3)
- **0–6** Whatever the model wrote is what the adjudicator gets.
- **7–14** The explanation is split into statements, each checked against retrieved
  clauses, with a cut-off you defend and a stated action below it.
- **15–20** Plus: what it did on the `sub_limit` claims (the case only retrieval can
  catch); the extra tokens and seconds (from the run log); whether you would keep it on.

## 3. Tools and safety — Lecture 7 — 25 marks (TODO 4, 5)
- **0–8** No real tool loop; no amounts.
- **9–17** A loop with a step limit; the model picks tools; a later call depends on an
  earlier one; a made-up tool, bad args or a failing tool never crashes the run.
- **18–25** Plus: an injection defence using at least two of the three approaches, tested
  on **every** injection case (`--redteam`: CLM-9001..9018, incl. the reworded RT-009..012), and a paragraph on what a reworded attack would
  still get past you. Full marks need the point that the guard is the code (the
  ApprovalToken check), not the model's judgement.

## 4. Flow — Lecture 8 — 30 marks (TODO 6)
- **0–9** Still the straight line, or a loop built without LangGraph.
- **10–20** Real branches (a claim that needs a human early takes a shorter path); a
  reasoned choice of which state fields grow vs. get replaced; output of
  `python -c "from claimsense_hw.graph import draw; draw()"` in the report.
- **21–30** Plus: memory shown by a two-turn conversation (`run_one.py --thread`); a
  settlement **blocked, then approved, then executed** (`--pause` then `approve.py --yes`),
  pasted; and a handover note with everything the adjudicator needs.

## Deductions (up to −10)
No method (changes on a hunch, no plot); a folder that does not run from a clean copy with
your documented commands; tuning to the dev gold (claim-id special cases, gold in prompts).

## Engineering habits (counted inside the four areas above)
- `tests/test_my_bugs.py` holds at least two real bugs, each written as a failing test first.
- Every result in the report has its plot from `runs/`.
