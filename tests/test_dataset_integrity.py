"""Shape checks for the synthetic starter data pack (ADR 0002).

The held-out split lives outside this repo and is deliberately not checked here.
"""

import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY_DIR = ROOT / "data/policy/new_india"
GOLDEN_DEV = ROOT / "eval/golden_dev"


def read_jsonl(path):
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def test_dev_claims_have_one_gold_worksheet_each():
    claims = read_jsonl(GOLDEN_DEV / "claims.jsonl")
    gold = read_jsonl(GOLDEN_DEV / "gold_worksheets.jsonl")
    assert len(claims) == 20
    assert all(claim["synthetic"] is True for claim in claims)
    assert [c["claim_id"] for c in claims] == [g["claim_id"] for g in gold]


def test_tariff_grid():
    with (ROOT / "data/tariffs/synthetic_tariffs.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 90
    assert len({r["procedure_code"] for r in rows}) == 30
    assert {r["city_tier"] for r in rows} == {"tier_1", "tier_2", "tier_3"}


def test_policy_pdfs_match_manifest_hashes():
    manifest = json.loads((POLICY_DIR / "manifest.json").read_text(encoding="utf-8"))
    for doc in manifest["documents"]:
        pdf = POLICY_DIR / doc["stored_filename"]
        assert hashlib.sha256(pdf.read_bytes()).hexdigest() == doc["sha256"], pdf.name


def test_redteam_attacks_have_expected_behaviour():
    attacks = read_jsonl(ROOT / "eval/redteam/attacks.jsonl")
    assert attacks
    assert len({a["attack_id"] for a in attacks}) == len(attacks)
    assert all(a["expected_behavior"] for a in attacks)
