"""The case files as pytest cases. A defect case is a strict xfail, so a fix makes it visible."""

import pytest

from eval.agentic import hook_eval, llm_eval, tool_eval, trajectory_eval
from eval.agentic.cases import DEFECT_FIXED, KNOWN_DEFECT, PASS, judge, load
from eval.agentic.run import DEFECTS


def _params(name: str) -> list:
    return [
        pytest.param(
            case,
            id=case["case_id"],
            marks=[pytest.mark.xfail(strict=True, reason=case["defect"])]
            if case.get("defect")
            else [],
        )
        for case in load(name)
    ]


@pytest.mark.parametrize("case", _params("tool_cases.jsonl"))
def test_tool_case(case: dict):
    assert tool_eval.run_case(case)["mismatches"] == {}


@pytest.mark.parametrize("case", _params("hook_cases.jsonl"))
def test_hook_case(case: dict):
    assert hook_eval.run_case(case)["mismatches"] == {}


@pytest.mark.parametrize("name", ["tool_cases.jsonl", "hook_cases.jsonl"])
def test_case_ids_are_unique(name: str):
    ids = [c["case_id"] for c in load(name)]
    assert len(ids) == len(set(ids))


def test_control_cases_outcomes():
    results = {r["case_id"]: r for r in trajectory_eval.control_cases()}
    defects = {k: r["defect"] for k, r in results.items() if r["status"] == KNOWN_DEFECT}
    assert defects == {
        "write-audit-covers-record_history": "AGENTIC-08",
        "long-bill-fits-budget": "AGENTIC-09",
    }
    assert all(r["status"] in (PASS, KNOWN_DEFECT) for r in results.values())


def test_llm_cases_pass():
    assert [r["mismatches"] for r in llm_eval.run_all() if r["status"] != PASS] == []


def test_rt003_duplicates_are_still_undetected():
    assert hook_eval.duplicate_detection_case()["status"] == KNOWN_DEFECT


def test_every_defect_tag_is_described():
    tags = {
        c["defect"]
        for n in ("tool_cases.jsonl", "hook_cases.jsonl")
        for c in load(n)
        if "defect" in c
    }
    assert tags <= set(DEFECTS)


def test_judge_outcomes():
    case = {"case_id": "x", "expect": {"a": 1}}
    assert judge("g", case, {"a": 1})["status"] == PASS
    assert judge("g", case, {"a": 2})["status"] == "fail"
    tagged = {**case, "defect": "D"}
    assert judge("g", tagged, {"a": 2})["status"] == KNOWN_DEFECT
    assert judge("g", tagged, {"a": 1})["status"] == DEFECT_FIXED
