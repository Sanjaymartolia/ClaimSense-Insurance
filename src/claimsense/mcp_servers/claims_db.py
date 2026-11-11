"""claims-db: policy / claim-history / settlement store. ClaimSense Role 4 (Tools, Control & Security).

Refactor of the former ``claims_db_server.py`` (renamed to the clean ``claims_db`` name). The
**database business logic** lives in :class:`ClaimsDatabase` and the Services-facing module
functions; the **FastMCP wrappers** are a thin, clearly-separated boundary at the bottom of the
file (``_tool_*`` + :func:`main`). Nothing in the business logic imports FastMCP.

It backs these Role 3 registry tools (see ``agents/permissions.TOOL_ACL`` and
``agents/services.Services.registry``):

* ``get_policy``          (read)  - coverage, fraud, settlement
* ``claim_history``       (read)  - fraud (duplicate bills, used sub-limits)
* ``settle_claim``        (WRITE) - settlement agent only; gated by a verified signed approval
* ``record_repudiation``  (WRITE) - settlement agent only; needs a signed adjudicator decision
* ``record_history``      (write) - memory update after a claim closes

Authorisation (Role 4 task 3D)
------------------------------
``settle_claim`` / ``record_repudiation`` are the only writes that move a claim's status. Three
independent locks guard them: the per-agent ACL (``ToolBelt`` / ``hooks``), and - enforced *here,
server-side* - :func:`approvals.assert_can_settle` / :func:`approvals.assert_can_repudiate`, which
require a valid, signed, non-replayed, non-expired approval bound to the exact worksheet (or, for a
repudiation, the admissibility subject). ``settle_claim`` deliberately takes **no amount argument**:
the amount comes from the approved worksheet (red-team RT-008). Both raise ``PermissionError`` on an
authorisation failure (matching the Role 3 orchestration tests and the ``Services`` stub);
``ToolError`` is used only at the MCP boundary wrappers.

Persistence (Role 4 task 3C)
----------------------------
Signed approval records live in the **same** SQLite database as policies/claims/settlements, via
:class:`approvals.SqliteApprovalStore` sharing this connection - one file, one source of truth. With
a stable ``CLAIMSENSE_APPROVAL_SECRET`` the records (and therefore settlement authority) survive a
process restart. ``settle_claim`` / ``record_repudiation`` default to this persistent store; tests
may inject an in-memory store explicitly.

All SQL is parameterised; writes run in transactions. Only pseudonymised identifiers and
fingerprints are stored - never diagnosis text or other health details.

Works both as a flat sibling module (``import claims_db``) and as a package module
(``from claimsense.mcp_servers import claims_db``). ``fastmcp`` is imported lazily in :func:`main`.
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
    for cand in candidates:
        if (cand / "claimsense").is_dir():
            sys.path.insert(0, str(cand))
            return


_ensure_claimsense_on_path()

from claimsense.agents.services import PastClaim, PolicyInfo, line_fingerprint  # noqa: E402
from claimsense.contracts import (  # noqa: E402
    ApprovalToken,
    Claim,
    DeductionReason,
    Worksheet,
)

# The approval framework. Aliased to ``appr`` because ``approvals`` is the keyword name the Services
# registry passes to settle_claim/record_repudiation and must stay free as a parameter name.
try:  # package layout: claimsense.mcp_servers.claims_db
    from . import approvals as appr
except ImportError:  # flat layout: sibling module on sys.path
    import approvals as appr


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


# ============================================================================================
# Database business logic
# ============================================================================================
class ClaimsDatabase:
    """SQLite-backed claims store. One connection per instance, guarded by a lock.

    The same connection also holds the signed-approval records (``approvals`` table), exposed as
    :attr:`approval_store`, so settlement authority and the claim data share one file.
    """

    def __init__(self, path: str | None = None):
        self.path = path or _default_db_path()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock, self._conn:
            self._conn.executescript(_SCHEMA)
        # Create the approvals table in this same database (no secret needed just to create it).
        appr.ensure_approvals_schema(self._conn)
        self._approval_store: appr.ApprovalStore | None = None

    def close(self) -> None:
        self._conn.close()

    @property
    def approval_store(self) -> appr.ApprovalStore:
        """The persistent approval store backed by *this* database connection.

        Constructed lazily. Requires a stable ``CLAIMSENSE_APPROVAL_SECRET`` (see
        :class:`approvals.SqliteApprovalStore`); wire the same object into the ``ReviewGate`` so
        issuance and verification use one store.
        """
        if self._approval_store is None:
            self._approval_store = appr.SqliteApprovalStore(connection=self._conn, lock=self._lock)
        return self._approval_store

    # -- writes: policies / history -------------------------------------------------------
    def upsert_policy(self, policy: PolicyInfo) -> None:
        """Insert or replace a (synthetic) policy record. Idempotent on ``policy_number``."""
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
        """Record claim fingerprints and sub-limit consumption without health details.

        ``sub_limit_usage`` is an optional clause-id -> amount-consumed mapping supplied by the
        caller for eligible sub-limits that have no worksheet deduction (for example, a bill
        below its cap). If omitted, usage is inferred from SUB_LIMIT worksheet deductions using
        each capped line's payable amount. Cataract 4.3 must remain informational until eye identity
        is available; callers must not include it in this mapping.
        """
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO claims (claim_id, policy_number, admission_date, status, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    claim.claim_id,
                    claim.policy_number,
                    claim.admission_date.isoformat(),
                    "recorded",
                    datetime.now(UTC).isoformat(),
                ),
            )
            if cur.rowcount == 0:
                return  # already recorded; do not duplicate fingerprints
            self._conn.executemany(
                "INSERT INTO bill_fingerprints (fingerprint, claim_id, policy_number, line_id)"
                " VALUES (?, ?, ?, ?)",
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
            # Infer consumed amounts for capped lines. Accumulate by clause so multiple lines
            # governed by the same sub-limit are recorded once as a total.
            consumed_by_clause: dict[str, Decimal] = {}
            if worksheet is not None:
                for wl in worksheet.lines:
                    clause_ids = {
                        d.clause_id
                        for d in wl.deductions
                        if d.reason == DeductionReason.SUB_LIMIT
                    }
                    for clause_id in clause_ids:
                        consumed_by_clause[clause_id] = (
                            consumed_by_clause.get(clause_id, Decimal("0")) + wl.payable
                        )

            # Explicit values cover within-cap / exactly-at-cap lines for which the Worksheet has
            # no SUB_LIMIT deduction and therefore no clause metadata. They are authoritative for
            # those clauses and are merged with inferred usage only when the clause is not inferred.
            for clause_id, amount in (sub_limit_usage or {}).items():
                if not isinstance(clause_id, str) or not clause_id.strip():
                    raise ValueError("sub-limit usage requires a non-empty clause id")
                value = Decimal(amount)
                if not value.is_finite() or value < 0:
                    raise ValueError(f"invalid sub-limit usage for clause {clause_id!r}")
                if clause_id not in consumed_by_clause:
                    consumed_by_clause[clause_id] = value

            rows = [
                (claim.policy_number, claim.claim_id, clause_id, str(amount))
                for clause_id, amount in consumed_by_clause.items()
                if amount > 0
            ]
            if rows:
                self._conn.executemany(
                    "INSERT INTO sub_limit_usage (policy_number, claim_id, sub_limit_name, amount)"
                    " VALUES (?, ?, ?, ?)",
                    rows,
                )

    def delete_history(self, claim_id: str) -> None:
        """Delete one claim's history rows only; safe to call repeatedly.

        Settlements, approvals, policies, other claims, and graph/playbook memory are untouched.
        All claim-history rows are deleted atomically.
        """
        if not isinstance(claim_id, str) or not claim_id.strip():
            raise ValueError("claim_id must be a non-empty string")
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM bill_fingerprints WHERE claim_id = ?", (claim_id,))
            self._conn.execute("DELETE FROM sub_limit_usage WHERE claim_id = ?", (claim_id,))
            self._conn.execute("DELETE FROM claims WHERE claim_id = ?", (claim_id,))

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

    def all_policy_numbers(self) -> list[str]:
        """Every policy number currently stored (used by the dev seeder's validation)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT policy_number FROM policies ORDER BY policy_number"
            ).fetchall()
        return [r["policy_number"] for r in rows]

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
            bucket[r["sub_limit_name"]] = bucket.get(r["sub_limit_name"], Decimal("0")) + Decimal(
                r["amount"]
            )
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
        return [
            line.line_id
            for line in claim.bill_lines
            if line_fingerprint(claim, line.description, line.amount) in seen
        ]

    # -- writes: money (gated) ------------------------------------------------------------
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
        """Write a settlement - only with a verified approval bound to this exact worksheet.

        Raises ``PermissionError`` if the approval is missing, stale, unsigned, replayed, expired,
        or a required senior sign-off is absent. Takes no amount argument: the amount is the
        approved worksheet's ``total_payable``. ``store`` defaults to the persistent
        :attr:`approval_store`; tests may pass an in-memory store.
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
            already = self._conn.execute(
                "SELECT status FROM settlements WHERE claim_id = ? AND worksheet_hash = ?",
                (claim_id, ws_hash),
            ).fetchone()
        if already is not None:
            raise PermissionError("this worksheet version has already been settled")

        # Server-side authorisation (consumes the approval to prevent replay).
        resolved_store = store if store is not None else self.approval_store
        appr.assert_can_settle(
            ws, tokens, needs_senior, store=resolved_store, require_signed=require_signed
        )

        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO settlements (claim_id, worksheet_hash, amount, status, settled_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    claim_id,
                    ws_hash,
                    str(ws.total_payable),
                    "settled",
                    datetime.now(UTC).isoformat(),
                ),
            )
            self._conn.execute(
                "UPDATE claims SET status = 'settled' WHERE claim_id = ?", (claim_id,)
            )
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
        """Record a repudiation - needs a signed adjudicator decision for this claim.

        Raises ``PermissionError`` when no decision is presented, or (in the default signed mode)
        when the decision is not backed by a signed, non-consumed, non-expired record. The record
        is consumed to prevent replay. ``store`` defaults to the persistent :attr:`approval_store`.
        """
        tokens = [
            t if isinstance(t, ApprovalToken) else ApprovalToken.model_validate(t)
            for t in (approvals or [])
        ]
        if not tokens:
            # Fail fast with the historical message, and without needing the store/secret.
            raise PermissionError("repudiation needs an adjudicator decision")

        resolved_store = store if store is not None else self.approval_store
        appr.assert_can_repudiate(
            claim_id, tokens, store=resolved_store, require_signed=require_signed
        )

        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO settlements (claim_id, worksheet_hash, amount, status, settled_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    claim_id,
                    "repudiation",
                    "0",
                    "repudiated",
                    datetime.now(UTC).isoformat(),
                ),
            )
            self._conn.execute(
                "UPDATE claims SET status = 'repudiated' WHERE claim_id = ?", (claim_id,)
            )
        return {"status": "repudiated", "claim_id": claim_id, "reasons": list(reasons)}


# ============================================================================================
# Default instance + Services-facing module functions
# ============================================================================================
_DB: ClaimsDatabase | None = None
_DB_LOCK = threading.Lock()


def get_db() -> ClaimsDatabase:
    global _DB
    with _DB_LOCK:
        if _DB is None:
            _DB = ClaimsDatabase()
        return _DB


def set_db(db: ClaimsDatabase) -> None:
    """Install a specific database instance (used by the services wiring and tests)."""
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
    """Insert one clearly-synthetic demo policy (POL-001) for local runs/integration. Optional."""
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


# ============================================================================================
# MCP boundary: FastMCP tool wrappers (structured results / errors; never raise to an agent)
# ============================================================================================
def _tool_get_policy(policy_number: str):
    """[read] Fetch a policy record."""
    policy = get_policy(policy_number)
    return (
        policy if policy is not None else ToolError(error="policy not found", code="unknown_policy")
    )


def _tool_claim_history(policy_number: str):
    """[read] List prior claims for a policy."""
    return {
        "policy_number": policy_number,
        "claims": [p.model_dump(mode="json") for p in claim_history(policy_number)],
    }


def _tool_settle_claim(claim_id: str, worksheet: dict, approvals: list[dict], needs_senior: bool):
    """[write] Settle a claim. Only succeeds with a verified signed approval for the exact worksheet."""
    try:
        return settle_claim(claim_id, worksheet, approvals, needs_senior)
    except PermissionError as exc:
        return ToolError(error=str(exc), code="approval_denied")
    except RuntimeError as exc:  # e.g. persistent store without a stable secret
        return ToolError(error=str(exc), code="server_misconfigured")
    except (ValueError, KeyError, TypeError) as exc:
        return ToolError(error=str(exc), code="invalid_input")


def _tool_record_repudiation(claim_id: str, reasons: list[str], approvals: list[dict]):
    """[write] Record a repudiation. Only succeeds with a signed adjudicator decision."""
    try:
        return record_repudiation(claim_id, reasons, approvals)
    except PermissionError as exc:
        return ToolError(error=str(exc), code="approval_denied")
    except RuntimeError as exc:
        return ToolError(error=str(exc), code="server_misconfigured")
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
    mcp.tool(name="record_repudiation")(_tool_record_repudiation)
    mcp.run()


if __name__ == "__main__":
    main()
