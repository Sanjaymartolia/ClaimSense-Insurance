"""The calibration collector: which lines become items, round-robin picking, the row format the
loader expects, and the refusals. No model is called."""

import json
from types import SimpleNamespace

import pytest

from eval.calibration import collect as C
from eval.calibration import judge_calibration as J


def _out(claim_id: str, n: int, placeholder_on: tuple[int, ...] = (), no_context_on=()):
    rationales, contexts = {}, {}
    for i in range(1, n + 1):
        lid = f"{claim_id}-L{i:02d}"
        rationales[lid] = (
            f"Line {lid} was adjudicated under clause x:1."
            if i in placeholder_on
            else f"Reason {i} for {claim_id}."
        )
        if i not in no_context_on:
            contexts[lid] = [f"clause text {i}", "claim facts"]
    return SimpleNamespace(claim_id=claim_id, rationales=rationales, retrieved_contexts=contexts)


def test_only_real_reasons_with_context_become_candidates():
    per_claim = C.candidates([_out("A", 4, placeholder_on=(1,), no_context_on=(2,))])
    assert [r["line_id"] for r in per_claim[0]] == ["A-L03", "A-L04"]


def test_claims_without_any_usable_line_are_dropped():
    assert C.candidates([_out("A", 2, placeholder_on=(1, 2))]) == []


def test_pick_is_round_robin_and_capped():
    per_claim = C.candidates([_out("A", 5), _out("B", 1), _out("C", 2)])
    rows = C.pick(per_claim, 4)
    assert [r["line_id"] for r in rows] == ["A-L01", "B-L01", "C-L01", "A-L02"]
    assert [r["item_id"] for r in rows] == ["CAL-001", "CAL-002", "CAL-003", "CAL-004"]


def test_pick_stops_when_lines_run_out():
    assert len(C.pick(C.candidates([_out("A", 2)]), 24)) == 2


def test_rows_load_once_labelled_and_are_refused_before(tmp_path):
    rows = C.pick(C.candidates([_out(c, 2) for c in "ABCDEFGHIJ"]), 20)
    path = tmp_path / "set.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    with pytest.raises(J.CalibrationError, match="unlabelled"):
        J.load_calibration_set(path)
    for r in rows:
        r["labels"] = {"rater_a": 1, "rater_b": 1}
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    items = J.load_calibration_set(path)
    assert len(items) == 20 and items[0].contexts == ["clause text 1", "claim facts"]


def test_collect_refuses_an_existing_file(tmp_path):
    path = tmp_path / "set.jsonl"
    path.write_text("labels in here\n", encoding="utf-8")
    assert C.main(["collect", "--out", str(path)]) == 2
    assert path.read_text(encoding="utf-8") == "labels in here\n"


def test_collect_refuses_stub_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAIMSENSE_LLM", "stub")
    path = tmp_path / "set.jsonl"
    assert C.main(["collect", "--out", str(path)]) == 2
    assert not path.exists()


def test_score_stops_before_the_judge_when_people_disagree(tmp_path, monkeypatch):
    rows = C.pick(C.candidates([_out(c, 2) for c in "ABCDEFGHIJ"]), 20)
    for i, r in enumerate(rows):
        r["labels"] = {"rater_a": i % 2, "rater_b": (i // 2) % 2}  # chance-level agreement
    path = tmp_path / "set.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

    def no_judge():
        raise AssertionError("the judge must not run")

    monkeypatch.setattr("eval.harness.llm_judge_metrics._build_scorer", no_judge)
    assert C.main(["score", "--out", str(path)]) == 1


def test_pick_rotates_lines_and_skips_duplicate_explanations():
    a = {"claim_id": "A", "line_id": "A-L01", "rationale": "Same words.", "contexts": ["x"]}
    copy = {**a, "claim_id": "B", "line_id": "B-L01"}  # a red-team copy of a dev claim
    two = [
        {"claim_id": "C", "line_id": "C-L01", "rationale": "c1", "contexts": ["x"]},
        {"claim_id": "C", "line_id": "C-L02", "rationale": "c2", "contexts": ["x"]},
    ]
    # B's word-for-word copy is skipped. C is claim 2 of 3, so it starts at line 2 % 2 = 0.
    assert [r["line_id"] for r in C.pick([[a], [copy], two], 3)] == ["A-L01", "C-L01", "C-L02"]
    # A claim at index 1 with two lines starts at its second line.
    assert [r["line_id"] for r in C.pick([[a], two], 2)] == ["A-L01", "C-L02"]


def _set(tmp_path, n=3):
    rows = C.pick(C.candidates([_out(c, 1) for c in "ABCDEFGHIJ"[:n]]), n)
    for r in rows:
        r["contexts"] = ["4.1 clause", f"Claim {r['claim_id']} facts, as filed."]
    path = tmp_path / "calibration_set.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def _fill(path, labels):
    import csv

    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    for row, label in zip(rows, labels, strict=True):
        row["label_1_or_0"] = label
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=C.SHEET_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def test_sheets_split_policy_text_from_claim_facts_and_round_trip(tmp_path):
    path = _set(tmp_path)
    assert C.main(["sheets", "--out", str(path)]) == 0
    a, b = tmp_path / "sheet_rater_a.csv", tmp_path / "sheet_rater_b.csv"
    first = C.sheet_row(json.loads(path.read_text(encoding="utf-8").splitlines()[0]))
    assert first["policy_text_shown"] == "4.1 clause"
    assert first["claim_facts_shown"].startswith("Claim A facts")
    _fill(a, ["1", "0", "1"])
    _fill(b, ["1", "1", "1"])
    assert C.main(["import", "--a", str(a), "--b", str(b), "--out", str(path)]) == 0
    labels = [json.loads(t)["labels"] for t in path.read_text(encoding="utf-8").splitlines()]
    assert labels == [
        {"rater_a": 1, "rater_b": 1},
        {"rater_a": 0, "rater_b": 1},
        {"rater_a": 1, "rater_b": 1},
    ]
    assert C.main(["sheets", "--out", str(path)]) == 2  # never overwrites a sheet


def test_import_refuses_a_blank_or_bad_label(tmp_path):
    path = _set(tmp_path)
    C.main(["sheets", "--out", str(path)])
    a, b = tmp_path / "sheet_rater_a.csv", tmp_path / "sheet_rater_b.csv"
    _fill(a, ["1", "", "1"])
    _fill(b, ["1", "1", "yes"])
    before = path.read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="use 1 or 0"):
        C.main(["import", "--a", str(a), "--b", str(b), "--out", str(path)])
    assert path.read_text(encoding="utf-8") == before
