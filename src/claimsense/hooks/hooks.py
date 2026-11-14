"""Pre-tool permission + budget, post-tool log + scrub (L14 hooks). ClaimSense Role 4.

Implements the control band from the reference architecture:
*"Hooks pre-tool: permission + budget check - post-tool: log + scrub."*

* **Permission** - reuses the project's single source of truth, ``agents.permissions.TOOL_ACL``
  (imported, never re-declared), so an agent can only reach the tools it is entitled to and a
  prompt-injected agent still cannot reach ``settle_claim``.
* **Budget** - deterministic per-claim / per-agent / per-tool / repeated-call tool-call ceilings.
  Totals default from ``config/models.yaml -> budgets.max_tool_calls_per_claim`` (40). There is no
  financial-cost ceiling: tool execution is a local Python call with no reliable per-call USD
  signal, so ``budgets.max_cost_usd_per_claim`` is **intentionally not
  enforced** here (see §Budget).
* **Audit** - post-tool records carry only metadata: timestamp, agent, tool, allowed/status, a safe
  error *code* (exception class name, never its message), optional claim id and execution duration.
  Never the tool arguments, results, documents or any health detail.

Why this module exists / how it actually runs
----------------------------------------------
Role 3 already funnels every agent tool call through ``agents.permissions.ToolBelt.call`` (the one
interception seam) and records a minimal ``{agent, tool, allowed}`` line in ``services.tool_log``.
Role 3 has **no** budget, **no** post-tool hook and **no** richer audit, and - critically - every
agent builds a *plain* ``ToolBelt`` in its ``__init__`` (``from .permissions import ToolBelt``), so
simply *defining* a hooked belt does nothing. :class:`HookedToolBelt` subclasses ``ToolBelt`` and
runs the hooks around every ``call`` (drop-in: same ``call(name, **kwargs)`` API, same ``tool_log``
entries). :func:`install_hooks` / :func:`build_hooked_team` then swap each already-built agent's
``.belt`` for a :class:`HookedToolBelt` **after** ``Team(...)`` is constructed - no Role 3 source,
no ``Services`` contract and no ``ToolBelt`` signature is modified. At an MCP-client boundary with
no belt, call :func:`pre_tool_hook` / :func:`post_tool_hook` directly. Importing this module changes
nothing in Role 3.

Scope boundaries (what hooks do NOT do)
---------------------------------------
Hooks enforce *tool permission* and *execution budget* and write a scrubbed audit line. They do
**not** verify approvals, issue tokens, or authorise settlement - that stays in ``approvals`` and in
``claims_db.settle_claim`` / ``record_repudiation`` (the server-side signed-approval locks). The
money is guarded by three independent locks: the per-agent ACL (here + base ``ToolBelt``), the
signed-approval check in the DB, and ``settle_claim`` taking no amount argument. A belt bypass alone
therefore still cannot move money.
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any


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

from claimsense.agents.permissions import TOOL_ACL, ToolBelt, ToolPermissionError  # noqa: E402
from claimsense.contracts import AgentName  # noqa: E402

if (
    TYPE_CHECKING
):  # import only for type checkers; avoids pulling the whole agents package at runtime
    from claimsense.agents import Team

logger = logging.getLogger("claimsense.hooks.audit")


class ToolBudgetExceeded(RuntimeError):
    """Raised when an agent or claim exceeds its tool-call budget (fail-closed: tool never runs)."""


class ToolScopeError(ToolPermissionError):
    """A tool argument named a record outside the current claim (claim id or policy number)."""


class AuditUnavailable(RuntimeError):
    """Raised on a successful call only when a *fail-closed* audit log cannot emit its record.

    Default audit is fail-open-but-observable (emit failures are counted, never concealed); set
    ``AuditLog(fail_closed=True)`` to make an audit-sink outage block completion instead.
    """


# --------------------------------------------------------------------------------------------
# Budgets
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


@lru_cache(maxsize=4)
def _budgets_config(cfg_path: str) -> dict:
    """Read and cache the ``budgets:`` block of ``config/models.yaml`` (keyed by resolved path)."""
    try:
        import yaml

        with Path(cfg_path).open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        budgets = data.get("budgets") or {}
        return budgets if isinstance(budgets, dict) else {}
    except (OSError, TypeError, ValueError, ImportError):
        return {}


def _config_path() -> str:
    env = os.environ.get("CLAIMSENSE_CONFIG")
    return env if env else str(_repo_root() / "config" / "models.yaml")


def default_max_tool_calls_per_claim() -> int:
    """From ``config/models.yaml -> budgets.max_tool_calls_per_claim``; env override;
    falls back to 40."""
    env = os.environ.get("CLAIMSENSE_MAX_TOOL_CALLS")
    if env and env.isdigit():
        return int(env)
    try:
        return int(_budgets_config(_config_path())["max_tool_calls_per_claim"])
    except (KeyError, TypeError, ValueError):
        return 40


def default_max_calls_per_tool() -> int | None:
    """Optional per-tool cap from ``budgets.max_calls_per_tool`` /
    ``CLAIMSENSE_MAX_CALLS_PER_TOOL``.

    ``None`` (the default when unset) means *no* per-tool cap. A per-tool cap is intentionally left
    off by default: the legitimate pipeline calls ``calculate`` several times per claim (coverage,
    fraud rebuild, critic re-check, each revision, apply-edits), so a tight default would break a
    normal run. Set it explicitly when you want the extra ceiling.
    """
    env = os.environ.get("CLAIMSENSE_MAX_CALLS_PER_TOOL")
    if env and env.isdigit():
        return int(env)
    val = _budgets_config(_config_path()).get("max_calls_per_tool")
    try:
        return int(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def default_max_repeated_calls() -> int | None:
    """Optional identical-call cap from ``budgets.max_repeated_calls`` /
    ``CLAIMSENSE_MAX_REPEATED_CALLS``.

    ``None`` (default) disables repeat detection. A "repeat" is the *same tool with the same
    arguments* called again - a loop tell. Detection uses a one-way fingerprint of the arguments;
    the raw arguments are never stored or logged.
    """
    env = os.environ.get("CLAIMSENSE_MAX_REPEATED_CALLS")
    if env and env.isdigit():
        return int(env)
    val = _budgets_config(_config_path()).get("max_repeated_calls")
    try:
        return int(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def _arg_fingerprint(tool: str, kwargs: dict[str, Any]) -> str | None:
    """A short, one-way fingerprint of (tool, arguments) for repeat detection.

    Returns ``None`` if a stable key cannot be built (then the repeat ceiling is simply skipped for
    that call; the per-tool and per-claim ceilings still bound it). The digest is never logged and
    cannot be reversed to recover arguments, so it carries no PHI.
    """
    try:
        key = tool + "|" + "&".join(f"{k}={kwargs[k]!r}" for k in sorted(kwargs))
        return hashlib.sha256(key.encode("utf-8", "replace")).hexdigest()[:16]
    except Exception:  # noqa: BLE001 - repeat detection must never crash a tool call
        return None


@dataclass
class BudgetState:
    """Deterministic, thread-safe tool-call budget for a single claim execution.

    Ceilings (all checked *before* a call runs; the call is rejected if any is already reached):

    * ``per_claim``   - total tool calls for the whole claim (default from ``config/models.yaml``).
    * ``per_agent``   - optional map of per-agent caps (an agent with no entry falls back to
      ``per_claim``).
    * ``per_tool``    - optional cap on how many times any single tool may be
      called (``None`` = off).
    * ``max_repeats`` - optional cap on identical (tool, arguments) repeats (``None`` = off).

    Create **one per claim** and do not share it across unrelated claims or graph executions (use
    :func:`claim_hooks` / :meth:`reset`). Counting is on *attempt*, not success: a call that passes
    the ACL is charged whether the tool then succeeds or raises, so a failing tool cannot be retried
    without bound. :meth:`try_charge` checks-and-increments under a single lock, so concurrent
    agents sharing this state can never slip past a ceiling (no check-then-charge race).
    """

    per_claim: int = field(default_factory=default_max_tool_calls_per_claim)
    per_agent: dict[AgentName, int] = field(default_factory=dict)
    per_tool: int | None = field(default_factory=default_max_calls_per_tool)
    max_repeats: int | None = field(default_factory=default_max_repeated_calls)
    _agent_counts: dict[str, int] = field(default_factory=dict)
    _tool_counts: dict[str, int] = field(default_factory=dict)
    _repeat_counts: dict[str, int] = field(default_factory=dict)
    _total: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # ---- back-compat helpers (agent + total only); kept for external callers -------------------
    def would_exceed(self, agent: AgentName) -> str | None:
        """Non-mutating check of the agent/claim totals (kept for compatibility; not atomic).

        Prefer :meth:`try_charge`, which checks *and* charges atomically. Using ``would_exceed``
        followed by :meth:`charge` has a check-then-charge race under concurrency.
        """
        with self._lock:
            agent_limit = self.per_agent.get(agent, self.per_claim)
            if self._agent_counts.get(agent.value, 0) >= agent_limit:
                return f"per-agent budget of {agent_limit} reached for {agent.value}"
            if self._total >= self.per_claim:
                return f"per-claim budget of {self.per_claim} reached"
            return None

    def charge(self, agent: AgentName) -> None:
        """Increment the agent + claim totals (back-compat; pairs with :meth:`would_exceed`)."""
        with self._lock:
            self._agent_counts[agent.value] = self._agent_counts.get(agent.value, 0) + 1
            self._total += 1

    # ---- the atomic, full-coverage charge used by the hooks ------------------------------------
    def try_charge(
        self, agent: AgentName, tool: str | None = None, *, fingerprint: str | None = None
    ) -> str | None:
        """Atomically check every ceiling and, if all pass, charge them. One lock acquisition.

        Returns ``None`` when the call is allowed (and counters were incremented), or a short reason
        string when a ceiling is already reached (and **nothing** was incremented). This single
        critical section is why concurrent calls cannot bypass the budget.
        """
        with self._lock:
            agent_limit = self.per_agent.get(agent, self.per_claim)
            if self._agent_counts.get(agent.value, 0) >= agent_limit:
                return f"per-agent budget of {agent_limit} reached for {agent.value}"
            if self._total >= self.per_claim:
                return f"per-claim budget of {self.per_claim} reached"
            if (
                self.per_tool is not None
                and tool is not None
                and self._tool_counts.get(tool, 0) >= self.per_tool
            ):
                return f"per-tool budget of {self.per_tool} reached for {tool}"
            if (
                self.max_repeats is not None
                and fingerprint is not None
                and self._repeat_counts.get(fingerprint, 0) >= self.max_repeats
            ):
                return f"repeated-call budget of {self.max_repeats} reached for {tool}"
            # all ceilings clear -> commit the charge
            self._agent_counts[agent.value] = self._agent_counts.get(agent.value, 0) + 1
            self._total += 1
            if tool is not None:
                self._tool_counts[tool] = self._tool_counts.get(tool, 0) + 1
            if fingerprint is not None:
                self._repeat_counts[fingerprint] = self._repeat_counts.get(fingerprint, 0) + 1
            return None

    def reset(self) -> None:
        """Clear all counters so the same object can start a fresh claim (ceilings are kept)."""
        with self._lock:
            self._agent_counts.clear()
            self._tool_counts.clear()
            self._repeat_counts.clear()
            self._total = 0

    @property
    def total(self) -> int:
        return self._total

    @property
    def agent_counts(self) -> dict[str, int]:
        with self._lock:
            return dict(self._agent_counts)

    @property
    def tool_counts(self) -> dict[str, int]:
        with self._lock:
            return dict(self._tool_counts)


# --------------------------------------------------------------------------------------------
# Audit (metadata only; never PHI)
# --------------------------------------------------------------------------------------------
# The only fields an audit record may ever carry. Enforced by tests: nothing here can hold a claim
# document, policy text, patient identity, diagnosis, approval secret, signature or token.
SAFE_AUDIT_FIELDS = frozenset(
    {
        "timestamp",
        "agent",
        "tool",
        "allowed",
        "status",
        "error_code",
        "claim_id",
        "duration_ms",
        "run_id",
    }
)


@dataclass(frozen=True)
class AuditRecord:
    timestamp: str
    agent: str
    tool: str
    allowed: bool
    status: str  # "ok" | "denied" | "error"
    error_code: str | None = None  # exception CLASS name or a safe code; never a message
    claim_id: str | None = None  # correlation id only (a claim id is not PHI)
    duration_ms: float | None = None
    run_id: str | None = None  # the claim run this call belongs to (a random id, rubric D3)


class AuditLog:
    """Collects scrubbed :class:`AuditRecord`s and emits them to ``claimsense.hooks.audit``.

    Fail-safe policy. The in-memory record is appended *before* the log sink is touched, so it
    is the source of truth and cannot be lost to a logging-backend outage. If the sink raises,
    the failure is counted in :attr:`emit_failures` and recorded in :attr:`last_emit_error`
    (never silently swallowed). With ``fail_closed=True`` a sink failure on a *successful*
    call additionally raises
    :class:`AuditUnavailable`, so an environment that mandates guaranteed audit can halt rather than
    proceed un-audited; the default (``False``) keeps processing but leaves the failure observable.
    """

    def __init__(self, *, fail_closed: bool = False, run_id: str | None = None) -> None:
        self.records: list[AuditRecord] = []
        self.fail_closed = fail_closed
        self.run_id = run_id  # stamped on every record: two runs of one claim stay apart
        self.emit_failures = 0
        self.last_emit_error: str | None = None
        self._lock = threading.Lock()

    def record(
        self,
        agent: AgentName | str,
        tool: str,
        *,
        allowed: bool,
        status: str,
        error_code: str | None = None,
        claim_id: str | None = None,
        duration_ms: float | None = None,
    ) -> AuditRecord:
        rec = AuditRecord(
            timestamp=datetime.now(UTC).isoformat(),
            agent=agent.value if isinstance(agent, AgentName) else str(agent),
            tool=tool,
            allowed=allowed,
            status=status,
            error_code=error_code,
            claim_id=claim_id,
            duration_ms=duration_ms,
            run_id=self.run_id,
        )
        with self._lock:
            self.records.append(rec)  # source of truth, captured before any sink can fail
        emitted = self._emit(rec)
        if not emitted and self.fail_closed:
            raise AuditUnavailable(f"audit sink unavailable for tool={tool} status={status}")
        return rec

    def _emit(self, rec: AuditRecord) -> bool:
        try:
            logger.info(
                "audit agent=%s tool=%s allowed=%s status=%s code=%s claim=%s dur_ms=%s",
                rec.agent,
                rec.tool,
                rec.allowed,
                rec.status,
                rec.error_code,
                rec.claim_id,
                None if rec.duration_ms is None else round(rec.duration_ms, 3),
                # The same record as fields, for a sink that writes data (`api/audit.py`).
                extra={"audit": {"event": "tool", **asdict(rec)}},
            )
            return True
        except Exception as exc:  # noqa: BLE001 - a broken sink must not lose the audit record
            with self._lock:
                self.emit_failures += 1
                self.last_emit_error = type(exc).__name__
            with contextlib.suppress(Exception):  # best-effort surfacing; never conceal
                logging.getLogger("claimsense.hooks.audit").warning(
                    "audit emit failed: %s", type(exc).__name__
                )
            return False


_DEFAULT_AUDIT = AuditLog()


def default_audit_log() -> AuditLog:
    return _DEFAULT_AUDIT


# --------------------------------------------------------------------------------------------
# Hook functions (usable without a ToolBelt, e.g. at an MCP-client boundary)
# --------------------------------------------------------------------------------------------
def check_permission(agent: AgentName, tool: str) -> bool:
    """True iff ``agent`` may call ``tool`` per the shared ``TOOL_ACL`` (never a second table)."""
    return tool in TOOL_ACL.get(agent, frozenset())


def pre_tool_hook(agent: AgentName, tool: str, budget: BudgetState | None = None) -> None:
    """Pre-tool gate: raise ``ToolPermissionError`` / ``ToolBudgetExceeded`` to block the call.

    Fail-closed: raises before the caller runs the tool. Charges the budget atomically on success.
    """
    if not check_permission(agent, tool):
        raise ToolPermissionError(f"{agent.value} may not call {tool}")
    if budget is not None:
        reason = budget.try_charge(agent, tool)
        if reason:
            raise ToolBudgetExceeded(reason)


def post_tool_hook(
    agent: AgentName,
    tool: str,
    *,
    status: str,
    error_code: str | None = None,
    claim_id: str | None = None,
    audit: AuditLog | None = None,
    duration_ms: float | None = None,
) -> AuditRecord:
    """Post-tool: write one scrubbed audit record (no arguments, results or health details)."""
    audit = audit or default_audit_log()
    return audit.record(
        agent,
        tool,
        allowed=(status != "denied"),
        status=status,
        error_code=error_code,
        claim_id=claim_id,
        duration_ms=duration_ms,
    )


# --------------------------------------------------------------------------------------------
# HookedToolBelt - the concrete interception point (drop-in subclass of Role 3 ToolBelt)
# --------------------------------------------------------------------------------------------
class HookedToolBelt(ToolBelt):
    """A ``ToolBelt`` that runs the pre/post hooks around every ``call``.

    Behaviour-compatible with the Role 3 ``ToolBelt``: agents call ``belt.call(name, **kwargs)``
    exactly as before, and the same ``{agent, tool, allowed}`` lines are appended to the shared
    ``tool_log``. On top, permission is enforced against ``TOOL_ACL``, budget against the
    ``BudgetState`` (atomically), and a scrubbed audit record is written for every attempt -
    allowed, denied or errored.

    Status semantics in the audit trail:

    * ``denied`` - blocked by this hook (ACL or budget) *before* the tool ran.
    * ``error``  - the tool was permitted and ran, but raised (e.g. ``settle_claim`` refusing an
      unsigned approval); the original exception is re-raised, never swallowed.
    * ``ok``     - the tool ran and returned.
    """

    def __init__(
        self,
        agent: AgentName,
        registry: dict[str, Callable[..., Any]],
        log=None,
        *,
        budget: BudgetState | None = None,
        audit: AuditLog | None = None,
        claim_id: str | None = None,
    ):
        super().__init__(agent, registry, log)
        self._budget = budget
        self._audit = audit or default_audit_log()
        self._claim_id = claim_id
        # L15 notebook section 8, least privilege: the record a tool may touch is the claim's own,
        # set by the system from trusted inputs only: the claim id from the graph state, and the
        # policy number the intake system registered (`graph.nodes.registered_policy`), never a
        # value a model extracted from document text. See `scope_to`.
        self._scope: dict[str, str] = {"claim_id": claim_id} if claim_id else {}

    def scope_to(self, **fields: str) -> None:
        """Pin record-selecting tool arguments (claim_id, policy_number) to this claim's values."""
        self._scope.update({k: str(v) for k, v in fields.items() if v})

    def _out_of_scope(self, kwargs: dict[str, Any]) -> str | None:
        for key, allowed in self._scope.items():
            value = kwargs.get(key)
            if value is not None and str(value) != allowed:
                return key
        return None

    # audit that must not downgrade a denial/error if the audit sink itself is fail-closed
    def _audit_nonblocking(
        self, tool: str, *, status: str, error_code: str | None, duration_ms: float | None = None
    ) -> None:
        try:
            post_tool_hook(
                self.agent,
                tool,
                status=status,
                error_code=error_code,
                claim_id=self._claim_id,
                audit=self._audit,
                duration_ms=duration_ms,
            )
        except AuditUnavailable:
            # The record is already captured + the failure counted. A denial/error is the dominant
            # outcome and still propagates; an audit-sink outage must never turn
            # a denial into allow.
            pass

    def call(self, name: str, /, **kwargs: Any) -> Any:
        # 1) Permission (fail-closed): an un-permitted tool is never executed.
        if not check_permission(self.agent, name):
            self._log.append({"agent": self.agent.value, "tool": name, "allowed": False})
            self._audit_nonblocking(name, status="denied", error_code="permission_denied")
            raise ToolPermissionError(f"{self.agent.value} may not call {name}")

        # 1b) Scope (fail-closed): a tool may read or write only this claim's records. Stops the
        # confused deputy: injected text that changes the extracted policy number cannot make an
        # agent fetch another policy's history (the scope comes from intake, not extraction).
        field_name = self._out_of_scope(kwargs)
        if field_name is not None:
            self._log.append({"agent": self.agent.value, "tool": name, "allowed": False})
            self._audit_nonblocking(name, status="denied", error_code="out_of_scope")
            raise ToolScopeError(f"{self.agent.value}: {name} asked for another {field_name}")

        # 2) Budget (fail-closed, atomic): reject before execution if any ceiling is reached.
        if self._budget is not None:
            fp = _arg_fingerprint(name, kwargs) if self._budget.max_repeats is not None else None
            reason = self._budget.try_charge(self.agent, name, fingerprint=fp)
            if reason is not None:
                self._log.append({"agent": self.agent.value, "tool": name, "allowed": False})
                self._audit_nonblocking(name, status="denied", error_code="budget_exceeded")
                raise ToolBudgetExceeded(reason)

        # 3) Execute via the base belt (re-checks the ACL and appends the
        # allowed=True tool_log line).
        start = time.perf_counter()
        try:
            result = super().call(name, **kwargs)
        except ToolPermissionError:
            dur = (time.perf_counter() - start) * 1000.0
            self._audit_nonblocking(
                name, status="denied", error_code="permission_denied", duration_ms=dur
            )
            raise
        except Exception as exc:  # noqa: BLE001 - record a safe code, never the payload/message
            dur = (time.perf_counter() - start) * 1000.0
            self._audit_nonblocking(
                name, status="error", error_code=type(exc).__name__, duration_ms=dur
            )
            raise  # propagate the ORIGINAL exception unchanged; never a fake success

        # 4) Post-tool success audit. Honours a fail-closed audit sink
        # (AuditUnavailable propagates).
        dur = (time.perf_counter() - start) * 1000.0
        post_tool_hook(
            self.agent,
            name,
            status="ok",
            claim_id=self._claim_id,
            audit=self._audit,
            duration_ms=dur,
        )
        return result


def hooked_belt(
    agent: AgentName,
    registry: dict[str, Callable[..., Any]],
    *,
    budget: BudgetState | None = None,
    audit: AuditLog | None = None,
    claim_id: str | None = None,
    log=None,
) -> HookedToolBelt:
    """Factory for a :class:`HookedToolBelt` (convenience for adapters and tests)."""
    return HookedToolBelt(agent, registry, log, budget=budget, audit=audit, claim_id=claim_id)


# --------------------------------------------------------------------------------------------
# Adapter: make the hooks fire in the REAL execution path without touching Role 3
# --------------------------------------------------------------------------------------------
# Role 3's Team builds these five agents, each exposing `.name` (AgentName) and `.belt` (ToolBelt).
_TEAM_AGENT_ATTRS = ("extraction", "coverage", "fraud", "critic", "settlement")


@dataclass
class HookGuard:
    """Handle returned by :func:`install_hooks`: the shared budget/audit plus a belt restorer.

    Also a context manager - on exit it restores each agent's original belt, so a ``Team`` can be
    reused for the next claim with a fresh budget (``with claim_hooks(...)``).
    """

    team: Team
    budget: BudgetState
    audit: AuditLog
    _original: dict[str, ToolBelt] = field(default_factory=dict, repr=False)

    def scope_to(self, **fields: str) -> None:
        """Pin every hooked belt's record-selecting arguments to this claim (``HookedToolBelt``)."""
        for attr in self._original:
            belt = getattr(getattr(self.team, attr, None), "belt", None)
            if isinstance(belt, HookedToolBelt):
                belt.scope_to(**fields)

    def restore(self) -> None:
        """Put back each agent's original (plain) ``ToolBelt``."""
        for attr, belt in self._original.items():
            agent_obj = getattr(self.team, attr, None)
            if agent_obj is not None:
                agent_obj.belt = belt
        self._original.clear()

    def __enter__(self) -> HookGuard:
        return self

    def __exit__(self, *exc) -> None:
        self.restore()


def install_hooks(
    team: Team,
    *,
    budget: BudgetState | None = None,
    audit: AuditLog | None = None,
    claim_id: str | None = None,
    agent_attrs: tuple[str, ...] = _TEAM_AGENT_ATTRS,
) -> HookGuard:
    """Swap every agent's ``.belt`` on an already-built ``Team`` for a :class:`HookedToolBelt`.

    All agents share one ``budget`` and one ``audit`` so the per-claim ceiling spans the whole team.
    The hooked belts reuse ``team.services.registry()`` and the shared
    ``team.services.tool_log``, so the base ACL check and the existing ``{agent, tool, allowed}``
    trace behave exactly as before.

    No Role 3 source is modified: this only reassigns the ``belt`` attribute on the Python objects
    Role 3 already created. Call it **per claim** with a fresh ``BudgetState`` (or use
    :func:`claim_hooks`). It assumes one claim per ``Team`` at a time (Role 3's model: one
    Team/Services per graph run); for concurrent claims, build one ``Team`` per claim.
    """
    budget = budget if budget is not None else BudgetState()
    audit = audit if audit is not None else default_audit_log()
    guard = HookGuard(team=team, budget=budget, audit=audit)
    registry = team.services.registry()
    tool_log = team.services.tool_log
    for attr in agent_attrs:
        agent_obj = getattr(team, attr, None)
        if agent_obj is None or not hasattr(agent_obj, "belt"):
            continue
        guard._original[attr] = agent_obj.belt
        agent_obj.belt = HookedToolBelt(
            agent_obj.name, registry, tool_log, budget=budget, audit=audit, claim_id=claim_id
        )
    return guard


def build_hooked_team(
    services,
    *,
    playbook=None,
    budget: BudgetState | None = None,
    audit: AuditLog | None = None,
    claim_id: str | None = None,
):
    """Build a Role 3 ``Team`` and immediately install hooked belts. Returns
    ``(team, HookGuard)``."""
    from claimsense.agents import Team  # lazy: only when an adapter is actually used

    team = Team(services, playbook=playbook)
    guard = install_hooks(team, budget=budget, audit=audit, claim_id=claim_id)
    return team, guard


@contextlib.contextmanager
def claim_hooks(
    team: Team,
    claim_id: str | None = None,
    *,
    per_claim: int | None = None,
    per_tool: int | None = None,
    max_repeats: int | None = None,
    per_agent: dict[AgentName, int] | None = None,
    audit: AuditLog | None = None,
):
    """Per-claim scope: install a FRESH budget, run the claim, then restore the original belts.

    Guarantees budget state is never shared across unrelated claims::

        with claim_hooks(team, claim_id="CLM-1") as guard:
            result = LocalRunner(team).run(packet_1, reviewer)   # audited, budgeted
        # team's plain belts are back; next claim starts from zero
    """
    kwargs: dict[str, Any] = {}
    if per_claim is not None:
        kwargs["per_claim"] = per_claim
    if per_agent is not None:
        kwargs["per_agent"] = per_agent
    if per_tool is not None:
        kwargs["per_tool"] = per_tool
    if max_repeats is not None:
        kwargs["max_repeats"] = max_repeats
    budget = BudgetState(**kwargs)
    guard = install_hooks(team, budget=budget, audit=audit, claim_id=claim_id)
    try:
        yield guard
    finally:
        guard.restore()
