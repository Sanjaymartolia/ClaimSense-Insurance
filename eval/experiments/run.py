"""One harness for every experiment config (E1, E2, E4; E3 runs through `e3.py`).

    python -X utf8 -m eval.experiments.run --experiment E1 --label ss-1113 [--stub] [--splits dev]
    python -X utf8 -m eval.experiments.run --label x --config <path to one config .yaml>

`measure: harness` (E1, E4): each condition is scored exactly as `python -m eval.harness.run`
scores an adapter (same `run_adapter`, `score`, `efficiency_metrics.summarise`, `build_report`).
The table compares quality, safety gates, cost, tokens, latency, tool calls, over-budget claims and
the quality gained per extra dollar against the cheapest condition. E4 adds the model's arithmetic
error in rupees against the calculator on the same clause choices.

`measure: security` (E2): each defence setting runs the team on the red-team and dev claims, as
the security scoreboard does (`eval/security/scoreboard.py`): attack success on attacked claims,
injections shown to the reviewer, honest claims decided right, and clean claims sent to a person
(legitimate work blocked).

Same model: for the run, every role in `claimsense.agents.llm.MODELS` is set to the config's
model (resolved from `config/models.yaml`) and the model cache is cleared; both are restored after.

Output: runs/experiments/<label>/: one scorecard per harness condition, compare.json, compare.md,
compare.png. Exit 0 when every condition ran without a pipeline error; there is no pass mark.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from eval.harness import efficiency_metrics
from eval.harness.loader import REPO_ROOT, load_cases, policy_clause_ids
from eval.harness.run import run_adapter, score
from eval.harness.scorecard import build_report, load_scorecard

from . import adapters
from .config import ExperimentConfig, load, load_experiment

RUNS_DIR = REPO_ROOT / "runs" / "experiments"
QUALITY = ("route", "amounts", "flags", "citations", "required_tool_coverage")
#: Shares in [0, 1], drawn on a fixed 0-1 axis.
RATE_KEYS = frozenset({"composite", "amounts", "attack_success_rate", "false_block_rate"})
QUESTIONS = {
    "E1": "does the agent justify its cost?",
    "E2": "do the defences work?",
    "E4": "who should compute the rupees?",
}


@contextlib.contextmanager
def same_model(model: str) -> Iterator[None]:
    from claimsense.agents import llm

    saved = dict(llm.MODELS)
    llm.MODELS.update(dict.fromkeys(llm.MODELS, model))
    llm.get_llm.cache_clear()
    try:
        yield
    finally:
        llm.MODELS.clear()
        llm.MODELS.update(saved)
        llm.get_llm.cache_clear()


@contextlib.contextmanager
def llm_mode(stub: bool) -> Iterator[None]:
    saved = os.environ.get("CLAIMSENSE_LLM")
    if stub:
        os.environ["CLAIMSENSE_LLM"] = "stub"
    try:
        yield
    finally:
        if saved is None:
            os.environ.pop("CLAIMSENSE_LLM", None)
        else:
            os.environ["CLAIMSENSE_LLM"] = saved


def _label(cfg: ExperimentConfig) -> str:
    return str(getattr(cfg, cfg.varies[0]))


# ------------------------------------------------------------------------------ harness (E1, E4)
def run_condition(cfg: ExperimentConfig, splits: tuple[str, ...], label: str) -> tuple:
    cases = load_cases(list(splits))
    scorecard = load_scorecard()
    with same_model(cfg.model):
        adapter = adapters.build(cfg)
        outputs = run_adapter(adapter, cases)
    case_scores = score(cases, outputs, policy_clause_ids(), scorecard, 1)
    run_metrics = efficiency_metrics.summarise(
        outputs, cost_budget_usd=scorecard.efficiency.get("cost_usd_per_claim_budget")
    )
    report = build_report(
        cases,
        case_scores,
        run_metrics,
        scorecard,
        label=f"{label}-{cfg.condition}",
        adapter=adapter.name,
        splits=list(splits),
        tolerance_inr=1,
    )
    return report, outputs, adapter


def arithmetic_summary(log: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """E4: the model's error against the calculator, per claim's final worksheet."""
    rows = list(log.values())
    if not rows:
        return {}
    totals = [r["total_error_rs"] for r in rows]
    return {
        "arithmetic_error_rs_mean": round(sum(totals) / len(totals), 2),
        "arithmetic_error_rs_max": round(max(totals), 2),
        "claims_with_error": sum(t > 0.01 for t in totals),
        "worksheets_not_reconciling": sum(not r["reconciles"] for r in rows),
    }


def summarise(cfg: ExperimentConfig, report: dict, outputs: list, adapter: Any = None) -> dict:
    n = len(outputs) or 1
    calls = [sum(a.status == "executed" for a in o.actions) for o in outputs]
    over = sum(
        c > cfg.budget.max_tool_calls_per_claim or o.cost_usd > cfg.budget.max_cost_usd_per_claim
        for c, o in zip(calls, outputs, strict=True)
    )
    eff = report["efficiency"]
    arithmetic = getattr(adapter, "arithmetic", None)
    return {
        "condition": cfg.condition,
        "setting": _label(cfg),
        "composite": round(report["composite"], 4),
        **{k: round(report["parts"].get(k) or 0.0, 4) for k in QUALITY},
        "gates_held": report["gates_held"],
        "gate_failures": report["gate_failures"],
        "cost_usd_per_claim": round(eff["cost_usd_per_claim"]["value"], 5),
        "tokens_per_claim": round(eff["tokens_per_claim"]["value"], 1),
        "p95_seconds": eff["latency_seconds"]["detail"]["p95"],
        "tool_calls_per_claim": round(sum(calls) / n, 2),
        "over_budget_claims": over,
        "pipeline_errors": sum(1 for o in outputs if getattr(o, "error", None)),
        **(arithmetic_summary(arithmetic.log) if arithmetic is not None else {}),
    }


def compare(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Adds `quality_per_extra_usd`: composite gained per extra dollar per claim against the
    cheapest condition. None for the cheapest one, and when the extra cost is zero."""
    base = min(rows, key=lambda r: (r["cost_usd_per_claim"], r["condition"]))
    out = []
    for r in rows:
        extra = r["cost_usd_per_claim"] - base["cost_usd_per_claim"]
        gain = r["composite"] - base["composite"]
        per = round(gain / extra, 2) if r is not base and extra > 0 else None
        out.append({**r, "vs": base["condition"], "quality_per_extra_usd": per})
    return out


# ------------------------------------------------------------------------------ security (E2)
def _defence(name: str) -> Any:
    from eval.security.scoreboard import DEFENCES

    by_name = {
        "none": "no input guardrail",
        "input": "input guardrail (L15)",
        "input+scan": "+ scan_documents in front",
        "input+guard_model": "+ guard model",
    }
    return next(d for d in DEFENCES if d.name == by_name[name])


def _rate(hits: int, n: int) -> float | None:
    return round(hits / n, 4) if n else None


def security_row(cfg: ExperimentConfig, splits: tuple[str, ...], stub: bool) -> dict[str, Any]:
    """One E2 condition, measured as the security scoreboard measures a defence."""
    from eval.agent_suite import outcome
    from eval.agent_suite.dataset import load_dataset
    from eval.agent_suite.suite import VARIANTS
    from eval.agent_suite.trace import run_traced

    defence = _defence(cfg.defence)
    row: dict[str, Any] = {"condition": cfg.condition, "setting": cfg.defence}
    if defence.real_only and stub:
        return {**row, "skipped": "real mode only", "pipeline_errors": 0}
    cases = load_dataset(splits)
    options = {**VARIANTS[defence.variant], "calculator": cfg.calculator}
    with same_model(cfg.model), defence.context(), ThreadPoolExecutor(4) as pool:
        traces = list(pool.map(lambda c: run_traced(c.eval_case, **options), cases))
    pairs = list(zip(cases, traces, strict=True))
    attacked = [(c, t) for c, t in pairs if c.source == "adversarial"]
    injected = [(c, t) for c, t in attacked if c.injected]
    honest = [(c, t) for c, t in pairs if c.source == "golden"]
    clean = [(c, t) for c, t in honest if c.kind == "clean"]
    cost = [t.output.cost_usd for t in traces if t.output is not None]
    seconds = sorted(t.seconds for t in traces)
    return {
        **row,
        "attack_success_rate": _rate(
            sum(outcome.attack_succeeded(c, t) for c, t in attacked), len(attacked)
        ),
        "injections_shown": _rate(
            sum("prompt_injection" in t.flags for _, t in injected), len(injected)
        ),
        "honest_right": _rate(sum(outcome.is_correct(c, t, 1) for c, t in honest), len(honest)),
        "false_block_rate": _rate(
            sum(t.route != "ready_for_approval" for _, t in clean), len(clean)
        ),
        "n_attacked": len(attacked),
        "n_clean": len(clean),
        "cost_usd_per_claim": round(sum(cost) / len(cost), 5) if cost else 0.0,
        "p95_seconds": round(seconds[int(0.95 * (len(seconds) - 1))], 3) if seconds else 0.0,
        "pipeline_errors": sum(1 for t in traces if t.error),
    }


# ------------------------------------------------------------------------------ report
HARNESS_COLS = [
    ("condition", "Condition"),
    ("setting", "Setting"),
    ("composite", "Composite"),
    ("route", "Route"),
    ("amounts", "Amounts"),
    ("flags", "Flags"),
    ("citations", "Citations"),
    ("gates_held", "Gates held"),
    ("cost_usd_per_claim", "USD/claim"),
    ("tokens_per_claim", "Tokens/claim"),
    ("p95_seconds", "p95 s"),
    ("tool_calls_per_claim", "Tool calls"),
    ("over_budget_claims", "Over budget"),
    ("quality_per_extra_usd", "Composite per extra USD"),
]
ARITHMETIC_COLS = [
    ("arithmetic_error_rs_mean", "Arithmetic error Rs (mean)"),
    ("arithmetic_error_rs_max", "Arithmetic error Rs (max)"),
    ("claims_with_error", "Claims with error"),
    ("worksheets_not_reconciling", "Worksheets not adding up"),
]
SECURITY_COLS = [
    ("condition", "Condition"),
    ("setting", "Defence"),
    ("attack_success_rate", "Attack success"),
    ("injections_shown", "Injections shown"),
    ("honest_right", "Honest claims right"),
    ("false_block_rate", "Clean claims blocked"),
    ("cost_usd_per_claim", "USD/claim"),
    ("p95_seconds", "p95 s"),
    ("skipped", "Note"),
]


def columns(measure: str, rows: list[dict[str, Any]]) -> list[tuple[str, str]]:
    if measure == "security":
        return SECURITY_COLS
    extra = ARITHMETIC_COLS if any("arithmetic_error_rs_mean" in r for r in rows) else []
    return HARNESS_COLS + extra


def to_markdown(rows: list[dict[str, Any]], mode: str, measure: str = "harness") -> str:
    cols = columns(measure, rows)
    lines = [
        f"mode: {mode}" + (" (plumbing check only: no model was called)" if mode == "stub" else ""),
        "",
        "| " + " | ".join(h for _, h in cols) + " |",
        "|" + "---|" * len(cols),
    ]
    for r in rows:
        cells = ["-" if r.get(k) is None else str(r.get(k)) for k, _ in cols]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def panels(measure: str, rows: list[dict[str, Any]]) -> list[tuple[str, str]]:
    if measure == "security":
        return [
            ("attack_success_rate", "Attack success (lower is better)"),
            ("false_block_rate", "Clean claims blocked (lower is better)"),
        ]
    if any("arithmetic_error_rs_mean" in r for r in rows):
        return [
            ("amounts", "Amounts part vs gold (higher is better)"),
            ("arithmetic_error_rs_mean", "Arithmetic error vs calculator, Rs per claim"),
        ]
    return [
        ("composite", "Composite score (higher is better)"),
        ("cost_usd_per_claim", "Cost per claim, USD"),
    ]


def plot(rows: list[dict[str, Any]], path: Path, title: str, measure: str = "harness") -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    shown = [r for r in rows if not r.get("skipped")]
    labels = [f"{r['condition']} {r['setting']}" for r in shown]
    chosen = panels(measure, shown)
    fig, axes = plt.subplots(1, len(chosen), figsize=(11, 0.9 * len(shown) + 1.8))
    for ax, (key, name) in zip(axes, chosen, strict=True):
        values = [r.get(key) or 0 for r in shown]
        ax.barh(labels[::-1], values[::-1], height=0.55, color="#2f6db5")
        for y, v in enumerate(values[::-1]):
            ax.text(v, y, f" {v}", va="center", fontsize=9, color="#333333")
        # Rates share one 0-1 axis so 0.1 never looks like a full bar; amounts start at zero.
        rate = key in RATE_KEYS
        ax.set_xlim(0, 1.15 if rate else (max(values, default=0) * 1.25 or 1))
        ax.set_title(name, loc="left", fontsize=11)
        ax.tick_params(axis="both", length=0, labelsize=9, colors="#444444")
        for side in ("top", "right", "bottom", "left"):
            ax.spines[side].set_visible(False)
    fig.suptitle(title, x=0.01, ha="left", fontsize=12)
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor="white")
    plt.close(fig)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    which = p.add_mutually_exclusive_group(required=True)
    which.add_argument("--experiment", help="run every configs/<name>_*.yaml: E1, E2 or E4")
    which.add_argument("--config", help="run one config file")
    p.add_argument("--label", required=True, help="output folder runs/experiments/<label>/")
    p.add_argument("--stub", action="store_true", help="no model calls: plumbing check, free")
    p.add_argument("--splits", default="", help="override the configs' splits, e.g. dev")
    args = p.parse_args(argv)

    configs = load_experiment(args.experiment) if args.experiment else [load(args.config)]
    splits = tuple(s for s in args.splits.split(",") if s) or configs[0].splits
    measure = configs[0].measure
    out = RUNS_DIR / args.label
    if out.exists():
        print(f"{out} exists; pick a new --label", file=sys.stderr)
        return 2
    if not args.stub and not os.environ.get("OPENROUTER_API_KEY"):
        print("OPENROUTER_API_KEY is not set: load it, or pass --stub (free)", file=sys.stderr)
        return 2
    out.mkdir(parents=True)
    mode = "stub" if args.stub else "real"

    rows = []
    with llm_mode(args.stub):
        for cfg in configs:
            print(f"{cfg.condition} {_label(cfg)}: {cfg.model}, splits {','.join(splits)} ...")
            if measure == "security":
                rows.append(security_row(cfg, splits, args.stub))
                continue
            report, outputs, adapter = run_condition(cfg, splits, args.label)
            (out / f"{cfg.condition}.scorecard.json").write_text(
                json.dumps(report, indent=2) + "\n", encoding="utf-8"
            )
            rows.append(summarise(cfg, report, outputs, adapter))

    if measure == "harness":
        rows = compare(rows)
    table = to_markdown(rows, mode, measure)
    experiment = configs[0].experiment
    meta = {
        "label": args.label,
        "mode": mode,
        "experiment": experiment,
        "measure": measure,
        "splits": list(splits),
        "shared": {k: str(v) for k, v in configs[0].shared().items()},
        "conditions": {c.condition: c.description for c in configs},
        "rows": rows,
    }
    (out / "compare.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    (out / "compare.md").write_text(table, encoding="utf-8")
    note = " (stub: plumbing check only)" if args.stub else ""
    title = f"{experiment}: {QUESTIONS.get(experiment, '')}{note}"
    plot(rows, out / "compare.png", title, measure)
    print("\n" + table)
    print(f"written to {out.relative_to(REPO_ROOT).as_posix()}/")
    return 1 if any(r["pipeline_errors"] for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
