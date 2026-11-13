"""Whole-dataset behaviour: clean metrics, repeatable reports, nothing sensitive in a trace."""

import json

import pytest

from eval.agentic import fixtures
from eval.agentic import run as runner
from eval.agentic.pipeline import run_packet
from eval.agentic.recorder import Recorder


@pytest.fixture(scope="module")
def built():
    return runner.build_report(("dev",))


def test_dev_trajectory_metrics_are_clean(built):
    report, _ = built
    assert report["pipeline_errors"] == {}
    assert {k: v["failures"] for k, v in report["trajectory"].items() if v["failures"]} == {}
    assert runner.is_clean(report)


def test_report_is_repeatable(built):
    report, _ = built
    again, _ = runner.build_report(("dev",))
    first = json.dumps(report, sort_keys=True, default=str)
    assert first == json.dumps(again, sort_keys=True, default=str)


def test_traces_hold_no_health_details():
    run = run_packet(fixtures.packet(), fixtures.policy())
    text = json.dumps(runner._trace(run), default=str)
    for secret in ("appendicitis", "Appendectomy", "Private room", "Surgeon", "PT-AG-1"):
        assert secret not in text


def test_reviewer_payload_holds_no_gold(monkeypatch):
    # The reviewer is scripted from the review payload. No gold field may reach it.
    seen = []
    from eval.agentic import pipeline

    original = pipeline.Reviewer.__call__

    def spy(self, payload):
        seen.append(set(payload))
        return original(self, payload)

    monkeypatch.setattr(pipeline.Reviewer, "__call__", spy)
    run_packet(fixtures.packet(), fixtures.policy())
    assert seen and not any(k.startswith("gold") or k == "scenario_label" for s in seen for k in s)


def test_recorder_marks_a_raised_tool():
    run = run_packet(fixtures.packet(), fixtures.policy(), fail_on="calculate")
    event = next(e for e in run.events if e["tool"] == "calculate")
    assert (event["status"], event["error_type"]) == ("raised", "InjectedFault")


def test_recorder_keeps_refusals_in_order():
    recorder = Recorder()
    recorder.log.append({"agent": "fraud", "tool": "settle_claim", "allowed": False})
    assert [e["status"] for e in recorder.events] == ["denied"]
