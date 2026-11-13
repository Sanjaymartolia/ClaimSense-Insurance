"""Final database state after full pipeline runs, on the real claims database.

Each claim runs through the real nodes with the real `claims_db.ClaimsDatabase` (in memory) and
its signed SQLite approval store; search and tariff stay stubs. Afterwards the tables are read
back and checked against rules written here, not taken from the product:

    one_write_or_none      a final approval gives exactly one settlements row; anything else none
    write_kind             settled for an admissible claim, repudiated for a not-admissible one
    amount_matches         settled amount = the approved worksheet's total; repudiation = 0
    hash_matches           the stored hash is the approved worksheet's hash
    amount_within_claimed  0 <= amount <= total claimed
    history_recorded       the claim and one fingerprint per bill line are stored iff written
    claim_status_updated   claims.status says settled / repudiated after the write

Which branch a run took (admissible, reviewer replies) comes from the run, as in
`trajectory_eval.py`; whether that branch was right is scored by `eval/harness`.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Callable, Iterator
from decimal import Decimal
from typing import Any

from claimsense.mcp_servers.claims_db import ClaimsDatabase
from eval.harness.claimsense_adapter import ClaimSenseAdapter
from eval.harness.loader import load_split

from .pipeline import Run, run_packet
from .trajectory_eval import _admissible

MODES = ("approve", "reject", "edit", "senior_reject")

#: Signs approvals in a throwaway in-memory database. Not a real secret.
EVAL_SECRET = "eval-agentic-db-state-only"  # noqa: S105

#: Checks that describe correct behaviour the product does not have yet (see run.DEFECTS).
KNOWN_DEFECTS = {"claim_status_updated": "AGENTIC-14"}


@contextlib.contextmanager
def _signing_secret() -> Iterator[None]:
    saved = os.environ.get("CLAIMSENSE_APPROVAL_SECRET")
    os.environ["CLAIMSENSE_APPROVAL_SECRET"] = saved or EVAL_SECRET
    try:
        yield
    finally:
        if saved is None:
            os.environ.pop("CLAIMSENSE_APPROVAL_SECRET", None)


def snapshot(db: ClaimsDatabase, claim_id: str) -> dict[str, Any]:
    """The rows a run left behind. Ids, hashes, amounts and statuses only: no health details."""
    q = db._conn.execute  # noqa: SLF001 - reading the tables is the point
    return {
        "settlements": [
            dict(r) for r in q("SELECT claim_id, worksheet_hash, amount, status FROM settlements")
        ],
        "claims": [dict(r) for r in q("SELECT claim_id, status FROM claims")],
        "fingerprints": q(
            "SELECT COUNT(*) FROM bill_fingerprints WHERE claim_id=?", (claim_id,)
        ).fetchone()[0],
    }


def run_on_db(packet: dict, policy: Any, mode: str) -> tuple[Run, dict[str, Any]]:
    with _signing_secret():
        db = ClaimsDatabase(":memory:")
        try:
            run = run_packet(packet, policy, mode=mode, db=db)
            snap = snapshot(db, run.claim_id)
        finally:
            db.close()
    return run, snap


def expected_write(run: Run) -> str | None:
    if not run.reviews or run.reviews[-1]["decision"] != "approve":
        return None
    return "settled" if _admissible(run) else "repudiated"


def _check(ok: bool, **detail: Any) -> dict[str, Any]:
    return {"applicable": True, "passed": bool(ok), "detail": {} if ok else detail}


NA = {"applicable": False, "passed": True, "detail": {}}


def checks(run: Run, snap: dict[str, Any]) -> dict[str, dict[str, Any]]:
    want = expected_write(run)
    rows = snap["settlements"]
    ws = run.state.get("worksheet")
    out: dict[str, dict[str, Any]] = {
        "one_write_or_none": _check(len(rows) == (1 if want else 0), want=want, rows=len(rows))
    }
    row = rows[0] if len(rows) == 1 else None
    out["write_kind"] = (
        _check(row["status"] == want, want=want, got=row["status"]) if want and row else NA
    )
    if want == "settled" and row and ws is not None:
        out["amount_matches"] = _check(
            Decimal(row["amount"]) == ws.total_payable, db=row["amount"], ws=str(ws.total_payable)
        )
        out["hash_matches"] = _check(row["worksheet_hash"] == ws.content_hash())
        out["amount_within_claimed"] = _check(
            Decimal(0) <= Decimal(row["amount"]) <= ws.total_claimed, db=row["amount"]
        )
    elif want == "repudiated" and row:
        out["amount_matches"] = _check(Decimal(row["amount"]) == 0, db=row["amount"])
        out["hash_matches"] = NA
        out["amount_within_claimed"] = NA
    else:
        out["amount_matches"] = out["hash_matches"] = out["amount_within_claimed"] = NA
    claim_rows = [c for c in snap["claims"] if c["claim_id"] == run.claim_id]
    written = bool(want)
    out["history_recorded"] = _check(
        len(claim_rows) == int(written) and snap["fingerprints"] == (run.n_lines if written else 0),
        claim_rows=len(claim_rows),
        fingerprints=snap["fingerprints"],
    )
    out["claim_status_updated"] = (
        _check(
            [c["status"] for c in claim_rows] == [want],
            want=want,
            got=[c["status"] for c in claim_rows],
        )
        if want
        else NA
    )
    return out


def dataset_runs(
    splits: tuple[str, ...] = ("dev", "redteam"), modes: tuple[str, ...] = MODES
) -> list[tuple[Run, dict[str, Any]]]:
    adapter = ClaimSenseAdapter(calculator="real", pass_documents=False)
    out = []
    for split in splits:
        for case in load_split(split):
            packet = adapter._packet(case.claim)  # noqa: SLF001
            policy = adapter._policy(case.claim)  # noqa: SLF001
            for mode in modes:
                run, snap = run_on_db(packet, policy, mode)
                run.tags["split"] = split
                out.append((run, snap))
    return out


def summarize(
    results: list[tuple[Run, dict[str, Any]]],
    check_fn: Callable[[Run, dict[str, Any]], dict[str, dict[str, Any]]] = checks,
) -> dict[str, dict[str, Any]]:
    table: dict[str, dict[str, Any]] = {}
    for run, snap in results:
        for name, c in check_fn(run, snap).items():
            row = table.setdefault(
                name,
                {"applicable": 0, "passed": 0, "failures": [], "defect": KNOWN_DEFECTS.get(name)},
            )
            if not c["applicable"]:
                continue
            row["applicable"] += 1
            row["passed"] += c["passed"]
            if not c["passed"] and len(row["failures"]) < 5:
                row["failures"].append(
                    {"claim_id": run.claim_id, "scenario": run.scenario, "detail": c["detail"]}
                )
    return table


__all__ = ["checks", "dataset_runs", "expected_write", "run_on_db", "snapshot", "summarize"]
