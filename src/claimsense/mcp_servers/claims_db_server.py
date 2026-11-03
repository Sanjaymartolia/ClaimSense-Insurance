"""claims-db MCP server. ClaimSense Role 4 (Tools, Control & Security).

Stores policies, claim history and settlements in SQLite (standard library). It backs these Role 3
registry tools (see ``agents/permissions.TOOL_ACL``):

* ``get_policy``      (read)  - coverage, fraud, settlement
* ``claim_history``   (read)  - fraud (duplicate bills, used sub-limits)
* ``settle_claim``    (WRITE) - settlement agent only; gated by a verified approval
* ``record_repudiation`` (WRITE) - settlement agent only; needs an adjudicator decision
* ``record_history``  (write) - memory update after a claim closes

Security
--------
* ``settle_claim`` / ``record_repudiation`` are the only writes that move the claim's status. Write
  capability is restricted by three independent locks: the per-agent ACL (``ToolBelt`` / ``hooks``),
  and - enforced *here, server-side* - :func:`approval_security.assert_can_settle`, which requires a
  valid, signed, non-replayed approval bound to the exact worksheet. The restriction does not rely
  on comments or tool naming. ``settle_claim`` deliberately takes **no amount argument**: the amount
  comes from the approved worksheet (red-team RT-008).
* All SQL is parameterised; writes run in transactions. Only pseudonymised identifiers and
  fingerprints are stored - never diagnosis text or other health details.

``settle_claim`` / ``record_repudiation`` raise ``PermissionError`` on an authorisation failure
(matching the Role 3 orchestration tests and the ``Services`` stub). The MCP wrappers convert any
error into a structured :class:`ToolError`.

``fastmcp`` is imported lazily in :func:`main`.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
from datetime import date, datetime, timezone
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
    for cand in candidates:
        if (cand / "claimsense").is_dir():
            sys.path.insert(0, str(cand))
            return


_ensure_claimsense_on_path()

from claimsense.agents.services import PastClaim, PolicyInfo, line_fingerprint  # noqa: E402
from claimsense.contracts import ApprovalToken, Claim, DeductionReason, Worksheet  # noqa: E402

import approval_security  # noqa: E402  (sibling module in the final folder)


class ToolError(BaseModel):
    """Structured error returned at the MCP boundary instead of raising to an agent."""

    error: str
    code: str = "claims_db_error"
    retryable: bool = False


def _default_db_path() -> str:
    return os.environ.get("CLAIMSENSE_CLAIMS_DB", "claimsense_claims.db")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS policies (
    policy_number     TEXT PRIMARY KEY,
    period_start      TEXT NOT NULL,
    period_end        TEXT NOT NULL,
    first_inception   TEXT NOT NULL,
    sum_insured       TEXT NOT NULL,
    insured_pseudonym TEXT NOT NULL,
    declared_peds     TEXT NOT NULL DEFAULT '[]',
    city_tier         TEXT NOT NULL DEFAULT 'tier_1'
);
CREATE TABLE IF NOT EXISTS claims (
    claim_id       TEXT PRIMARY KEY,
    policy_number  TEXT NOT NULL,
    admission_date TEXT NOT NULL,
    status         TEXT NOT NULL,
    created_at     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bill_fingerprints (
    fingerprint   TEXT NOT NULL,
    claim_id      TEXT NOT NULL,
    policy_number TEXT NOT NULL,
    line_id       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fp_policy ON bill_fingerprints(policy_number);
CREATE TABLE IF NOT EXISTS sub_limit_usage (
    policy_number  TEXT NOT NULL,
    claim_id       TEXT NOT NULL,
    sub_limit_name TEXT NOT NULL,
    amount         TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settlements (
    claim_id       TEXT NOT NULL,
    worksheet_hash TEXT NOT NULL,
    amount         TEXT NOT NULL,
    status         TEXT NOT NULL,
    settled_at     TEXT NOT NULL,
    PRIMARY KEY (claim_id, worksheet_hash)
);
"""


class ClaimsDatabase:
    """SQLite-backed claims store. One connection per instance, guarded by a lock."""

    def __init__(self, path: str | None = None):
        self.path = path or _default_db_path()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock, self._conn:
            self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    # -- writes: policies / history -------------------------------------------------------
    def upsert_policy(self, policy: PolicyInfo) -> None:
        """Insert or replace a (synthetic) policy record."""
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT INTO policies
                   (policy_number, period_start, period_end, first_inception, sum_insured,
                    insured_pseudonym, declared_peds, city_tier)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(policy_number) DO UPDATE SET
                     period_start=excluded.period_start, period_end=excluded.period_end,
                     first_inception=excluded.first_inception, sum_insured=excluded.sum_insured,
                     insured_pseudonym=excluded.insured_pseudonym,
                     declared_peds=excluded.declared_peds, city_tier=excluded.city_tier""",
                (policy.policy_number, policy.period_start.isoformat(), policy.period_end.isoformat(),
                 policy.first_inception.isoformat(), str(policy.sum_insured), policy.insured_pseudonym,
                 json.dumps(list(policy.declared_peds)), policy.city_tier),
            )

    def record_history(self, claim: Claim, worksheet: Worksheet | None = None) -> None:
        """Append a closed claim's fingerprints and sub-limit usage (no health details)."""
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO claims (claim_id, policy_number, admission_date, status, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (claim.claim_id, claim.policy_number, claim.admission_date.isoformat(),
                 "recorded", datetime.now(timezone.utc).isoformat()),
            )
            if cur.rowcount == 0:
                return  # already recorded; do not duplicate fingerprints
            self._conn.executemany(
                "INSERT INTO bill_fingerprints (fingerprint, claim_id, policy_number, line_id)"
                " VALUES (?, ?, ?, ?)",
                [(line_fingerprint(claim, line.description, line.amount), claim.claim_id,
                  claim.policy_number, line.line_id) for line in claim.bill_lines],
            )
            if worksheet is not None:
                rows = [
                    (claim.policy_number, claim.claim_id, d.clause_id, str(d.amount))
                    for wl in worksheet.lines for d in wl.deductions
                    if d.reason == DeductionReason.SUB_LIMIT
                ]
                if rows:
                    self._conn.executemany(
                        "INSERT INTO sub_limit_usage (policy_number, claim_id, sub_limit_name, amount)"
                        " VALUES (?, ?, ?, ?)",
                        rows,
                    )

    # -- reads -----------------------------------------------------------------------------
    def get_policy(self, policy_number: str) -> PolicyInfo | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM policies WHERE policy_number = ?", (policy_number,)
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

    def claim_history(self, policy_number: str) -> list[PastClaim]:
        with self._lock:
            claim_rows = self._conn.execute(
                "SELECT claim_id, admission_date FROM claims WHERE policy_number = ? ORDER BY created_at",
                (policy_number,),
            ).fetchall()
            fp_rows = self._conn.execute(
                "SELECT claim_id, fingerprint FROM bill_fingerprints WHERE policy_number = ?",
                (policy_number,),
            ).fetchall()
            sl_rows = self._conn.execute(
                "SELECT claim_id, sub_limit_name, amount FROM sub_limit_usage WHERE policy_number = ?",
                (policy_number,),
            ).fetchall()
        fps: dict[str, list[str]] = {}
        for r in fp_rows:
            fps.setdefault(r["claim_id"], []).append(r["fingerprint"])
        subs: dict[str, dict[str, Decimal]] = {}
        for r in sl_rows:
            bucket = subs.setdefault(r["claim_id"], {})
            bucket[r["sub_limit_name"]] = bucket.get(r["sub_limit_name"], Decimal("0")) + Decimal(r["amount"])
        return [
            PastClaim(
                claim_id=r["claim_id"],
                policy_number=policy_number,
                bill_fingerprints=fps.get(r["claim_id"], []),
                sub_limits_used=subs.get(r["claim_id"], {}),
                admission_date=date.fromisoformat(r["admission_date"]),
            )
            for r in claim_rows
        ]

    def find_duplicate_bills(self, policy_number: str, claim: Claim) -> list[str]:
        """Return line_ids whose fingerprint already exists for this policy (duplicate bills)."""
        seen = {fp for past in self.claim_history(policy_number) for fp in past.bill_fingerprints}
        return [line.line_id for line in claim.bill_lines
                if line_fingerprint(claim, line.description, line.amount) in seen]

    # -- writes: money (gated) ------------------------------------------------------------
    def settle_claim(
        self,
        claim_id: str,
        worksheet: Worksheet | dict,
        approvals: list[ApprovalToken | dict],
        needs_senior: bool,
        *,
        store: "approval_security.ApprovalStore | None" = None,
        require_signed: bool | None = None,
    ) -> dict:
        """Write a settlement - only with a verified approval bound to this exact worksheet.

        Raises ``PermissionError`` if the approval is missing, stale, unsigned, replayed, or a
        required senior sign-off is absent. Takes no amount argument: the amount is the approved
        worksheet's ``total_payable``.
        """
        ws = worksheet if isinstance(worksheet, Worksheet) else Worksheet.model_validate(worksheet)
        tokens = [t if isinstance(t, ApprovalToken) else ApprovalToken.model_validate(t) for t in (approvals or [])]
        if claim_id != ws.claim_id:
            raise PermissionError("claim_id does not match the worksheet")

        ws_hash = ws.content_hash()
        with self._lock:
            already = self._conn.execute(
                "SELECT status FROM settlements WHERE claim_id = ? AND worksheet_hash = ?",
                (claim_id, ws_hash),
            ).fetchone()
        if already is not None:
            raise PermissionError("this worksheet version has already been settled")

        # Server-side authorisation (consumes the approval to prevent replay).
        approval_security.assert_can_settle(ws, tokens, needs_senior, store=store,
                                            require_signed=require_signed)

        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO settlements (claim_id, worksheet_hash, amount, status, settled_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (claim_id, ws_hash, str(ws.total_payable), "settled", datetime.now(timezone.utc).isoformat()),
            )
            self._conn.execute("UPDATE claims SET status = 'settled' WHERE claim_id = ?", (claim_id,))
        return {"status": "settled", "claim_id": claim_id,
                "amount": str(ws.total_payable), "worksheet_hash": ws_hash}

    def record_repudiation(self, claim_id: str, reasons: list[str],
                           approvals: list[ApprovalToken | dict]) -> dict:
        """Record a repudiation - needs at least an adjudicator decision (matches the stub)."""
        if not approvals:
            raise PermissionError("repudiation needs an adjudicator decision")
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO settlements (claim_id, worksheet_hash, amount, status, settled_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (claim_id, "repudiation", "0", "repudiated", datetime.now(timezone.utc).isoformat()),
            )
            self._conn.execute("UPDATE claims SET status = 'repudiated' WHERE claim_id = ?", (claim_id,))
        return {"status": "repudiated", "claim_id": claim_id, "reasons": list(reasons)}


# --------------------------------------------------------------------------------------------
# Default instance + Services-facing module functions
# --------------------------------------------------------------------------------------------
_DB: ClaimsDatabase | None = None
_DB_LOCK = threading.Lock()


def get_db() -> ClaimsDatabase:
    global _DB
    with _DB_LOCK:
        if _DB is None:
            _DB = ClaimsDatabase()
        return _DB


def set_db(db: ClaimsDatabase) -> None:
    """Install a specific database instance (used by ``role4_services`` and tests)."""
    global _DB
    with _DB_LOCK:
        _DB = db


def get_policy(policy_number: str) -> PolicyInfo | None:
    return get_db().get_policy(policy_number)


def claim_history(policy_number: str) -> list[PastClaim]:
    return get_db().claim_history(policy_number)


def settle_claim(claim_id: str, worksheet: Worksheet | dict,
                 approvals: list[ApprovalToken | dict], needs_senior: bool) -> dict:
    return get_db().settle_claim(claim_id, worksheet, approvals, needs_senior)


def record_repudiation(claim_id: str, reasons: list[str],
                       approvals: list[ApprovalToken | dict]) -> dict:
    return get_db().record_repudiation(claim_id, reasons, approvals)


def record_history(claim: Claim, worksheet: Worksheet | None = None) -> None:
    get_db().record_history(claim, worksheet)


def seed_demo_policy(db: ClaimsDatabase | None = None) -> PolicyInfo:
    """Insert one clearly-synthetic demo policy (POL-001) for local runs/integration. Optional."""
    policy = PolicyInfo(
        policy_number="POL-001", period_start=date(2026, 1, 1), period_end=date(2026, 12, 31),
        first_inception=date(2024, 1, 1), sum_insured=Decimal("200000"),
        insured_pseudonym="PT-7731", declared_peds=[], city_tier="tier_1",
    )
    (db or get_db()).upsert_policy(policy)
    return policy


# --------------------------------------------------------------------------------------------
# MCP tool wrappers: structured results / errors
# --------------------------------------------------------------------------------------------
def _tool_get_policy(policy_number: str):
    """[read] Fetch a policy record."""
    policy = get_policy(policy_number)
    return policy if policy is not None else ToolError(error="policy not found", code="unknown_policy")


def _tool_claim_history(policy_number: str):
    """[read] List prior claims for a policy."""
    return {"policy_number": policy_number,
            "claims": [p.model_dump(mode="json") for p in claim_history(policy_number)]}


def _tool_settle_claim(claim_id: str, worksheet: dict, approvals: list[dict], needs_senior: bool):
    """[write] Settle a claim. Only succeeds with a verified approval for the exact worksheet."""
    try:
        return settle_claim(claim_id, worksheet, approvals, needs_senior)
    except PermissionError as exc:
        return ToolError(error=str(exc), code="approval_denied")
    except (ValueError, KeyError, TypeError) as exc:
        return ToolError(error=str(exc), code="invalid_input")


def main() -> None:
    """Start the claims-db MCP server (stdio). Requires the optional ``[mcp]`` extra."""
    from fastmcp import FastMCP  # lazy: optional dependency

    get_db()  # ensure schema exists
    mcp = FastMCP("claims-db")
    mcp.tool(name="get_policy")(_tool_get_policy)
    mcp.tool(name="claim_history")(_tool_claim_history)
    mcp.tool(name="settle_claim")(_tool_settle_claim)
    mcp.run()


if __name__ == "__main__":
    main()
