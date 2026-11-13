"""Synthetic demo claims for the case API: the dev and red-team fixtures, never real data.

A demo packet is the team's fixture adapter (``reflexion.cases.packet_from_fixture``, which already
drops the eval-only ``scenario_label`` and ``fixture_notes`` and carries the claim history) plus
the fixture's documents. The itemised bill gets its bill lines written in, as the eval adapter
does, so span checks pass and an attack planted in a document still reaches extraction. Gold
answers live in other files and are never read here.

Sources: ``CLAIMSENSE_DEMO_CLAIMS`` (comma-separated JSONL paths), else the two fixture files.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SOURCES = ("eval/golden_dev/claims.jsonl", "eval/redteam/claims.jsonl")


def sources() -> list[Path]:
    raw = os.environ.get("CLAIMSENSE_DEMO_CLAIMS")
    names = [p.strip() for p in raw.split(",") if p.strip()] if raw else list(DEFAULT_SOURCES)
    resolved = []
    for name in names:
        path = Path(name)
        resolved.append(path if path.is_absolute() or path.exists() else REPO_ROOT / path)
    return resolved


def _fixtures() -> dict[str, tuple[str, dict[str, Any]]]:
    """claim_id -> (source name, fixture), in file order. Missing files are skipped."""
    found: dict[str, tuple[str, dict[str, Any]]] = {}
    for path in sources():
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                fixture = json.loads(line)
                found.setdefault(fixture["claim_id"], (path.parent.name, fixture))
    return found


def demo_claims() -> list[dict[str, str]]:
    return [{"claim_id": cid, "source": src} for cid, (src, _) in _fixtures().items()]


def render_documents(fixture: dict[str, Any]) -> dict[str, str]:
    """The fixture's documents, with the bill lines written into the itemised bill."""
    documents = {
        str(d.get("document_id", "doc")): str(d.get("synthetic_text", ""))
        for d in fixture.get("documents") or []
    }
    bill = next(
        (
            str(d["document_id"])
            for d in fixture.get("documents") or []
            if d.get("type") == "itemized_bill"
        ),
        None,
    )
    if bill in documents:
        rendered = "\n".join(
            f"{b['line_id']}  {b['description']}  Rs {b['amount_inr']}"
            for b in fixture["bill_lines"]
        )
        documents[bill] = f"{documents[bill]}\n{rendered}"
    return documents


def demo_packet(claim_id: str) -> dict[str, Any] | None:
    """The packet for one synthetic claim, or None if no source holds it."""
    from claimsense.reflexion.cases import packet_from_fixture

    entry = _fixtures().get(claim_id)
    if entry is None:
        return None
    fixture = entry[1]
    packet = packet_from_fixture(fixture)
    packet["documents"] = render_documents(fixture)
    packet["policy_number"] = fixture["policy"]["policy_id"]  # as the intake system files it
    return packet
