"""Read the eval sets from disk and hand the agent only what it may see.

This module is the single gate between the fixtures and anything that runs. It is the reason the
agent cannot read the answer:

  - `scenario_label` and `fixture_notes` are removed from every claim (`EVAL_ONLY_FIELDS`).
  - `potentially_payable`, `room_linked` and `duplicate_of` are removed from every bill line
    (`ANSWER_HINT_FIELDS`, REC-04): they pre-label the decision the agent must make.
  - Gold is loaded into a separate object the adapter never receives.

The held-out set is deliberately not reachable from here. It lives in `data/claimsense-heldout/`
(ADR-0013) and only a person from Eval & Red-Team runs it, once. `assert_not_heldout` refuses any
path that looks like it.
"""

from __future__ import annotations

import json
from pathlib import Path

from .models import ANSWER_HINT_FIELDS, EVAL_ONLY_FIELDS, ClaimRecord, EvalCase, GoldRecord

#: Repository root, found from this file so the harness runs from any working directory.
REPO_ROOT = Path(__file__).resolve().parents[2]

DEV_DIR = REPO_ROOT / "eval" / "golden_dev"
REDTEAM_DIR = REPO_ROOT / "eval" / "redteam"
KNOWLEDGE_BASE = REPO_ROOT / "data" / "knowledge_base" / "policy_knowledge_base.jsonl"

SPLITS: dict[str, tuple[Path, str, str]] = {
    "dev": (DEV_DIR, "claims.jsonl", "gold_worksheets.jsonl"),
    "redteam": (REDTEAM_DIR, "claims.jsonl", "gold.jsonl"),
}


class HeldOutAccessError(RuntimeError):
    """Raised when a path looks like the held-out set. CLAUDE.md rule 5."""


def assert_not_heldout(path: Path) -> None:
    """Refuse anything outside the repository or named like the held-out set."""
    text = str(path).replace("\\", "/").lower()
    if "heldout" in text or "held-out" in text or "held_out" in text:
        raise HeldOutAccessError(
            f"{path} looks like the held-out set. Only Eval & Red-Team runs it, once, by hand "
            "(CLAUDE.md rule 5). The harness will not read it."
        )


def read_jsonl(path: Path) -> list[dict]:
    assert_not_heldout(path)
    if not path.exists():
        raise FileNotFoundError(f"{path} not found")
    out: list[dict] = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as e:
            raise ValueError(f"{path}:{n} is not valid JSON: {e}") from e
    return out


def strip_eval_only(raw: dict) -> dict:
    """Return a copy of a claim with every answer-revealing field removed.

    Removing rather than blanking is deliberate: a blank `scenario_label` still tells an agent the
    field exists and invites it to look for the value somewhere else.
    """
    claim = {k: v for k, v in raw.items() if k not in EVAL_ONLY_FIELDS}
    claim["bill_lines"] = [
        {k: v for k, v in line.items() if k not in ANSWER_HINT_FIELDS}
        for line in raw.get("bill_lines", [])
    ]
    return claim


def load_split(split: str) -> list[EvalCase]:
    """Load one split, pairing each claim with its gold. Raises if they do not pair up exactly."""
    if split not in SPLITS:
        raise ValueError(f"unknown split {split!r}; choose from {sorted(SPLITS)}")
    directory, claims_file, gold_file = SPLITS[split]
    raw_claims = read_jsonl(directory / claims_file)
    raw_gold = read_jsonl(directory / gold_file)

    claim_ids = [c["claim_id"] for c in raw_claims]
    if len(set(claim_ids)) != len(claim_ids):
        raise ValueError(f"{directory / claims_file} has duplicate claim ids")
    gold_by_id = {g["claim_id"]: g for g in raw_gold}
    if set(claim_ids) != set(gold_by_id):
        only_claims = sorted(set(claim_ids) - set(gold_by_id))
        only_gold = sorted(set(gold_by_id) - set(claim_ids))
        raise ValueError(
            f"claims and gold do not pair up: only-claims={only_claims} only-gold={only_gold}"
        )

    cases: list[EvalCase] = []
    for raw in raw_claims:
        cases.append(
            EvalCase(
                claim=ClaimRecord.model_validate(strip_eval_only(raw)),
                gold=GoldRecord.model_validate(gold_by_id[raw["claim_id"]]),
                split=split,
            )
        )
    return cases


def load_cases(splits: list[str]) -> list[EvalCase]:
    """Load several splits in the order given."""
    cases: list[EvalCase] = []
    for split in splits:
        cases.extend(load_split(split))
    return cases


def policy_clause_ids() -> frozenset[str]:
    """Every clause id a citation may legitimately name.

    Only `searchable` chunks count. Row 12.5 is excluded from search by ADR-0004 because it
    contradicts clause 6.1, so citing it is not grounding a decision in the governing wording.
    """
    ids = {
        row["clause_id"]
        for row in read_jsonl(KNOWLEDGE_BASE)
        if row.get("searchable", True) and row.get("clause_id")
    }
    if not ids:
        raise ValueError(f"no searchable clause ids in {KNOWLEDGE_BASE}")
    return frozenset(ids)
