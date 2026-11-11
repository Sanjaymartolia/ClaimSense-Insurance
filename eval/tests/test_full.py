"""`python -m eval.full`: the harness and the agent suite in one run.

The key property: a traced run and a harness adapter run give the harness scorer the same output,
so the combined report's harness numbers are the harness's own, not a near copy.
"""

from __future__ import annotations

import csv
import json

import pytest

pytest.importorskip("claimsense.agents", reason="needs pip install -e '.[dev]'")

from eval import full  # noqa: E402
from eval.agent_suite import suite as agent  # noqa: E402
from eval.agent_suite.dataset import load_dataset  # noqa: E402
from eval.harness.adapters import build_adapter  # noqa: E402
from eval.harness.loader import load_cases, policy_clause_ids  # noqa: E402
from eval.harness.run import run_adapter, score  # noqa: E402
from eval.harness.scorecard import load_scorecard  # noqa: E402
from eval.harness.suite import PIPELINE_ROWS, stub_llm  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _stub():
    with stub_llm():
        yield


@pytest.mark.parametrize("split", ["dev", "redteam"])
def test_traced_run_scores_exactly_like_the_harness_adapter(split):
    config, ids = load_scorecard(), policy_clause_ids()
    cases = load_cases([split])
    direct = score(cases, run_adapter(build_adapter("claimsense", cases), cases), ids, config, 0)

    res = agent.run_suite("t", "v1", load_dataset([split]))
    _, traced = full.harness_scorecard(res, "t")

    assert [(s.claim_id, s.score, s.gates_failed, s.parts) for s in traced] == [
        (s.claim_id, s.score, s.gates_failed, s.parts) for s in direct
    ]


def test_self_check_runs_every_row_except_the_pipeline_rows():
    assert {r.label for r in full.SELF_CHECK_ROWS} & PIPELINE_ROWS == set()
    assert len(full.SELF_CHECK_ROWS) == 7
    ok, lines = full.self_check()
    assert ok, "\n".join(lines)


@pytest.mark.parametrize(
    ("self_ok", "harness", "agent_ok", "passed"),
    [
        (True, True, True, True),
        (False, True, True, False),
        (None, True, True, False),  # a skipped self-check can never pass the run
        (True, False, True, False),
        (True, True, False, False),
    ],
)
def test_combined_gate_needs_all_three(self_ok, harness, agent_ok, passed):
    ok, lines = full.combined_gate(self_ok, harness, agent_ok)
    assert ok is passed
    assert (
        lines[0].strip().startswith("SKIP" if self_ok is None else ("PASS" if self_ok else "FAIL"))
    )


def test_one_command_writes_both_scorers_side_by_side(tmp_path):
    code = full.main(
        ["--stub", "--label", "t", "--splits", "dev", "--quiet", "--out", str(tmp_path)]
    )
    assert code == 1  # today's pipeline fails the gate; 0 here would mean a gate went quiet
    with (tmp_path / "rows.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 22
    assert {"correct", "path_complete", "h_score", "h_amounts", "h_gates_failed"} <= set(rows[0])
    summary = json.loads((tmp_path / "full.json").read_text(encoding="utf-8"))
    assert summary["self_check"]["ok"] is True
    assert summary["harness"]["v1"]["per_split"]["dev"] == pytest.approx(0.728, abs=0.01)
    assert (tmp_path / "harness.v1.scorecard.json").exists()
