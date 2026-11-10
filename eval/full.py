"""The whole evaluation in one run: harness + agent suite, one report, one gate, one exit code.

    python -m eval.full --stub --label baseline                     # free, deterministic, seconds
    python -m eval.full --stub --label cmp --variant v1,guarded     # compare configurations
    python -m eval.full --label real-dev --splits dev               # real models (costs money)

Four stages, in this order:

    A  harness self-check   Can the scorer be trusted? The harness suite's ceiling, floor and
                            gate rows (gold replay, null, injected faults) must give their
                            recorded outcomes. If a safety gate stopped firing, nothing after it
                            means anything, so a mismatch fails the run.
    B  one pipeline pass    Every claim runs once through the real agents, with a trace.
    C  two scorers          The SAME outputs are scored by the harness (route, per-line amounts,
                            flags, citations, the six catastrophic gates, weighted composite) and
                            by the agent suite (outcome, process, guardrail, payload checks).
    D  combined gate        Passes only if A matched, the harness run passed (gates held and
                            composite >= threshold) and every agent-suite threshold held. The
                            first --variant decides the exit code.

Nothing is computed twice and nothing is copied: stage C calls `eval.harness.run.score` and
`eval.harness.scorecard.build_report` exactly as `python -m eval.harness.run` does, and the
traced output is field for field what the harness adapter returns (tested in
`eval/tests/test_full.py`), so the composites here equal the harness's own.

The harness suite's two pipeline rows (`real-dev`, `real-redteam`) are not rerun in stage A:
stage B is that run. Run `python -m eval.harness.suite` on its own to check their pinned values.

Output: `runs/full/<label>/` with `full.json` (everything), `rows.csv` (one row per claim and
variant, both scorers' columns side by side), `traces.jsonl`, `card.json`, `card.png` and
`harness.<variant>.scorecard.json`.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from eval.agent_suite import suite as agent
from eval.agent_suite.dataset import Case, load_dataset
from eval.harness import efficiency_metrics
from eval.harness import suite as harness_suite
from eval.harness.loader import REPO_ROOT, policy_clause_ids
from eval.harness.run import score as harness_score
from eval.harness.scorecard import build_report, format_report, load_scorecard

RUNS_DIR = REPO_ROOT / "runs" / "full"

#: Stage A: every harness suite row except the pipeline rows, which stage B replaces.
SELF_CHECK_ROWS = tuple(r for r in harness_suite.ROWS if r.label not in harness_suite.PIPELINE_ROWS)


# ------------------------------------------------------------------------- A. self-check
def self_check(tolerance_inr: int = 0) -> tuple[bool, list[str]]:
    """Run the harness's ceiling/floor/gate rows against their recorded outcomes."""
    config = load_scorecard()
    ok, lines = True, [f"  {'row':<26}{'composite':>10}  {'gates fired':<26}check"]
    with harness_suite.stub_llm():
        for row in SELF_CHECK_ROWS:
            report = harness_suite.run_row(row, config, tolerance_inr)
            problems = harness_suite.check(row, report)
            ok &= not problems
            gates = ",".join(sorted(report["gate_failures"])) or "-"
            mark = "ok" if not problems else "MISMATCH"
            lines.append(f"  {row.label:<26}{report['composite']:>10.3f}  {gates[:25]:<26}{mark}")
            lines.extend(f"      {p}" for p in problems)
    _reset_model_cache()
    return ok, lines


def _reset_model_cache() -> None:
    """`agents.llm.get_llm` caches per role. Anything built under the stub override must not be
    reused by a real-model run that follows, so the cache is cleared (runtime only, no code
    change)."""
    from claimsense.agents.llm import get_llm

    get_llm.cache_clear()


# --------------------------------------------------------------------- C. the harness scorer
def harness_scorecard(res: agent.SuiteResult, label: str, tolerance_inr: int = 0) -> tuple:
    """Score one variant's traced outputs with the harness, unchanged. Returns (report, scores)."""
    config = load_scorecard()
    cases = [c.eval_case for c in res.cases]
    outputs = [t.output for t in res.traces]
    scores = harness_score(cases, outputs, policy_clause_ids(), config, tolerance_inr)
    run_metrics = efficiency_metrics.summarise(
        outputs, cost_budget_usd=config.efficiency.get("cost_usd_per_claim_budget")
    )
    splits = sorted({c.split for c in res.cases})
    report = build_report(
        cases,
        scores,
        run_metrics,
        config,
        label=f"{label}:{res.variant}",
        adapter=f"traced[{res.variant}]",
        splits=splits,
        tolerance_inr=tolerance_inr,
    )
    by_split: dict[str, list[float]] = {}
    for case, s in zip(cases, scores, strict=True):
        by_split.setdefault(case.split, []).append(s.score)
    report["per_split"] = {k: round(sum(v) / len(v), 4) for k, v in sorted(by_split.items())}
    return report, scores


# ------------------------------------------------------------------------- D. combined gate
def combined_gate(
    self_ok: bool | None, harness_passed: bool, agent_passed: bool
) -> tuple[bool, list[str]]:
    """self_ok None means the self-check was skipped: reported, and it cannot pass the run."""
    parts = [
        ("A  harness self-check", self_ok),
        ("C  harness: gates held and composite >= threshold", harness_passed),
        ("C  agent suite: every gate.yaml threshold", agent_passed),
    ]
    lines = []
    for name, ok in parts:
        mark = "SKIP" if ok is None else ("PASS" if ok else "FAIL")
        lines.append(f"  {mark}  {name}")
    passed = self_ok is True and harness_passed and agent_passed
    lines.append(
        "  ==> " + ("ALL GATES PASSED: safe to ship" if passed else "FAILED: does not ship")
    )
    return passed, lines


# --------------------------------------------------------------------------------- output
def merged_rows(res: agent.SuiteResult, scores: list) -> list[dict]:
    """One row per claim: the agent suite's columns, then the harness's, prefixed `h_`."""
    rows = []
    for row, s in zip(res.rows, scores, strict=True):
        rows.append(
            {
                "variant": res.variant,
                **row,
                "h_score": s.score,
                "h_gates_failed": ";".join(s.gates_failed),
                **{f"h_{k}": v for k, v in s.parts.items()},
            }
        )
    return rows


def write_all(
    label: str,
    results: list[agent.SuiteResult],
    harness: dict[str, tuple],
    summary: dict,
    out_dir: Path | None = None,
) -> Path:
    out = agent.write_outputs(results, label, out_dir or RUNS_DIR / label)
    rows = [r for res in results for r in merged_rows(res, harness[res.variant][1])]
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with (out / "rows.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    for variant, (report, _) in harness.items():
        (out / f"harness.{variant}.scorecard.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
    (out / "full.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    return out


# ------------------------------------------------------------------------------------ CLI
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="python -m eval.full", description="Harness + agent suite in one run."
    )
    p.add_argument("--label", required=True, help="run name; output goes to runs/full/<label>")
    p.add_argument("--stub", action="store_true", help="free deterministic agents, even with a key")
    p.add_argument("--variant", default="v1", help=f"comma list from {sorted(agent.VARIANTS)}")
    p.add_argument("--splits", default="dev,redteam", help="comma list: dev, redteam")
    p.add_argument("--tolerance-inr", type=int, default=0, help="rupee tolerance (GOLD-08)")
    p.add_argument("--workers", type=int, default=1, help="claims in parallel (real-model runs)")
    p.add_argument("--show", default="", help="claim ids whose full trace to print")
    p.add_argument("--judge", action="store_true", help="agent-suite payload judge (costs money)")
    p.add_argument("--judge-limit", type=int, default=None, help="judge at most this many claims")
    p.add_argument("--skip-self-check", action="store_true", help="skip stage A (run cannot pass)")
    p.add_argument("--quiet", action="store_true", help="print the summary and gates only")
    p.add_argument("--out", default=None, help="output folder (default runs/full/<label>)")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    problem = agent.preflight(args.stub)
    if problem:
        print(problem, file=sys.stderr)
        return 2
    mode = "stub" if args.stub else None

    print("## A. Harness self-check: can the scorer be trusted?")
    if args.skip_self_check:
        self_ok, lines = None, ["  skipped (--skip-self-check): this run cannot pass the gate"]
    else:
        self_ok, lines = self_check(args.tolerance_inr)  # restores the mode preflight chose
    print("\n".join(lines))
    if self_ok is False:
        print("  SELF-CHECK MISMATCH: fix the harness before reading any score below.")

    cases: list[Case] = load_dataset([s.strip() for s in args.splits.split(",") if s.strip()])
    variants = [v.strip() for v in args.variant.split(",") if v.strip()]
    show = [s.strip() for s in args.show.split(",") if s.strip()] or None

    results: list[agent.SuiteResult] = []
    harness: dict[str, tuple] = {}
    verdicts: dict[str, dict] = {}
    for variant in variants:
        res = agent.run_suite(
            args.label,
            variant,
            cases,
            tolerance_inr=args.tolerance_inr,
            workers=args.workers,
            use_judge=args.judge,
            judge_limit=args.judge_limit,
        )
        results.append(res)
        mode = mode or res.traces[0].mode
        report, scores = harness_scorecard(res, args.label, args.tolerance_inr)
        harness[variant] = (report, scores)
        agent_ok, agent_lines = agent.check_gate(res.card)
        verdicts[variant] = {"harness": report["passed"], "agent": agent_ok}

        print(f"\n######## variant {variant} ########")
        print("\n## B+C. Harness scorecard: is the final answer right?")
        if args.quiet:
            fired = ", ".join(report["gate_failures"])
            print(
                f"  composite {report['composite']:.3f} (needs {report['composite_threshold']}), "
                f"gates {'held' if report['gates_held'] else 'FAILED: ' + fired}"
            )
        else:
            print(format_report(report))
        print("  composite by split:", report["per_split"])
        print("\n## B+C. Agent suite: what did the agents do?")
        print("\n".join(agent_lines) if args.quiet else agent.report(res, show=show))

    if len(results) > 1:
        print("\n## Side by side")
        print(agent.side_by_side(results))
        for r in results:
            rep = harness[r.variant][0]
            print(f"  harness composite {r.variant:<10} {rep['composite']:.4f}")

    primary = variants[0]
    passed, gate_lines = combined_gate(
        self_ok, verdicts[primary]["harness"], verdicts[primary]["agent"]
    )
    print(f"\n## D. Combined gate (variant {primary}, {mode} mode)")
    print("\n".join(gate_lines))

    summary = {
        "label": args.label,
        "mode": mode,
        "splits": args.splits,
        "variants": variants,
        "self_check": {"ok": self_ok, "lines": lines},
        "harness": {v: harness[v][0] for v in variants},
        "agent_cards": {r.variant: r.card for r in results},
        "verdicts": verdicts,
        "passed": passed,
    }
    out = write_all(args.label, results, harness, summary, Path(args.out) if args.out else None)
    print(f"\nwritten to {out}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
