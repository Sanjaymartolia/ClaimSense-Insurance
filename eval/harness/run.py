"""CLI entry point for the evaluation harness. Owner: Eval & Red-Team.

    python -m eval.harness.run --adapter gold-replay --split dev --label ceiling
    python -m eval.harness.run --adapter null        --split dev --label floor
    python -m eval.harness.run --adapter perturbed --fault unsafe_settle --split dev,redteam
    python -m eval.harness.run --split dev --judge --judge-limit 5      # costs money

Exit code is 0 only when every catastrophic gate holds and the composite reaches the threshold in
`scorecard.yaml`, so this is usable directly as a CI gate (T48).

Start with `--adapter gold-replay`. It replays the gold answer, so it must pass with no gate
failures and score 0.975 on dev (0.990 on red-team). It is not 1.000 because five dev gold claims
have no `clause_id` to cite yet (GOLD-07 is only partly fixed). If the ceiling moves, the harness
or the fixtures broke and no other number from it means anything.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import efficiency_metrics, reference_metrics, safety_metrics, trajectory_metrics
from .adapters import ADAPTERS, FAULTS, build_adapter
from .loader import load_cases, policy_clause_ids
from .models import AgentOutput, EvalCase
from .scorecard import build_report, format_report, load_scorecard

RUNS_DIR = Path(__file__).resolve().parents[2] / "runs"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m eval.harness.run",
        description="Score a ClaimSense agent against the dev and red-team eval sets.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="adapters for --adapter:\n"
        + "\n".join(f"  {name:<22}{why}" for name, why in ADAPTERS.items())
        + "\n\nfaults for --fault (with --adapter perturbed):\n"
        + "\n".join(f"  {name:<22}{why}" for name, why in FAULTS.items()),
    )
    parser.add_argument(
        "--adapter",
        default="gold-replay",
        choices=sorted(ADAPTERS),
        metavar="NAME",
        help="thing under test (default: gold-replay). See the list below.",
    )
    parser.add_argument(
        "--fault",
        action="append",
        default=[],
        help="with --adapter perturbed: inject this fault. Repeatable.",
    )
    parser.add_argument(
        "--split",
        default="dev",
        help="comma-separated: dev, redteam, or dev,redteam (default: dev)",
    )
    parser.add_argument("--label", default="", help="run label; names the files in runs/")
    parser.add_argument(
        "--tolerance-inr",
        type=int,
        default=1,
        help="allowed rupee difference per amount; 1 forgives the GOLD-08 rounding gap (ADR-0007, "
        "default: 1). Pass 0 for strict scoring",
    )
    parser.add_argument(
        "--judge",
        action="store_true",
        help="also run the RAGAS faithfulness judge. Needs OPENROUTER_API_KEY and costs money.",
    )
    parser.add_argument(
        "--judge-limit",
        type=int,
        default=5,
        help="judge at most this many claims (default: 5). Keeps a first run cheap.",
    )
    parser.add_argument(
        "--scorecard", default=None, help="path to a scorecard yaml (default: the shipped one)"
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=None,
        help="override the composite threshold from the scorecard",
    )
    parser.add_argument("--output", default=None, help="write the scorecard JSON here")
    parser.add_argument("--quiet", action="store_true", help="print the JSON only")
    return parser.parse_args(argv)


def run_adapter(adapter, cases: list[EvalCase]) -> list[AgentOutput]:  # noqa: ANN001
    """Run the thing under test over every case, timing each one.

    The adapter receives `case.claim` and never `case.gold`. That is enforced here, by passing one
    argument, rather than trusted.
    """
    outputs: list[AgentOutput] = []
    for case in cases:
        started = time.perf_counter()
        out = adapter.run(case.claim)
        elapsed = time.perf_counter() - started
        if out.claim_id != case.claim_id:
            raise ValueError(
                f"adapter returned claim_id {out.claim_id!r} for case {case.claim_id!r}"
            )
        if not out.latency_s:
            out.latency_s = elapsed
        outputs.append(out)
    return outputs


def score(
    cases: list[EvalCase],
    outputs: list[AgentOutput],
    policy_ids: frozenset[str],
    config,  # noqa: ANN001 - ScorecardConfig
    tolerance_inr: int,
) -> list:
    from .scorecard import score_case as compose

    scores = []
    for case, out in zip(cases, outputs, strict=True):
        metrics = {
            **reference_metrics.score_case(out, case.gold, policy_ids, tolerance_inr),
            **trajectory_metrics.score_case(out, case.gold),
            **safety_metrics.score_case(out, case.gold, case.claim, policy_ids),
        }
        scores.append(compose(case, out, metrics, config))
    return scores


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    splits = [s.strip() for s in args.split.split(",") if s.strip()]

    config = load_scorecard(args.scorecard) if args.scorecard else load_scorecard()
    if args.min_score is not None:
        config.composite_threshold = args.min_score

    cases = load_cases(splits)
    policy_ids = policy_clause_ids()
    from .real_retrieval import RetrievalUnavailableError

    try:
        adapter = build_adapter(args.adapter, cases, args.fault or None)
    except RetrievalUnavailableError as e:
        print(f"eval.harness: the real retriever cannot open: {e}", file=sys.stderr)
        return 2

    outputs = run_adapter(adapter, cases)
    case_scores = score(cases, outputs, policy_ids, config, args.tolerance_inr)

    run_metrics = efficiency_metrics.summarise(
        outputs, cost_budget_usd=config.efficiency.get("cost_usd_per_claim_budget")
    )
    if args.judge:
        from . import llm_judge_metrics

        # `cases` is passed so the claim's own facts reach the judge alongside the clause text.
        # Without them a correct rationale scores 0.200 instead of 0.800; see `claim_facts`.
        llm_judge_metrics.attach_clause_contexts(outputs, cases)
        run_metrics.update(llm_judge_metrics.score_outputs(outputs, limit=args.judge_limit))

    label = args.label or f"{adapter.name}-{'+'.join(splits)}"
    report = build_report(
        cases,
        case_scores,
        run_metrics,
        config,
        label=label,
        adapter=adapter.name,
        splits=splits,
        tolerance_inr=args.tolerance_inr,
    )

    destination = Path(args.output) if args.output else RUNS_DIR / f"{label}.scorecard.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if args.quiet:
        print(json.dumps(report, indent=2))
    else:
        print(format_report(report))
        print(f"  scorecard written to {destination}")

    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
