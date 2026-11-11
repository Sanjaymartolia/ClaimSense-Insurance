"""The Tools & Security input and output guardrail modules, as components (L15).

Not wired into the pipeline: `eval/agent_suite/io_guardrails.py` measures them on the dev and
red-team data. Each strict `xfail` names an open defect (G-01 to G-04, in
`docs/AGENT_SUITE_REPORT.md`) and turns red the day it is fixed: then remove the mark.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("langgraph", reason='needs pip install -e ".[agents]"')
os.environ["CLAIMSENSE_LLM"] = "stub"  # no model call, ever

from eval.agent_suite import io_guardrails as io  # noqa: E402
from eval.agent_suite.dataset import load_dataset  # noqa: E402
from eval.agent_suite.trace import run_traced  # noqa: E402

G01 = "G-01: input_guardrails.py cannot be imported (pydantic field `date: date` clashes)"


@pytest.fixture(scope="module")
def cases():
    return load_dataset(("dev", "redteam"))


@pytest.fixture(scope="module")
def output_report(cases):
    return io.measure_output(cases, [run_traced(c.eval_case) for c in cases])


def _input_module():
    module, error = io.import_module(io.INPUT_MODULE)
    if module is None:
        pytest.xfail(f"{G01}: {error}")
    return module


# ------------------------------------------------------------------------------------ input
@pytest.mark.xfail(strict=True, reason=G01)
def test_the_input_guardrail_module_imports():
    assert io.import_module(io.INPUT_MODULE)[1] is None


@pytest.mark.xfail(
    strict=True,
    reason="G-01, then G-04: process_input_pipeline's flags mask_pii/verify_scope hide the "
    "functions of the same name, so its defaults raise TypeError",
)
def test_the_input_pipeline_runs_with_its_defaults():
    module = io.import_module(io.INPUT_MODULE)[0]
    assert module is not None
    assert not module.process_input_pipeline("Claim for policy POL-1 at the hospital.").blocked


def test_the_input_checks_raise_no_false_alarm_and_mask_every_pii_seed(cases):
    """Runs once G-01 is fixed (xfails until then): the dev claims are what an honest
    policyholder sends, so no injection or scope block there, and no PII seed stays visible."""
    report = io.measure_input(cases, _input_module())
    assert report.false_alarms == []
    assert report.scope_false_blocks == []
    assert report.pii_left_visible == []
    assert report.dev_documents_changed == []


# ----------------------------------------------------------------------------------- output
@pytest.mark.xfail(
    strict=True,
    reason="G-02: process_output_pipeline's flags scrub_leaks/verify_grounding hide the "
    "functions of the same name, so its defaults raise TypeError",
)
def test_the_output_pipeline_runs_with_its_defaults(output_report):
    assert output_report.pipeline_error is None


@pytest.mark.xfail(strict=True, reason="G-03: check_output_safe blocks every letter (via G-02)")
def test_check_output_safe_passes_the_clean_letters(output_report):
    assert output_report.check_output_safe_blocks == 0


def test_the_output_scrubbers_catch_planted_leaks_and_leave_clean_letters_alone(output_report):
    assert output_report.n_letters >= 10  # the clean set is real letters, not a handful
    assert output_report.false_blocks == [] and output_report.changed == []
    assert output_report.missed == []
    assert len(output_report.caught) == len(io.load_seeds("output"))


def test_a_letter_naming_another_patient_is_stopped_by_the_settlement_guard(output_report):
    """RT-005. The output module has no claim to compare names with; the settlement agent's own
    guard does, and it must keep doing so whatever replaces it."""
    assert output_report.wrong_patient["SettlementAgent.output_guard"] == "blocked"
