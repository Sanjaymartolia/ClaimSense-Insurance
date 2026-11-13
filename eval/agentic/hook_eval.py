"""Hooks, ACLs, output guard and guardrails against `hook_cases.jsonl`, plus the attack table.

`guardrails.py` is scored too. Each result carries `wired`, which is true only when product code
outside `guardrails/` imports a guardrails module. Since dc934a7 the extraction and settlement
agents do; `check_consistency` and `scan_documents` themselves are still not called by the
pipeline, so the attack table reports them separately as `module_only`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest import mock

from claimsense.agents import make_stub_services
from claimsense.agents.permissions import ToolBelt, ToolPermissionError
from claimsense.agents.settlement import OutputGuardError, SettlementAgent
from claimsense.contracts import AgentName, Claim, Worksheet, WorksheetLine
from claimsense.guardrails import guardrails as G
from claimsense.hooks import hooks as H
from eval.harness.claimsense_adapter import ClaimSenseAdapter
from eval.harness.loader import REPO_ROOT, load_split

from . import fixtures
from .cases import judge, load
from .pipeline import run_packet

TOOLS = (
    "policy_search",
    "get_clause",
    "calculate",
    "tariff_range",
    "get_policy",
    "claim_history",
    "settle_claim",
    "record_repudiation",
    "retrieve_lessons",
)
#: In the ACL for coverage, but no such tool is registered, so a call can never succeed.
REGISTERED = tuple(t for t in TOOLS if t != "retrieve_lessons")
SECRET_ARG = "SECRET-DIAGNOSIS-TEXT"  # noqa: S105 - a marker, not a password


def _registry(fn: Any = None) -> dict[str, Any]:
    return {name: fn or (lambda **_: "ok") for name in REGISTERED}


def _allowed(belt: ToolBelt) -> list[str]:
    allowed = []
    for tool in TOOLS:
        try:
            belt.call(tool)
        except ToolPermissionError:
            continue
        allowed.append(tool)
    return sorted(allowed)


def acl(case: dict) -> dict:
    agent = AgentName(case["agent"])
    plain = _allowed(ToolBelt(agent, _registry(), []))
    hooked = _allowed(H.hooked_belt(agent, _registry(), audit=H.AuditLog(), log=[]))
    return {"allowed": plain if plain == hooked else {"plain": plain, "hooked": hooked}}


def _budget(spec: dict) -> H.BudgetState:
    spec = dict(spec)
    if "per_agent" in spec:
        spec["per_agent"] = {AgentName(k): v for k, v in spec["per_agent"].items()}
    spec.setdefault("per_tool", None)
    spec.setdefault("max_repeats", None)
    return H.BudgetState(**spec)


def budget(case: dict) -> dict:
    ran = {"n": 0}

    def tool(**_: Any) -> str:
        ran["n"] += 1
        if case.get("raises"):
            raise RuntimeError("tool failed")
        return "ok"

    state, audit, outcomes = _budget(case["budget"]), H.AuditLog(), []
    for call in case["calls"]:
        belt = H.hooked_belt(AgentName(call[0]), _registry(tool), budget=state, audit=audit, log=[])
        kwargs = call[2] if len(call) > 2 else {}
        try:
            belt.call(call[1], **kwargs)
            outcomes.append("ok")
        except H.ToolBudgetExceeded:
            outcomes.append("budget_exceeded")
        except ToolPermissionError:
            outcomes.append("permission_denied")
        except RuntimeError as exc:
            outcomes.append(type(exc).__name__)
    return {"outcomes": outcomes, "tool_ran": ran["n"]}


def budget_reset(_case: dict) -> dict:
    state = H.BudgetState(per_claim=1, per_tool=None, max_repeats=None)
    belt = H.hooked_belt(AgentName.COVERAGE, _registry(), budget=state, audit=H.AuditLog(), log=[])
    belt.call("get_policy")
    state.reset()
    belt.call("get_policy")
    return {"second_claim": "ok", "total_after_reset": state.total}


def _audited_call(kind: str) -> tuple[H.AuditRecord, bool]:
    def tool(**_: Any) -> str:
        if kind == "error":
            raise RuntimeError(SECRET_ARG)
        return "ok"

    audit, propagated = H.AuditLog(), False
    agent = AgentName.FRAUD if kind == "denied" else AgentName.COVERAGE
    belt = H.hooked_belt(agent, _registry(tool), audit=audit, claim_id="CLM-H", log=[])
    name = "settle_claim" if kind == "denied" else "get_policy"
    try:
        belt.call(name, policy_number=SECRET_ARG)
    except (RuntimeError, ToolPermissionError):
        propagated = True
    return audit.records[0], propagated


def audit(case: dict) -> dict:
    record, propagated = _audited_call(case["call"])
    return {
        "status": record.status,
        "allowed": record.allowed,
        "error_code": record.error_code,
        "claim_id": record.claim_id,
        "message_leaked": SECRET_ARG in str(record),
        "payload_leaked": SECRET_ARG in str(record),
        "exception_propagated": propagated,
        "extra_fields": sorted(set(vars(record)) - H.SAFE_AUDIT_FIELDS),
    }


def audit_sink(case: dict) -> dict:
    ran = {"yes": False}

    def tool(**_: Any) -> str:
        ran["yes"] = True
        return "ok"

    log = H.AuditLog(fail_closed=case["fail_closed"])
    denied = case.get("call") == "denied"
    agent = AgentName.FRAUD if denied else AgentName.COVERAGE
    belt = H.hooked_belt(agent, _registry(tool), audit=log, log=[])
    raised = None
    with mock.patch.object(H.logger, "info", side_effect=OSError("sink down")):
        try:
            belt.call("settle_claim" if denied else "get_policy")
        except (H.AuditUnavailable, ToolPermissionError) as exc:
            raised = type(exc).__name__
    return {
        "tool_ran": ran["yes"],
        "raised": raised,
        "records": len(log.records),
        "emit_failures": log.emit_failures,
    }


def _worksheet(claim_id: str = "CLM-AG-001") -> Worksheet:
    line = WorksheetLine(line_id="L1", claimed="76000.00", payable="76000.00")
    return Worksheet(
        claim_id=claim_id, lines=[line], total_claimed="76000.00", total_payable="76000.00"
    )


def _letter() -> str:
    return "Policy number: POL-AG\nClaim: CLM-AG-001\nInsured: PT-AG-1\nAmount payable: Rs 76000.00"


def output_guard(case: dict) -> dict:
    letter, ws = _letter(), _worksheet()
    change = case["change"]
    if change == "other_claim":
        ws = _worksheet("OTHER")
    elif change == "wrong_patient":
        letter = letter.replace("PT-AG-1", "PT-OTHER")
    elif change == "wrong_policy":
        letter = letter.replace("POL-AG", "POL-OTHER")
    elif change == "wrong_total":
        letter = letter.replace("76000.00", "96000.00")
    try:
        SettlementAgent.output_guard(fixtures.claim(), ws, letter)
    except OutputGuardError:
        return {"outcome": "blocked"}
    return {"outcome": "passed"}


def guard_before_write(_case: dict) -> dict:
    services = make_stub_services()
    agent = SettlementAgent(services)
    agent.draft_letter = lambda *_: "letter for the wrong person"
    outcome = "no error"
    try:
        agent.settle(fixtures.claim(), _worksheet(), [], needs_senior=False)
    except OutputGuardError as exc:
        outcome = type(exc).__name__
    return {"outcome": outcome, "settled": len(services.settled)}


def _broken_worksheet() -> Worksheet:
    line = WorksheetLine.model_construct(line_id="L1", claimed=100, deductions=[], payable=90)
    return Worksheet.model_construct(
        claim_id="X", lines=[line], co_pay=None, total_claimed=100, total_payable=50
    )


def guardrail(case: dict) -> dict:
    name = case["fn"]
    if name == "scan_text":
        findings = G.scan_text(case["text"])
    elif name == "validate_claim_fields":
        claim = fixtures.claim().model_copy(update={"bill_total": case["total"]})
        findings = G.validate_claim_fields(claim)
    elif name == "check_consistency":
        findings = G.check_consistency(fixtures.claim(), {"doc": case["text"]})
    elif name == "validate_worksheet_arithmetic":
        findings = G.validate_worksheet_arithmetic(_broken_worksheet())
    else:
        findings = G.check_letter(
            fixtures.claim(), _worksheet(), _letter().replace("PT-AG-1", "PT-OTHER")
        )
    return {"codes": sorted({f.code for f in findings}), "wired": _guardrails_wired()}


def scrub(_case: dict) -> dict:
    return G.scrub({"diagnosis": "synthetic", "claim_id": "CLM-H"})


def _guardrails_wired() -> bool:
    src = REPO_ROOT / "src" / "claimsense"
    needles = ("guardrails import", "guardrails.guardrails", "import guardrails")
    for path in Path(src).rglob("*.py"):
        if path.parent.name == "guardrails":
            continue
        if any(n in path.read_text(encoding="utf-8") for n in needles):
            return True
    return False


def guardrails_wired(_case: dict) -> dict:
    return {"wired": _guardrails_wired()}


def patient_false_positive(_case: dict) -> dict:
    text = "Patient discharged on 2026-05-13 in stable condition."
    findings = G.check_consistency(fixtures.claim(), {"doc": text})
    return {"codes": sorted({f.code for f in findings})}


KINDS = {
    "acl": acl,
    "budget": budget,
    "budget_reset": budget_reset,
    "audit": audit,
    "audit_sink": audit_sink,
    "output_guard": output_guard,
    "guard_before_write": guard_before_write,
    "guardrail": guardrail,
    "scrub": scrub,
    "guardrails_wired": guardrails_wired,
    "patient_false_positive": patient_false_positive,
}


def run_case(case: dict) -> dict:
    try:
        observed = KINDS[case["kind"]](case)
    except Exception as exc:  # noqa: BLE001 - a crash is an outcome
        observed = {"outcome": f"crash:{type(exc).__name__}"}
    return judge("hook", case, observed)


def run_all() -> list[dict]:
    return [run_case(case) for case in load("hook_cases.jsonl")]


# ------------------------------------------------------------------------------ attack table
def _live(attack_id: str, state: dict) -> bool:
    """What the pipeline itself raised for this claim (extraction issues and fraud flags)."""
    issues = " ".join([*state.get("extraction_issues", []), *state.get("fraud_flags", [])]).lower()
    if attack_id == "RT-002":
        return "bill total" in issues
    if attack_id == "RT-003":
        return "duplicate" in issues
    if attack_id == "RT-004":
        return any(k in issues for k in ("date conflict", "admission date outside", "billed"))
    return "possible prompt injection" in issues


def _module_only(attack_id: str, claim: Claim, documents: dict[str, str]) -> bool:
    if attack_id == "RT-002":
        return any(f.code == "bill_total_mismatch" for f in G.check_consistency(claim, documents))
    if attack_id == "RT-003":
        return False
    if attack_id == "RT-004":
        return any(f.code == "date_mismatch" for f in G.check_consistency(claim, documents))
    return bool(G.scan_documents(documents))


CASE_LEVEL_ATTACKS = {
    "RT-005": "guard-wrong-patient-RT005",
    "RT-006": "settle-stale-hash-RT006",
    "RT-008": "settle-tampered-amount-RT008",
}


def attack_table() -> list[dict]:
    """Which control notices each attack. Detection only; gating is scored by the gates."""
    adapter = ClaimSenseAdapter(calculator="real", pass_documents=True)
    rows: dict[str, dict] = {}
    for case in load_split("redteam"):
        packet = adapter._packet(case.claim)  # noqa: SLF001
        run = run_packet(packet, adapter._policy(case.claim), mode="reject")  # noqa: SLF001
        attack = case.gold.model_dump()["attack_id"]
        row = rows.setdefault(
            attack, {"attack_id": attack, "n": 0, "live": 0, "module_only": 0, "missed_by_both": 0}
        )
        live = _live(attack, run.state)
        module_only = _module_only(attack, run.state["claim"], packet["documents"])
        row["n"] += 1
        row["live"] += live
        row["module_only"] += module_only
        row["missed_by_both"] += not (live or module_only)
    return [rows[k] for k in sorted(rows)] + [
        {"attack_id": attack, "covered_by_case": case_id}
        for attack, case_id in sorted(CASE_LEVEL_ATTACKS.items())
    ]


def duplicate_detection_case() -> dict:
    row = next(r for r in attack_table() if r["attack_id"] == "RT-003")
    return judge(
        "hook",
        {
            "case_id": "rt003-in-bill-duplicate-detected",
            "expect": {"detected": row["n"]},
            "defect": "AGENTIC-12",
        },
        {"detected": row["live"]},
    )


__all__ = ["attack_table", "duplicate_detection_case", "run_all", "run_case"]
