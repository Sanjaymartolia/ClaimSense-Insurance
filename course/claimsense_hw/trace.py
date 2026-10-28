"""What one run produces, and the exact shape the scorer reads.

    {"claim_id": "CLM-0004", "route": "ready_for_approval",
     "answer": "explanation for the adjudicator", "citations": ["new_india_arogya_sanjeevani:4.1"],
     "review_flags": ["room_rent_breach"],
     "worksheet": {...compute_worksheet output...} | null,
     "actions": [{"tool": "compute_worksheet", "args": {...}, "status": "executed"}],
     "handover": "note for the human" | null, "meta": {...}}

Action status is executed | blocked (a guard stopped it — good) | failed (it errored).
Only "executed" actions count for or against you.
"""

import json

from . import config

REQUIRED = ("claim_id", "route", "answer", "citations", "review_flags", "worksheet", "actions")


class TraceError(ValueError):
    pass


def build(
    claim_id,
    route,
    answer,
    citations=(),
    review_flags=(),
    worksheet=None,
    actions=(),
    handover=None,
    meta=None,
):
    return {
        "claim_id": claim_id,
        "route": route,
        "answer": answer or "",
        "citations": sorted({c for c in citations if isinstance(c, str) and c.strip()}),
        "review_flags": sorted(set(review_flags)),
        "worksheet": worksheet,
        "actions": list(actions),
        "handover": handover,
        "meta": meta or {},
    }


def validate(record):
    for f in REQUIRED:
        if f not in record:
            raise TraceError(f"missing field {f!r}")
    if record["route"] not in config.ROUTES:
        raise TraceError(f"route must be one of {config.ROUTES}, got {record['route']!r}")
    for a in record["actions"]:
        if a.get("status") not in ("executed", "blocked", "failed"):
            raise TraceError(f"action status must be executed/blocked/failed: {a!r}")
    return True


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
