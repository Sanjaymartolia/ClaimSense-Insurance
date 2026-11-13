"""Final database state on the real claims database: the checks pass on clean runs, each one
can fail on a corrupted snapshot, and the known defect stays visible (strict xfail)."""

import copy

import pytest

from eval.agentic import db_state as D
from eval.agentic import fixtures


@pytest.fixture(scope="module")
def approved():
    return D.run_on_db(fixtures.packet(), fixtures.policy(), "approve")


@pytest.fixture(scope="module")
def rejected():
    return D.run_on_db(fixtures.packet(), fixtures.policy(), "reject")


def _failed(run, snap) -> set[str]:
    out = D.checks(run, snap)
    known = set(D.KNOWN_DEFECTS)
    return {k for k, c in out.items() if c["applicable"] and not c["passed"]} - known


def test_approved_claim_leaves_one_settlement_for_the_approved_worksheet(approved):
    run, snap = approved
    assert run.error is None
    ws = run.state["worksheet"]
    assert len(snap["settlements"]) == 1
    row = snap["settlements"][0]
    assert row["status"] == "settled"
    assert row["amount"] == str(ws.total_payable)
    assert row["worksheet_hash"] == ws.content_hash()
    assert snap["fingerprints"] == run.n_lines
    assert _failed(run, snap) == set()


def test_rejected_claim_writes_nothing(rejected):
    run, snap = rejected
    assert snap["settlements"] == [] and snap["claims"] == [] and snap["fingerprints"] == 0
    assert _failed(run, snap) == set()


def test_inadmissible_claim_is_repudiated_at_zero():
    run, snap = D.run_on_db(fixtures.packet(), fixtures.inadmissible_policy(), "approve")
    assert [r["status"] for r in snap["settlements"]] == ["repudiated"]
    assert snap["settlements"][0]["amount"] == "0"
    assert _failed(run, snap) == set()


@pytest.mark.parametrize(
    ("corrupt", "metric"),
    [
        (lambda s: s["settlements"].append(dict(s["settlements"][0])), "one_write_or_none"),
        (lambda s: s["settlements"][0].update(status="repudiated"), "write_kind"),
        (lambda s: s["settlements"][0].update(amount="1.00"), "amount_matches"),
        (lambda s: s["settlements"][0].update(worksheet_hash="other"), "hash_matches"),
        (lambda s: s["settlements"][0].update(amount="99999999.00"), "amount_within_claimed"),
        (lambda s: s.update(fingerprints=0), "history_recorded"),
    ],
)
def test_each_check_can_fail(approved, corrupt, metric):
    run, snap = approved
    bad = copy.deepcopy(snap)
    corrupt(bad)
    assert metric in _failed(run, bad)


def test_a_write_on_a_rejected_claim_is_caught(approved, rejected):
    run, snap = rejected
    bad = copy.deepcopy(snap)
    bad["settlements"] = copy.deepcopy(approved[1]["settlements"])
    assert "one_write_or_none" in _failed(run, bad)


@pytest.mark.xfail(strict=True, reason="AGENTIC-14")
def test_claim_status_says_settled(approved):
    run, snap = approved
    assert D.checks(run, snap)["claim_status_updated"]["passed"]


def test_signing_secret_is_restored(monkeypatch):
    monkeypatch.delenv("CLAIMSENSE_APPROVAL_SECRET", raising=False)
    with D._signing_secret():  # noqa: SLF001
        pass
    import os

    assert "CLAIMSENSE_APPROVAL_SECRET" not in os.environ
