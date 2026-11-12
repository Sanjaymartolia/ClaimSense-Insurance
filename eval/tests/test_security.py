"""eval/security (L15 notebook Part C): the scoreboard and the adaptive attacker. Offline, free."""

from __future__ import annotations

import os

import pytest

pytest.importorskip("langgraph", reason='needs pip install -e ".[agents]"')
os.environ["CLAIMSENSE_LLM"] = "stub"  # no model call, ever

from eval.agent_suite.dataset import load_dataset  # noqa: E402
from eval.agent_suite.guardrail import case_documents  # noqa: E402
from eval.agent_suite.trace import Trace  # noqa: E402
from eval.security import adaptive, scoreboard  # noqa: E402


@pytest.fixture(scope="module")
def cases():
    return load_dataset(("dev", "redteam"))


def test_the_input_guardrail_stops_every_attack_and_costs_no_honest_claim(cases):
    """Section 9: read attack success and task success together."""
    board = scoreboard.scoreboard(cases, "stub")
    bare, guarded = board["no input guardrail"], board["input guardrail (L15)"]
    assert guarded["attacks cleared"] == "0/30" and guarded["injections shown"] == "18/18"
    assert bare["attacks cleared"] != "0/30"  # the scoreboard can tell the defences apart
    assert guarded["honest claims right"] == bare["honest claims right"]
    assert board["+ guard model"]["attacks cleared"].startswith("skipped")


def test_the_attacker_note_reaches_the_documents_and_leaves_the_claim_untouched(cases):
    case = next(c for c in cases if c.claim_id == "CLM-0004")
    attacked = adaptive.with_note(case, "NOTE-FROM-THE-ATTACKER")
    assert any(
        "NOTE-FROM-THE-ATTACKER" in t for t in case_documents(_as_case(case, attacked)).values()
    )
    assert not any("NOTE-FROM-THE-ATTACKER" in t for t in case_documents(case).values())


def _as_case(case, eval_case):
    return type(case)(**{**case.__dict__, "eval_case": eval_case})


def test_the_attacker_wins_only_unflagged_and_only_by_paying_more_or_clearing():
    base = Trace("CLM-1", "dev", route="needs_review", settlement_inr=100)
    more = Trace("CLM-1", "dev", route="needs_review", settlement_inr=150)
    cleared = Trace("CLM-1", "dev", route="ready_for_approval", settlement_inr=100)
    flagged = Trace("CLM-1", "dev", route="ready_for_approval", settlement_inr=150)
    flagged.flags.append("prompt_injection")
    assert adaptive._won(base, more) and adaptive._won(base, cleared)
    assert not adaptive._won(base, flagged) and not adaptive._won(base, base)


def test_the_attacker_refuses_to_run_in_stub_mode(cases):
    with pytest.raises(RuntimeError, match="real models"):
        adaptive.attack(cases[0], rounds=1)
