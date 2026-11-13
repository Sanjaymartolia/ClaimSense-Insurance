"""Run the tool-use evaluation. Offline, no key, no cost.

    python -m eval.agentic.run --label agentic-dev

Writes `runs/agentic/<label>.json`, `.traces.jsonl` and `.png`. Exit code 0 means no case failed
unexpectedly. Known product defects do not fail the run, but they are counted against the pass
rates in the chart. This report is separate from the weighted scorecard in `eval/harness`.
"""

from __future__ import annotations

import argparse
import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any

from eval.harness.loader import REPO_ROOT

from . import db_state, hook_eval, llm_eval, tool_eval, trajectory_eval
from .cases import DEFECT_FIXED, FAIL, PASS
from .pipeline import Run

OUT_DIR = REPO_ROOT / "runs" / "agentic"

SCOPE = (
    "No LLM selects tools in this product: tool order is fixed in Python, so tool-selection "
    "accuracy is not measured. Pipeline runs use stub tools with the real calculator, approval "
    "gate and hooks. Real database, approval, tariff and policy-kb code is covered by the direct "
    "tool cases. Branch decisions are taken from each run and judged by eval/harness."
)

DEFECTS = {
    "AGENTIC-02": "A new worksheet version with a fresh approval settles the same claim again.",
    "AGENTIC-03": "A settlement approval can authorise a repudiation of the same claim.",
    "AGENTIC-04": "A claim can be repudiated after it has been settled.",
    "AGENTIC-05": "A database failure after verification spends the approval.",
    "AGENTIC-06": "settle_claim MCP wrapper raises sqlite3 errors instead of returning ToolError.",
    "AGENTIC-07": "get_policy MCP wrapper raises sqlite3 errors instead of returning ToolError.",
    "AGENTIC-08": "record_history writes outside the ToolBelt: no ACL, budget or audit.",
    "AGENTIC-09": "A 40-line bill exceeds the 40-call budget, so a valid claim cannot finish.",
    "AGENTIC-11": "check_consistency reads 'Patient discharged' as a patient id.",
    "AGENTIC-12": "A not-admissible claim skips the fraud screen, so an in-bill duplicate is not "
    "shown at repudiation review (RT-003, CLM-9026). An override re-runs the screen (B7).",
    "AGENTIC-14": "claims.status stays 'recorded' after a settlement or repudiation: the write "
    "updates the claims row before record_history has inserted it.",
    "AGENTIC-13": "A room/ICU line without `days` is capped for 1 day: the contract's default "
    "quantity of 1 is read as days, so the stay length (Claim.nights) is ignored.",
}

#: Defects the product has since fixed. Their cases now guard against regressions.
FIXED = {
    "AGENTIC-01": "settle_claim derives the senior gate on the server (claims_db, after cfad026).",
    "AGENTIC-10": "Input and output guardrails are called by extraction and settlement (dc934a7).",
}


def _tally(results: list[dict]) -> dict[str, int]:
    return dict(sorted(Counter(r["status"] for r in results).items()))


def _trace(run: Run) -> dict[str, Any]:
    return {
        "claim_id": run.claim_id,
        "scenario": run.scenario,
        "split": run.tags.get("split"),
        "error": run.error,
        "events": run.events,
        "reviews": run.reviews,
    }


def build_report(splits: tuple[str, ...]) -> tuple[dict[str, Any], list[Run]]:
    runs = trajectory_eval.dataset_runs(splits)
    db_table = db_state.summarize(db_state.dataset_runs(splits))
    trajectory = trajectory_eval.summarize(runs)
    groups = {
        "tool": tool_eval.run_all(),
        "hook": [*hook_eval.run_all(), hook_eval.duplicate_detection_case()],
        "control": trajectory_eval.control_cases(),
        "llm": llm_eval.run_all(),
    }
    open_defects = sorted(
        {
            r["defect"]
            for results in groups.values()
            for r in results
            if r["status"] == "known_defect"
        }
        | {row["defect"] for row in db_table.values() if row["defect"] and row["failures"]}
    )
    report = {
        "scope": SCOPE,
        "splits": list(splits),
        "n_pipeline_runs": len(runs),
        "pipeline_errors": dict(Counter(r.error for r in runs if r.error)),
        "trajectory": trajectory,
        "cases": {
            name: {"totals": _tally(results), "results": results}
            for name, results in groups.items()
        },
        "attacks": hook_eval.attack_table(),
        "db_state": db_table,
        "open_defects": {d: DEFECTS[d] for d in open_defects},
        "fixed_defects": FIXED,
    }
    return report, runs


def is_clean(report: dict[str, Any]) -> bool:
    if report["pipeline_errors"]:
        return False
    if any(row["failures"] for row in report["trajectory"].values()):
        return False
    for row in report["db_state"].values():
        unexpected = row["failures"] and not row["defect"]
        stale = row["defect"] and row["applicable"] and row["passed"] == row["applicable"]
        if unexpected or stale:
            return False
    bad = (FAIL, DEFECT_FIXED)
    return not any(
        r["status"] in bad for group in report["cases"].values() for r in group["results"]
    )


def _bars(ax: Any, rows: list[tuple[str, int, int]], title: str) -> None:
    labels = [r[0] for r in rows][::-1]
    rates = [r[1] / r[2] if r[2] else 0 for r in rows][::-1]
    ax.barh(labels, rates, height=0.55, color="#2f6db5")
    for y, row in enumerate(rows[::-1]):
        ax.text(1.02, y, f"{row[1]}/{row[2]}", va="center", fontsize=9, color="#333333")
    ax.set_xlim(0, 1)
    ax.set_xticks([0, 0.5, 1], ["0%", "50%", "100%"])
    ax.set_title(title, loc="left", fontsize=11)
    ax.tick_params(axis="both", length=0, labelsize=9, colors="#444444")
    for side in ("top", "right", "bottom", "left"):
        ax.spines[side].set_visible(False)


def plot(report: dict[str, Any], path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    metrics = [(k, v["passed"], v["applicable"]) for k, v in report["trajectory"].items()]
    groups = [
        (f"{name} cases", g["totals"].get(PASS, 0), len(g["results"]))
        for name, g in report["cases"].items()
    ]
    attacks = [(r["attack_id"], r["live"], r["n"]) for r in report["attacks"] if "n" in r]
    db_rows = [(f"db: {k}", v["passed"], v["applicable"]) for k, v in report["db_state"].items()]

    fig, axes = plt.subplots(1, 2, figsize=(11, 7.4), constrained_layout=True)
    _bars(
        axes[0],
        metrics + db_rows + groups,
        "Tool-use checks passed (known defects count as not passed)",
    )
    _bars(axes[1], attacks, "Attacks noticed by a live control")
    fig.savefig(path, dpi=150, facecolor="white")
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", default="agentic-dev")
    parser.add_argument("--splits", default="dev,redteam")
    args = parser.parse_args()

    logging.getLogger("claimsense.hooks.audit").setLevel(logging.CRITICAL)
    report, runs = build_report(tuple(args.splits.split(",")))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = OUT_DIR / f"{args.label}.json"
    report_path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    with (OUT_DIR / f"{args.label}.traces.jsonl").open("w", encoding="utf-8") as fh:
        for run in runs:
            fh.write(json.dumps(_trace(run), default=str) + "\n")
    plot(report, OUT_DIR / f"{args.label}.png")

    for name, row in report["trajectory"].items():
        print(f"{name:20} {row['passed']}/{row['applicable']}")
    for name, row in report["db_state"].items():
        tag = f"  ({row['defect']})" if row["defect"] else ""
        print(f"db: {name:16} {row['passed']}/{row['applicable']}{tag}")
    for name, group in report["cases"].items():
        print(f"{name:20} {group['totals']}")
    print(f"open defects: {len(report['open_defects'])}")
    print(f"report: {report_path}")
    return 0 if is_clean(report) else 1


if __name__ == "__main__":
    raise SystemExit(main())
