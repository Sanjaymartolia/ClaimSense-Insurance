"""Pre-tool permission + budget, post-tool log + scrub (L14 hooks). ClaimSense Role 4.

Implements the control band from the reference architecture:
*"Hooks pre-tool: permission + budget check - post-tool: log + scrub."*

* **Permission** - reuses the project's single source of truth, ``agents.permissions.TOOL_ACL``
  (imported, never re-declared), so an agent can only reach the tools it is entitled to and a
  prompt-injected agent still cannot reach ``settle_claim``.
* **Budget** - per-agent and per-claim tool-call ceilings, defaulting to
  ``config/models.yaml -> budgets.max_tool_calls_per_claim`` (40).
* **Audit** - post-tool records carry only metadata: timestamp, agent, tool, allowed/status and a
  safe error code. Never the tool arguments, results, documents or any health detail.

Integration (so hooks are actually *called*, not just defined):
:class:`HookedToolBelt` subclasses the Role 3 ``ToolBelt`` and runs the hooks around every
``call``. Role 3 can obtain belts via :func:`hooked_belt` / build a team with hooked belts (see
``role4_services``); at an MCP-client boundary, call :func:`pre_tool_hook` / :func:`post_tool_hook`
directly. Nothing in Role 3 is modified by importing this module.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


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

logger = logging.getLogger("claimsense.hooks.audit")


class ToolBudgetExceeded(RuntimeError):
    """Raised when an agent or claim exceeds its tool-call budget."""


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


def default_max_tool_calls_per_claim() -> int:
    """From ``config/models.yaml -> budgets.max_tool_calls_per_claim``; falls back to 40."""
    env = os.environ.get("CLAIMSENSE_MAX_TOOL_CALLS")
    if env and env.isdigit():
        return int(env)
    cfg = Path(os.environ.get("CLAIMSENSE_CONFIG", "")) if os.environ.get("CLAIMSENSE_CONFIG") \
        else _repo_root() / "config" / "models.yaml"
    try:
        import yaml

        with cfg.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return int(data["budgets"]["max_tool_calls_per_claim"])
    except (OSError, KeyError, TypeError, ValueError, ImportError):
        return 40


@dataclass
class BudgetState:
    """Per-claim tool-call budget, shared across that claim's agents.

    ``per_claim`` caps the total calls for the whole claim; ``per_agent`` optionally caps a single
    agent (defaults to the per-claim cap). Create one per claim.
    """

    per_claim: int = field(default_factory=default_max_tool_calls_per_claim)
    per_agent: dict[AgentName, int] = field(default_factory=dict)
    _agent_counts: dict[str, int] = field(default_factory=dict)
    _total: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def would_exceed(self, agent: AgentName) -> str | None:
        with self._lock:
            agent_limit = self.per_agent.get(agent, self.per_claim)
            if self._agent_counts.get(agent.value, 0) >= agent_limit:
                return f"per-agent budget of {agent_limit} reached for {agent.value}"
            if self._total >= self.per_claim:
                return f"per-claim budget of {self.per_claim} reached"
            return None

    def charge(self, agent: AgentName) -> None:
        with self._lock:
            self._agent_counts[agent.value] = self._agent_counts.get(agent.value, 0) + 1
            self._total += 1

    @property
    def total(self) -> int:
        return self._total


# --------------------------------------------------------------------------------------------
# Audit (metadata only; never PHI)
# --------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class AuditRecord:
    timestamp: str
    agent: str
    tool: str
    allowed: bool
    status: str                 # "ok" | "denied" | "error"
    error_code: str | None = None
    claim_id: str | None = None


class AuditLog:
    """Collects scrubbed :class:`AuditRecord`s and emits them to the ``claimsense.hooks.audit`` logger."""

    def __init__(self) -> None:
        self.records: list[AuditRecord] = []
        self._lock = threading.Lock()

    def record(self, agent: AgentName | str, tool: str, *, allowed: bool, status: str,
               error_code: str | None = None, claim_id: str | None = None) -> AuditRecord:
        rec = AuditRecord(
            timestamp=datetime.now(timezone.utc).isoformat(),
            agent=agent.value if isinstance(agent, AgentName) else str(agent),
            tool=tool, allowed=allowed, status=status, error_code=error_code, claim_id=claim_id,
        )
        with self._lock:
            self.records.append(rec)
        logger.info("audit agent=%s tool=%s allowed=%s status=%s code=%s claim=%s",
                    rec.agent, rec.tool, rec.allowed, rec.status, rec.error_code, rec.claim_id)
        return rec


_DEFAULT_AUDIT = AuditLog()


def default_audit_log() -> AuditLog:
    return _DEFAULT_AUDIT


# --------------------------------------------------------------------------------------------
# Hook functions (usable without a ToolBelt, e.g. at an MCP-client boundary)
# --------------------------------------------------------------------------------------------
def check_permission(agent: AgentName, tool: str) -> bool:
    """True iff ``agent`` may call ``tool`` per ``TOOL_ACL``."""
    return tool in TOOL_ACL.get(agent, frozenset())


def pre_tool_hook(agent: AgentName, tool: str, budget: BudgetState | None = None) -> None:
    """Pre-tool gate: raise ``ToolPermissionError`` / ``ToolBudgetExceeded`` to block the call."""
    if not check_permission(agent, tool):
        raise ToolPermissionError(f"{agent.value} may not call {tool}")
    if budget is not None:
        reason = budget.would_exceed(agent)
        if reason:
            raise ToolBudgetExceeded(reason)
        budget.charge(agent)


def post_tool_hook(agent: AgentName, tool: str, *, status: str, error_code: str | None = None,
                   claim_id: str | None = None, audit: AuditLog | None = None) -> AuditRecord:
    """Post-tool: write a scrubbed audit record (no arguments, results or health details)."""
    audit = audit or default_audit_log()
    return audit.record(agent, tool, allowed=(status != "denied"), status=status,
                        error_code=error_code, claim_id=claim_id)


# --------------------------------------------------------------------------------------------
# HookedToolBelt - the concrete integration point
# --------------------------------------------------------------------------------------------
class HookedToolBelt(ToolBelt):
    """A ``ToolBelt`` that runs the pre/post hooks around every ``call``.

    Drop-in for the Role 3 ``ToolBelt``: the agents call ``belt.call(name, **kwargs)`` exactly as
    before. Permission is enforced against ``TOOL_ACL`` (shared table), budget against the
    ``BudgetState``, and a scrubbed audit record is written for every attempt.
    """

    def __init__(self, agent: AgentName, registry: dict[str, Callable[..., Any]], log=None, *,
                 budget: BudgetState | None = None, audit: AuditLog | None = None,
                 claim_id: str | None = None):
        super().__init__(agent, registry, log)
        self._budget = budget
        self._audit = audit or default_audit_log()
        self._claim_id = claim_id

    def call(self, name: str, /, **kwargs: Any) -> Any:
        # Pre-tool: permission (TOOL_ACL) + budget.
        if not check_permission(self.agent, name):
            self._log.append({"agent": self.agent.value, "tool": name, "allowed": False})
            post_tool_hook(self.agent, name, status="denied", error_code="permission_denied",
                           claim_id=self._claim_id, audit=self._audit)
            raise ToolPermissionError(f"{self.agent.value} may not call {name}")
        if self._budget is not None:
            reason = self._budget.would_exceed(self.agent)
            if reason:
                self._log.append({"agent": self.agent.value, "tool": name, "allowed": False})
                post_tool_hook(self.agent, name, status="denied", error_code="budget_exceeded",
                               claim_id=self._claim_id, audit=self._audit)
                raise ToolBudgetExceeded(reason)
            self._budget.charge(self.agent)

        # Execute via the base belt (re-checks ACL and appends the allowed=True tool_log entry).
        try:
            result = super().call(name, **kwargs)
        except ToolPermissionError:
            post_tool_hook(self.agent, name, status="denied", error_code="permission_denied",
                           claim_id=self._claim_id, audit=self._audit)
            raise
        except Exception as exc:  # noqa: BLE001 - we record a safe code, never the payload
            post_tool_hook(self.agent, name, status="error", error_code=type(exc).__name__,
                           claim_id=self._claim_id, audit=self._audit)
            raise
        post_tool_hook(self.agent, name, status="ok", claim_id=self._claim_id, audit=self._audit)
        return result


def hooked_belt(agent: AgentName, registry: dict[str, Callable[..., Any]], *,
                budget: BudgetState | None = None, audit: AuditLog | None = None,
                claim_id: str | None = None, log=None) -> HookedToolBelt:
    """Factory for a :class:`HookedToolBelt` (convenience for ``role4_services`` and tests)."""
    return HookedToolBelt(agent, registry, log, budget=budget, audit=audit, claim_id=claim_id)
