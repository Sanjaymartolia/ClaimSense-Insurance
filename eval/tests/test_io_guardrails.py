"""The Tools & Security input and output guardrails on the eval data (L15).

`eval/agent_suite/io_guardrails.py` measures them. Defects G-01 to G-04 were pinned here as strict
`xfail` tests on 12 November 2026; they were fixed the same day (docs/GUARDRAILS_BEFORE_AFTER.md),
and these are now the regression tests.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("langgraph", reason='needs pip install -e ".[agents]"')
os.environ["CLAIMSENSE_LLM"] = "stub"  # no model call, ever

from eval.agent_suite import io_guardrails as io  # noqa: E402
from eval.agent_suite.dataset import load_dataset  # noqa: E402
from eval.agent_suite.trace import run_traced  # noqa: E402


@pytest.fixture(scope="module")
def cases():
    return load_dataset(("dev", "redteam"))


@pytest.fixture(scope="module")
def output_report(cases):
    return io.measure_output(cases, [run_traced(c.eval_case) for c in cases])


# ------------------------------------------------------------------------------------ input
def test_the_input_module_imports_and_its_pipeline_runs_with_its_defaults():
    """G-01 (a field `date: date` stopped the import) and G-04 (flags hid the functions)."""
    module, error = io.import_module(io.INPUT_MODULE)
    assert error is None
    assert not module.process_input_pipeline("Claim for policy POL-1 at the hospital.").blocked


def test_the_input_checks_catch_every_injection_without_a_false_alarm(cases):
    report = io.measure_input(cases)
    assert report.pipeline_error is None
    assert report.missed == [] and report.n_attacks == len(report.caught) > 0
    assert report.false_alarms == [] and report.scope_false_blocks == []
    assert report.pii_left_visible == [] and report.dev_documents_changed == []


# ----------------------------------------------------------------------------------- output
def test_the_output_pipeline_runs_and_passes_every_clean_letter(output_report):
    """G-02 (flags hid the functions) and G-03 (so check_output_safe blocked every letter)."""
    assert output_report.pipeline_error is None
    assert output_report.n_letters >= 10  # the clean set is real letters, not a handful
    assert output_report.check_output_safe_blocks == 0


def test_the_settlement_output_guard_stops_every_leak_and_leaves_clean_letters_alone(
    output_report,
):
    assert output_report.false_blocks == [] and output_report.changed == []
    assert output_report.missed == []
    assert len(output_report.caught) == len(io.load_seeds("output"))


def test_a_letter_naming_another_patient_is_blocked(output_report):
    """RT-005: only a check against the claim can see it; check_letter_safe does it."""
    assert output_report.wrong_patient["SettlementAgent.output_guard"] == "blocked"


def test_the_payment_ceiling_passes_clean_worksheets_and_blocks_an_overpayment(output_report):
    """L15 notebook section 7: a fooled step that proposes more than was claimed is not paid."""
    assert output_report.ceiling_false_blocks == []
    assert output_report.ceiling_blocks_overpayment
