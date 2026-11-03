"""Approval security for the L14 human-control gate. ClaimSense Role 4 (Tools, Control & Security).

Binds a human approval to the *exact* settlement worksheet and makes the binding hard to forge or
replay:

* **Canonical hash** - we reuse the contract's own ``Worksheet.content_hash()``
  (SHA-256 over ``model_dump_json``). We never invent a second hashing scheme, so a token minted
  anywhere in the system (including Role 3's ``graph/nodes._review``) stays comparable.
* **Trusted identity** - the approver id and role come from an :class:`IdentityProvider`
  (authenticated session / SSO), not a free-form string chosen by the caller.
* **Hash alone is not proof** - settlement requires a signed :class:`ApprovalRecord` in the store,
  HMAC'd with a server secret, in addition to a token whose hash matches the worksheet.
* **Replay prevention** - each record carries a nonce and is *consumed* on settlement; a stale,
  rejected, edited (different hash) or already-used approval can never settle.
* **Senior approval** - high-value or fraud-flagged claims require a SENIOR approval as well.

The settlement write path (``claims_db_server.settle_claim``) calls :func:`assert_can_settle`,
which raises ``PermissionError`` on any failure - matching the behaviour the Role 3 orchestration
tests rely on.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable, Protocol


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

from claimsense.contracts import ApprovalLevel, ApprovalToken, Worksheet  # noqa: E402


# --------------------------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------------------------
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
    """Senior-approval threshold (INR). Env override, else ``config/models.yaml``, else 100000."""
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


def _require_signed_default() -> bool:
    return os.environ.get("CLAIMSENSE_REQUIRE_SIGNED_APPROVAL", "1").strip().lower() not in {"0", "false", "no"}


_SECRET_LOCK = threading.Lock()
_EPHEMERAL_SECRET: bytes | None = None


def _server_secret() -> bytes:
    """HMAC secret for signing approval records.

    Prefers ``CLAIMSENSE_APPROVAL_SECRET``. If unset, a random per-process secret is generated so
    signatures still work within a run; records do not then survive a restart (documented).
    """
    env = os.environ.get("CLAIMSENSE_APPROVAL_SECRET")
    if env:
        return env.encode("utf-8")
    global _EPHEMERAL_SECRET
    with _SECRET_LOCK:
        if _EPHEMERAL_SECRET is None:
            _EPHEMERAL_SECRET = secrets.token_bytes(32)
        return _EPHEMERAL_SECRET


# --------------------------------------------------------------------------------------------
# Canonical worksheet hash (single source of truth)
# --------------------------------------------------------------------------------------------
def worksheet_hash(worksheet: Worksheet | dict) -> str:
    """Return ``Worksheet.content_hash()`` for a worksheet (dicts are validated first)."""
    ws = worksheet if isinstance(worksheet, Worksheet) else Worksheet.model_validate(worksheet)
    return ws.content_hash()


# --------------------------------------------------------------------------------------------
# Trusted identity
# --------------------------------------------------------------------------------------------
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
    """DEV ONLY. Trusts a preset id/level map. Production must use real authentication (SSO/JWT).

    It still models the contract: identity is provided here, not accepted as an arbitrary string
    from the worksheet or the document under review.
    """

    approver_ids: dict[ApprovalLevel, str] = field(
        default_factory=lambda: {ApprovalLevel.ADJUDICATOR: "demo-adjudicator",
                                 ApprovalLevel.SENIOR: "demo-senior"}
    )

    def authenticate(self, claim_id: str, level: ApprovalLevel) -> AuthenticatedApprover:
        approver_id = self.approver_ids.get(level)
        if not approver_id:
            raise PermissionError(f"no authenticated approver available for level {level}")
        return AuthenticatedApprover(approver_id=approver_id, level=level, auth_source="demo",
                                     authenticated_at=datetime.now(timezone.utc))


# --------------------------------------------------------------------------------------------
# Signed approval records + store
# --------------------------------------------------------------------------------------------
def _signature(token: ApprovalToken, nonce: str, secret: bytes) -> str:
    msg = "|".join(
        [token.claim_id, token.worksheet_hash, token.level.value, token.approver_id,
         token.decided_at.isoformat(), nonce]
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
        return hmac.compare_digest(self.signature, _signature(self.token, self.nonce, secret or _server_secret()))


class ApprovalStore(Protocol):
    """Durable store of signed approval records (swap the in-memory default for a DB in prod)."""

    def add(self, record: ApprovalRecord) -> None: ...
    def find(self, claim_id: str, worksheet_hash: str) -> list[ApprovalRecord]: ...
    def consume(self, record: ApprovalRecord) -> None: ...
    def is_consumed(self, record: ApprovalRecord) -> bool: ...


class InMemoryApprovalStore:
    """Thread-safe in-memory :class:`ApprovalStore`. Default store for development and tests."""

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
            return [r for r in self._records
                    if r.token.claim_id == claim_id and r.token.worksheet_hash == worksheet_hash]

    def consume(self, record: ApprovalRecord) -> None:
        with self._lock:
            self._consumed.add(self._key(record))

    def is_consumed(self, record: ApprovalRecord) -> bool:
        with self._lock:
            return self._key(record) in self._consumed


_DEFAULT_STORE = InMemoryApprovalStore()


def default_store() -> ApprovalStore:
    return _DEFAULT_STORE


def reset_default_store() -> None:
    """Clear the module-level store (tests)."""
    global _DEFAULT_STORE
    _DEFAULT_STORE = InMemoryApprovalStore()


# --------------------------------------------------------------------------------------------
# Issue / verify
# --------------------------------------------------------------------------------------------
def issue_approval(
    worksheet: Worksheet,
    approver: AuthenticatedApprover,
    *,
    nonce: str | None = None,
    store: ApprovalStore | None = None,
) -> ApprovalToken:
    """Mint a signed approval bound to this worksheet for a trusted approver, and store the record.

    Returns the :class:`ApprovalToken` (Role 3-compatible) to attach to graph state. The signed
    record (nonce + HMAC) is kept in ``store`` so later verification cannot be satisfied by a token
    alone.
    """
    store = store or default_store()
    token = ApprovalToken(
        claim_id=worksheet.claim_id,
        worksheet_hash=worksheet.content_hash(),
        level=approver.level,
        approver_id=approver.approver_id,
        decided_at=approver.authenticated_at,
    )
    nonce = nonce or secrets.token_hex(16)
    record = ApprovalRecord(token=token, nonce=nonce,
                            signature=_signature(token, nonce, _server_secret()),
                            auth_source=approver.auth_source)
    store.add(record)
    return token


def needs_senior(worksheet: Worksheet, fraud_flags: Iterable[str] | None, threshold: Decimal | None = None) -> bool:
    """Senior approval is required for high-value *or* fraud-flagged claims."""
    threshold = threshold if threshold is not None else senior_threshold_inr()
    return worksheet.total_payable > threshold or bool(list(fraud_flags or []))


@dataclass(frozen=True)
class ApprovalVerification:
    """Result of checking whether a settlement may proceed."""

    ok: bool
    reasons: tuple[str, ...] = ()
    used: tuple[ApprovalRecord, ...] = ()


def _matching_record(
    token: ApprovalToken, store: ApprovalStore
) -> ApprovalRecord | None:
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
    consume: bool = True,
) -> ApprovalVerification:
    """Decide whether ``worksheet`` may be settled given the presented ``tokens``.

    Enforces: a valid ADJUDICATOR approval bound to the exact worksheet (and a SENIOR one when
    ``senior_required``); that the hash matches (stale/edited approvals fail); that - when
    ``require_signed`` - the token is backed by a signed, non-consumed store record (so a hash
    alone is never proof); and consumes the records to stop replay.
    """
    store = store or default_store()
    require_signed = _require_signed_default() if require_signed is None else require_signed
    tokens = list(tokens or [])
    reasons: list[str] = []

    def find_valid(level: ApprovalLevel) -> tuple[ApprovalRecord | ApprovalToken | None, str | None]:
        """Return (valid record/token, reason-if-none). Only reports a reason when no token of this
        level is valid, so one stale token alongside a valid one does not cause a false rejection."""
        signed_missing = False
        for tok in tokens:
            if tok.level != level or not tok.is_valid_for(worksheet):
                continue
            record = _matching_record(tok, store)
            if record is not None:
                return record, None
            if require_signed:
                signed_missing = True
                continue
            return tok, None  # compatibility mode: accept a hash-valid bare token
        if signed_missing:
            return None, f"{level.value} approval is not backed by a signed record (hash alone is not proof)"
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
    consume: bool = True,
) -> None:
    """Raise ``PermissionError`` unless settlement is authorised (used by the write path)."""
    result = verify_for_settlement(worksheet, tokens, senior_required, store=store,
                                   require_signed=require_signed, consume=consume)
    if not result.ok:
        raise PermissionError("; ".join(result.reasons))
