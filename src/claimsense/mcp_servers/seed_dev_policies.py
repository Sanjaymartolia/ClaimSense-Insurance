"""Seed the claims DB with the development policies. ClaimSense Role 4 (Tools, Control & Security).

Run::

    python -m claimsense.mcp_servers.seed_dev_policies      # after integration into the package
    python -m seed_dev_policies                             # from this output folder
    python seed_dev_policies.py                             # likewise

What it does
------------
Reads **only** ``eval/golden_dev/claims.jsonl`` and, for each development claim, constructs the
existing ``PolicyInfo`` contract and ``upsert_policy()``s it into the one claims database. It reuses
the project's own machinery rather than duplicating it:

* ``eval.harness.loader.read_jsonl`` + ``strip_eval_only`` read the claims and remove every
  answer-revealing field, so no evaluation-only field is ever read into a policy.
* the policy fields come from the *exact* mapping in
  ``eval.harness.claimsense_adapter.ClaimSenseAdapter._policy`` - reused, not re-implemented - which
  takes only the policy block, ``hospital.city_tier`` and the insured pseudonym (plus the declared
  pre-existing condition, exactly as the adapter does).

Strict data rules (enforced by reuse)
-------------------------------------
* ``scenario_label`` and ``fixture_notes`` are stripped by ``strip_eval_only`` before mapping.
* ``gold_worksheets.jsonl`` and any expected result are never opened (we read one file only).
* The held-out set is refused by ``loader.assert_not_heldout`` inside ``read_jsonl``.

Idempotency
-----------
``upsert_policy`` keys on ``policy_number`` (``INSERT ... ON CONFLICT DO UPDATE``), so re-running
the script never creates duplicates and never introduces a second database - it reuses the existing
schema and the existing ``CLAIMSENSE_CLAIMS_DB`` file.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _bootstrap_paths() -> Path:
    """Put the repo's ``src`` (for ``claimsense``) and root (for ``eval``) on ``sys.path``.

    Returns the located repository root. Honours ``CLAIMSENSE_SRC`` / ``CLAIMSENSE_REPO`` overrides,
    and is a no-op for whichever of the two is already importable (e.g. when this file has been
    moved into ``src/claimsense/mcp_servers/`` and only ``eval`` still needs locating).
    """
    here = Path(__file__).resolve()
    repo_env = os.environ.get("CLAIMSENSE_REPO")
    src_env = os.environ.get("CLAIMSENSE_SRC")
    candidates: list[Path] = []
    if repo_env:
        candidates.append(Path(repo_env))
    if src_env:
        candidates.append(Path(src_env).parent)
    candidates += [
        here.parent.parent / "ClaimSense-Insurance",
        here.parent / "ClaimSense-Insurance",
        here.parents[3] if len(here.parents) > 3 else here.parent,  # src/claimsense/mcp_servers/..
    ]
    repo_root = next((c for c in candidates if (c / "src" / "claimsense").is_dir()), None)
    if repo_root is None:
        # Already-installed package: claimsense importable, find the repo for its ``eval`` package.
        repo_root = next((c for c in candidates if (c / "eval").is_dir()), candidates[0])
    for p in (str(repo_root / "src"), str(repo_root)):
        if (Path(p) / "claimsense").is_dir() or (Path(p) / "eval").is_dir():
            if p not in sys.path:
                sys.path.insert(0, p)
    return repo_root


_REPO_ROOT = _bootstrap_paths()

from claimsense.agents.services import PolicyInfo  # noqa: E402
from eval.harness.claimsense_adapter import ClaimSenseAdapter  # noqa: E402
from eval.harness.loader import DEV_DIR, read_jsonl, strip_eval_only  # noqa: E402
from eval.harness.models import ClaimRecord  # noqa: E402

try:  # package layout: claimsense.mcp_servers.seed_dev_policies
    from . import claims_db
except ImportError:  # flat layout: sibling module on sys.path
    import claims_db


class _PolicyMapper:
    """Reuse the adapter's exact ``_policy`` mapping without running its heavy ``_load()``.

    ``ClaimSenseAdapter._policy`` only needs ``self._imports["PolicyInfo"]``; binding the unbound
    method to this tiny object runs the identical mapping with the identical module globals, so the
    policy this seeder writes is byte-for-byte what the eval harness would build.
    """

    _imports = {"PolicyInfo": PolicyInfo}
    _policy = ClaimSenseAdapter._policy


def dev_claims_path() -> Path:
    """Path to the development claims file (``eval/golden_dev/claims.jsonl``)."""
    return DEV_DIR / "claims.jsonl"


def seed_dev_policies(
    db: claims_db.ClaimsDatabase | None = None,
    *,
    claims_path: str | os.PathLike[str] | None = None,
    dry_run: bool = False,
) -> dict:
    """Seed (upsert) every development policy into the claims DB.

    Returns a summary dict: ``seeded`` (claim_id -> policy_number), ``invalid`` (claim_id -> error),
    ``distinct_policies`` and ``missing_after_seed`` (policies that failed to round-trip).
    Re-running is safe (upsert); nothing is written when ``dry_run`` is set.
    """
    db = db if db is not None else claims_db.get_db()
    path = Path(claims_path) if claims_path is not None else dev_claims_path()
    rows = read_jsonl(path)  # reads ONLY this file; refuses held-out paths

    mapper = _PolicyMapper()
    seeded: dict[str, str] = {}
    invalid: dict[str, str] = {}
    for raw in rows:
        claim_id = str(raw.get("claim_id", "<unknown>"))
        try:
            claim = ClaimRecord.model_validate(strip_eval_only(raw))
            policy = mapper._policy(claim)
        except Exception as exc:  # noqa: BLE001 - one bad fixture must not abort the whole seed
            invalid[claim_id] = f"{type(exc).__name__}: {exc}"
            continue
        if not dry_run:
            db.upsert_policy(policy)
        seeded[claim_id] = policy.policy_number

    distinct = sorted(set(seeded.values()))
    missing = [] if dry_run else [pn for pn in distinct if db.get_policy(pn) is None]
    return {
        "claims_file": str(path),
        "claims_read": len(rows),
        "seeded": seeded,
        "distinct_policies": distinct,
        "invalid": invalid,
        "missing_after_seed": missing,
        "dry_run": dry_run,
    }


def _print_summary(summary: dict) -> None:
    print(f"claims file           : {summary['claims_file']}")
    print(f"claims read           : {summary['claims_read']}")
    print(f"policies seeded       : {len(summary['seeded'])}")
    print(f"distinct policies     : {len(summary['distinct_policies'])}")
    if summary["invalid"]:
        print(f"invalid records       : {len(summary['invalid'])}")
        for cid, err in summary["invalid"].items():
            print(f"    - {cid}: {err}")
    else:
        print("invalid records       : 0")
    if summary["missing_after_seed"]:
        print(f"MISSING after seed    : {summary['missing_after_seed']}")
    else:
        print("missing after seed    : 0")
    if summary["dry_run"]:
        print("(dry run - nothing written)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Seed the claims DB with the development policies."
    )
    parser.add_argument(
        "--db",
        default=None,
        help=(
            "SQLite path for the claims DB "
            "(defaults to CLAIMSENSE_CLAIMS_DB / claimsense_claims.db)."
        ),
    )
    parser.add_argument(
        "--claims",
        default=None,
        help="Override the claims file (defaults to eval/golden_dev/claims.jsonl).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Map policies but write nothing.")
    args = parser.parse_args(argv)

    if args.db is not None and not args.dry_run:
        claims_db.set_db(claims_db.ClaimsDatabase(args.db))
    db = claims_db.get_db()

    summary = seed_dev_policies(db, claims_path=args.claims, dry_run=args.dry_run)
    _print_summary(summary)

    # Required validation: CLM-0001's policy (POL-10001) must be retrievable after seeding.
    if not args.dry_run:
        pol = db.get_policy("POL-10001")
        ok = pol is not None
        print(
            f"validate get_policy('POL-10001'): {'OK' if ok else 'MISSING'}"
            + (
                f" (SI={pol.sum_insured}, tier={pol.city_tier}, insured={pol.insured_pseudonym})"
                if pol
                else ""
            )
        )
        if not ok or summary["missing_after_seed"] or summary["invalid"]:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
