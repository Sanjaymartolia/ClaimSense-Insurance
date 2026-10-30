"""Plan-and-execute with a monitor (L10).

The step order for a claim is known in advance, so the plan is written by code from a template
(L11: "if routing is predictable, a fixed router will do"). What adapts is the *monitor*: when a
result contradicts the plan (claim not admissible, bill doesn't add up), it rewrites the
remaining steps and bumps Plan.revision, so the adjudicator sees why the path changed.
"""

from __future__ import annotations

from claimsense.contracts import AgentName, Plan, PlanStep

TEMPLATE: list[tuple[str, AgentName]] = [
    ("extract", AgentName.EXTRACTION),
    ("admissibility", AgentName.COVERAGE),
    ("adjudicate_lines", AgentName.COVERAGE),
    ("fraud_screen", AgentName.FRAUD),
    ("review", AgentName.CRITIC),
    ("approve", AgentName.SUPERVISOR),  # human gate
    ("settle", AgentName.SETTLEMENT),
    ("update_memory", AgentName.SUPERVISOR),
]


def make_plan(claim_id: str) -> Plan:
    return Plan(claim_id=claim_id, steps=[PlanStep(name=n, agent=a) for n, a in TEMPLATE])


def mark(plan: Plan, step: str, status: str) -> Plan:
    steps = [s.model_copy(update={"status": status}) if s.name == step else s for s in plan.steps]
    return plan.model_copy(update={"steps": steps})


def replan(plan: Plan, skip: list[str] = (), insert_before: dict[str, PlanStep] | None = None) -> Plan:
    """Skip steps that no longer make sense and insert new ones. Counts as one revision."""
    steps = []
    for s in plan.steps:
        if insert_before and s.name in insert_before:
            steps.append(insert_before[s.name])
        steps.append(s.model_copy(update={"status": "skipped"}) if s.name in skip else s)
    return plan.model_copy(update={"steps": steps, "revision": plan.revision + 1})


def monitor_after_admissibility(plan: Plan, admissible: bool) -> Plan:
    if admissible:
        return plan
    return replan(
        plan,
        skip=["adjudicate_lines", "fraud_screen", "review", "settle"],
        insert_before={"update_memory": PlanStep(name="repudiate", agent=AgentName.SETTLEMENT)},
    )


def render(plan: Plan) -> str:
    """What the case UI shows next to the worksheet."""
    icon = {"pending": "·", "running": "▶", "done": "✓", "failed": "✗", "skipped": "–"}
    return f"plan r{plan.revision}: " + "  ".join(f"{icon.get(s.status, '?')}{s.name}" for s in plan.steps)
