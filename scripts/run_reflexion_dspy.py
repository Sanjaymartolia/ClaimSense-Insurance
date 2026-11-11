"""L12 notebook §6-9 replicated on ClaimSense: DSPy, BootstrapFewShot, GEPA against the playbook.

    # harness check, no key (stub LMs; stamped HARNESS CHECK ONLY, never a result)
    python scripts/run_reflexion_dspy.py --out docs/experiments/reflexion/dspy-harness-check-stub \
        --tolerance-rs 1 --gepa-metric-calls 20

    # the real run (your own OpenRouter key in the environment; a few hundred calls, cents)
    export OPENROUTER_API_KEY=...  CLAIMSENSE_MODEL_REFLECTOR=openai/gpt-4.1-mini
    python scripts/run_reflexion_dspy.py --out docs/experiments/reflexion/dspy-run-01 --tolerance-rs 1

Notebook step -> what runs here:
    §6   signature, Predict vs ChainOfThought, metric       ChooseClauses; rows 3-4; make_metric
    §7.1 BootstrapFewShot (the student teaches itself)      row 5
    §7.2 BootstrapFewShot + a stronger teacher              row 6 (teacher = the reflector model)
    §7.3 GEPA (reflect on failures, rewrite the prompt)     row 7
    §7.5 the improvement is a file                          programs/*.json in --out
    §5   the Reflexion playbook (memory lever)              row 2, the frozen run-02 playbook
    §9   one table                                          report.md, results.json, plot.png

One rule, as in the notebook: methods learn from the training half of the admissible development
claims; the test half is only scored. Nothing here reads the held-out set (the path is refused).
The money never enters any metric: rows are scored on clause accuracy, and the settlement error of
each row is measured separately through the ordinary pipeline, with the same evaluator and
tolerance as `run_reflexion_experiment.py`.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import dspy

from claimsense.agents.llm import MODELS
from claimsense.reflexion.cases import load_cases, stub_services_factory
from claimsense.reflexion.dspy_coverage import (
    ChooseClauses,
    configure_dspy,
    coverage_examples,
    gold_chooser,
    make_metric,
    program_chooser,
)
from claimsense.reflexion.optimizers import (
    MethodResult,
    choose_winner,
    comparison_md,
    compile_bootstrap,
    compile_gepa,
    measure,
    plot,
    save_program,
    split_cases,
)
from claimsense.reflexion.playbook import Playbook
from claimsense.reflexion.reporting import mode_label, to_json

HELDOUT_MARKERS = ("heldout", "held-out", "held_out")
DEFAULT_PLAYBOOK = "docs/experiments/reflexion/run-02/playbook.json"


def slug(name: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in name.lower()).strip("-")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--cases", default="eval/golden_dev", help="development claims directory")
    ap.add_argument("--out", default="docs/experiments/reflexion/dspy-run-01")
    ap.add_argument(
        "--playbook",
        default=DEFAULT_PLAYBOOK,
        help="frozen playbook for the Reflexion row (skipped if the file is missing)",
    )
    ap.add_argument("--tolerance-rs", type=Decimal, default=Decimal("0"))
    ap.add_argument("--gepa-metric-calls", type=int, default=100)
    ap.add_argument("--bootstrap-demos", type=int, default=4)
    ap.add_argument("--threads", type=int, default=1, help="GEPA threads (1 = deterministic)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument(
        "--calculator",
        choices=["reference", "team"],
        default="reference",
        help="'team' uses the team calculator through agents.services.real_calculate",
    )
    ap.add_argument(
        "--skip",
        nargs="*",
        default=[],
        choices=["bootstrap", "coach", "gepa"],
        help="leave out slow optimizers (every other row still runs)",
    )
    args = ap.parse_args(argv)
    if any(m in str(args.cases).lower() for m in HELDOUT_MARKERS):
        sys.exit("refusing: this script learns from cases, so it must never see the held-out set")
    if args.tolerance_rs < 0:
        sys.exit("--tolerance-rs must be 0 or positive")

    cases = load_cases(args.cases, split="dev")
    assert all(c.split == "dev" for c in cases)
    if args.calculator == "team":
        from claimsense.agents.services import real_calculate

        factory = stub_services_factory(calculate=real_calculate)
    else:
        factory = stub_services_factory()
    train, test = split_cases(cases)
    models = configure_dspy(train)  # the oracle coach only ever sees training cases
    trainset = coverage_examples(train, factory)
    metric = make_metric(train, factory)
    out = Path(args.out)
    (out / "programs").mkdir(parents=True, exist_ok=True)

    banner = (
        f"mode: {mode_label()} | dspy {dspy.__version__} | student: "
        f"{models.ids.get('student', 'stub')} | coach/reflection: "
        f"{models.ids.get('coach', 'stub (oracle coach)')} | calculator: {args.calculator} | "
        f"tolerance: Rs {args.tolerance_rs} | GEPA budget: {args.gepa_metric_calls} metric calls"
        + (" | HARNESS CHECK ONLY, NOT A RESULT" if models.mode == "stub" else "")
    )
    print(banner)
    print(f"train: {[c.case_id for c in train]}\ntest:  {[c.case_id for c in test]}")

    results: list[MethodResult] = []
    tol = args.tolerance_rs

    def row(name: str, calls0: int | None = None, **kw) -> MethodResult:
        """`calls0`: the LM call count before this row's compile step, so `lm_calls` covers
        compiling plus scoring both halves and the pipeline run."""
        print(f"[{len(results) + 1}/8] {name} ...", flush=True)
        r = measure(name, train, test, factory, tol, **kw)
        r.lm_calls = models.calls() - calls0 if calls0 is not None else 0
        results.append(r)
        print(
            f"      test clause accuracy {r.test_accuracy}, settlement error Rs "
            f"{r.settlement_error_total_rs}, edit rate {r.edit_rate}"
        )
        return r

    # 1-2: the shipped prompt, without and with the frozen playbook (memory lever, §5)
    row("Agent prompt (as shipped)")
    pb_path = Path(args.playbook)
    if pb_path.exists():
        pb = Playbook.load(pb_path)
        n_approved = len(pb.by_status("approved"))
        row(
            "Agent prompt + Reflexion playbook",
            playbook=pb,
            notes=[
                f"playbook {pb_path} ({n_approved} approved lesson(s), "
                f"{'frozen ' + (pb.frozen_hash or '')[:8] if pb.frozen else 'NOT frozen'})"
            ],
        )
    else:
        print(f"      (no playbook at {pb_path}; Reflexion row skipped)")

    # 3-4: §6 signatures and modules
    calls0 = models.calls()
    predict = dspy.Predict(ChooseClauses)
    row("DSPy Predict", program=predict, chooser=program_chooser(predict), calls0=calls0)
    save_program(predict, out / "programs" / "dspy-predict.json")
    calls0 = models.calls()
    cot = dspy.ChainOfThought(ChooseClauses)
    row("DSPy ChainOfThought", program=cot, chooser=program_chooser(cot), calls0=calls0)
    save_program(cot, out / "programs" / "dspy-chainofthought.json")

    # 5-6: §7.1-7.2 BootstrapFewShot, then with the coach as teacher
    if "bootstrap" not in args.skip:
        calls0 = models.calls()
        prog, secs = compile_bootstrap(trainset, metric, demos=args.bootstrap_demos)
        row(
            "BootstrapFewShot",
            program=prog,
            chooser=program_chooser(prog),
            compile_seconds=secs,
            calls0=calls0,
            notes=[f"demos: {[d.get('case_id') for d in prog.predict.demos]}"],
        )
        save_program(prog, out / "programs" / "bootstrapfewshot.json")
    if "coach" not in args.skip:
        calls0 = models.calls()
        prog, secs = compile_bootstrap(
            trainset, metric, teacher_lm=models.coach, demos=args.bootstrap_demos
        )
        row(
            "BootstrapFewShot + coach",
            program=prog,
            chooser=program_chooser(prog),
            compile_seconds=secs,
            calls0=calls0,
            notes=[f"demos: {[d.get('case_id') for d in prog.predict.demos]}"],
        )
        save_program(prog, out / "programs" / "bootstrapfewshot-coach.json")

    # 7: §7.3 GEPA
    if "gepa" not in args.skip:
        calls0 = models.calls()
        prog, secs = compile_gepa(
            trainset,
            metric,
            models.reflection,
            args.gepa_metric_calls,
            seed=args.seed,
            num_threads=args.threads,
        )
        row(
            "GEPA",
            program=prog,
            chooser=program_chooser(prog),
            compile_seconds=secs,
            calls0=calls0,
            notes=[
                f"instruction grew from {len(ChooseClauses.instructions)} to "
                f"{len(prog.predict.signature.instructions)} characters"
            ],
        )
        save_program(prog, out / "programs" / "gepa.json")

    # 8: the ceiling the candidates allow
    row(
        "Ceiling: gold replay within candidates",
        chooser=gold_chooser(train + test),
        notes=["not a method: the gold clause wherever the policy search returned it"],
    )

    winner = choose_winner(results)
    table = comparison_md(results, winner)
    plotted = plot(results, out / "plot.png")
    header = ["# DSPy / GEPA vs the Reflexion playbook (L12 §6-9 on ClaimSense)", ""]
    if models.mode == "stub":
        header += [
            "> **HARNESS CHECK ONLY.** Stub LMs: the student always picks the top-ranked "
            "candidate and the coach replays the gold. These numbers prove the loop runs; they "
            "are not a result. Re-run with a key.",
            "",
        ]
    unreachable = sorted({lid for r in results for pc in r.per_case for lid in pc["unreachable"]})
    lines = header + [
        banner,
        "",
        f"- development cases: {len(cases)} from `{args.cases}`; admissible {len(train) + len(test)}; "
        f"train {len(train)}, test {len(test)} (sorted by id, alternating)",
        f"- train: {', '.join(c.case_id for c in train)}",
        f"- test: {', '.join(c.case_id for c in test)}",
        f"- unreachable test lines (gold clause not among the candidates, excluded from accuracy): "
        f"{', '.join(unreachable) or 'none'}",
        f"- generated {datetime.now(UTC).isoformat()}",
        "",
        "## One table",
        "",
        table,
        "",
        f"**Chosen: {winner[0] or 'none'}** ({winner[1]}).",
        "",
        ("![plot](plot.png)" if plotted else "(matplotlib not installed: no plot)"),
        "",
        "## Instructions after optimisation",
        "",
    ]
    for r in results:
        if r.instruction:
            lines += [
                f"### {r.name} ({len(r.instruction)} chars, {r.demos} demos)",
                "",
                "```",
                r.instruction,
                "```",
                "",
            ]
    lines += ["## Per case (test half)", ""]
    for r in results:
        lines += [
            f"### {r.name}",
            "",
            "| case | accuracy | wrong (line, chose, expected) | "
            "unreachable | settlement error Rs |",
            "|---|---|---|---|---|",
        ]
        for pc in r.per_case:
            wrong = (
                "; ".join(
                    f"{w[0].split('-')[-1]}: {w[1].split(':')[-1]}→{w[2].split(':')[-1]}"
                    for w in pc["wrong"]
                )
                or "-"
            )
            lines.append(
                f"| {pc['case_id']} | {pc['accuracy']} | {wrong} | "
                f"{', '.join(x.split('-')[-1] for x in pc['unreachable']) or '-'} | "
                f"{pc['settlement_error_rs']} |"
            )
        lines += [""] + [f"- {n}" for n in r.notes] + [""]
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    summary = {
        "mode": banner,
        "harness_check_only": models.mode == "stub",
        "models": models.ids or {"student": "stub", "coach": "oracle stub"},
        "agent_models": MODELS,
        "tolerance_rs": args.tolerance_rs,
        "train": [c.case_id for c in train],
        "test": [c.case_id for c in test],
        "rows": [r.to_json() for r in results],
        "winner": {"name": winner[0], "reason": winner[1]},
    }
    # UTF-8 on purpose: the per-case table uses an arrow, and Windows defaults to cp1252.
    (out / "results.json").write_text(to_json(summary), encoding="utf-8")
    print("\n" + table + f"\n\nChosen: {winner[0]} ({winner[1]})\nwrote {out / 'report.md'}")


if __name__ == "__main__":
    main()
