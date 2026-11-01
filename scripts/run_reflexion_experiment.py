"""Day 4 of the agents plan: the Reflexion experiment on the 20 development claims.

    # 1. baseline: empty playbook, save the numbers
    python scripts/run_reflexion_experiment.py baseline --out docs/experiments/reflexion/run-01

    # 2. the full experiment, with a PERSON approving each lesson at the terminal
    python scripts/run_reflexion_experiment.py experiment --reviewer "<your name>" \
        --out docs/experiments/reflexion/run-01 --after-runs 2

    # harness check only (never for the report): approve everything automatically
    python scripts/run_reflexion_experiment.py experiment --approve auto --out /tmp/reflexion-check

Stages inside `experiment`, in the plan's order: baseline -> learn (human gate) -> ablation ->
withdraw harmful lessons (with a note) -> after pass, repeated -> freeze -> report.

Guard rails, all enforced here or in `claimsense.reflexion`:
- development cases only (`learn` asserts the split; this script also refuses any path that
  mentions the held-out set);
- the playbook file is never silently reused once frozen: freezing is the end of the experiment;
- `--approve auto` is loud in the console and in the report header, so it cannot be mistaken
  for the reviewed run.

Outputs land in `--out`: `playbook.json` (frozen, with its hash), `baseline.json/.md`,
`report.md`, `report.json`. Nothing outside `--out` is written.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from claimsense.agents import make_stub_services
from claimsense.contracts import LessonStatus
from claimsense.reflexion import (
    CaseResult,
    Playbook,
    Report,
    ablate,
    compare_table,
    evaluate,
    langgraph_run_fn,
    learn,
    local_run_fn,
    summarize,
)
from claimsense.reflexion.cases import RULE_DISAGREEMENTS, load_cases, stub_services_factory
from claimsense.reflexion.reporting import (
    ablation_md,
    breakdown_md,
    case_table,
    error_breakdown,
    lessons_md,
    mode_label,
    spread_md,
    summary_table,
    to_json,
)
from claimsense.reflexion.review_cli import console_approver

HELDOUT_MARKERS = ("heldout", "held-out", "held_out")


# ------------------------------------------------------------------------------ helpers
def mode_banner(args) -> str:
    return (
        f"mode: {mode_label()} | executor: {args.executor} | calculator: {args.calculator} | "
        f"approval: {args.approve.upper()}"
        + (" (harness check only, NOT for the report)" if args.approve == "auto" else "")
    )


def disagreements_md() -> str:
    return "\n".join(f"- {d}" for d in RULE_DISAGREEMENTS)


def build_run_fn(args):
    if args.calculator == "team":
        from claimsense.agents.services import real_calculate

        factory = stub_services_factory(calculate=real_calculate)
    else:
        factory = stub_services_factory()
    return (langgraph_run_fn if args.executor == "langgraph" else local_run_fn)(factory)


def load_dev_cases(args):
    if any(m in str(args.cases).lower() for m in HELDOUT_MARKERS):
        sys.exit("refusing: this script learns from cases, so it must never see the held-out set")
    cases = load_cases(args.cases, split="dev")
    assert all(c.split == "dev" for c in cases)
    return cases


# ------------------------------------------------------------------------------ stages
def stage_baseline(args) -> list[CaseResult]:
    cases = load_dev_cases(args)
    run_fn = build_run_fn(args)
    results = evaluate(run_fn, cases, None)
    summary = summarize(results)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "baseline.json").write_text(
        to_json(
            {
                "generated_at": datetime.now(UTC).isoformat(),
                "mode": mode_banner(args),
                "summary": summary,
                "breakdown": error_breakdown(results),
                "per_case": [r.model_dump(mode="json") for r in results],
            }
        )
    )
    (out / "baseline.md").write_text(
        "\n".join(
            [
                "# Reflexion baseline (empty playbook), 20 development claims",
                "",
                mode_banner(args),
                "",
                "## Summary",
                "",
                summary_table(summary),
                "",
                "## Where the error comes from",
                "",
                breakdown_md(results),
                "",
                "## Known gold vs calculator rule disagreements",
                "",
                disagreements_md(),
                "",
                "## Per case",
                "",
                case_table(results),
                "",
            ]
        )
    )
    print(mode_banner(args))
    print(to_json(summary))
    print(breakdown_md(results))
    print(f"\nwrote {out / 'baseline.md'}")
    return results


def stage_experiment(args) -> None:
    cases = load_dev_cases(args)
    run_fn = build_run_fn(args)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    pb_path = out / "playbook.json"
    pb = Playbook.load(pb_path)
    if pb.frozen:
        sys.exit(
            f"{pb_path} is already frozen ({pb.frozen_hash[:12]}...). A frozen playbook is the "
            "end of an experiment: use a new --out directory for a new run."
        )
    if args.approve == "console":
        approve_fn = console_approver(args.reviewer)
    else:
        print(
            "\n*** --approve auto: every lesson is approved without review. Harness check only. "
            "Do NOT put these numbers in the report. ***\n"
        )

        def approve_fn(lesson):
            return True, f"AUTO-{args.reviewer}", "auto-approved (harness check)"

    clause_text = make_stub_services().get_clause

    def get_clause_text(cid: str) -> str:
        c = clause_text(cid) if cid else None
        return c.text if c else ""

    print(mode_banner(args))
    print(f"\n[1/6] baseline on {len(cases)} development claims")
    baseline_results = evaluate(run_fn, cases, None)
    baseline = summarize(baseline_results)
    print(to_json(baseline))

    print("\n[2/6] learning pass: each mistake -> one lesson -> your decision")
    proposed = learn(run_fn, cases, pb, approve_fn, get_clause_text)
    approved = pb.by_status(LessonStatus.APPROVED)
    rejected = pb.by_status(LessonStatus.REJECTED)
    print(f"proposed {len(proposed)}, approved {len(approved)}, rejected {len(rejected)}")

    print("\n[3/6] ablation: leave one lesson out at a time")
    ablation = ablate(run_fn, cases, pb)
    for row in ablation:
        print(
            f"  {row['lesson_id']} harmful={row['harmful']} dRs={row['error_increase_rs']} "
            f"dEdit={row['edit_rate_increase']}"
        )

    print("\n[4/6] withdraw harmful lessons, each with a note")
    withdrawn = []
    for row in ablation:
        if row["harmful"]:
            pb.withdraw(
                row["lesson_id"], args.reviewer, "made development results worse in ablation"
            )
            withdrawn.append(row["lesson_id"])
    pb.save()
    print(f"withdrawn: {withdrawn or 'none'}")

    print(f"\n[5/6] after pass, {args.after_runs} run(s)")
    after_runs = []
    for i in range(args.after_runs):
        results = evaluate(run_fn, cases, pb)
        after_runs.append(results)
        print(f"  run {i + 1}: {to_json(summarize(results))}")

    print("\n[6/6] freeze")
    frozen = pb.freeze()
    print(f"frozen playbook hash {frozen}")

    report = Report(baseline, summarize(after_runs[0]), ablation, withdrawn, frozen)
    extra = [
        "",
        "## Run details",
        "",
        mode_banner(args),
        "",
        f"- development cases: {len(cases)} from `{args.cases}`",
        f"- lessons proposed {len(proposed)}, approved {len(approved)}, rejected {len(rejected)}, "
        f"withdrawn after ablation {len(withdrawn)}",
        f"- generated {datetime.now(UTC).isoformat()}",
        "",
        "## Baseline: where the error comes from",
        "",
        breakdown_md(baseline_results),
        "",
        f"## Spread across the {len(after_runs)} after-pass run(s)",
        "",
        spread_md(after_runs),
    ]
    for i, results in enumerate(after_runs, 1):
        extra += [
            "",
            f"## After pass, run {i}",
            "",
            compare_table(baseline, summarize(results)),
            "",
            breakdown_md(results),
        ]
    extra += [
        "",
        "## All lessons and their review status",
        "",
        lessons_md(pb),
        "",
        "## Ablation table (leave one lesson out)",
        "",
        ablation_md(ablation),
        "",
        "## Known gold vs calculator rule disagreements (not fixable by any lesson)",
        "",
        disagreements_md(),
        "",
        "## Per case: baseline",
        "",
        case_table(baseline_results),
    ]
    for i, results in enumerate(after_runs, 1):
        extra += ["", f"## Per case: after pass, run {i}", "", case_table(results)]
    header = ["# Reflexion experiment: 20 development claims", ""]
    if args.approve == "auto":
        header += [
            "> **HARNESS CHECK ONLY.** Lessons were auto-approved. These numbers must not be "
            "reported; re-run with `--approve console`.",
            "",
        ]
    (out / "report.md").write_text("\n".join(header + [report.markdown()] + extra) + "\n")
    (out / "report.json").write_text(
        to_json(
            {
                "mode": mode_banner(args),
                "baseline": baseline,
                "after_runs": [summarize(r) for r in after_runs],
                "ablation": ablation,
                "withdrawn": withdrawn,
                "frozen_hash": frozen,
                "lessons": [lesson.model_dump(mode="json") for lesson in pb.lessons.values()],
                "per_case_baseline": [r.model_dump(mode="json") for r in baseline_results],
                "per_case_after": [[r.model_dump(mode="json") for r in run] for run in after_runs],
            }
        )
    )
    print(f"\nwrote {out / 'report.md'}, {out / 'report.json'}, {pb_path}")
    print("\n" + report.markdown())


def stage_status(args) -> None:
    pb = Playbook.load(Path(args.out) / "playbook.json")
    print(f"frozen: {pb.frozen} hash: {pb.frozen_hash}")
    print(lessons_md(pb))
    if pb.frozen:
        ok = pb.content_hash() == pb.frozen_hash
        print("hash check:", "OK, unchanged since freezing" if ok else "CHANGED since freezing")


# ------------------------------------------------------------------------------ main
def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("stage", choices=["baseline", "experiment", "status"])
    ap.add_argument("--cases", default="eval/golden_dev", help="development claims directory")
    ap.add_argument(
        "--out",
        default="docs/experiments/reflexion/run-01",
        help="results and playbook.json go here",
    )
    ap.add_argument(
        "--reviewer",
        default=os.getenv("USER", "adjudicator"),
        help="your name, recorded on every decision",
    )
    ap.add_argument("--approve", choices=["console", "auto"], default="console")
    ap.add_argument(
        "--after-runs", type=int, default=2, help="repeat the after pass (20 claims is noisy)"
    )
    ap.add_argument("--executor", choices=["local", "langgraph"], default="local")
    ap.add_argument(
        "--calculator",
        choices=["reference", "team"],
        default="reference",
        help="'team' uses claimsense.calc.adjudicate once T15 lands",
    )
    args = ap.parse_args(argv)
    {"baseline": stage_baseline, "experiment": stage_experiment, "status": stage_status}[
        args.stage
    ](args)


if __name__ == "__main__":
    main()
