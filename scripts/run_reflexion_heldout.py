"""Day 5 of the agents plan: the held-out run, for the Evaluation owner.

    python scripts/run_reflexion_heldout.py \
        --playbook docs/experiments/reflexion/run-01/playbook.json \
        --heldout ../claimsense-heldout \
        --out ../claimsense-heldout-results/run-01

Runs the 60 held-out claims twice, once with no playbook and once with the frozen playbook, and
writes the before/after table. No reflection, no proposals, nothing learned.

`claimsense.reflexion.run_heldout` refuses to run if the playbook is not frozen, if it changed
since freezing, if any lesson came from a held-out case, or if a held-out id also appears in the
development set. This script adds two more refusals: the held-out directory must not be inside the
repository, and the output directory must not be inside the repository either, so held-out ids and
amounts never land in git by accident.

The held-out files are expected in the same format as `eval/golden_dev/` (`claims.jsonl` +
`gold_worksheets.jsonl`). Only the Evaluation owner runs this, once, with code, model, prompts and
playbook frozen.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from claimsense.reflexion import Playbook, evaluate, langgraph_run_fn, local_run_fn, run_heldout
from claimsense.reflexion.cases import load_cases, stub_services_factory
from claimsense.reflexion.metrics import compare_table, summarize
from claimsense.reflexion.reporting import (
    breakdown_md,
    case_table,
    mode_label,
    playbook_counts,
    spread_md,
    to_json,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _inside_repo(p: Path) -> bool:
    try:
        p.resolve().relative_to(REPO_ROOT)
        return True
    except ValueError:
        return False


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--playbook", required=True, help="frozen playbook.json from the day-4 experiment"
    )
    ap.add_argument("--heldout", required=True, help="held-out directory, OUTSIDE the repository")
    ap.add_argument(
        "--dev", default="eval/golden_dev", help="development set, to check for id overlap"
    )
    ap.add_argument("--out", required=True, help="results directory, OUTSIDE the repository")
    ap.add_argument("--repeat", type=int, default=3, help="repeat the with-playbook run (brief: 3)")
    ap.add_argument("--executor", choices=["local", "langgraph"], default="local")
    ap.add_argument("--calculator", choices=["reference", "team"], default="reference")
    ap.add_argument(
        "--tolerance-rs",
        type=Decimal,
        default=Decimal("0"),
        help="rounding tolerance in rupees, use the SAME value as the day-4 run; 0 = strict",
    )
    ap.add_argument("--allow-inside-repo", action="store_true", help="tests only")
    args = ap.parse_args(argv)
    if args.tolerance_rs < 0:
        sys.exit("--tolerance-rs must be 0 or positive")

    heldout_dir, out = Path(args.heldout), Path(args.out)
    if not args.allow_inside_repo:
        if _inside_repo(heldout_dir):
            sys.exit("refusing: the held-out set must live outside the repository")
        if _inside_repo(out):
            sys.exit("refusing: held-out results must be written outside the repository")

    pb = Playbook.load(args.playbook)
    if not pb.frozen:
        sys.exit(f"refusing: {args.playbook} is not frozen; finish the day-4 experiment first")
    if pb.content_hash() != pb.frozen_hash:
        sys.exit("refusing: the playbook changed after it was frozen")

    dev = load_cases(args.dev, split="dev")
    held = load_cases(heldout_dir, split="heldout")
    if args.calculator == "team":
        from claimsense.agents.services import real_calculate

        factory = stub_services_factory(calculate=real_calculate)
    else:
        factory = stub_services_factory()
    run_fn = (langgraph_run_fn if args.executor == "langgraph" else local_run_fn)(factory)

    # run_heldout performs every guard (frozen, unchanged, no leaked lesson, no id overlap) and
    # the first before/after pass; the per-case tables and the repeats come from evaluate().
    tol = args.tolerance_rs
    before, _after_first = run_heldout(run_fn, held, pb, dev, tol)
    before_results = evaluate(run_fn, held, None, tol)
    after_runs = [evaluate(run_fn, held, pb, tol) for _ in range(args.repeat)]

    banner = (
        f"mode: {mode_label()} | executor: {args.executor} | calculator: {args.calculator} | "
        f"tolerance: Rs {tol} | playbook hash: {pb.frozen_hash} | "
        f"approved lessons: {playbook_counts(pb)['approved']}"
    )
    out.mkdir(parents=True, exist_ok=True)
    md = [
        "# Reflexion held-out run (frozen playbook)",
        "",
        banner,
        "",
        f"- held-out cases: {len(held)} from `{heldout_dir}`; development cases checked for overlap: {len(dev)}",
        f"- generated {datetime.now(UTC).isoformat()}",
        "",
        "## Before vs after (first with-playbook run)",
        "",
        compare_table(before, summarize(after_runs[0])),
        "",
        f"## Spread across {args.repeat} with-playbook runs",
        "",
        spread_md(after_runs),
        "",
        "## Where the error comes from, no playbook",
        "",
        breakdown_md(before_results),
        "",
        "## Where the error comes from, with the frozen playbook (run 1)",
        "",
        breakdown_md(after_runs[0]),
        "",
        "## Per case, no playbook",
        "",
        case_table(before_results),
    ]
    for i, run in enumerate(after_runs, 1):
        md += ["", f"## Per case, with playbook, run {i}", "", case_table(run)]
    (out / "heldout_report.md").write_text("\n".join(md) + "\n")
    (out / "heldout_report.json").write_text(
        to_json(
            {
                "mode": banner,
                "tolerance_rs": tol,
                "playbook_hash": pb.frozen_hash,
                "before": before,
                "after_runs": [summarize(r) for r in after_runs],
                "per_case_before": [r.model_dump(mode="json") for r in before_results],
                "per_case_after": [[r.model_dump(mode="json") for r in run] for run in after_runs],
            }
        )
    )
    print(banner)
    print(compare_table(before, summarize(after_runs[0])))
    print(f"\nwrote {out / 'heldout_report.md'}")


if __name__ == "__main__":
    main()
