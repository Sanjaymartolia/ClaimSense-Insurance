"""Rubric D3: every claim run has its own run id, and the audit trail reaches a file (rule 4)."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from claimsense.api.auth import parse_reviewers
from claimsense.api.main import create_app
from claimsense.api.runner import Settings
from claimsense.hooks.hooks import SAFE_AUDIT_FIELDS, AuditLog

from .conftest import ALICE, BOB, REVIEWERS, decide, sse, start

DEV = Path(__file__).resolve().parents[2] / "eval" / "golden_dev" / "claims.jsonl"


def claim_texts(claim_id: str) -> list[str]:
    """Free text of one synthetic dev claim (diagnosis, bill lines, patient name) that no audit
    record may hold."""
    for line in DEV.read_text(encoding="utf-8").splitlines():
        fixture = json.loads(line) if line.strip() else {}
        if fixture.get("claim_id") == claim_id:
            texts = [fixture["hospitalisation"]["diagnosis"]]
            texts += [item["description"] for item in fixture["bill_lines"]]
            texts.append(fixture["policyholder"]["display_name"])
            return [t for t in texts if t and len(t) > 4]
    raise AssertionError(f"no dev claim {claim_id}")


def test_a_run_id_is_content_free_and_stamped_on_every_tool_record():
    assert "run_id" in SAFE_AUDIT_FIELDS
    record = AuditLog(run_id="run-1").record("coverage", "calculate", allowed=True, status="ok")
    assert record.run_id == "run-1"
    assert AuditLog().record("coverage", "calculate", allowed=True, status="ok").run_id is None


def test_every_run_starts_with_its_own_run_id(client):
    first = sse(start(client, "CLM-0019"))
    assert first[0][0] == "run"
    started = first[0][1]
    assert (started["case_id"], started["kind"]) == ("CLM-0019", "start")
    assert len(started["run_id"]) == 32
    resumed = sse(decide(client, "CLM-0019", ALICE))
    assert resumed[0][0] == "run"
    assert resumed[0][1]["kind"] == "decision"
    assert resumed[0][1]["run_id"] != started["run_id"]


def test_the_audit_file_holds_each_run_and_its_tool_calls_and_no_claim_text(tmp_path):
    path = tmp_path / "audit" / "audit.jsonl"
    settings = Settings(
        checkpoints=":memory:", reviewers=parse_reviewers(REVIEWERS), audit_log=str(path)
    )
    with TestClient(create_app(settings)) as client:  # the app's start-up opens the sink
        start_run = sse(start(client, "CLM-0004"))[0][1]["run_id"]
        again = sse(start(client, "CLM-0004", case_id="CLM-0004-again"))[0][1]["run_id"]
        decided = sse(decide(client, "CLM-0004", ALICE))[0][1]["run_id"]
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    by_run = {}
    for row in rows:
        by_run.setdefault(row["run_id"], []).append(row)
    assert {start_run, again, decided} <= set(by_run)  # two cases of one claim, told apart
    for run_id in (start_run, again, decided):
        events = [row["event"] for row in by_run[run_id]]
        assert events[0] == "run.start" and events[-1] == "run.end", events
        assert "tool" in events  # the hooks' records carry the same run id
    end = next(r for r in by_run[decided] if r["event"] == "run.end")
    assert (end["kind"], end["decision"], end["approver_id"], end["status"]) == (
        "decision",
        "approve",
        "alice",
        "settled",
    )
    assert end["worksheet_hash"]  # the exact worksheet the approval bound to

    text = path.read_text(encoding="utf-8")
    for fragment in claim_texts("CLM-0004"):
        assert fragment not in text, fragment
    assert ALICE not in text and BOB not in text  # tokens never; approver ids only


def test_no_audit_file_without_the_setting(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = Settings(checkpoints=":memory:", reviewers=parse_reviewers(REVIEWERS))
    with TestClient(create_app(settings)) as client:
        sse(start(client, "CLM-0004"))
    assert list(tmp_path.iterdir()) == []
