"""L13 section 7: the eval suite and a CI gate.

One function runs every case through the pipeline, keeps a trace of each, computes the outcome,
process, payload and system metrics from those traces, and compares them with `gate.yaml`. If any
measured threshold is missed, the change does not ship.

    python -m eval.agent_suite --label baseline                    # v1 over dev + red-team
    python -m eval.agent_suite --label pr42 --variant v1,guarded   # side by side (section 7.1)
    python -m eval.agent_suite --label rel --k 3                   # + pass@3 / pass^3 (3.2)
    python -m eval.agent_suite --label x --show CLM-9001           # one claim's full trace (1.4)
    python -m eval.agent_suite --label x --judge --judge-limit 10  # + the judge (needs a key)

Variants are configurations set here; none of them edits a file under `src/`:

    v1        the pipeline as the `claimsense` harness adapter runs it (documents passed in)
    no-docs   the documents dropped, as the product loader does today (defect CLAIM-03)
    guarded   the product input guardrail in front of the graph (section 5.1)
    lean-pr   section 7.1's "teammate's PR": the fraud agent's tool calls are skipped to save
              three calls per claim. Outcome metrics barely move; the process metrics block it

Without `OPENROUTER_API_KEY` (or with `CLAIMSENSE_LLM=stub`) the agents run their deterministic
fallbacks: free, seconds, and repeatable. With a key the real models run and the trace gains llm
spans with tokens and cost.

Writes `runs/agent_suite/<label>/`: `card.json`, `rows.csv`, `traces.jsonl` (no claim text) and
`card.png`. Exit code 0 only if the first variant passes the gate, so this is a CI step as it is
(section 7.3).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from eval.harness.loader import REPO_ROOT

from . import guardrail, io_guardrails, judge, outcome, process
from .dataset import Case, composition, load_dataset
from .trace import Trace, format_trace, run_traced

GATE_FILE = Path(__file__).with_name("gate.yaml")
RUNS_DIR = REPO_ROOT / "runs" / "agent_suite"

VARIANTS: dict[str, dict] = {
    "v1": {"pass_documents": True, "guardrail": False},
    "no-docs": {"pass_documents": False, "guardrail": False},
    "guarded": {"pass_documents": True, "guardrail": True},
    "lean-pr": {"pass_documents": True, "guardrail": False, "fraud_screen": False},
    # v1 with the real hybrid retriever (policy-kb) instead of the stub clause table. Needs
    # .[retrieval] and `python -m claimsense.retrieval.index`; see eval/harness/real_retrieval.py.
    "real-retrieval": {"pass_documents": True, "guardrail": False, "retrieval": "real"},
}

#: Metrics that are shares in [0, 1], drawn on the chart. Counts and seconds are printed only.
RATE_METRICS: tuple[str, ...] = (
    "task_success",
    "golden_success",
    "adversarial_success",
    "attack_success_rate",
    "over_escalation_rate",
    "path_complete",
    "clause_match",
    "injection_surfaced",
    "payload_checks_ok",
    "redundant_call_share",
    "judge_pass_rate",
)


@dataclass
class SuiteResult:
    name: str
    variant: str
    cases: list[Case]
    traces: list[Trace]
    rows: list[dict]
    card: dict[str, float | None]
    judge_verdicts: dict[str, object] = field(default_factory=dict)
    #: The settlement tolerance the card was scored with; `report` reuses it, so the printed
    #: tables can never disagree with the gate (GOLD-08).
    tolerance_inr: int = 0


def load_gate(path: Path = GATE_FILE) -> dict[str, tuple[str, float]]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    gate = {k: (str(v[0]), float(v[1])) for k, v in (raw.get("gate") or {}).items()}
    bad = [k for k, (d, _) in gate.items() if d not in (">=", "<=")]
    if bad:
        raise ValueError(f"{path}: direction must be >= or <= for {bad}")
    return gate


def run_cases(cases: list[Case], variant: str = "v1", workers: int = 1) -> list[Trace]:
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant!r}; choose from {sorted(VARIANTS)}")
    opts = VARIANTS[variant]

    def one(c: Case) -> Trace:
        return run_traced(c.eval_case, variant=variant, **opts)

    if workers <= 1:
        return [one(c) for c in cases]
    with ThreadPoolExecutor(workers) as ex:
        return list(ex.map(one, cases))


def _rate(values: list) -> float | None:
    vals = [float(v) for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def build_card(
    cases: list[Case],
    traces: list[Trace],
    rows: list[dict],
    tolerance_inr: int = 0,
    judge_verdicts: dict | None = None,
) -> dict[str, float | None]:
    pairs = list(zip(cases, traces, strict=True))
    correct = [outcome.is_correct(c, t, tolerance_inr) for c, t in pairs]
    adversarial = [(c, t) for c, t in pairs if c.source == "adversarial"]
    clean = [(c, t) for c, t in pairs if c.source == "golden" and not c.escalation_ok]
    ran = [r for r in rows if not r["blocked"]]
    tool_calls = sum(r["tool_calls"] for r in ran)
    checks = [judge.payload_checks(c, t) for c, t in pairs]
    system = process.latency_and_cost(traces)
    verdicts = [v for v in (judge_verdicts or {}).values() if v is not None]
    sources = [c.source for c in cases]
    return {
        "task_success": _rate(correct),
        "golden_success": _rate(
            [ok for s, ok in zip(sources, correct, strict=True) if s == "golden"]
        ),
        "adversarial_success": _rate(
            [ok for s, ok in zip(sources, correct, strict=True) if s == "adversarial"]
        ),
        "attack_success_rate": _rate([outcome.attack_succeeded(c, t) for c, t in adversarial]),
        "over_escalation_rate": _rate([t.route == "needs_review" for _, t in clean]),
        "path_complete": _rate([r["path_complete"] for r in ran]),
        "clause_match": _rate([r["clause_match"] for r in ran]),
        # over every row: a claim the guardrail blocked did reach a person, flagged
        "injection_surfaced": _rate([r["injection_surfaced"] for r in rows]),
        "payload_checks_ok": _rate([all(ch.values()) for ch in checks if ch]),
        "redundant_call_share": (
            sum(r["redundant"] for r in ran) / tool_calls if tool_calls else None
        ),
        "tool_error_rate": sum(r["tool_errors"] for r in ran) / tool_calls if tool_calls else 0.0,
        "acl_denied": float(sum(r["acl_denied"] for r in ran)),
        "forbidden_tool_calls": float(sum(r["forbidden"] for r in rows)),
        "pipeline_errors": float(sum(t.status == "error" for t in traces)),
        "mean_steps": _rate([r["steps"] for r in ran]),
        "p95_seconds": system["p95_seconds"],
        "cost_per_claim_usd": system["mean_cost_usd"],
        "judge_pass_rate": _rate([v.verdict == "pass" for v in verdicts]) if verdicts else None,
    }


def run_suite(
    name: str,
    variant: str = "v1",
    cases: list[Case] | None = None,
    *,
    tolerance_inr: int = 0,
    workers: int = 1,
    use_judge: bool = False,
    judge_limit: int | None = None,
    structured: judge.Structured | None = None,
) -> SuiteResult:
    cases = cases if cases is not None else load_dataset()
    traces = run_cases(cases, variant, workers)
    rows = process.process_table(cases, traces, tolerance_inr)
    verdicts: dict[str, object] = {}
    if use_judge:
        judged = [t for t in traces if t.review_payloads][:judge_limit]
        for t in judged:
            verdicts[t.claim_id] = judge.judge_trace(t, structured)
    card = build_card(cases, traces, rows, tolerance_inr, verdicts)
    return SuiteResult(name, variant, cases, traces, rows, card, verdicts, tolerance_inr)


def check_gate(
    card: dict[str, float | None], gate: dict[str, tuple[str, float]] | None = None
) -> tuple[bool, list[str]]:
    gate = gate if gate is not None else load_gate()
    ok_all, lines = True, []
    for metric, (direction, limit) in gate.items():
        value = card.get(metric)
        if value is None:
            lines.append(f"  SKIP  {metric:<22} {'not measured':>12}   (needs {direction} {limit})")
            continue
        ok = value >= limit if direction == ">=" else value <= limit
        ok_all &= ok
        verdict = "PASS" if ok else "FAIL"
        lines.append(f"  {verdict}  {metric:<22} {value:>12.4f}   (needs {direction} {limit})")
    lines.append(
        "  ==> " + ("GATE PASSED: safe to ship" if ok_all else "GATE FAILED: this does not ship")
    )
    return ok_all, lines


def side_by_side(results: list[SuiteResult]) -> str:
    names = [r.variant for r in results]
    metrics = list(results[0].card)
    lines = [f"  {'metric':<24}" + "".join(f"{n:>12}" for n in names)]
    for m in metrics:
        cells = []
        for r in results:
            v = r.card.get(m)
            cells.append(f"{'-' if v is None else f'{v:.4f}':>12}")
        lines.append(f"  {m:<24}" + "".join(cells))
    return "\n".join(lines)


def pairwise(a: SuiteResult, b: SuiteResult, structured: judge.Structured | None = None) -> dict:
    """7.2: which variant gives the adjudicator the better payload, judged in both orders."""
    out: dict[str, int] = {a.variant: 0, b.variant: 0, "tie": 0}
    for ta, tb in zip(a.traces, b.traces, strict=True):
        if not (ta.review_payloads and tb.review_payloads):
            continue
        ev_a, ev_b = judge.evidence_from_trace(ta), judge.evidence_from_trace(tb)
        win = judge.swap_compare("Two versions of one claim's review.", ev_a, ev_b, structured)
        out[{"a": a.variant, "b": b.variant}.get(win, "tie")] += 1
    return out


# --------------------------------------------------------------------------------- the report
def report(
    res: SuiteResult, *, tolerance_inr: int | None = None, show: list[str] | None = None
) -> str:
    """Sections 1-7 of the notebook, in order, for one run. The tolerance defaults to the one
    the run was scored with."""
    tolerance_inr = res.tolerance_inr if tolerance_inr is None else tolerance_inr
    cases, traces, rows = res.cases, res.traces, res.rows
    by_id = {t.claim_id: t for t in traces}
    out: list[str] = [f"=== {res.name} / variant {res.variant} / {traces[0].mode} mode ==="]

    out.append("\n## 1. Traces")
    picks = show or [
        next(
            (
                c.claim_id
                for c, t in zip(cases, traces, strict=True)
                if outcome.why_wrong(c, t, tolerance_inr)
            ),
            cases[0].claim_id,
        )
    ]
    for cid in picks:
        if cid in by_id:
            out.append(format_trace(by_id[cid]))
        else:
            out.append(f"  {cid}: not in this run")

    out.append("\n## 2. The eval dataset\n" + composition(cases))

    out.append("\n## 3. Outcome metrics\n### 3.1 Task success by source")
    out.append(outcome.format_success_table(outcome.success_table(cases, traces, tolerance_inr)))
    out.append("by kind:")
    out.append(
        outcome.format_success_table(outcome.success_table(cases, traces, tolerance_inr, by="kind"))
    )
    wrong = outcome.wrong_ones(cases, traces, tolerance_inr)
    out.append(f"wrong ones ({len(wrong)}):")
    out.extend(wrong or ["  none"])

    out.append("\n## 4. Process metrics (mean over claims where each applies)")
    out.append(process.summary_by_source(rows))
    out.append("\n### 4.1 Cost and time")
    system = process.latency_and_cost(traces)
    out.append(
        f"  latency   P50 {system['p50_seconds'] * 1000:.1f} ms   "
        f"P95 {system['p95_seconds'] * 1000:.1f} ms   P99 {system['p99_seconds'] * 1000:.1f} ms"
    )
    out.append(
        f"  cost      mean ${system['mean_cost_usd']:.5f}   P95 ${system['p95_cost_usd']:.5f}   "
        f"-> ${system['cost_per_1000_claims_usd']:.2f} per 1,000 claims"
    )
    out.append(f"  LLM calls mean {system['mean_llm_calls']:.1f}   max {system['max_llm_calls']}")
    out.append("  time by node (runs, mean ms):")
    for node, (n, ms) in process.node_time(traces).items():
        out.append(f"    {node:<14} {n:>4}  {ms:8.2f}")
    out.append("  who called what (agent, tool, status: count):")
    for (agent, tool, status), n in sorted(process.who_called_what(traces).items()):
        out.append(f"    {agent:<12} {tool:<18} {status:<8} {n}")
    lucky, unlucky = process.lucky_and_unlucky(rows)
    out.append("\n### 4.2 Right answer, wrong path (and the other way round)")
    out.append(f"  right, but skipped a required step: {lucky or 'none'}")
    out.append(f"  took every step, still wrong:       {unlucky or 'none'}")

    out.append("\n## 5.1 The input guardrail (claimsense.guardrails.scan_documents)")
    out.append(guardrail.measure(cases).format())
    bare, guarded = guardrail.attack_success_rates(cases, traces)
    out.append(
        f"attack success rate on {sum(c.source == 'adversarial' for c in cases)} attacked claims: "
        f"this run {bare:.0%}, with the guardrail in front {guarded:.0%}"
    )
    out.append("\n## 5.2 The input and output guardrail modules (L15: wired in since 12 Nov 2026)")
    out.append(io_guardrails.format_both(cases, traces))

    out.append("\n## 6.2 Code checks on the review payload (claims failing each)")
    fails = judge.payload_check_summary(cases, traces)
    out.extend([f"  {name:<30} {n}" for name, n in fails.most_common()] or ["  all pass"])
    if res.judge_verdicts:
        verdicts = [v for v in res.judge_verdicts.values() if v is not None]
        passed = sum(v.verdict == "pass" for v in verdicts)
        out.append(f"\n## 6.1 Judge: {passed}/{len(verdicts)} payloads pass")
        for cid, v in res.judge_verdicts.items():
            if v is not None and v.verdict == "fail":
                out.append(f"  {cid}: {v.reasoning[:160]}")

    out.append("\n## 7. Gate")
    _, gate_lines = check_gate(res.card)
    out.extend(gate_lines)
    return "\n".join(out)


# ------------------------------------------------------------------------------- write & plot
def write_outputs(results: list[SuiteResult], label: str, out_dir: Path | None = None) -> Path:
    out = out_dir or RUNS_DIR / label
    out.mkdir(parents=True, exist_ok=True)
    cards = {r.variant: r.card for r in results}
    (out / "card.json").write_text(json.dumps(cards, indent=2), encoding="utf-8")
    with (out / "traces.jsonl").open("w", encoding="utf-8") as f:
        for r in results:
            for t in r.traces:
                f.write(json.dumps(t.to_dict(), default=str) + "\n")
    rows = [{"variant": r.variant, **row} for r in results for row in r.rows]
    if rows:
        with (out / "rows.csv").open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    plot_cards(results, out / "card.png")
    return out


#: Categorical slots 1-3 of the dataviz reference palette, in fixed order (one per variant).
SERIES = ("#2a78d6", "#eb6834", "#1baf7a")
INK, INK_2, SURFACE = "#0b0b0b", "#52514e", "#fcfcfb"


def plot_cards(results: list[SuiteResult], path: Path) -> bool:
    """Rate metrics as horizontal bars, the gate threshold as a dark tick. Needs matplotlib
    (the `docs` or `course` extra); returns False and skips the chart without it."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    gate = load_gate()
    metrics = [m for m in RATE_METRICS if any(r.card.get(m) is not None for r in results)]
    n = len(results)
    height = 0.8 / n
    fig, ax = plt.subplots(figsize=(8, 0.42 * len(metrics) * max(1, n * 0.7) + 1.4))
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    for i, r in enumerate(results[:3]):
        ys = [k + (i - (n - 1) / 2) * height for k in range(len(metrics))]
        vals = [r.card.get(m) or 0.0 for m in metrics]
        ax.barh(ys, vals, height=height * 0.85, color=SERIES[i], label=r.variant, edgecolor=SURFACE)
        for y, v, m in zip(ys, vals, metrics, strict=True):
            if r.card.get(m) is not None:
                ax.text(v + 0.01, y, f"{v:.2f}", va="center", fontsize=8, color=INK_2)
    for k, m in enumerate(metrics):
        if m in gate:
            direction, limit = gate[m]
            ax.plot([limit, limit], [k - 0.45, k + 0.45], color=INK, linewidth=2)
            ax.text(1.12, k, f"{direction} {limit:g}", va="center", fontsize=8, color=INK_2)
    ax.set_yticks(range(len(metrics)), labels=metrics, fontsize=9, color=INK)
    ax.invert_yaxis()
    ax.set_xlim(0, 1.1)
    ax.tick_params(axis="x", colors=INK_2, labelsize=8)
    ax.grid(axis="x", color="#e4e3df", linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color("#c3c2b7")
    title = f"Agent suite: {results[0].name}  (black tick = gate threshold)"
    ax.set_title(title, loc="left", fontsize=11, color=INK)
    if n > 1:
        ax.legend(frameon=False, fontsize=9, loc="lower right")
    fig.tight_layout()
    fig.savefig(path, dpi=130, facecolor=SURFACE)
    plt.close(fig)
    return True


# ------------------------------------------------------------------------------------- CLI
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="python -m eval.agent_suite", description=__doc__.split("\n")[0]
    )
    p.add_argument(
        "--label", required=True, help="run name; outputs go to runs/agent_suite/<label>"
    )
    p.add_argument("--variant", default="v1", help=f"comma list from {sorted(VARIANTS)}")
    p.add_argument("--splits", default="dev,redteam", help="comma list: dev, redteam")
    p.add_argument(
        "--tolerance-inr",
        type=int,
        default=1,
        help="settlement tolerance in rupees (GOLD-08, ADR-0007; default 1, pass 0 for strict)",
    )
    p.add_argument("--k", type=int, default=1, help="runs per golden+adversarial case for pass@k")
    p.add_argument(
        "--workers", type=int, default=1, help="claims run in parallel (real-model runs)"
    )
    p.add_argument("--show", default="", help="comma list of claim ids whose full trace to print")
    p.add_argument(
        "--judge", action="store_true", help="LLM judge on review payloads (costs money)"
    )
    p.add_argument("--judge-limit", type=int, default=None, help="judge at most this many claims")
    p.add_argument("--quiet", action="store_true", help="print the gate only, not the report")
    p.add_argument(
        "--stub", action="store_true", help="force the free deterministic agents, even with a key"
    )
    return p.parse_args(argv)


def preflight(force_stub: bool) -> str | None:
    """Decide stub vs real model before any claim runs. Returns an error message, or None.

    A key in the environment (VS Code loads `.env` into its terminals) switches the agents to real
    models. Without the `agents` extra that used to crash half way through the first claim.
    """
    import os

    if force_stub:
        os.environ["CLAIMSENSE_LLM"] = "stub"
    from claimsense.agents.llm import stub_mode

    if stub_mode():
        print("mode: stub (deterministic agents, no model calls, free)\n")
        return None
    try:
        import langchain_openai  # noqa: F401
    except ImportError:
        return (
            "OPENROUTER_API_KEY is set, so the agents would call real models, but langchain-openai "
            "is not installed.\n"
            "  free, deterministic run:  python -m eval.agent_suite --stub --label <name>\n"
            '  real-model run:           pip install -e ".[agents]"  (then rerun; costs money)'
        )
    print("mode: REAL MODELS via OpenRouter (costs money; add --stub for a free run)\n")
    return None


def overwrite_problem(out: Path) -> str | None:
    """A stub run never replaces a real-model run: reports quote those runs, and they cost money
    to redo (on 14 November 2026 two quoted runs were found overwritten by stub reruns). An error
    message, or None. Call after `preflight`, which settles stub or real."""
    from claimsense.agents.llm import stub_mode

    try:
        with (out / "traces.jsonl").open(encoding="utf-8") as f:
            previous = json.loads(f.readline()).get("mode")
    except (OSError, ValueError):  # no earlier run there, or not one we can read
        return None
    if stub_mode() and previous not in (None, "stub"):
        return (
            f"{out} holds a real-model run that this stub run would replace. Reports quote such "
            "runs: use another --label."
        )
    return None


def retrieval_problem(variants: list[str]) -> str | None:
    """Open the real retriever once, before any claim, if a variant needs it. An error message, or
    None. Without this a missing index would crash the run (or a worker pool) on the first claim."""
    if not any(VARIANTS.get(v, {}).get("retrieval") == "real" for v in variants):
        return None
    from eval.harness.real_retrieval import RetrievalUnavailableError, open_real_retrieval

    try:
        open_real_retrieval()
    except RetrievalUnavailableError as e:
        return f"the real retriever cannot open: {e}"
    return None


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    problem = preflight(args.stub) or overwrite_problem(RUNS_DIR / args.label)
    if problem:
        print(problem, file=sys.stderr)
        return 2
    cases = load_dataset([s.strip() for s in args.splits.split(",") if s.strip()])
    variants = [v.strip() for v in args.variant.split(",") if v.strip()]
    problem = retrieval_problem(variants)
    if problem:
        print(problem, file=sys.stderr)
        return 2
    show = [s.strip() for s in args.show.split(",") if s.strip()] or None
    results = [
        run_suite(
            args.label,
            v,
            cases,
            tolerance_inr=args.tolerance_inr,
            workers=args.workers,
            use_judge=args.judge,
            judge_limit=args.judge_limit,
        )
        for v in variants
    ]
    for r in results:
        if args.quiet:
            print(f"{r.variant}:")
            print("\n".join(check_gate(r.card)[1]))
        else:
            print(report(r, tolerance_inr=args.tolerance_inr, show=show))
        print()

    if args.k > 1:
        mode = results[0].traces[0].mode
        subset = [c for c in cases if c.source in ("golden", "adversarial")]
        opts = VARIANTS[variants[0]]
        outcomes = outcome.repeat_outcomes(
            subset,
            args.k,
            lambda c: run_traced(c.eval_case, variant=variants[0], **opts),
            args.tolerance_inr,
        )
        print(f"## 3.2 pass@k over {len(subset)} cases x {args.k} runs ({mode} mode)")
        for name, value in outcome.reliability(outcomes, args.k).items():
            print(f"  {name:<8} {value:.2f}")
        print("  flaky cases:", *(outcome.flaky(outcomes) or ["none"]), sep="\n")
        if mode == "stub":
            print(
                "  (stub mode is deterministic, so pass@k == pass^k; run with a key to see the gap)"
            )
        print()

    if len(results) > 1:
        print("## 7.1 Side by side")
        print(side_by_side(results))
        if args.judge:
            print("\n## 7.2 Pairwise (both orders):", pairwise(results[0], results[1]))
        print()

    out = write_outputs(results, args.label)
    print(f"written to {out}")
    return 0 if check_gate(results[0].card)[0] else 1


if __name__ == "__main__":
    sys.exit(main())
