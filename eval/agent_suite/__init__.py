"""Trace-based agent eval suite (L13 hands-on, sections 1-7, applied to ClaimSense).

Owner: Eval & Red-Team. The scoring harness in `eval.harness` answers "how close is the final
worksheet to the gold?". This package answers the question the L13 notebook keeps asking: *what did
the agents do on the way there?* It records a trace for every claim (one span per graph node, tool
call and model call) and computes every metric from those traces.

    L13 section                              module
    1    the agent under test, and its trace  trace.py      (Span, Trace, run_traced, show_trace)
    2    the eval dataset                     dataset.py    (Case, load_dataset, composition)
    3    outcome metrics, pass@k / pass^k     outcome.py
    4    process metrics, cost and time       process.py
    5    unit tests + an input guardrail      guardrail.py, eval/tests/test_agent_trajectory.py
    6    LLM-as-a-judge                       judge.py      (code checks first; the judge is opt-in)
    7    the eval suite and a CI gate         suite.py + gate.yaml  (`python -m eval.agent_suite`)

It observes the product and never changes it: nothing under `src/claimsense/` is edited or patched
globally. Instrumentation wraps the per-claim `Services` object and subclasses `LocalRunner`.
"""
