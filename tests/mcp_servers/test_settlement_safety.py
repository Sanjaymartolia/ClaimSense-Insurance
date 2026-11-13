"""The money path in the claims database (rule 3: a person approves the exact change).

A claim gets one final decision: it is paid once, even if a new worksheet version is approved,
and a paid claim cannot then be repudiated. A repudiation needs a repudiation approval: a
settlement approval for the same claim does not authorise one. An approval is spent only when
the write succeeds, so a database failure leaves it usable. The claims-db MCP tools return a
`ToolError` on a database failure instead of raising to the agent.

These reproduce AGENTIC-02 to -07 from `eval/agentic/REPORT.md`.
"""

import hashlib
import hmac
import sqlite3
from decimal import Decimal

import pytest

from claimsense.contracts import ApprovalLevel, Worksheet, WorksheetLine
from claimsense.mcp_servers import approvals as appr
from claimsense.mcp_servers import claims_db
from claimsense.mcp_servers.claims_db import ClaimsDatabase, ToolError

CLAIM = "CLM-T-001"
SECRET = "test-only-approval-secret"  # noqa: S105 - signs approvals in an in-memory test database


@pytest.fixture
def db():
    database = ClaimsDatabase(":memory:")
    yield database
    database.close()


@pytest.fixture
def store():
    return appr.InMemoryApprovalStore()


def worksheet(total: str = "1000.00", version: int = 1) -> Worksheet:
    amount = Decimal(total)
    line = WorksheetLine(line_id="L1", claimed=amount, payable=amount)
    return Worksheet(
        claim_id=CLAIM, version=version, lines=[line], total_claimed=amount, total_payable=amount
    )


def adjudicator() -> appr.AuthenticatedApprover:
    return appr.DemoIdentityProvider().authenticate(CLAIM, ApprovalLevel.ADJUDICATOR)


def settle(db: ClaimsDatabase, store, ws: Worksheet, tokens: list) -> dict:
    return db.settle_claim(CLAIM, ws, tokens, False, store=store)


def repudiate(db: ClaimsDatabase, store, tokens: list) -> dict:
    return db.record_repudiation(CLAIM, ["not admissible"], tokens, store=store)


def decisions(db: ClaimsDatabase) -> list[tuple[str, str]]:
    rows = db._conn.execute("SELECT status, amount FROM settlements").fetchall()  # noqa: SLF001
    return [(r["status"], r["amount"]) for r in rows]


def block_writes(db: ClaimsDatabase) -> None:
    db._conn.execute(  # noqa: SLF001
        "CREATE TRIGGER block BEFORE INSERT ON settlements "
        "BEGIN SELECT RAISE(ABORT, 'simulated write failure'); END"
    )


# ---------------------------------------------------------------------- one final decision
def test_the_same_worksheet_is_never_paid_twice(db, store):
    ws = worksheet()
    settle(db, store, ws, [appr.issue_approval(ws, adjudicator(), store=store)])
    with pytest.raises(PermissionError, match="already been settled"):
        settle(db, store, ws, [appr.issue_approval(ws, adjudicator(), store=store)])
    assert decisions(db) == [("settled", "1000.00")]


def test_a_new_worksheet_version_does_not_pay_the_claim_again(db, store):
    """AGENTIC-02: idempotency was per worksheet hash, so version 2 wrote a second payment."""
    first = worksheet()
    settle(db, store, first, [appr.issue_approval(first, adjudicator(), store=store)])
    second = worksheet(total="900.00", version=2)
    with pytest.raises(PermissionError, match="final decision"):
        settle(db, store, second, [appr.issue_approval(second, adjudicator(), store=store)])
    assert decisions(db) == [("settled", "1000.00")]


def test_a_settled_claim_cannot_be_repudiated(db, store):
    """AGENTIC-04: `INSERT OR REPLACE` let a repudiation follow a payment."""
    ws = worksheet()
    settle(db, store, ws, [appr.issue_approval(ws, adjudicator(), store=store)])
    token = appr.issue_repudiation_approval(CLAIM, "subject", adjudicator(), store=store)
    with pytest.raises(PermissionError, match="final decision"):
        repudiate(db, store, [token])
    assert decisions(db) == [("settled", "1000.00")]


def test_a_repudiation_is_recorded_once(db, store):
    token = appr.issue_repudiation_approval(CLAIM, "subject", adjudicator(), store=store)
    assert repudiate(db, store, [token])["status"] == "repudiated"
    with pytest.raises(PermissionError):
        repudiate(db, store, [token])
    assert decisions(db) == [("repudiated", "0")]


# ---------------------------------------------------------------------- approval purpose
def test_a_settlement_approval_does_not_authorise_a_repudiation(db, store):
    """AGENTIC-03: any signed adjudicator approval for the claim used to be enough."""
    ws = worksheet()
    with pytest.raises(PermissionError):
        repudiate(db, store, [appr.issue_approval(ws, adjudicator(), store=store)])
    assert decisions(db) == []


def test_a_repudiation_approval_does_not_authorise_a_settlement(db, store):
    """The reverse, even when the repudiation approval names the worksheet's own hash."""
    ws = worksheet()
    token = appr.issue_repudiation_approval(CLAIM, ws.content_hash(), adjudicator(), store=store)
    with pytest.raises(PermissionError):
        settle(db, store, ws, [token])
    assert decisions(db) == []


def test_settlement_signatures_are_unchanged_by_the_purpose(monkeypatch):
    """Stored settlement approvals signed before purposes existed must still verify."""
    monkeypatch.setenv("CLAIMSENSE_APPROVAL_SECRET", SECRET)
    token = appr.issue_approval(worksheet(), adjudicator(), store=appr.InMemoryApprovalStore())
    fields = [
        token.claim_id,
        token.worksheet_hash,
        token.level.value,
        token.approver_id,
        token.decided_at.isoformat(),
        "nonce",
    ]
    legacy = hmac.new(SECRET.encode(), "|".join(fields).encode(), hashlib.sha256).hexdigest()
    assert appr._signature(token, "nonce", SECRET.encode()) == legacy  # noqa: SLF001


def test_the_sqlite_store_keeps_the_purpose_and_migrates_old_tables(db, monkeypatch):
    monkeypatch.setenv("CLAIMSENSE_APPROVAL_SECRET", SECRET)
    store = db.approval_store
    appr.issue_repudiation_approval(CLAIM, "subject", adjudicator(), store=store)
    [record] = store.find(CLAIM, "subject")
    assert record.purpose == appr.REPUDIATE and record.signature_valid()

    old = sqlite3.connect(":memory:")
    old.execute(
        "CREATE TABLE approvals (signature TEXT PRIMARY KEY, claim_id TEXT NOT NULL, "
        "worksheet_hash TEXT NOT NULL, level TEXT NOT NULL, approver_id TEXT NOT NULL, "
        "decided_at TEXT NOT NULL, nonce TEXT NOT NULL, auth_source TEXT NOT NULL, "
        "consumed INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL)"
    )
    appr.ensure_approvals_schema(old)
    columns = [row[1] for row in old.execute("PRAGMA table_info(approvals)")]
    assert "purpose" in columns
    old.close()


# ---------------------------------------------------------------------- failed writes
def test_a_failed_write_leaves_the_approval_usable(db, store):
    """AGENTIC-05: the approval was spent before the write, so the retry was refused."""
    ws = worksheet()
    token = appr.issue_approval(ws, adjudicator(), store=store)
    block_writes(db)
    with pytest.raises(sqlite3.Error):
        settle(db, store, ws, [token])
    db._conn.execute("DROP TRIGGER block")  # noqa: SLF001
    assert decisions(db) == []
    assert settle(db, store, ws, [token])["status"] == "settled"
    [record] = store.find(CLAIM, ws.content_hash())
    assert store.is_consumed(record)  # spent once the payment is recorded


@pytest.fixture
def default_db(db, monkeypatch):
    """`db` as the module default the MCP wrappers use, with its signed SQLite store."""
    monkeypatch.setenv("CLAIMSENSE_APPROVAL_SECRET", SECRET)
    monkeypatch.setattr(claims_db, "_DB", db)
    return db


def test_settle_tool_returns_a_tool_error_on_a_database_failure(default_db):
    """AGENTIC-06: an `IntegrityError` reached the agent."""
    ws = worksheet()
    token = appr.issue_approval(ws, adjudicator(), store=default_db.approval_store)
    block_writes(default_db)
    result = claims_db._tool_settle_claim(  # noqa: SLF001
        CLAIM, ws.model_dump(mode="json"), [token.model_dump(mode="json")], False
    )
    assert isinstance(result, ToolError) and result.code == "db_error"
    assert "simulated" not in result.error  # no database internals reach the agent


def test_policy_tool_returns_a_tool_error_on_a_database_failure(default_db):
    """AGENTIC-07: `_tool_get_policy` had no error handling."""
    default_db.close()
    result = claims_db._tool_get_policy("POL-1")  # noqa: SLF001
    assert isinstance(result, ToolError) and result.code == "db_error"
