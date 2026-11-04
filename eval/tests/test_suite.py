"""The suite's self-check.

`check()` is tested against synthetic reports rather than by running the suite, because the point
is the comparison logic, not the scores. One test does run every row end to end, because a suite
that cannot run is worth nothing.
"""

from __future__ import annotations

from eval.harness import suite
from eval.harness.safety_metrics import GATE_NAMES


def report(*, passed: bool, composite: float, gates: dict | None = None) -> dict:
    return {"passed": passed, "composite": composite, "gate_failures": gates or {}}


# ------------------------------------------------------------------ check()
def test_a_matching_row_reports_no_problem():
    row = suite.Row("r", "null", ["dev"], expect_pass=True, expect_composite=0.9)
    assert suite.check(row, report(passed=True, composite=0.9)) == []


def test_a_gate_that_should_fire_but_did_not_is_caught():
    """The most important check in the file. A safety gate that silently stops working is the
    worst failure this suite can have, and a score table would not show it."""
    row = suite.Row("r", "p", ["dev"], expect_gates=frozenset({"unsafe_settlement"}))
    problems = suite.check(row, report(passed=False, composite=0.1))
    assert any("did not fire" in p for p in problems)


def test_a_gate_firing_when_none_was_expected_is_caught():
    """A ceiling row must trip nothing. An unexpected gate means the fixtures or harness broke."""
    row = suite.Row("r", "gold-replay", ["dev"], expect_gates=frozenset())
    problems = suite.check(
        row, report(passed=True, composite=0.97, gates={"pii_exposure": ["CLM-0001"]})
    )
    assert any("unexpected gate" in p for p in problems)


def test_a_changed_composite_is_caught_outside_the_tolerance():
    row = suite.Row("r", "gold-replay", ["dev"], expect_composite=0.975)
    assert suite.check(row, report(passed=True, composite=0.975)) == []
    assert suite.check(row, report(passed=True, composite=0.980)) == []  # within 0.01
    assert suite.check(row, report(passed=True, composite=0.900)) != []


def test_a_wrong_verdict_is_caught():
    row = suite.Row("r", "null", ["dev"], expect_pass=False)
    assert any("expected passed" in p for p in suite.check(row, report(passed=True, composite=0.9)))


def test_an_unchecked_expectation_is_skipped():
    """`expect_pass=None` and `expect_composite=None` mean "do not check", for rows whose value
    is expected to move."""
    row = suite.Row("r", "claimsense", ["dev"])
    assert suite.check(row, report(passed=False, composite=0.123)) == []


# ------------------------------------------------------------------ the rows
def test_every_gate_is_exercised_by_some_row():
    """A gate with no row proving it fires is untested. Two gates are excluded on purpose:
    `eval_only_field_leak` and `pii_exposure` cannot be tripped by a fixture adapter, because the
    loader strips the fields and the fixtures echo no identity. Unit tests cover those two."""
    exercised = {gate for row in suite.ROWS for gate in row.expect_gates}
    untested = set(GATE_NAMES) - exercised - {"eval_only_field_leak", "pii_exposure"}
    assert untested == set(), f"no suite row proves these gates fire: {sorted(untested)}"


def test_row_labels_are_unique():
    """Labels name the output files, so a duplicate would overwrite a result."""
    labels = [row.label for row in suite.ROWS]
    assert len(labels) == len(set(labels))


def test_the_pipeline_rows_exist_and_are_named():
    """`--accept-pipeline` only relaxes rows in PIPELINE_ROWS, so the names must match real rows."""
    labels = {row.label for row in suite.ROWS}
    assert suite.PIPELINE_ROWS
    assert suite.PIPELINE_ROWS <= labels


def test_a_ceiling_row_expects_no_gate_and_a_pass():
    """If a ceiling row ever expected a gate, the suite would be asserting that a known-correct
    answer is unsafe."""
    for row in suite.ROWS:
        if row.label.startswith("ceiling"):
            assert row.expect_pass is True, row.label
            assert row.expect_gates == frozenset(), row.label


# ------------------------------------------------------------------ end to end
def test_the_whole_suite_runs_and_every_row_matches():
    """Slow by design: it runs all nine rows, including the real pipeline. This is the one test
    that would catch a regression anywhere in the harness."""
    code = suite.main(["--output", str(suite.RUNS_DIR / "suite-test.json")])
    assert code == 0, "a suite row no longer matches the outcome the report records"
