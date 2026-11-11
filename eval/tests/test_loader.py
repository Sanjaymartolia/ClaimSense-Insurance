"""The loader is the gate that stops the agent seeing the answer. These tests are that promise.

Run with:  pytest eval/tests -q
"""

from __future__ import annotations

import pytest

from eval.harness import loader
from eval.harness.models import ANSWER_HINT_FIELDS, EVAL_ONLY_FIELDS


def test_dev_split_loads_twenty_two_paired_cases():
    cases = loader.load_split("dev")
    assert len(cases) == 22
    assert all(case.claim.claim_id == case.gold.claim_id for case in cases)


def test_redteam_split_loads_thirty_paired_cases():
    cases = loader.load_split("redteam")
    assert len(cases) == 30
    assert all(case.gold.safety_critical for case in cases)
    assert all(case.gold.human_review_required for case in cases)


def test_unknown_split_is_rejected():
    with pytest.raises(ValueError, match="unknown split"):
        loader.load_split("production")


def test_strip_eval_only_removes_the_scenario_label_and_notes():
    raw = {
        "claim_id": "X",
        "scenario_label": "room_rent_breach",
        "fixture_notes": "the answer",
        "bill_lines": [],
    }
    stripped = loader.strip_eval_only(raw)
    for field in EVAL_ONLY_FIELDS:
        assert field not in stripped, f"{field} survived stripping"


def test_strip_eval_only_removes_answer_hints_from_bill_lines():
    raw = {
        "claim_id": "X",
        "bill_lines": [
            {
                "line_id": "X-L01",
                "description": "d",
                "amount_inr": 1,
                "category": "room_rent",
                "potentially_payable": True,
                "room_linked": False,
                "duplicate_of": "X-L00",
            }
        ],
    }
    line = loader.strip_eval_only(raw)["bill_lines"][0]
    for field in ANSWER_HINT_FIELDS:
        assert field not in line, f"{field} survived stripping"
    assert line["amount_inr"] == 1, "stripping must not remove data the agent needs"


def test_no_loaded_dev_claim_carries_an_eval_only_field():
    """The real fixtures, not a synthetic dict. This is the one that would catch a regression."""
    for case in loader.load_split("dev"):
        dumped = case.claim.model_dump()
        assert not (EVAL_ONLY_FIELDS & set(dumped)), case.claim_id
        for line in case.claim.bill_lines:
            assert not (ANSWER_HINT_FIELDS & set(line.model_dump())), line.line_id


@pytest.mark.parametrize(
    "path",
    [
        "../claimsense-heldout/claims.jsonl",
        "/var/held-out/gold.jsonl",
        "C:/data/held_out/claims.jsonl",
    ],
)
def test_heldout_paths_are_refused(path):
    """CLAUDE.md rule 5. The harness must not be the thing that reads the held-out set."""
    from pathlib import Path

    with pytest.raises(loader.HeldOutAccessError):
        loader.assert_not_heldout(Path(path))


def test_policy_clause_ids_excludes_the_superseded_table_row():
    """ADR-0004 made 12.5 unsearchable because it contradicts clause 6.1, so citing it is not
    grounding a decision in the governing wording."""
    ids = loader.policy_clause_ids()
    assert "new_india_arogya_sanjeevani:4.1" in ids
    assert "new_india_arogya_sanjeevani:12.5" not in ids
    assert len(ids) > 100
