"""ClaimSense evaluation package (L13, L15). Owner: Eval & Red-Team.

    eval.harness        the scoring harness. `python -m eval.harness.suite` runs everything.
    eval.calibration    the Cohen's kappa workflow for the judge
    eval.tools          supporting tools, not on the scoring path (the report DOCX builder)

Nothing in this package is imported by `src/claimsense/`: the harness observes the product, never
the reverse. See `eval/README.md` to run it, and `docs/EVAL_HARNESS_REPORT.md` for the full
documentation.
"""
