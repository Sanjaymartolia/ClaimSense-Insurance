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
    assert len(claims) == 22
    assert all(claim["synthetic"] is True for claim in claims)
    assert [c["claim_id"] for c in claims] == [g["claim_id"] for g in gold]


#: Gold reason code -> review flag (ADR-0007, GOLD-06). `icu_daily_cap` files as `sub_limit`, the
#: convention GOLD-04 set and `eval/harness/claimsense_adapter.py::DEDUCTION_FLAGS` follows.
REASON_FLAGS = {
    "initial_waiting_period_not_elapsed": "waiting_period",
    "specific_illness_waiting_period": "waiting_period",
    "pre_existing_disease_waiting_period": "waiting_period",
    "admission_or_discharge_outside_policy_period": "policy_period_inconsistency",
    "maternity_childbirth_exclusion": "maternity_childbirth_exclusion",
    "room_rent_daily_cap": "room_rent_breach",
    "room_rent_proportional_reduction": "room_rent_breach",
    "icu_daily_cap": "sub_limit",
    "cataract_sub_limit": "sub_limit",
    "non_payable_item_demo_rule": "non_payable_items",
    "duplicate_line": "duplicate_bill",
}
GATE = "claim_level_admissibility_gate"


def test_gold_flags_follow_reason_codes():
    """GOLD-06 / ADR-0007: a flag for every rule that changed money. A not-admissible claim pays
    Rs 0 whatever its lines say, so it carries only its claim-level gate's flag."""
    for g in read_jsonl(GOLDEN_DEV / "gold_worksheets.jsonl"):
        if g["expected_admissibility"] == "admissible":
            codes = {c for li in g["line_items"] for c in li["reason_codes"] if c != GATE}
        else:
            codes = set(g["reason_codes"])
        assert sorted({REASON_FLAGS[c] for c in codes}) == g["expected_review_flags"], g["claim_id"]


def test_every_claim_states_first_policy_inception():
    """GOLD-03 / ADR-0007: waiting periods run from the first policy, so every claim says when."""
    for c in read_jsonl(GOLDEN_DEV / "claims.jsonl"):
        p = c["policy"]
        assert p["first_policy_inception_date"] <= p["policy_start_date"], c["claim_id"]


def test_a_sub_limit_case_exists_with_partly_used_limit():
    """GOLD-05 / ADR-0007: at least one claim where clause 4.3 changes the amount, and one where an
    earlier claim this policy year already used part of the limit."""
    gold = {g["claim_id"]: g for g in read_jsonl(GOLDEN_DEV / "gold_worksheets.jsonl")}
    capped = [
        cid
        for cid, g in gold.items()
        if any("cataract_sub_limit" in li["reason_codes"] for li in g["line_items"])
    ]
    assert len(capped) >= 2
    claims = {c["claim_id"]: c for c in read_jsonl(GOLDEN_DEV / "claims.jsonl")}
    assert any(claims[cid]["history"]["prior_claims"] for cid in capped)


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
