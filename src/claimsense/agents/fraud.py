"""Fraud analyst: duplicate bills, used sub-limits, tariff outliers and date checks.

All checks are code: a flag must be reproducible and explainable. A model adds nothing here
except an optional one-paragraph summary for the adjudicator (left as a TODO, low priority).
Flags never change amounts; they route the claim to senior approval.
"""

from __future__ import annotations

from decimal import Decimal

from claimsense.contracts import AgentName, Claim, LineCategory

from .permissions import ToolBelt
from .services import Services, line_fingerprint

OUTLIER_FACTOR = Decimal("1.5")  # flag above 1.5 x the tariff max. TODO: agree with domain lead


class FraudAgent:
    name = AgentName.FRAUD

    def __init__(self, services: Services):
        self.belt = ToolBelt(self.name, services.registry(), services.tool_log)

    def run(self, claim: Claim, extraction_issues: list[str] | None = None) -> list[str]:
        flags: list[str] = []
        history = self.belt.call("claim_history", policy_number=claim.policy_number)

        # 1. same claim id or same bill lines submitted before
        seen = {fp for past in history for fp in past.bill_fingerprints}
        if any(p.claim_id == claim.claim_id for p in history):
            flags.append(f"duplicate claim id {claim.claim_id} already in history")
        dups = [l.line_id for l in claim.bill_lines
                if line_fingerprint(claim, l.description, l.amount) in seen]
        if dups:
            flags.append(f"duplicate bill lines already claimed: {', '.join(dups)}")

        # 2. sub-limits already used this policy year (the calculator must also receive these)
        used: dict[str, Decimal] = {}
        for past in history:
            for k, v in past.sub_limits_used.items():
                used[k] = used.get(k, Decimal("0")) + Decimal(v)
        if used:
            flags.append("sub-limits partly used earlier: " +
                         ", ".join(f"{k} Rs {v}" for k, v in used.items()))
            # TODO(day 3): pass `used` to the calculator; agree the parameter with T15

        # 3. tariff outliers for the procedure line(s)
        pol = self.belt.call("get_policy", policy_number=claim.policy_number)
        tier = pol.city_tier if pol else "tier_1"
        if claim.procedure:
            rng = self.belt.call("tariff_range", procedure=claim.procedure, city_tier=tier)
            proc_total = sum((l.amount for l in claim.bill_lines
                              if l.category in (LineCategory.PROCEDURE, LineCategory.OT)), Decimal(0))
            if rng and proc_total > rng[1] * OUTLIER_FACTOR:
                flags.append(f"procedure charges Rs {proc_total} above tariff range {rng[0]}-{rng[1]}")

        # 4. dates
        if pol and not (pol.period_start <= claim.admission_date <= pol.period_end):
            flags.append("admission date outside policy period")
        for l in claim.bill_lines:
            if l.days is not None and l.days > max(claim.nights, 1):
                flags.append(f"{l.line_id}: billed {l.days} days for a {claim.nights}-night stay")

        # 5. anything extraction noticed (total mismatch, injected notes, bad spans)
        flags += [f"extraction: {i}" for i in (extraction_issues or [])]
        return flags
