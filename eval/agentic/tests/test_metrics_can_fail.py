"""A metric that cannot fail measures nothing. Each corruption must trip the matching metric."""

import copy

import pytest

from eval.agentic import fixtures, trajectory_eval
from eval.agentic.expected_path import PathFacts, expected_calls
from eval.agentic.pipeline import Run, run_packet


@pytest.fixture(scope="module")
def clean() -> Run:
    return run_packet(fixtures.packet(), fixtures.policy())


@pytest.fixture
def run(clean: Run) -> Run:
    return copy.deepcopy(clean)


def failed(run: Run) -> set[str]:
    return {m["metric"] for m in trajectory_eval.score(run) if m["applicable"] and not m["passed"]}


def _index(run: Run, tool: str, agent: str | None = None) -> int:
    return next(
        i for i, e in enumerate(run.events) if e["tool"] == tool and agent in (None, e["agent"])
    )


def test_clean_trace_passes_everything(run: Run):
    assert run.error is None
    assert failed(run) == set()


def test_hand_counted_path_for_the_fixture():
    # 1 get_policy + 5 search + calc + history + policy + tariff + calc + critic calc
    # + 3 get_clause + settlement get_policy (payment ceiling) + settle + record_history = 18
    facts = PathFacts(5, True, True, [True], [3], [("adjudicator", "approve")])
    assert len(expected_calls(facts)) == 18


def test_swapped_order_fails_order_only(run: Run):
    a, b = _index(run, "claim_history"), _index(run, "tariff_range")
    run.events[a], run.events[b] = run.events[b], run.events[a]
    # The audit log still holds the true order, so the cross-check notices as well.
    assert failed(run) == {"tool_order", "hook_fired"}


def test_skipped_calculator_is_caught(run: Run):
    del run.events[_index(run, "calculate", "coverage")]
    assert {"tool_order", "call_counts", "correct_agent"} <= failed(run)


def test_extra_call_is_caught(run: Run):
    run.events.insert(1, copy.deepcopy(run.events[1]))
    assert {"tool_order", "call_counts"} <= failed(run)


def test_wrong_agent_fails_agent_only(run: Run):
    run.events[_index(run, "claim_history")]["agent"] = "coverage"
    assert "correct_agent" in failed(run)
    assert "tool_order" not in failed(run)


def test_settle_without_review_is_forbidden(run: Run):
    run.reviews.clear()
    assert "forbidden_calls" in failed(run)


def test_settle_before_final_approval_is_forbidden(run: Run):
    run.reviews[-1]["at_event"] = len(run.events)
    assert "forbidden_calls" in failed(run)


def test_denied_call_is_forbidden(run: Run):
    run.events.append(
        {
            "seq": 99,
            "agent": "fraud",
            "tool": "settle_claim",
            "status": "denied",
            "error_type": None,
            "args": {},
            "result": {},
        }
    )
    assert "forbidden_calls" in failed(run)


def test_settling_a_different_worksheet_is_caught(run: Run):
    event = run.events[_index(run, "settle_claim")]
    event["args"]["worksheet_hash"] = "other"
    assert "args_consistent" in failed(run)


def test_token_for_another_worksheet_is_caught(run: Run):
    run.events[_index(run, "settle_claim")]["args"]["approvals"][0]["hash"] = "other"
    assert "args_consistent" in failed(run)


def test_wrong_needs_senior_is_caught(run: Run):
    run.events[_index(run, "settle_claim")]["args"]["needs_senior"] = True
    assert "args_consistent" in failed(run)


def test_wrong_claim_argument_is_caught(run: Run):
    run.events[_index(run, "calculate")]["args"]["claim_id"] = "OTHER"
    assert "args_consistent" in failed(run)


def test_settled_amount_differing_is_caught(run: Run):
    run.events[_index(run, "settle_claim")]["result"]["amount"] = "1.00"
    assert "tool_result_used" in failed(run)


def test_critic_total_differing_is_caught(run: Run):
    run.events[_index(run, "calculate", "critic")]["result"]["total_payable"] = "1.00"
    assert "tool_result_used" in failed(run)


def test_clause_not_from_search_is_caught(run: Run):
    for event in run.events:
        event["result"].pop("clause_ids", None)
    assert "tool_result_used" in failed(run)


def test_missing_audit_row_is_caught(run: Run):
    run.audit.pop()
    assert "hook_fired" in failed(run)


def test_audit_for_another_claim_is_caught(run: Run):
    import dataclasses

    run.audit[0] = dataclasses.replace(run.audit[0], claim_id="OTHER")
    assert "hook_fired" in failed(run)


def test_stale_approval_accepted_is_caught():
    edited = run_packet(fixtures.packet(), fixtures.policy(), mode="edit")
    assert failed(edited) == set()
    edited.stale_token_refused = False
    assert failed(edited) == {"edit_invalidates"}
