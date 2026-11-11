"""DeepEval suite for the ClaimSense pipeline (AAI-13: production-grade evaluation, pytest style).

Owner: Eval & Red-Team. How to run it: `eval/deepeval_suite/README.md`.

    test_trajectory.py       free, no key: the right tools (ToolCorrectnessMetric), no forbidden
                             tool, the tool budget (a deterministic custom metric)
    test_payload_quality.py  opt-in LLM judge: G-Eval with the payload checklist, and the
                             faithfulness of each deduction to the policy text it cites

Mode, as everywhere in the project: `CLAIMSENSE_LLM=stub` runs the free deterministic agents; a
key in the environment (and no stub setting) runs the real models and costs money.
"""
