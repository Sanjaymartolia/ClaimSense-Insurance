"""The ship runner: stage selection, skip rules, exit-code mapping and the verdict. No stage
here runs a real tool; the subprocess tests use a one-line Python command."""

import argparse
import sys

import pytest

from eval.ship import runner as R


def _args(**over) -> argparse.Namespace:
    return R.parse_args(["--label", "t", *[a for k, v in over.items() for a in (f"--{k}", v)]])


def _all(stub: bool = True) -> list[R.Stage]:
    return R.stages("t", stub, 4, 5, "v1")


def _result(status: str, blocking: bool = True) -> R.Result:
    return R.Result("s", "w", blocking, status, 0, 0.0, "log")


def test_every_eval_family_is_a_stage():
    names = {s.name for s in _all()}
    assert {"tests", "lint", "release-gate", "tool-use", "deepeval", "security"} <= names
    assert {"retrieval", "ragas", "deepeval-judge", "attacker"} <= names


def test_only_ci_and_release_checks_block():
    blocking = {s.name for s in _all() if s.blocking}
    assert blocking == {
        "tests",
        "lint",
        "format",
        "tool-pins",
        "release-gate",
        "tool-use",
        "deepeval",
    }


def test_attacker_is_opt_in():
    assert "attacker" not in {s.name for s in R.select(_all(), _args())}
    chosen = R.select(_all(), R.parse_args(["--label", "t", "--attack"]))
    assert "attacker" in {s.name for s in chosen}


def test_only_and_skip():
    assert [s.name for s in R.select(_all(), _args(only="lint,tests"))] == ["tests", "lint"]
    assert "retrieval" not in {s.name for s in R.select(_all(), _args(skip="retrieval"))}
    with pytest.raises(SystemExit):
        R.select(_all(), _args(skip="nope"))


def test_stub_flag_reaches_paid_stages():
    by = {s.name: s for s in _all(stub=True)}
    assert "--stub" in by["release-gate"].cmd and "--stub" in by["security"].cmd
    real = {s.name: s for s in _all(stub=False)}
    assert "--stub" not in real["release-gate"].cmd
    # An uncalibrated judge never blocks: the paid DeepEval judge is its own report-only stage.
    assert ("CLAIMSENSE_DEEPEVAL_JUDGE", "1") not in real["deepeval"].env
    judge = real["deepeval-judge"]
    assert ("CLAIMSENSE_DEEPEVAL_JUDGE", "1") in judge.env
    assert not judge.blocking and judge.real_only


def test_child_env_forces_stub_and_utf8(monkeypatch):
    monkeypatch.delenv("CLAIMSENSE_LLM", raising=False)
    assert R.child_env(True, ())["CLAIMSENSE_LLM"] == "stub"
    assert "CLAIMSENSE_LLM" not in R.child_env(False, (("A", "1"),))
    assert R.child_env(False, (("A", "1"),))["A"] == "1"
    assert R.child_env(False, ())["PYTHONUTF8"] == "1"


def test_real_mode_needs_a_key_and_no_stub_override(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("CLAIMSENSE_LLM", raising=False)
    assert R.mode_problem(stub=True) == ""
    assert "OPENROUTER_API_KEY" in R.mode_problem(stub=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    assert R.mode_problem(stub=False) == ""
    monkeypatch.setenv("CLAIMSENSE_LLM", "stub")
    assert "--stub" in R.mode_problem(stub=False)


def _stage(code: int, blocking: bool = True, **kw) -> R.Stage:
    return R.Stage(
        "x", "x", blocking, (sys.executable, "-c", f"print('hi'); raise SystemExit({code})"), **kw
    )


@pytest.mark.parametrize(("code", "status"), [(0, R.PASSED), (1, R.FAILED), (2, R.ERROR)])
def test_exit_code_maps_to_status(tmp_path, code, status):
    res = R.run_stage(_stage(code), stub=True, log_dir=tmp_path)
    assert res.status == status and res.exit_code == code
    assert (tmp_path / "x.log").read_text(encoding="utf-8").strip() == "hi"


def test_missing_package_blocks_as_error_but_only_skips_a_report(tmp_path):
    gone = ("no_such_package_xyz",)
    assert R.run_stage(_stage(0, needs=gone), True, tmp_path).status == R.ERROR
    assert R.run_stage(_stage(0, False, needs=gone), True, tmp_path).status == R.SKIPPED


def test_real_only_stage_is_skipped_in_stub_mode(tmp_path):
    res = R.run_stage(_stage(1, False, real_only=True), True, tmp_path)
    assert res.status == R.SKIPPED and res.exit_code is None


def test_verdict():
    ok, bad, err = _result(R.PASSED), _result(R.FAILED), _result(R.ERROR)
    report_failed = _result(R.FAILED, blocking=False)
    assert R.verdict([ok, report_failed], stub=False) == (R.SHIP, 0)
    assert R.verdict([ok], stub=True) == (R.REHEARSAL, 0)
    assert R.verdict([ok, err, bad], stub=False) == (R.NO_SHIP, 1)
    assert R.verdict([ok, err], stub=False) == (R.NOT_VERIFIED, 2)


def test_existing_label_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "RUNS_DIR", tmp_path)
    (tmp_path / "t").mkdir()
    assert R.main(["--label", "t", "--stub", "--only", "tool-pins"]) == 2
