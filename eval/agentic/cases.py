"""Shared case handling: load a case file, compare observed with expected, name the outcome."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from eval.harness.loader import read_jsonl

HERE = Path(__file__).resolve().parent

PASS = "pass"  # noqa: S105 - an outcome label, not a password
FAIL = "fail"
KNOWN_DEFECT = "known_defect"
DEFECT_FIXED = "defect_fixed"


def load(name: str) -> list[dict]:
    return read_jsonl(HERE / name)


def judge(group: str, case: dict, observed: dict[str, Any]) -> dict[str, Any]:
    """Every expected key must match. A case tagged `defect` describes correct behaviour the
    product does not have yet, so failing it is `known_defect`; passing it means the tag is stale.
    """
    mismatches = {
        key: {"expected": want, "observed": observed.get(key)}
        for key, want in case["expect"].items()
        if observed.get(key) != want
    }
    defect = case.get("defect")
    if defect:
        status = DEFECT_FIXED if not mismatches else KNOWN_DEFECT
    else:
        status = FAIL if mismatches else PASS
    return {
        "case_id": case["case_id"],
        "group": group,
        "status": status,
        "defect": defect,
        "mismatches": mismatches,
    }
