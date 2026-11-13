"""claims-db: policy / claim-history / settlement store. ClaimSense Role 4.

Signed approval records share the claims SQLite database. Settlement decisions
are verified server-side against the exact worksheet, including the senior
approval requirement derived from authoritative worksheet fields.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel


def _ensure_claimsense_on_path() -> None:
    try:
        import claimsense  # noqa: F401

        return
    except ModuleNotFoundError:
        pass
    env = os.environ.get("CLAIMSENSE_SRC")
    here = Path(__file__).resolve()
    candidates = [Path(env)] if env else []
    candidates += [
        here.parent.parent / "ClaimSense-Insurance" / "src",
        here.parent / "ClaimSense-Insurance" / "src",
    ]
    for candidate in candidates:
        if (candidate / "claimsense").is_dir():
            sys.path.insert(0, str(candidate))
            return


_ensure_claimsense_on_path()

from claimsense.agents.services import PastClaim, PolicyInfo, line_fingerprint  # noqa: E402
from claimsense.contracts import ApprovalToken, Claim, DeductionReason, Worksheet  # noqa: E402

try:
    from . import approvals as appr
except ImportError:
    import approvals as appr


class ToolError(BaseModel):
    error: str
    code: str = "claims_db_error"
    retryable: bool = False


def _default_db_path() -> str:
    return os.environ.get("CLAIMSENSE_CLAIMS_DB", "claimsense_claims.db")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS policies (
 policy_number TEXT PRIMARY KEY, period_start TEXT NOT NULL, period_end TEXT NOT NULL,
 first_inception TEXT NOT NULL, sum_insured TEXT NOT NULL,
 insured_pseudonym TEXT NOT NULL, declared_peds TEXT NOT NULL DEFAULT '[]',
 city_tier TEXT NOT NULL DEFAULT 'tier_1');
CREATE TABLE IF NOT EXISTS claims (
 claim_id TEXT PRIMARY KEY, policy_number TEXT NOT NULL, admission_date TEXT NOT NULL,
 status TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS bill_fingerprints (
 fingerprint TEXT NOT NULL, claim_id TEXT NOT NULL, policy_number TEXT NOT NULL,
 line_id TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_fp_policy ON bill_fingerprints(policy_number);
CREATE TABLE IF NOT EXISTS sub_limit_usage (
 policy_number TEXT NOT NULL, claim_id TEXT NOT NULL, sub_limit_name TEXT NOT NULL,
 amount TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settlements (
 claim_id TEXT NOT NULL, worksheet_hash TEXT NOT NULL, amount TEXT NOT NULL,
 status TEXT NOT NULL, settled_at TEXT NOT NULL,
 PRIMARY KEY (claim_id, worksheet_hash));
"""


class ClaimsDatabase:
    """SQLite-backed claims store with the signed approval store on the same connection."""

    def __init__(self, path: str | None = None):
        self.path = path or _default_db_path()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock, self._conn:
            self._conn.executescript(_SCHEMA)
        appr.ensure_approvals_schema(self._conn)
        self._approval_store: appr.ApprovalStore | None = None

    def close(self) -> None:
        self._conn.close()

    @property
    def approval_store(self) -> appr.ApprovalStore:
        if self._approval_store is None:
            self._approval_store = appr.SqliteApprovalStore(connection=self._conn, lock=self._lock)
        return self._approval_store

    def upsert_policy(self, policy: PolicyInfo) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT INTO policies
                (policy_number,period_start,period_end,first_inception,sum_insured,
                 insured_pseudonym,declared_peds,city_tier) VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(policy_number) DO UPDATE SET period_start=excluded.period_start,
                period_end=excluded.period_end, first_inception=excluded.first_inception,
                sum_insured=excluded.sum_insured, insured_pseudonym=excluded.insured_pseudonym,
                declared_peds=excluded.declared_peds, city_tier=excluded.city_tier""",
                (
                    policy.policy_number,
                    policy.period_start.isoformat(),
                    policy.period_end.isoformat(),
                    policy.first_inception.isoformat(),
                    str(policy.sum_insured),
                    policy.insured_pseudonym,
                    json.dumps(list(policy.declared_peds)),
                    policy.city_tier,
                ),
            )

    def record_history(
        self,
        claim: Claim,
        worksheet: Worksheet | None = None,
        *,
        sub_limit_usage: dict[str, Decimal] | None = None,
    ) -> None:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO claims "
                "(claim_id,policy_number,admission_date,status,created_at) VALUES (?,?,?,?,?)",
                (
                    claim.claim_id,
                    claim.policy_number,
                    claim.admission_date.isoformat(),
                    "recorded",
                    datetime.now(UTC).isoformat(),
                ),
            )
            if cur.rowcount == 0:
                return
            self._conn.executemany(
                "INSERT INTO bill_fingerprints (fingerprint,claim_id,policy_number,line_id) "
                "VALUES (?,?,?,?)",
                [
                    (
                        line_fingerprint(claim, line.description, line.amount),
                        claim.claim_id,
                        claim.policy_number,
                        line.line_id,
                    )
                    for line in claim.bill_lines
                ],
            )
            consumed: dict[str, Decimal] = {}
            if worksheet is not None:
                for wl in worksheet.lines:
                    for clause_id in {
                        d.clause_id for d in wl.deductions if d.reason == DeductionReason.SUB_LIMIT
                    }:
                        consumed[clause_id] = consumed.get(clause_id, Decimal("0")) + wl.payable
            for clause_id, amount in (sub_limit_usage or {}).items():
                if not isinstance(clause_id, str) or not clause_id.strip():
                    raise ValueError("sub-limit usage requires a non-empty clause id")
                value = Decimal(amount)
                if not value.is_finite() or value < 0:
                    raise ValueError(f"invalid sub-limit usage for clause {clause_id!r}")
                if clause_id not in consumed:
                    consumed[clause_id] = value
            rows = [
                (claim.policy_number, claim.claim_id, key, str(value))
                for key, value in consumed.items()
                if value > 0
            ]
            if rows:
                self._conn.executemany(
                    "INSERT INTO sub_limit_usage (policy_number,claim_id,sub_limit_name,amount) "
                    "VALUES (?,?,?,?)",
                    rows,
                )

    def delete_history(self, claim_id: str) -> None:
        if not isinstance(claim_id, str) or not claim_id.strip():
            raise ValueError("claim_id must be a non-empty string")
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM bill_fingerprints WHERE claim_id=?", (claim_id,))
            self._conn.execute("DELETE FROM sub_limit_usage WHERE claim_id=?", (claim_id,))
            self._conn.execute("DELETE FROM claims WHERE claim_id=?", (claim_id,))

    def get_policy(self, policy_number: str) -> PolicyInfo | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM policies WHERE policy_number=?", (policy_number,)
            ).fetchone()
        if row is None:
            return None
        return PolicyInfo(
            policy_number=row["policy_number"],
            period_start=date.fromisoformat(row["period_start"]),
            period_end=date.fromisoformat(row["period_end"]),
            first_inception=date.fromisoformat(row["first_inception"]),
            sum_insured=Decimal(row["sum_insured"]),
            insured_pseudonym=row["insured_pseudonym"],
            declared_peds=json.loads(row["declared_peds"] or "[]"),
            city_tier=row["city_tier"],
        )

    def all_policy_numbers(self) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT policy_number FROM policies ORDER BY policy_number"
            ).fetchall()
        return [row["policy_number"] for row in rows]

    def claim_history(self, policy_number: str) -> list[PastClaim]:
        with self._lock:
            claims = self._conn.execute(
                "SELECT claim_id,admission_date FROM claims WHERE policy_number=? "
                "ORDER BY created_at",
                (policy_number,),
            ).fetchall()
            fps = self._conn.execute(
                "SELECT claim_id,fingerprint FROM bill_fingerprints WHERE policy_number=?",
                (policy_number,),
            ).fetchall()
            subs = self._conn.execute(
                "SELECT claim_id,sub_limit_name,amount FROM sub_limit_usage WHERE policy_number=?",
                (policy_number,),
            ).fetchall()
        by_claim: dict[str, list[str]] = {}
        for row in fps:
            by_claim.setdefault(row["claim_id"], []).append(row["fingerprint"])
        usage: dict[str, dict[str, Decimal]] = {}
        for row in subs:
            bucket = usage.setdefault(row["claim_id"], {})
            key = row["sub_limit_name"]
            bucket[key] = bucket.get(key, Decimal("0")) + Decimal(row["amount"])
        return [
            PastClaim(
                claim_id=row["claim_id"],
                policy_number=policy_number,
                bill_fingerprints=by_claim.get(row["claim_id"], []),
                sub_limits_used=usage.get(row["claim_id"], {}),
                admission_date=date.fromisoformat(row["admission_date"]),
            )
            for row in claims
        ]

    def find_duplicate_bills(self, policy_number: str, claim: Claim) -> list[str]:
        seen = {fp for past in self.claim_history(policy_number) for fp in past.bill_fingerprints}
        return [
            line.line_id
            for line in claim.bill_lines
            if line_fingerprint(claim, line.description, line.amount) in seen
        ]

    def settle_claim(
        self,
        claim_id: str,
        worksheet: Worksheet | dict,
        approvals: list[ApprovalToken | dict],
        needs_senior: bool,
        *,
        store: appr.ApprovalStore | None = None,
        require_signed: bool | None = None,
    ) -> dict:
        """Settle only with signed approvals for this exact worksheet.

        `needs_senior` is caller input and may make approval stricter, never weaker.
        The server independently derives the mandatory senior gate from worksheet
        value and fraud flags (approval policy source of truth).
        """
        ws = worksheet if isinstance(worksheet, Worksheet) else Worksheet.model_validate(worksheet)
        tokens = [
            t if isinstance(t, ApprovalToken) else ApprovalToken.model_validate(t)
            for t in (approvals or [])
        ]
        if claim_id != ws.claim_id:
            raise PermissionError("claim_id does not match the worksheet")
        ws_hash = ws.content_hash()
        with self._lock:
            self._refuse_second_decision(claim_id, ws_hash)

        resolved_store = store if store is not None else self.approval_store
        effective_needs_senior = bool(needs_senior) or appr.needs_senior(ws, ws.fraud_flags)
        # Checked, not yet spent: the approvals are spent only once the payment is written, so a
        # failed write leaves them usable (AGENTIC-05).
        verdict = appr.verify_for_settlement(
            ws,
            tokens,
            effective_needs_senior,
            store=resolved_store,
            require_signed=require_signed,
            consume=False,
        )
        if not verdict.ok:
            raise PermissionError("; ".join(verdict.reasons))
        with self._lock, self._conn:
            # Again inside the write: a concurrent call may have decided the claim meanwhile.
            self._refuse_second_decision(claim_id, ws_hash)
            self._conn.execute(
                "INSERT INTO settlements (claim_id,worksheet_hash,amount,status,settled_at) "
                "VALUES (?,?,?,?,?)",
                (
                    claim_id,
                    ws_hash,
                    str(ws.total_payable),
                    "settled",
                    datetime.now(UTC).isoformat(),
                ),
            )
            self._conn.execute("UPDATE claims SET status='settled' WHERE claim_id=?", (claim_id,))
        for record in verdict.used:
            resolved_store.consume(record)
        return {
            "status": "settled",
            "claim_id": claim_id,
            "amount": str(ws.total_payable),
            "worksheet_hash": ws_hash,
        }

    def record_repudiation(
        self,
        claim_id: str,
        reasons: list[str],
        approvals: list[ApprovalToken | dict],
        *,
        store: appr.ApprovalStore | None = None,
        require_signed: bool | None = None,
    ) -> dict:
        tokens = [
            t if isinstance(t, ApprovalToken) else ApprovalToken.model_validate(t)
            for t in (approvals or [])
        ]
        if not tokens:
            raise PermissionError("repudiation needs an adjudicator decision")
        with self._lock:
            self._refuse_second_decision(claim_id)
        resolved_store = store if store is not None else self.approval_store
        verdict = appr.verify_repudiation(
            claim_id, tokens, store=resolved_store, require_signed=require_signed, consume=False
        )
        if not verdict.ok:
            raise PermissionError("; ".join(verdict.reasons))
        with self._lock, self._conn:
            self._refuse_second_decision(claim_id)
            self._conn.execute(
                "INSERT INTO settlements "
                "(claim_id,worksheet_hash,amount,status,settled_at) VALUES (?,?,?,?,?)",
                (claim_id, "repudiation", "0", "repudiated", datetime.now(UTC).isoformat()),
            )
            self._conn.execute(
                "UPDATE claims SET status='repudiated' WHERE claim_id=?", (claim_id,)
            )
        for record in verdict.used:
            resolved_store.consume(record)
        return {"status": "repudiated", "claim_id": claim_id, "reasons": list(reasons)}

    def _refuse_second_decision(self, claim_id: str, ws_hash: str | None = None) -> None:
        """A claim gets one final decision: paid once, or repudiated once, never both
        (AGENTIC-02, -04). The caller holds the lock."""
        row = self._conn.execute(
            "SELECT worksheet_hash, status FROM settlements WHERE claim_id=?", (claim_id,)
        ).fetchone()
        if row is None:
            return
        if ws_hash is not None and row["worksheet_hash"] == ws_hash:
            raise PermissionError("this worksheet version has already been settled")
        raise PermissionError(
            f"claim {claim_id} already has a final decision ({row['status']}); "
            "a claim is settled or repudiated once"
        )


_DB: ClaimsDatabase | None = None
_DB_LOCK = threading.Lock()


def get_db() -> ClaimsDatabase:
    global _DB
    with _DB_LOCK:
        if _DB is None:
            _DB = ClaimsDatabase()
        return _DB


def set_db(db: ClaimsDatabase) -> None:
    global _DB
    with _DB_LOCK:
        _DB = db


def get_policy(policy_number: str) -> PolicyInfo | None:
    return get_db().get_policy(policy_number)


def claim_history(policy_number: str) -> list[PastClaim]:
    return get_db().claim_history(policy_number)


def settle_claim(
    claim_id: str,
    worksheet: Worksheet | dict,
    approvals: list[ApprovalToken | dict],
    needs_senior: bool,
) -> dict:
    return get_db().settle_claim(claim_id, worksheet, approvals, needs_senior)


def record_repudiation(
    claim_id: str, reasons: list[str], approvals: list[ApprovalToken | dict]
) -> dict:
    return get_db().record_repudiation(claim_id, reasons, approvals)


def record_history(
    claim: Claim,
    worksheet: Worksheet | None = None,
    *,
    sub_limit_usage: dict[str, Decimal] | None = None,
) -> None:
    get_db().record_history(claim, worksheet, sub_limit_usage=sub_limit_usage)


def delete_history(claim_id: str) -> None:
    get_db().delete_history(claim_id)


def seed_demo_policy(db: ClaimsDatabase | None = None) -> PolicyInfo:
    policy = PolicyInfo(
        policy_number="POL-001",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 12, 31),
        first_inception=date(2024, 1, 1),
        sum_insured=Decimal("200000"),
        insured_pseudonym="PT-7731",
        declared_peds=[],
        city_tier="tier_1",
    )
    (db or get_db()).upsert_policy(policy)
    return policy


# MCP boundary wrappers. They never raise to an agent (CLAUDE.md): a database failure becomes a
# `db_error` naming only the exception class, never its message (it can quote SQL or data).
def _db_error(exc: sqlite3.Error) -> ToolError:
    return ToolError(error=f"claims database error ({type(exc).__name__})", code="db_error")


def _tool_get_policy(policy_number: str):
    """[read] The policy record for a policy number, or a ``ToolError``."""
    try:
        policy = get_policy(policy_number)
    except sqlite3.Error as exc:
        return _db_error(exc)
    return (
        policy if policy is not None else ToolError(error="policy not found", code="unknown_policy")
    )


def _tool_claim_history(policy_number: str):
    """[read] Earlier claims on a policy (duplicate and sub-limit checks), or a ``ToolError``."""
    try:
        claims = [past.model_dump(mode="json") for past in claim_history(policy_number)]
    except sqlite3.Error as exc:
        return _db_error(exc)
    return {"policy_number": policy_number, "claims": claims}


def _tool_settle_claim(claim_id: str, worksheet: dict, approvals: list[dict], needs_senior: bool):
    """[write] Pay a claim. Needs signed approvals for this exact worksheet; paid once only."""
    try:
        return settle_claim(claim_id, worksheet, approvals, needs_senior)
    except PermissionError as exc:
        return ToolError(error=str(exc), code="approval_denied")
    except RuntimeError as exc:
        return ToolError(error=str(exc), code="server_misconfigured")
    except (ValueError, KeyError, TypeError) as exc:
        return ToolError(error=str(exc), code="invalid_input")
    except sqlite3.Error as exc:
        return _db_error(exc)


def _tool_record_repudiation(claim_id: str, reasons: list[str], approvals: list[dict]):
    """[write] Record a repudiation. Needs a signed repudiation approval; one final decision."""
    try:
        return record_repudiation(claim_id, reasons, approvals)
    except PermissionError as exc:
        return ToolError(error=str(exc), code="approval_denied")
    except RuntimeError as exc:
        return ToolError(error=str(exc), code="server_misconfigured")
    except (ValueError, KeyError, TypeError) as exc:
        return ToolError(error=str(exc), code="invalid_input")
    except sqlite3.Error as exc:
        return _db_error(exc)


def server():
    """The claims-db MCP app, built without opening the database (tool listing, pins, tests)."""
    from fastmcp import FastMCP

    mcp = FastMCP("claims-db")
    mcp.tool(name="get_policy")(_tool_get_policy)
    mcp.tool(name="claim_history")(_tool_claim_history)
    mcp.tool(name="settle_claim")(_tool_settle_claim)
    mcp.tool(name="record_repudiation")(_tool_record_repudiation)
    return mcp


def main() -> None:
    get_db()
    server().run(show_banner=False)


if __name__ == "__main__":
    main()
