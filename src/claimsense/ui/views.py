"""What the case UI shows and sends, as plain functions: no Streamlit here, so pytest covers it.

Money arrives from the API as Decimal strings and is only formatted here (Indian digit grouping);
every amount a claim is paid on comes from the calculator, never from the page. Text that came
from a claim's documents (fraud flags quote them) is returned as is: the page shows it as plain
text, never as markdown (rule 2).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from prometheus_client.parser import text_string_to_metric_families

from claimsense.api.metrics import flag_kind

#: The planner's own marks for a step's status (`graph/planner.py::render`).
STEP_MARKS = {"pending": "·", "running": "▶", "done": "✓", "failed": "✗", "skipped": "–"}
_CENT = Decimal("0.01")
_MARKDOWN = str.maketrans({c: f"\\{c}" for c in "\\`*_{}[]()<>#+-.!|~:$"})


def inr(amount: str | Decimal | float | int) -> str:
    """'Rs 2,01,962.52': Indian digit grouping (thousands, then lakhs and crores), two decimals."""
    value = Decimal(str(amount)).quantize(_CENT, rounding=ROUND_HALF_UP)
    whole, paise = f"{abs(value):.2f}".split(".")
    head, groups = whole[:-3], [whole[-3:]]
    while head:
        groups.insert(0, head[-2:])
        head = head[:-2]
    return f"{'-' if value < 0 else ''}Rs {','.join(groups)}.{paise}"


def a_level(level: str) -> str:
    """'an adjudicator', 'a senior'."""
    return f"{'an' if level[:1] in 'aeiou' else 'a'} {level}"


def md_escape(text: str) -> str:
    """`text` with every markdown character escaped, for an id inside the page's own labels."""
    return text.translate(_MARKDOWN)


# ------------------------------------------------------------------------------- worksheet
def worksheet_rows(worksheet: Mapping[str, Any]) -> list[dict[str, str]]:
    """One row per bill line: claimed, deducted, payable, and why, under which clause."""
    rows = []
    for line in worksheet["lines"]:
        deductions = line.get("deductions") or []
        rows.append(
            {
                "line": line["line_id"],
                "claimed": inr(line["claimed"]),
                "deducted": inr(sum((Decimal(d["amount"]) for d in deductions), Decimal(0))),
                "payable": inr(line["payable"]),
                "reason": ", ".join(dict.fromkeys(d["reason"] for d in deductions)),
                "clause": ", ".join(dict.fromkeys(d["clause_id"] for d in deductions)),
            }
        )
    return rows


def deduction_rows(worksheet: Mapping[str, Any]) -> list[dict[str, str]]:
    """Every deduction with its clause and the calculator's explanation; the co-pay comes last."""
    found = [
        (line["line_id"], d) for line in worksheet["lines"] for d in line.get("deductions") or []
    ]
    if worksheet.get("co_pay"):
        found.append(("whole claim", worksheet["co_pay"]))
    return [
        {
            "line": line_id,
            "reason": d["reason"],
            "clause": d["clause_id"],
            "amount": inr(d["amount"]),
            "explanation": d["explanation"],
        }
        for line_id, d in found
    ]


def totals(worksheet: Mapping[str, Any]) -> dict[str, str]:
    """The worksheet's own totals; `deducted` is what separates them, co-pay included."""
    claimed, payable = Decimal(worksheet["total_claimed"]), Decimal(worksheet["total_payable"])
    co_pay = worksheet.get("co_pay")
    return {
        "claimed": inr(claimed),
        "deducted": inr(claimed - payable),
        "co_pay": inr(co_pay["amount"] if co_pay else 0),
        "payable": inr(payable),
    }


def flag_rows(flags: Iterable[str]) -> list[tuple[str, str]]:
    """(kind, flag) per fraud flag: the kind the API's metrics count it under."""
    return [(flag_kind(flag), flag) for flag in flags]


def plan_rows(plan: Mapping[str, Any]) -> list[dict[str, str]]:
    return [
        {"step": f"{STEP_MARKS.get(step['status'], '?')} {step['name']}", "agent": step["agent"]}
        for step in plan.get("steps", [])
    ]


# ------------------------------------------------------------------------------- decisions
#: What approve, edit and reject each do, per kind of review (`build_review_payload`).
_DECISIONS = {
    "worksheet": {
        "approve": "Approve this worksheet as it stands. The approval binds to its exact hash.",
        "edit": (
            "Point one line to another clause, or correct a misread amount. The calculator "
            "recomputes the totals, and every earlier approval becomes void."
        ),
        "reject": "Close the case as rejected. Nothing is settled.",
    },
    "repudiation": {
        "approve": "Approve the repudiation: the claim is not admissible, and nothing is paid.",
        "edit": (
            "An edit overrides the not-admissible finding. Give one line a clause or a corrected "
            "amount: coverage, the fraud screen and the calculator run again, and the claim "
            "comes back for review."
        ),
        "reject": "Close the case as rejected. Nothing is settled or repudiated.",
    },
}


def decision_texts(kind: str) -> dict[str, str]:
    """One line per decision, for the kind of review in front of the reviewer."""
    return dict(_DECISIONS.get(kind, _DECISIONS["worksheet"]))


def edit_line_ids(case: Mapping[str, Any]) -> list[str]:
    """The lines an edit can name: the API's `line_ids`, else the worksheet's own lines."""
    if case.get("line_ids"):
        return list(case["line_ids"])
    return [line["line_id"] for line in (case.get("worksheet") or {}).get("lines", [])]


# ------------------------------------------------------------------------------- approvals
def current_hash(case: Mapping[str, Any]) -> str | None:
    """The worksheet a decision binds to now: the pending review's, else the settled one's."""
    for part in ("review", "settlement"):
        found = case.get(part) or {}
        if found.get("worksheet_hash"):
            return found["worksheet_hash"]
    return None


def remember_approvals(seen: list[dict[str, Any]], case: Mapping[str, Any]) -> list[dict[str, Any]]:
    """`seen` plus the case's approvals not seen before, each with the hash it was given on.

    The API clears approvals when an edit changes the worksheet, so the page keeps the ones it
    saw: an approval given on an earlier hash is the one the edit voided (demo scene 3)."""
    known = {(a["level"], a["approver_id"], a["decided_at"]) for a in seen}
    current = current_hash(case)
    new = [
        {**a, "worksheet_hash": current}
        for a in case.get("approvals") or []
        if (a["level"], a["approver_id"], a["decided_at"]) not in known
    ]
    return [*seen, *new]


def mark_void(seen: list[dict[str, Any]], current: str | None) -> list[dict[str, Any]]:
    """Each approval with `void`: it was given on another worksheet than the current one."""
    return [{**a, "void": a.get("worksheet_hash") != current} for a in seen]


# ------------------------------------------------------------------------------- dashboard
def _samples(text: str) -> Iterator[tuple[str, dict[str, str], float]]:
    for family in text_string_to_metric_families(text):
        for sample in family.samples:
            yield sample.name, sample.labels, sample.value


def dashboard(metrics_text: str) -> dict[str, Any]:
    """The L16 numbers from the API's `/metrics/` text: counts since the API process started."""
    processed: dict[str, int] = {}
    decisions: dict[str, int] = {}
    deducted: dict[str, float] = {}
    flags: dict[str, int] = {}
    tools: dict[str, int] = {}
    sums = dict.fromkeys(("claims", "cost", "turnaround", "decided", "in_flight"), 0.0)
    for name, labels, value in _samples(metrics_text):
        if name == "claimsense_claims_processed_total":
            processed[labels["outcome"]] = int(value)
        elif name == "claimsense_review_decisions_total":
            decisions[f"{labels['level']} {labels['decision']}"] = int(value)
        elif name == "claimsense_rupees_deducted_total":
            deducted[labels["reason"]] = value
        elif name == "claimsense_fraud_flags_total":
            flags[labels["kind"]] = int(value)
        elif name == "claimsense_tool_calls_total":
            tools[labels["status"]] = tools.get(labels["status"], 0) + int(value)
        elif name == "claimsense_claims_total":
            sums["claims"] += value
        elif name == "claimsense_cost_usd_total":
            sums["cost"] += value
        elif name == "claimsense_turnaround_seconds_sum":
            sums["turnaround"] = value
        elif name == "claimsense_turnaround_seconds_count":
            sums["decided"] = value
        elif name == "claimsense_in_flight":
            sums["in_flight"] = value
    decided = sum(decisions.values())
    edits = sum(n for key, n in decisions.items() if key.endswith(" edit"))
    return {
        "processed": processed,
        "processed_total": sum(processed.values()),
        "decisions": decisions,
        "edit_rate": edits / decided if decided else None,
        "deducted": deducted,
        "flags": flags,
        "turnaround_mean_s": sums["turnaround"] / sums["decided"] if sums["decided"] else None,
        "cost_per_claim_usd": sums["cost"] / sums["claims"] if sums["claims"] else None,
        "tool_calls": tools,
        "in_flight": int(sums["in_flight"]),
    }


# ------------------------------------------------------------------------------- uploads
def packet_from_documents(
    claim_id: str, policy_number: str | None, documents: Mapping[str, str], claim_json: str
) -> dict[str, Any]:
    """A `POST /claims` body from the upload form. Empty documents are left out. The extracted
    claim (JSON) is optional; agents in stub mode read no documents and need it."""
    claim_id = (claim_id or "").strip()
    if not claim_id:
        raise ValueError("a claim id is needed")
    packet: dict[str, Any] = {"claim_id": claim_id}
    if policy_number and policy_number.strip():
        packet["policy_number"] = policy_number.strip()
    packet["documents"] = {name: text for name, text in documents.items() if text.strip()}
    if claim_json.strip():
        try:
            claim = json.loads(claim_json)
        except json.JSONDecodeError as exc:
            raise ValueError(f"the extracted claim is not JSON ({exc.msg})") from None
        if not isinstance(claim, dict) or claim.get("claim_id") != claim_id:
            raise ValueError("the extracted claim must be a JSON object with this claim_id")
        packet["claim"] = claim
    elif not packet["documents"]:
        raise ValueError("add a document, or an extracted claim")
    return packet


def packet_from_json(text: str) -> dict[str, Any]:
    """A `POST /claims` body pasted or uploaded as JSON, such as a synthetic fixture packet."""
    try:
        packet = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"the packet is not JSON ({exc.msg})") from None
    if not isinstance(packet, dict) or not packet.get("claim_id"):
        raise ValueError("the packet must be a JSON object with a claim_id")
    return packet
