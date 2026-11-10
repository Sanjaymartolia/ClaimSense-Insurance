"""Signed human approvals for the L14 control gate. ClaimSense Role 4 (Tools, Control & Security).

This is the **single public approval module** for Role 4. It consolidates the two earlier files
(``approval_security.py`` - the cryptographic core - and ``approval_gate.py`` - the ``ReviewGate``)
into one integration surface, and adds the two things Role 3 integration needs:

* a **persistent** approval store (:class:`SqliteApprovalStore`) that keeps signed approval records
  in the *same* SQLite database as the claims DB, so approvals survive a process restart; and
* a **repudiation** approval path (:func:`issue_repudiation_approval`, :func:`verify_repudiation`)
  so a "not admissible" decision can be signed and verified the same way a settlement is - closing
  the gap where ``ReviewGate`` issued no token for a claim with no worksheet.

The file keeps a clean *internal* separation even though it is one module:

    1. configuration (thresholds, signed-by-default, approval TTL, server secret)
    2. canonical worksheet hash (reuses ``Worksheet.content_hash`` - never a second scheme)
    3. trusted identity (``IdentityProvider`` / ``DemoIdentityProvider``)
    4. signed records + stores (in-memory for tests, SQLite for persistence)
    5. issue / verify (settlement and repudiation)
    6. the human ``ReviewGate`` and its payload/decision helpers
    7. drivers / a small LangGraph demo

Security model (unchanged from the original, hardened):

* **Canonical hash** - an approval is bound to ``Worksheet.content_hash()`` (SHA-256 over the
  exact payload). Any edit changes the hash, so earlier approvals are void (red-team RT-006).
* **Trusted identity** - the approver id/role come from an :class:`IdentityProvider`, never from a
  free-form string in the claim or a document under review.
* **Hash alone is not proof** - settlement needs a *signed* :class:`ApprovalRecord` in the store
  (nonce + HMAC over a server secret), not just a token whose hash matches.
* **Replay / expiry** - each record carries a nonce, is *consumed* on use, and may be rejected once
  older than the configured TTL. A stale, edited, replayed or expired approval can never settle.
* **Senior approval** - high-value or fraud-flagged claims need a SENIOR approval as well.

The settlement write path (``claims_db.settle_claim`` / ``record_repudiation``) calls
:func:`assert_can_settle` / :func:`assert_can_repudiate`, which raise ``PermissionError`` on any
failure - matching the behaviour the Role 3 orchestration tests rely on. ``ToolError`` is used only
at the MCP boundary wrappers, never here.

Import compatibility: this module keeps the exact public names ``approval_security`` and
``approval_gate`` exposed (``issue_approval``, ``ReviewGate``, ``verify_for_settlement``,
``assert_can_settle``, ``DemoIdentityProvider``, ...), so existing callers only change the import
site. It works both as a flat sibling module (``import approvals``) and as a package module
(``from claimsense.mcp_servers import approvals``).
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import sys
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Protocol


def _ensure_claimsense_on_path() -> None:
    """Put the repo's ``src`` on ``sys.path`` when this module is run as a flat file.

    A no-op once ``claimsense`` is importable (for example when this file has been moved into
    ``src/claimsense/mcp_servers/`` for the final integration).
    """
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

from claimsense.contracts import (  # noqa: E402
    ApprovalDecision,
    ApprovalLevel,
    ApprovalToken,
    Worksheet,
)
from claimsense.graph.state import ReviewDecision, Status  # noqa: E402

__all__ = [
    # configuration
    "senior_threshold_inr",
    "require_signed_default",
    "DEFAULT_APPROVAL_TTL_SECONDS",
    # hashing
    "worksheet_hash",
    # identity
    "AuthenticatedApprover",
    "IdentityProvider",
    "DemoIdentityProvider",
    # records + stores
    "ApprovalRecord",
    "ApprovalStore",
    "InMemoryApprovalStore",
    "SqliteApprovalStore",
    "APPROVALS_SCHEMA",
    "ensure_approvals_schema",
    "default_store",
    "reset_default_store",
    # issue / verify
    "issue_approval",
    "issue_repudiation_approval",
    "needs_senior",
    "ApprovalVerification",
    "verify_for_settlement",
    "assert_can_settle",
    "verify_repudiation",
    "assert_can_repudiate",
    # gate
    "build_review_payload",
    "parse_decision",
    "needs_senior_review",
    "ReviewGate",
    "make_node_review",
    # drivers
    "run_with_review",
    "build_demo_gate",
]


# ============================================================================================
# 1. Configuration
# ============================================================================================
def _repo_root() -> Path:
    env = os.environ.get("CLAIMSENSE_REPO")
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    for cand in (here.parent.parent / "ClaimSense-Insurance", here.parent / "ClaimSense-Insurance"):
        if cand.is_dir():
            return cand
    return here.parent.parent / "ClaimSense-Insurance"


def senior_threshold_inr() -> Decimal:
    """Senior-approval threshold (INR). Env override, else ``config/models.yaml``, else 100000.

    This is the one threshold the graph and the claims DB must share (Role 4 task 3F). Wire it into
    ``Services.senior_threshold`` so ``graph.nodes.needs_senior`` and :func:`needs_senior` agree.
    """
    env = os.environ.get("CLAIMSENSE_SENIOR_THRESHOLD_INR")
    if env:
        try:
            return Decimal(env)
        except InvalidOperation:
            pass
    cfg = _repo_root() / "config" / "models.yaml"
    override = os.environ.get("CLAIMSENSE_CONFIG")
    if override:
        cfg = Path(override)
    try:
        import yaml  # pyyaml is a core dependency

        with cfg.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return Decimal(str(data["approval"]["senior_threshold_inr"]))
    except (OSError, KeyError, TypeError, InvalidOperation, ImportError):
        return Decimal("100000")


def require_signed_default() -> bool:
    """Whether a signed store record is required by default (``CLAIMSENSE_REQUIRE_SIGNED_APPROVAL``).

    Defaults to ``True`` (secure): a token whose hash matches is *not* enough; a signed record must
    back it. Set the env var to ``0``/``false``/``no`` only for the documented bare-token
    compatibility mode.
    """
    return os.environ.get("CLAIMSENSE_REQUIRE_SIGNED_APPROVAL", "1").strip().lower() not in {
        "0",
        "false",
        "no",
    }


#: Default lifetime of an approval, in seconds (24h). Overridable with
#: ``CLAIMSENSE_APPROVAL_TTL_SECONDS``; set it to ``0`` (or a negative value) to disable expiry.
DEFAULT_APPROVAL_TTL_SECONDS: float = 24 * 60 * 60

_TTL_SENTINEL = object()  # "caller did not pass max_age; use the configured default"


def _approval_ttl_seconds() -> float | None:
    raw = os.environ.get("CLAIMSENSE_APPROVAL_TTL_SECONDS")
    if raw is None or raw.strip() == "":
        return DEFAULT_APPROVAL_TTL_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_APPROVAL_TTL_SECONDS
    return None if value <= 0 else value


def _resolve_max_age(max_age: Any) -> float | None:
    return _approval_ttl_seconds() if max_age is _TTL_SENTINEL else max_age


_SECRET_LOCK = threading.Lock()
_EPHEMERAL_SECRET: bytes | None = None


def _stable_secret_present() -> bool:
    return bool(os.environ.get("CLAIMSENSE_APPROVAL_SECRET"))


def _server_secret() -> bytes:
    """HMAC secret for signing approval records.

    Prefers ``CLAIMSENSE_APPROVAL_SECRET`` (stable across processes - required for persistence). If
    unset, a random per-process secret is used so signatures still work within a single run; such
    records do **not** survive a restart, which is why :class:`SqliteApprovalStore` refuses to run
    without a stable secret.
    """
    env = os.environ.get("CLAIMSENSE_APPROVAL_SECRET")
    if env:
        return env.encode("utf-8")
    global _EPHEMERAL_SECRET
    with _SECRET_LOCK:
        if _EPHEMERAL_SECRET is None:
            _EPHEMERAL_SECRET = secrets.token_bytes(32)
        return _EPHEMERAL_SECRET


def _default_claims_db_path() -> str:
    """Same default path as ``claims_db`` so one SQLite file holds claims *and* approvals."""
    return os.environ.get("CLAIMSENSE_CLAIMS_DB", "claimsense_claims.db")


# ============================================================================================
# 2. Canonical worksheet hash (single source of truth)
# ============================================================================================
def worksheet_hash(worksheet: Worksheet | dict) -> str:
    """Return ``Worksheet.content_hash()`` for a worksheet (dicts are validated first)."""
    ws = worksheet if isinstance(worksheet, Worksheet) else Worksheet.model_validate(worksheet)
    return ws.content_hash()


# ============================================================================================
# 3. Trusted identity
# ============================================================================================
@dataclass(frozen=True)
class AuthenticatedApprover:
    """An approver whose identity and role were established by a trusted auth mechanism."""

    approver_id: str
    level: ApprovalLevel
    auth_source: str  # e.g. "oidc", "session", "demo"
    authenticated_at: datetime


class IdentityProvider(Protocol):
    """Supplies an authenticated approver for a review decision. Implemented by the UI/API layer."""

    def authenticate(self, claim_id: str, level: ApprovalLevel) -> AuthenticatedApprover: ...


@dataclass
class DemoIdentityProvider:
    """DEV / DEMO ONLY. Trusts a preset id/level map.

    **Not production-grade.** It performs no real authentication: it maps an approval level to a
    fixed, clearly-synthetic id. A real deployment must replace it with an SSO/OIDC/JWT-backed
    provider so the approver's identity is proven, not asserted. It is kept here only so the gate
    and the signed-record machinery can be exercised end to end without an auth server. It still
    models the important contract: identity is *provided by the provider*, never read from the
    worksheet or from a document under review.
    """

    approver_ids: dict[ApprovalLevel, str] = field(
        default_factory=lambda: {
            ApprovalLevel.ADJUDICATOR: "demo-adjudicator",
            ApprovalLevel.SENIOR: "demo-senior",
        }
    )

    def authenticate(self, claim_id: str, level: ApprovalLevel) -> AuthenticatedApprover:
        approver_id = self.approver_ids.get(level)
        if not approver_id:
            raise PermissionError(f"no authenticated approver available for level {level}")
        return AuthenticatedApprover(
            approver_id=approver_id,
            level=level,
            auth_source="demo",
            authenticated_at=datetime.now(UTC),
        )


# ============================================================================================
# 4. Signed approval records + stores
# ============================================================================================
def _signature(token: ApprovalToken, nonce: str, secret: bytes) -> str:
    msg = "|".join(
        [
            token.claim_id,
            token.worksheet_hash,
            token.level.value,
            token.approver_id,
            token.decided_at.isoformat(),
            nonce,
        ]
    ).encode("utf-8")
    return hmac.new(secret, msg, hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class ApprovalRecord:
    """A token plus the proof it was issued by this server for a trusted approver."""

    token: ApprovalToken
    nonce: str
    signature: str
    auth_source: str

    def signature_valid(self, secret: bytes | None = None) -> bool:
        return hmac.compare_digest(
            self.signature, _signature(self.token, self.nonce, secret or _server_secret())
        )


class ApprovalStore(Protocol):
    """Durable store of signed approval records (swap the in-memory default for SQLite in prod)."""

    def add(self, record: ApprovalRecord) -> None: ...
    def find(self, claim_id: str, worksheet_hash: str) -> list[ApprovalRecord]: ...
    def consume(self, record: ApprovalRecord) -> None: ...
    def is_consumed(self, record: ApprovalRecord) -> bool: ...


class InMemoryApprovalStore:
    """Thread-safe in-memory :class:`ApprovalStore`. Default store for development and tests.

    It does **not** persist: records are lost when the process exits. Use
    :class:`SqliteApprovalStore` for anything that must survive a restart.
    """

    def __init__(self) -> None:
        self._records: list[ApprovalRecord] = []
        self._consumed: set[str] = set()
        self._lock = threading.Lock()

    @staticmethod
    def _key(record: ApprovalRecord) -> str:
        return record.signature

    def add(self, record: ApprovalRecord) -> None:
        with self._lock:
            self._records.append(record)

    def find(self, claim_id: str, worksheet_hash: str) -> list[ApprovalRecord]:
        with self._lock:
            return [
                r
                for r in self._records
                if r.token.claim_id == claim_id and r.token.worksheet_hash == worksheet_hash
            ]

    def consume(self, record: ApprovalRecord) -> None:
        with self._lock:
            self._consumed.add(self._key(record))

    def is_consumed(self, record: ApprovalRecord) -> bool:
        with self._lock:
            return self._key(record) in self._consumed


# -- persistent store -------------------------------------------------------------------------
APPROVALS_SCHEMA = """
CREATE TABLE IF NOT EXISTS approvals (
    signature      TEXT PRIMARY KEY,
    claim_id       TEXT NOT NULL,
    worksheet_hash TEXT NOT NULL,
    level          TEXT NOT NULL,
    approver_id    TEXT NOT NULL,
    decided_at     TEXT NOT NULL,
    nonce          TEXT NOT NULL,
    auth_source    TEXT NOT NULL,
    consumed       INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_approvals_lookup ON approvals(claim_id, worksheet_hash);
"""


def ensure_approvals_schema(conn: sqlite3.Connection) -> None:
    """Create the ``approvals`` table if absent. Safe to call repeatedly; needs no secret.

    ``claims_db`` calls this at startup so the one claims database also holds the approval records
    (no second database, no two sources of truth).
    """
    with conn:
        conn.executescript(APPROVALS_SCHEMA)


class SqliteApprovalStore:
    """Persistent :class:`ApprovalStore` backed by SQLite.

    Records survive a process restart and stay verifiable afterwards **because the HMAC secret is
    stable** (``CLAIMSENSE_APPROVAL_SECRET``). The store refuses to start on a random per-process
    secret, so a restart can never silently invalidate every stored approval.

    To keep a single source of truth, pass the claims DB's own ``connection`` (and its ``lock``):
    the approvals then live in the same SQLite file as the policies, claims and settlements. Given
    only a ``path``, it opens (and owns) its own connection to that file.
    """

    def __init__(
        self,
        path: str | None = None,
        *,
        connection: sqlite3.Connection | None = None,
        lock: threading.Lock | None = None,
        allow_ephemeral_secret: bool = False,
    ) -> None:
        if not allow_ephemeral_secret and not _stable_secret_present():
            raise RuntimeError(
                "SqliteApprovalStore needs a stable CLAIMSENSE_APPROVAL_SECRET so signed approvals "
                "stay verifiable across restarts; it will not fall back to a random per-process "
                "secret. Set CLAIMSENSE_APPROVAL_SECRET in the environment, or pass "
                "allow_ephemeral_secret=True for a throwaway single-process test."
            )
        if connection is not None:
            self._conn = connection
            self._owns = False
            self._lock = lock or threading.Lock()
        else:
            self.path = path or _default_claims_db_path()
            self._conn = sqlite3.connect(self.path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._owns = True
            self._lock = threading.Lock()
        if self._conn.row_factory is None:
            self._conn.row_factory = sqlite3.Row
        with self._lock:
            ensure_approvals_schema(self._conn)

    def close(self) -> None:
        if self._owns:
            self._conn.close()

    @staticmethod
    def _record_from_row(row: sqlite3.Row) -> ApprovalRecord:
        token = ApprovalToken(
            claim_id=row["claim_id"],
            worksheet_hash=row["worksheet_hash"],
            level=ApprovalLevel(row["level"]),
            approver_id=row["approver_id"],
            decided_at=datetime.fromisoformat(row["decided_at"]),
        )
        return ApprovalRecord(
            token=token,
            nonce=row["nonce"],
            signature=row["signature"],
            auth_source=row["auth_source"],
        )

    def add(self, record: ApprovalRecord) -> None:
        t = record.token
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO approvals (signature, claim_id, worksheet_hash, level, "
                "approver_id, decided_at, nonce, auth_source, consumed, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)",
                (
                    record.signature,
                    t.claim_id,
                    t.worksheet_hash,
                    t.level.value,
                    t.approver_id,
                    t.decided_at.isoformat(),
                    record.nonce,
                    record.auth_source,
                    datetime.now(UTC).isoformat(),
                ),
            )

    def find(self, claim_id: str, worksheet_hash: str) -> list[ApprovalRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM approvals WHERE claim_id = ? AND worksheet_hash = ?",
                (claim_id, worksheet_hash),
            ).fetchall()
        return [self._record_from_row(r) for r in rows]

    def consume(self, record: ApprovalRecord) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE approvals SET consumed = 1 WHERE signature = ?", (record.signature,)
            )

    def is_consumed(self, record: ApprovalRecord) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT consumed FROM approvals WHERE signature = ?", (record.signature,)
            ).fetchone()
        return bool(row["consumed"]) if row is not None else False


_DEFAULT_STORE: ApprovalStore = InMemoryApprovalStore()


def default_store() -> ApprovalStore:
    """The module-level in-memory store. Production wires a :class:`SqliteApprovalStore` instead."""
    return _DEFAULT_STORE


def reset_default_store() -> None:
    """Clear the module-level in-memory store (tests)."""
    global _DEFAULT_STORE
    _DEFAULT_STORE = InMemoryApprovalStore()


# ============================================================================================
# 5. Issue / verify
# ============================================================================================
def _sign_and_store(
    token: ApprovalToken, auth_source: str, store: ApprovalStore | None, nonce: str | None
) -> ApprovalToken:
    store = store or default_store()
    nonce = nonce or secrets.token_hex(16)
    record = ApprovalRecord(
        token=token,
        nonce=nonce,
        signature=_signature(token, nonce, _server_secret()),
        auth_source=auth_source,
    )
    store.add(record)
    return token


def issue_approval(
    worksheet: Worksheet,
    approver: AuthenticatedApprover,
    *,
    nonce: str | None = None,
    store: ApprovalStore | None = None,
) -> ApprovalToken:
    """Mint a signed settlement approval bound to this worksheet, and store the record.

    Returns the :class:`ApprovalToken` (Role 3-compatible) to attach to graph state. The signed
    record (nonce + HMAC) is kept in ``store`` so later verification cannot be satisfied by a token
    alone.
    """
    token = ApprovalToken(
        claim_id=worksheet.claim_id,
        worksheet_hash=worksheet.content_hash(),
        level=approver.level,
        approver_id=approver.approver_id,
        decided_at=approver.authenticated_at,
    )
    return _sign_and_store(token, approver.auth_source, store, nonce)


def issue_repudiation_approval(
    claim_id: str,
    subject_hash: str,
    approver: AuthenticatedApprover,
    *,
    nonce: str | None = None,
    store: ApprovalStore | None = None,
) -> ApprovalToken:
    """Mint a signed *repudiation* approval bound to a non-worksheet subject.

    A "not admissible" claim has no worksheet, so the approval is bound to ``subject_hash`` - the
    SHA-256 of the admissibility finding (the same hash ``build_review_payload`` puts in the
    repudiation payload). Everything else (nonce, HMAC, store, consume-on-use) is identical to a
    settlement approval, so there is one signing/verifying mechanism, not two.
    """
    token = ApprovalToken(
        claim_id=claim_id,
        worksheet_hash=subject_hash,
        level=approver.level,
        approver_id=approver.approver_id,
        decided_at=approver.authenticated_at,
    )
    return _sign_and_store(token, approver.auth_source, store, nonce)


def needs_senior(
    worksheet: Worksheet, fraud_flags: Iterable[str] | None, threshold: Decimal | None = None
) -> bool:
    """Senior approval is required for high-value *or* fraud-flagged claims."""
    threshold = threshold if threshold is not None else senior_threshold_inr()
    return worksheet.total_payable > threshold or bool(list(fraud_flags or []))


@dataclass(frozen=True)
class ApprovalVerification:
    """Result of checking whether a settlement or repudiation may proceed."""

    ok: bool
    reasons: tuple[str, ...] = ()
    used: tuple[ApprovalRecord, ...] = ()


def _is_expired(decided_at: datetime, max_age: float | None) -> bool:
    if max_age is None:
        return False
    dt = decided_at if decided_at.tzinfo is not None else decided_at.replace(tzinfo=UTC)
    return (datetime.now(UTC) - dt).total_seconds() > max_age


def _find_signed_record(token: ApprovalToken, store: ApprovalStore) -> ApprovalRecord | None:
    """A signature-valid, same-level, same-approver, not-yet-consumed record for this token.

    Expiry is applied by the caller so the reason reported can distinguish "expired" from
    "no signed record".
    """
    for rec in store.find(token.claim_id, token.worksheet_hash):
        if (
            rec.token.level == token.level
            and rec.token.approver_id == token.approver_id
            and not store.is_consumed(rec)
            and rec.signature_valid()
        ):
            return rec
    return None


def verify_for_settlement(
    worksheet: Worksheet,
    tokens: Iterable[ApprovalToken],
    senior_required: bool,
    *,
    store: ApprovalStore | None = None,
    require_signed: bool | None = None,
    max_age: Any = _TTL_SENTINEL,
    consume: bool = True,
) -> ApprovalVerification:
    """Decide whether ``worksheet`` may be settled given the presented ``tokens``.

    Enforces: a valid ADJUDICATOR approval bound to the exact worksheet (and a SENIOR one when
    ``senior_required``); that the hash matches (stale/edited approvals fail); that - when
    ``require_signed`` - the token is backed by a signed, non-consumed store record (so a hash
    alone is never proof); that the approval has not expired; and consumes the records to stop
    replay.
    """
    store = store or default_store()
    require_signed = require_signed_default() if require_signed is None else require_signed
    max_age = _resolve_max_age(max_age)
    tokens = list(tokens or [])
    reasons: list[str] = []

    def find_valid(
        level: ApprovalLevel,
    ) -> tuple[ApprovalRecord | ApprovalToken | None, str | None]:
        """Return (valid record/token, reason-if-none). Only reports a reason when no token of this
        level is valid, so one stale token alongside a valid one does not cause a false rejection."""
        signed_missing = expired = False
        for tok in tokens:
            if tok.level != level or not tok.is_valid_for(worksheet):
                continue
            record = _find_signed_record(tok, store)
            if record is not None:
                if _is_expired(record.token.decided_at, max_age):
                    expired = True
                    continue
                return record, None
            if require_signed:
                signed_missing = True
                continue
            if _is_expired(tok.decided_at, max_age):  # bare-token compat path still honours expiry
                expired = True
                continue
            return tok, None  # compatibility mode: accept a hash-valid bare token
        if expired:
            return None, f"{level.value} approval has expired"
        if signed_missing:
            return None, (
                f"{level.value} approval is not backed by a signed record (hash alone is not proof)"
            )
        return None, None

    adjudicator, adj_reason = find_valid(ApprovalLevel.ADJUDICATOR)
    if adjudicator is None:
        reasons.append(adj_reason or "no valid adjudicator approval for this worksheet version")

    senior = None
    if senior_required:
        senior, sen_reason = find_valid(ApprovalLevel.SENIOR)
        if senior is None:
            reasons.append(sen_reason or "senior approval required for this claim")

    if reasons:
        return ApprovalVerification(ok=False, reasons=tuple(reasons))

    used = tuple(r for r in (adjudicator, senior) if isinstance(r, ApprovalRecord))
    if consume:
        for rec in used:
            store.consume(rec)
    return ApprovalVerification(ok=True, used=used)


def assert_can_settle(
    worksheet: Worksheet,
    tokens: Iterable[ApprovalToken],
    senior_required: bool,
    *,
    store: ApprovalStore | None = None,
    require_signed: bool | None = None,
    max_age: Any = _TTL_SENTINEL,
    consume: bool = True,
) -> None:
    """Raise ``PermissionError`` unless settlement is authorised (used by the write path)."""
    result = verify_for_settlement(
        worksheet,
        tokens,
        senior_required,
        store=store,
        require_signed=require_signed,
        max_age=max_age,
        consume=consume,
    )
    if not result.ok:
        raise PermissionError("; ".join(result.reasons))


def verify_repudiation(
    claim_id: str,
    tokens: Iterable[ApprovalToken],
    *,
    store: ApprovalStore | None = None,
    require_signed: bool | None = None,
    max_age: Any = _TTL_SENTINEL,
    consume: bool = True,
) -> ApprovalVerification:
    """Decide whether a repudiation of ``claim_id`` is authorised.

    A repudiation needs at least an ADJUDICATOR decision for this claim. When ``require_signed``
    (the default), that decision must be backed by a signed, non-consumed, non-expired record -
    exactly like a settlement, but bound to the admissibility subject hash rather than a worksheet.
    The record is consumed to prevent replay.
    """
    store = store or default_store()
    require_signed = require_signed_default() if require_signed is None else require_signed
    max_age = _resolve_max_age(max_age)
    tokens = list(tokens or [])

    adjudicator_tokens = [
        t for t in tokens if t.level == ApprovalLevel.ADJUDICATOR and t.claim_id == claim_id
    ]
    if not adjudicator_tokens:
        return ApprovalVerification(
            ok=False, reasons=("repudiation needs an adjudicator decision",)
        )

    if not require_signed:
        return ApprovalVerification(ok=True)  # compatibility: an adjudicator decision is enough

    expired = False
    for tok in adjudicator_tokens:
        record = _find_signed_record(tok, store)
        if record is None:
            continue
        if _is_expired(record.token.decided_at, max_age):
            expired = True
            continue
        if consume:
            store.consume(record)
        return ApprovalVerification(ok=True, used=(record,))

    reason = (
        "repudiation approval has expired"
        if expired
        else "repudiation approval is not backed by a signed record (hash alone is not proof)"
    )
    return ApprovalVerification(ok=False, reasons=(reason,))


def assert_can_repudiate(
    claim_id: str,
    tokens: Iterable[ApprovalToken],
    *,
    store: ApprovalStore | None = None,
    require_signed: bool | None = None,
    max_age: Any = _TTL_SENTINEL,
    consume: bool = True,
) -> None:
    """Raise ``PermissionError`` unless the repudiation is authorised (used by the write path)."""
    result = verify_repudiation(
        claim_id,
        tokens,
        store=store,
        require_signed=require_signed,
        max_age=max_age,
        consume=consume,
    )
    if not result.ok:
        raise PermissionError("; ".join(result.reasons))


# ============================================================================================
# 6. The human ReviewGate (payload / decision helpers + the gate itself)
# ============================================================================================
def build_review_payload(
    state: dict,
    level: ApprovalLevel,
    *,
    render_plan: Callable[[Any], str] | None = None,
) -> dict:
    """Build the payload the adjudicator sees at ``interrupt()``. Mirrors ``nodes._review``.

    Health details are never included - only the worksheet, its hash, flags and routing context.
    For a not-admissible claim the ``worksheet_hash`` is the SHA-256 of the admissibility finding,
    which is what a repudiation approval binds to.
    """
    worksheet: Worksheet | None = state.get("worksheet")
    admissibility = state.get("admissibility")
    admissible = getattr(admissibility, "admissible", True)
    kind = "worksheet" if admissible else "repudiation"
    if kind == "worksheet" and worksheet is not None:
        subject_hash = worksheet.content_hash()
    elif admissibility is not None:
        subject_hash = hashlib.sha256(admissibility.model_dump_json().encode()).hexdigest()
    else:  # pragma: no cover - defensive
        subject_hash = ""
    plan = state.get("plan")
    return {
        "claim_id": state.get("claim_id"),
        "kind": kind,
        "level": level.value,
        "worksheet": worksheet.model_dump(mode="json")
        if worksheet and kind == "worksheet"
        else None,
        "worksheet_hash": subject_hash,
        "admissibility": admissibility.model_dump(mode="json")
        if admissibility is not None
        else None,
        "fraud_flags": state.get("fraud_flags", []),
        "critic": state["critic_report"].feedback() if state.get("critic_report") else [],
        "escalation": state.get("escalation"),
        "plan": render_plan(plan) if (render_plan and plan is not None) else None,
    }


def parse_decision(raw: Any) -> ReviewDecision:
    """Validate the UI reply (dict or ``ReviewDecision``) into a ``ReviewDecision``."""
    return raw if isinstance(raw, ReviewDecision) else ReviewDecision.model_validate(raw)


def needs_senior_review(
    worksheet: Worksheet | None, fraud_flags, threshold: Decimal | None = None
) -> bool:
    """True when the claim needs a senior sign-off (high value or any fraud flag)."""
    if worksheet is None:
        return False
    return needs_senior(worksheet, fraud_flags, threshold)


class ReviewGate:
    """Runs one review round and returns a state update identical in shape to ``nodes._review``.

    ``interrupt_fn`` is injected: pass ``langgraph.types.interrupt`` in production, or a test
    callback (as ``LocalRunner`` does) to answer synchronously. ``identity_provider`` supplies the
    *authenticated* approver; the approver id baked into the token comes from there, not from the
    UI payload (which is treated as untrusted). Pass ``store`` so issued approvals land in the
    persistent :class:`SqliteApprovalStore` the claims DB verifies against.

    An APPROVE on a claim with a worksheet issues a signed *settlement* approval; an APPROVE on a
    not-admissible claim (no worksheet) issues a signed *repudiation* approval bound to the
    admissibility hash, so ``record_repudiation`` has a signed decision to verify. An EDIT changes
    the worksheet (new hash), so any earlier approval is void.
    """

    def __init__(
        self,
        interrupt_fn: Callable[[dict], Any],
        identity_provider: IdentityProvider | None = None,
        *,
        store: ApprovalStore | None = None,
        render_plan: Callable[[Any], str] | None = None,
    ):
        self.interrupt = interrupt_fn
        self.identity = identity_provider
        self.store = store
        self._render_plan = render_plan

    def _authenticate(
        self, claim_id: str, level: ApprovalLevel, decision: ReviewDecision
    ) -> AuthenticatedApprover:
        if self.identity is not None:
            return self.identity.authenticate(claim_id, level)
        # Compatibility fallback: trust the decision's approver_id (documented as weaker). A real
        # deployment must pass an IdentityProvider so identity is not a free-form string.
        return AuthenticatedApprover(
            approver_id=decision.approver_id,
            level=level,
            auth_source="unverified",
            authenticated_at=datetime.now(UTC),
        )

    def review(self, state: dict, level: ApprovalLevel) -> dict:
        worksheet: Worksheet | None = state.get("worksheet")
        payload = build_review_payload(state, level, render_plan=self._render_plan)
        decision = parse_decision(self.interrupt(payload))
        base = {"review_decision": decision.decision.value}

        if decision.decision == ApprovalDecision.APPROVE:
            approver = self._authenticate(state.get("claim_id", ""), level, decision)
            if worksheet is not None:
                token = issue_approval(worksheet, approver, store=self.store)
            else:
                # Repudiation approval: bind to the admissibility subject hash from the payload.
                subject_hash = payload.get("worksheet_hash") or ""
                if not subject_hash:  # pragma: no cover - nothing to bind to
                    return base
                token = issue_repudiation_approval(
                    state.get("claim_id", ""), subject_hash, approver, store=self.store
                )
            return {**base, "approvals": [*state.get("approvals", []), token]}

        if decision.decision == ApprovalDecision.EDIT:
            prior = state.get("clause_choices") or {}
            edit_log = [
                {
                    "claim_id": state.get("claim_id"),
                    "level": level.value,
                    "line_id": e.line_id,
                    "old_clause": prior.get(e.line_id),
                    "new_clause": e.clause_id,
                    "new_amount": str(e.amount) if e.amount is not None else None,
                    "reason": e.reason,
                }
                for e in decision.edits
            ]
            return {**base, "pending_edits": decision.edits, "edit_log": edit_log}

        return {**base, "status": Status.REJECTED}


def make_node_review(
    interrupt_fn: Callable[[dict], Any],
    identity_provider: IdentityProvider | None = None,
    **kwargs: Any,
) -> Callable[[dict, ApprovalLevel], dict]:
    """Return a ``(state, level) -> update`` callable - the form ``nodes._review`` could delegate to."""
    gate = ReviewGate(interrupt_fn, identity_provider, **kwargs)
    return gate.review


# ============================================================================================
# 7. Drivers / demo
# ============================================================================================
def run_with_review(
    app: Any,
    packet: dict,
    reviewer: Callable[[dict], dict],
    max_reviews: int = 8,
    thread_id: str | None = None,
) -> dict:
    """Drive a compiled graph to completion, answering each pause with ``reviewer(payload)``.

    Delegates to Role 3's ``graph.build.run_claim`` (``interrupt`` + ``Command(resume=...)``).
    """
    from claimsense.graph.build import run_claim

    return run_claim(app, packet, reviewer, max_reviews=max_reviews, thread_id=thread_id)


def build_demo_gate(identity_provider: IdentityProvider | None = None):
    """A small standalone LangGraph showing the pause/resume cycle with the real contracts.

    Requires ``langgraph``. State carries a ``Worksheet``; approval is issued via this module, and
    an edit re-pauses with a new worksheet hash so the old approval is void. Role 3's full pipeline
    is the production path; this is a focused L14 demo.
    """
    from typing import TypedDict

    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import interrupt

    class GateState(TypedDict, total=False):
        claim_id: str
        worksheet: dict
        approvals: list
        review_decision: str
        status: str

    gate = ReviewGate(interrupt, identity_provider)

    def human_review(state: GateState) -> dict:
        ws = Worksheet.model_validate(state["worksheet"])
        s = {
            "claim_id": state["claim_id"],
            "worksheet": ws,
            "approvals": state.get("approvals", []),
            "admissibility": None,
        }
        update = gate.review(s, ApprovalLevel.ADJUDICATOR)
        out: dict = {"review_decision": update["review_decision"]}
        if "approvals" in update:
            out["approvals"] = [t.model_dump(mode="json") for t in update["approvals"]]
            out["status"] = "approved"
        elif update["review_decision"] == ApprovalDecision.REJECT.value:
            out["status"] = Status.REJECTED
        else:
            out["status"] = "edited"
        return out

    g = StateGraph(GateState)
    g.add_node("human_review", human_review)
    g.add_edge(START, "human_review")
    g.add_edge("human_review", END)
    return g.compile(checkpointer=InMemorySaver())
