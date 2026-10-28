"""Score a traces file against a gold file — for the held-out run (Eval & Red-Team only).

    python scripts/run_batch.py   --in ../../../claimsense-heldout/claims.jsonl --out heldout.jsonl
    python scripts/score_traces.py --traces heldout.jsonl \
        --gold ../../../claimsense-heldout/gold_worksheets.jsonl \
        --claims ../../../claimsense-heldout/claims.jsonl --label heldout_v1

A person runs this, once, with everything frozen. Never paste its rows into a prompt.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from claimsense_hw import config, kb, trace  # noqa: E402
from evalkit import metrics  # noqa: E402
from evaluate_dev import log_and_plot, plot_bars  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--traces", required=True)
ap.add_argument("--gold", required=True)
ap.add_argument("--claims", help="optional: gives each claim its category for the plot")
ap.add_argument("--label", default="scored")
a = ap.parse_args()

golds = trace.read_jsonl(a.gold)
labels = (
    {c["claim_id"]: c.get("scenario_label", "") for c in trace.read_jsonl(a.claims)}
    if a.claims
    else {}
)
for g in golds:
    g.setdefault("category", labels.get(g["claim_id"], "all"))
policy_ids = {r["clause_id"] for r in kb.load_records() if r["record_type"] == "policy_clause"}
report = metrics.score_all(trace.read_jsonl(a.traces), golds, policy_ids)
print(metrics.format_report(report))
config.RUNS_DIR.mkdir(exist_ok=True)
plot_bars(
    report["per_category"], f"{a.label}: score per category", config.RUNS_DIR / f"{a.label}.png"
)
log_and_plot(a.label, "score", report["score"])
