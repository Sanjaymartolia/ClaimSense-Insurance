"""Your bugs, one failing test each — written BEFORE the fix.

The loop:
  1. You see something wrong (run_one.py output, a weak category in the plot).
  2. Write the smallest test that shows it, and watch it FAIL.
  3. Fix the code. Watch it pass. Keep the test forever: the bug can't sneak back.

Tests here should need no LLM: call a node, a tool or a rules function directly,
or replace llm.chat_json with a lambda (see the last test in test_contract.py).
The rubric gives marks for this file. Delete the example once you have your own.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from claimsense_hw import graph  # noqa: E402


def test_example_a_citation_given_as_a_title_is_dropped_not_crashed():
    # Bug report (example): the model cited "Hospitalization" (a title) instead of the id.
    # Expected: the bad citation is dropped quietly, the run carries on.
    class R:
        chunks = []

    g = graph.ClaimGraph({"claim_id": "CLM-0000", "hospitalisation": {}}, retriever=R())
    assert g._clean_citations(["Hospitalization"]) == []
