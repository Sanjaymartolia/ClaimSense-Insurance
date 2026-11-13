"""Score how a run used its tools. Each metric reads a `Run`, so a corrupted trace can be scored."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import fields
from decimal import Decimal
from typing import Any

from claimsense.agents import Team
from claimsense.hooks.hooks import SAFE_AUDIT_FIELDS, AuditRecord
from eval.harness.claimsense_adapter import ClaimSenseAdapter
from eval.harness.loader import load_split

from . import fixtures
from .cases import judge
from .expected_path import COVERAGE, CRITIC, PathFacts, expected_calls, senior_required
from .pipeline import Run, run_packet
from .recorder import TOOLS

WRITES = ("settle_claim", "record_repudiation")
AUDITED = tuple(t for t in TOOLS if t != "record_history")

Metric = dict[str, Any]


def _result(name: str, passed: bool, applicable: bool = True, **detail: Any) -> Metric:
    return {"metric": name, "applicable": applicable, "passed": passed, "detail": detail}


def _admissible(run: Run) -> bool:
    adm = run.state.get("admissibility")
    return bool(adm is not None and adm.admissible)


def path_facts(run: Run) -> PathFacts:
    critic_calcs = [e for e in run.events if e["agent"] == CRITIC and e["tool"] == "calculate"]
    return PathFacts(
        n_lines=run.n_lines,
        has_procedure=run.has_procedure,
        admissible=_admissible(run),
        critic_passed=[r.passed for r in run.state.get("critic_history", [])],
        critic_deductions=[e["result"].get("n_deductions", 0) for e in critic_calcs],
        reviews=[(r["level"], r["decision"]) for r in run.reviews],
        gate_has_clause=bool(getattr(run.state.get("admissibility"), "clause_ids", None)),
    )


def _ran(run: Run) -> list[dict]:
    return [e for e in run.events if e["status"] != "denied"]


def tool_order(run: Run) -> Metric:
    want = [tool for _, tool in expected_calls(path_facts(run))]
    got = [e["tool"] for e in _ran(run)]
    first = next((i for i, (a, b) in enumerate(zip(want, got, strict=False)) if a != b), None)
    return _result(
        "tool_order", want == got, first_difference=first, n_want=len(want), n_got=len(got)
    )


def call_counts(run: Run) -> Metric:
    want = Counter(tool for _, tool in expected_calls(path_facts(run)))
    got = Counter(e["tool"] for e in _ran(run))
    return _result("call_counts", want == got, missing=dict(want - got), extra=dict(got - want))


def correct_agent(run: Run) -> Metric:
    want = Counter(expected_calls(path_facts(run)))
    got = Counter((e["agent"], e["tool"]) for e in _ran(run))
    diff = {f"{a}:{t}": n for (a, t), n in ((got - want) + (want - got)).items()}
    return _result("correct_agent", want == got, differences=diff)


def forbidden_calls(run: Run) -> Metric:
    denied = [e["tool"] for e in run.events if e["status"] == "denied"]
    writes = [e for e in run.events if e["tool"] in WRITES]
    problems = list(denied)
    if len(writes) > 1:
        problems.append("more than one write")
    for write in writes:
        last = run.reviews[-1] if run.reviews else None
        if last is None or last["decision"] != "approve" or write["seq"] < last["at_event"]:
            problems.append(f"{write['tool']} without a final approval")
        if (write["tool"] == "settle_claim") != _admissible(run):
            problems.append(f"{write['tool']} on the wrong admissibility branch")
    return _result("forbidden_calls", not problems, problems=problems)


def _hash_problems(write: dict, final_calc: dict | None, run: Run, needed: bool) -> list[str]:
    problems: list[str] = []
    args = write["args"]
    if final_calc is None or args["worksheet_hash"] != final_calc["result"]["worksheet_hash"]:
        problems.append("settled worksheet is not the last calculated one")
    if any(t["hash"] != args["worksheet_hash"] for t in args["approvals"]):
        problems.append("approval bound to a different worksheet")
    levels = {t["level"] for t in args["approvals"]}
    if "adjudicator" not in levels:
        problems.append("no adjudicator approval")
    if needed and "senior" not in levels:
        problems.append("senior approval missing")
    if args["needs_senior"] != needed:
        problems.append(f"needs_senior was {args['needs_senior']}, rule says {needed}")
    return problems


def _coverage_calcs(run: Run) -> list[dict]:
    return [
        e
        for e in run.events
        if e["agent"] == COVERAGE and e["tool"] == "calculate" and e["status"] == "ok"
    ]


def args_consistent(run: Run) -> Metric:
    claim = run.state.get("claim")
    problems = [
        f"{e['tool']} used claim {e['args']['claim_id']}"
        for e in run.events
        if "claim_id" in e["args"] and e["args"]["claim_id"] != run.claim_id
    ]
    if claim is not None:
        problems += [
            f"{e['tool']} used another policy"
            for e in run.events
            if "policy_number" in e["args"] and e["args"]["policy_number"] != claim.policy_number
        ]
    calcs = _coverage_calcs(run)
    final_calc = calcs[-1] if calcs else None
    for write in (e for e in _ran(run) if e["tool"] == "settle_claim"):
        worksheet = run.state.get("worksheet")
        needed = (
            senior_required(Decimal(worksheet.total_payable), run.state.get("fraud_flags", []))
            if worksheet is not None
            else True
        )
        problems += _hash_problems(write, final_calc, run, needed)
    for write in (e for e in _ran(run) if e["tool"] == "record_repudiation"):
        if "adjudicator" not in {t["level"] for t in write["args"]["approvals"]}:
            problems.append("repudiation without an adjudicator approval")
    return _result("args_consistent", not problems, problems=problems)


def tool_result_used(run: Run) -> Metric:
    worksheet = run.state.get("worksheet")
    if worksheet is None or not _admissible(run):
        return _result("tool_result_used", True, applicable=False)
    problems: list[str] = []
    calcs = _coverage_calcs(run)
    last = calcs[-1]["result"] if calcs else {}
    if last.get("worksheet_hash") != worksheet.content_hash():
        problems.append("final worksheet is not the last calculator result")
    critic_totals = [
        e["result"].get("total_payable")
        for e in run.events
        if e["agent"] == CRITIC and e["tool"] == "calculate"
    ]
    if critic_totals and critic_totals[-1] != str(worksheet.total_payable):
        problems.append("critic recomputed a different total")
    for event in run.events:
        if event["tool"] == "settle_claim" and event["status"] == "ok":
            if event["result"]["amount"] != str(worksheet.total_payable):
                problems.append("settled amount differs from the worksheet")
    returned = {c for e in run.events for c in e["result"].get("clause_ids", [])}
    problems += [
        f"{line}: clause never returned by search"
        for line, clause in (run.state.get("clause_choices") or {}).items()
        if clause not in returned
    ]
    fetched = {e["result"].get("clause_id") for e in run.events if e["tool"] == "get_clause"}
    cited = {d.clause_id for line in worksheet.lines for d in line.deductions}
    problems += [f"deduction cites unverified clause {c}" for c in sorted(cited - fetched)]
    return _result("tool_result_used", not problems, problems=problems)


def hook_fired(run: Run) -> Metric:
    audited = [e for e in run.events if e["tool"] in AUDITED]
    status_map = {"ok": "ok", "raised": "error", "denied": "denied"}
    want = [(e["agent"], e["tool"], status_map[e["status"]]) for e in audited]
    got = [(r.agent, r.tool, r.status) for r in run.audit]
    unsafe = {f.name for f in fields(AuditRecord)} - SAFE_AUDIT_FIELDS
    wrong_claim = [r.tool for r in run.audit if r.claim_id != run.claim_id]
    passed = want == got and not unsafe and not wrong_claim
    return _result(
        "hook_fired", passed, n_tool_calls=len(want), n_audit=len(got), wrong_claim=wrong_claim
    )


def edit_invalidates(run: Run) -> Metric:
    edits = [r for r in run.reviews if r["decision"] == "edit"]
    worksheet = run.state.get("worksheet")
    if not edits or worksheet is None:
        return _result("edit_invalidates", True, applicable=False)
    old = edits[0]["hash"]
    problems: list[str] = []
    if worksheet.content_hash() == old:
        problems.append("worksheet hash did not change after an edit")
    if any(t.worksheet_hash == old for t in run.state.get("approvals", [])):
        problems.append("pre-edit approval survived")
    if run.stale_token_refused is not True:
        problems.append("stale approval was accepted")
    return _result("edit_invalidates", not problems, problems=problems)


METRICS: tuple[Callable[[Run], Metric], ...] = (
    tool_order,
    call_counts,
    correct_agent,
    forbidden_calls,
    args_consistent,
    tool_result_used,
    hook_fired,
    edit_invalidates,
)


def score(run: Run) -> list[Metric]:
    return [metric(run) for metric in METRICS]


# ------------------------------------------------------------------------------ dataset runs
SCENARIOS: dict[str, dict[str, Any]] = {
    "approve": {"mode": "approve", "documents": True},
    "approve_no_documents": {"mode": "approve", "documents": False},
    "reject": {"mode": "reject", "documents": True},
    "edit": {"mode": "edit", "documents": False},
    "senior_reject": {"mode": "senior_reject", "documents": True},
}


def dataset_runs(splits: tuple[str, ...] = ("dev", "redteam")) -> list[Run]:
    with_docs = ClaimSenseAdapter(calculator="real", pass_documents=True)
    without_docs = ClaimSenseAdapter(calculator="real", pass_documents=False)
    runs: list[Run] = []
    for split in splits:
        for case in load_split(split):
            for name, spec in SCENARIOS.items():
                adapter = with_docs if spec["documents"] else without_docs
                run = run_packet(
                    adapter._packet(case.claim),  # noqa: SLF001 - reuse, not a second copy
                    adapter._policy(case.claim),  # noqa: SLF001
                    mode=spec["mode"],
                    scenario=name,
                )
                run.tags["split"] = split
                runs.append(run)
    return runs


# ------------------------------------------------------------------------------ control cases
def _writes_ok(run: Run) -> list[str]:
    return [e["tool"] for e in run.events if e["tool"] in WRITES and e["status"] == "ok"]


def _control(case_id: str, observed: dict, expect: dict, defect: str | None = None) -> dict:
    return judge("control", {"case_id": case_id, "expect": expect, "defect": defect}, observed)


def _budget_breach() -> dict:
    run = run_packet(fixtures.packet(), fixtures.policy(), hook_options={"per_claim": 3})
    codes = [r.error_code for r in run.audit if r.status == "denied"]
    return _control(
        "midrun-budget-breach",
        {
            "error": run.error,
            "tools_run": len([e for e in run.events if e["status"] == "ok"]),
            "writes": _writes_ok(run),
            "audit_code": codes[:1],
        },
        {
            "error": "ToolBudgetExceeded",
            "tools_run": 3,
            "writes": [],
            "audit_code": ["budget_exceeded"],
        },
    )


def _acl_breach() -> dict:
    """A compromised fraud agent reaches for `settle_claim` through its own belt."""

    def compromise(team: Team) -> None:
        def run(claim: Any, _issues: Any) -> list[str]:
            team.fraud.belt.call("settle_claim", claim_id=claim.claim_id)
            return []

        team.fraud.run = run

    run = run_packet(fixtures.packet(), fixtures.policy(), configure=compromise)
    denied = [(r.agent, r.tool, r.error_code) for r in run.audit if r.status == "denied"]
    return _control(
        "midrun-acl-breach",
        {"error": run.error, "writes": _writes_ok(run), "denied": denied},
        {
            "error": "ToolPermissionError",
            "writes": [],
            "denied": [("fraud", "settle_claim", "permission_denied")],
        },
    )


def _fault(tool: str) -> dict:
    repudiation = tool == "record_repudiation"
    policy = fixtures.inadmissible_policy() if repudiation else fixtures.policy()
    run = run_packet(fixtures.packet(), policy, fail_on=tool)
    # record_history runs after the money has moved, so that one write is expected to stand.
    writes = ["settle_claim"] if tool == "record_history" else []
    errors = [r.tool for r in run.audit if r.status == "error"]
    return _control(
        f"fault-{tool}",
        {"error": run.error, "writes": _writes_ok(run), "audited_error": errors},
        {
            "error": "InjectedFault",
            "writes": writes,
            "audited_error": [] if tool == "record_history" else [tool],
        },
    )


def _history_audited() -> dict:
    run = run_packet(fixtures.packet(), fixtures.policy())
    return _control(
        "write-audit-covers-record_history",
        {"audited": any(r.tool == "record_history" for r in run.audit)},
        {"audited": True},
        defect="AGENTIC-08",
    )


def _long_bill() -> dict:
    run = run_packet(fixtures.long_bill_packet(40), fixtures.policy())
    return _control(
        "long-bill-fits-budget", {"error": run.error}, {"error": None}, defect="AGENTIC-09"
    )


def control_cases() -> list[dict]:
    return [
        _budget_breach(),
        _acl_breach(),
        *[_fault(tool) for tool in TOOLS],
        _history_audited(),
        _long_bill(),
    ]


def summarize(runs: list[Run]) -> dict[str, dict[str, Any]]:
    table: dict[str, dict[str, Any]] = {}
    for run in runs:
        for metric in score(run):
            row = table.setdefault(metric["metric"], {"applicable": 0, "passed": 0, "failures": []})
            if not metric["applicable"]:
                continue
            row["applicable"] += 1
            if metric["passed"]:
                row["passed"] += 1
            else:
                row["failures"].append(
                    {"claim_id": run.claim_id, "scenario": run.scenario, "detail": metric["detail"]}
                )
    return table
