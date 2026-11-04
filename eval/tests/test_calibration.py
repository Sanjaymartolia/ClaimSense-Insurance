"""Cohen's kappa and the calibration workflow's refusals.

The refusals are the point of these tests. A calibration step that silently passes is worse than
no calibration, because the report then claims a calibrated judge that nobody checked.
"""

from __future__ import annotations

import json

import pytest

from eval.calibration import judge_calibration as jc


def item(item_id: str, a: int, b: int) -> jc.CalibrationItem:
    return jc.CalibrationItem(
        item_id=item_id,
        rationale=f"r{item_id}",
        contexts=["c"],
        labels={"rater_a": a, "rater_b": b},
    )


# ------------------------------------------------------------------ kappa
def test_perfect_agreement_on_a_mixed_set_is_one():
    labels = [1, 0, 1, 0, 1, 0]
    assert jc.cohens_kappa(labels, labels) == pytest.approx(1.0)


def test_total_disagreement_is_negative():
    assert jc.cohens_kappa([1, 1, 0, 0], [0, 0, 1, 1]) < 0


def test_kappa_is_zero_when_agreement_is_only_chance():
    """Two raters who agree exactly as often as their label frequencies predict score 0."""
    a = [1, 1, 0, 0]
    b = [1, 0, 1, 0]
    assert jc.cohens_kappa(a, b) == pytest.approx(0.0)


def test_identical_constant_labels_count_as_perfect_not_undefined():
    """Both raters said 'grounded' to everything: no disagreement exists to measure. The 0/0 case
    is treated as perfect rather than crashing."""
    assert jc.cohens_kappa([1, 1, 1], [1, 1, 1]) == pytest.approx(1.0)


def test_high_raw_agreement_can_still_give_a_low_kappa():
    """The reason kappa is used at all: 90% agreement between two raters who almost always say
    'grounded' is mostly luck, and kappa must say so."""
    a = [1] * 18 + [0, 1]
    b = [1] * 18 + [1, 0]
    raw = sum(1 for x, y in zip(a, b, strict=True) if x == y) / len(a)
    assert raw == pytest.approx(0.9)
    assert jc.cohens_kappa(a, b) < 0.2


def test_mismatched_lengths_are_rejected():
    with pytest.raises(ValueError, match="differ in length"):
        jc.cohens_kappa([1, 0], [1])


def test_empty_input_is_rejected():
    with pytest.raises(ValueError, match="no items"):
        jc.cohens_kappa([], [])


# ------------------------------------------------------------------ loading
def test_the_shipped_template_refuses_to_load():
    """It has null labels on purpose. A half-finished file must not be mistaken for a real one."""
    template = jc.CALIBRATION_DIR / "calibration_set.template.jsonl"
    with pytest.raises(jc.CalibrationError, match="unlabelled"):
        jc.load_calibration_set(template)


def test_a_missing_file_explains_what_to_do(tmp_path):
    with pytest.raises(jc.CalibrationError, match="does not exist"):
        jc.load_calibration_set(tmp_path / "nope.jsonl")


def test_a_single_rater_is_rejected(tmp_path):
    """One rater cannot be checked against anyone, so the file is unusable by design."""
    path = tmp_path / "one.jsonl"
    path.write_text(
        json.dumps({"item_id": "1", "rationale": "r", "contexts": [], "labels": {"a": 1}}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(jc.CalibrationError, match="at least two raters"):
        jc.load_calibration_set(path)


# ------------------------------------------------------------------ the workflow
def test_too_few_items_fails_even_with_perfect_agreement():
    """Five items agreeing perfectly is not evidence. eval/README.md asks for 20+."""
    items = [item(str(i), 1, 1) for i in range(5)]
    result = jc.inter_rater_reliability(items)
    assert result["kappa"] == pytest.approx(1.0)
    assert result["enough_items"] is False
    assert result["passed"] is False


def test_enough_items_with_good_agreement_passes():
    items = [item(str(i), i % 2, i % 2) for i in range(jc.MIN_ITEMS)]
    result = jc.inter_rater_reliability(items)
    assert result["passed"] is True
    assert result["interpretation"] == "almost perfect"


def test_the_worst_rater_pair_decides_not_the_average():
    """One rater who disagrees with everyone is a rubric problem. Averaging the pairs hides them."""
    items = [
        jc.CalibrationItem(
            item_id=str(i), rationale="r", contexts=[], labels={"a": i % 2, "b": i % 2, "c": 1}
        )
        for i in range(jc.MIN_ITEMS)
    ]
    result = jc.inter_rater_reliability(items)
    assert result["pairwise_kappa"]["a|b"] == pytest.approx(1.0)
    assert result["kappa"] < 1.0, "the a|c disagreement must pull the reported kappa down"
    assert result["passed"] is False


def test_a_tied_item_is_excluded_from_judge_comparison():
    """If people split 1-1 on an item, it cannot fairly judge a judge."""
    items = [item("tied", 1, 0), *[item(str(i), 1, 1) for i in range(3)]]
    result = jc.judge_agreement(items, {i.item_id: 1.0 for i in items})
    assert result["skipped_ties"] == ["tied"]
    assert result["n_compared"] == 3


def test_judge_agreement_reports_missing_scores_rather_than_assuming():
    items = [item(str(i), 1, 1) for i in range(3)]
    result = jc.judge_agreement(items, {"0": 1.0})
    assert result["missing_judge_scores"] == ["1", "2"]
    assert result["n_compared"] == 1


def test_freeze_hash_changes_when_the_model_changes():
    items = [item(str(i), 1, 1) for i in range(3)]
    first = jc.freeze(items, "model-a")["frozen_hash"]
    second = jc.freeze(items, "model-b")["frozen_hash"]
    assert first != second, "the hash must pin the judge model, or a swap goes unnoticed"


def test_freeze_hash_changes_when_a_label_changes():
    before = jc.freeze([item("1", 1, 1)], "model-a")["frozen_hash"]
    after = jc.freeze([item("1", 1, 0)], "model-a")["frozen_hash"]
    assert before != after


def test_report_stops_at_step_two_when_the_people_disagree():
    """The workflow must not walk past a failed human-agreement check."""
    items = [item(str(i), 1, (i + 1) % 2) for i in range(jc.MIN_ITEMS)]
    text = jc.report(items, judge_scores={i.item_id: 1.0 for i in items})
    assert "do not agree well enough" in text
    assert "step 4" not in text
