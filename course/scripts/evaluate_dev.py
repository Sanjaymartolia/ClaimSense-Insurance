"""Score yourself on the 20 dev claims. Run it after every change.

    python scripts/evaluate_dev.py --label baseline            # run the agent, score, plot
    python scripts/evaluate_dev.py --label todo4 --redteam     # + the 30 red-team claims
    python scripts/evaluate_dev.py --retrieval-only --label dense   # search only, no LLM, free

Every run appends to runs/log.csv and redraws runs/log.png (one bar per label), and
draws runs/<label>.png (score per category). Rule: show the plot before you claim a
result. 20 claims is a thermometer, not an exam: one claim moves the score by 5.
"""

import argparse
import csv
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # this folder's package

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from claimsense_hw import config, kb, trace  # noqa: E402
from evalkit import metrics  # noqa: E402


def plot_bars(values, title, path):
    fig, ax = plt.subplots(figsize=(7, 0.4 * len(values) + 1.2))
    ax.barh(list(values), list(values.values()), color="#4C72B0")
    for i, v in enumerate(values.values()):
        ax.text(v, i, f" {v:.2f}", va="center")
    ax.set_title(title)
    ax.set_xlim(0, max([*values.values(), 1]) * 1.15)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    print(f"plot -> {path}")


def log_and_plot(label, kind, value, extra=""):
    config.RUNS_DIR.mkdir(exist_ok=True)
    log = config.RUNS_DIR / "log.csv"
    with log.open("a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([label, kind, value, extra])
    rows = list(csv.reader(log.open(encoding="utf-8")))
    latest = {f"{r[0]} ({r[1]})": float(r[2]) for r in rows}  # last run of each label wins
    plot_bars(latest, "all runs (runs/log.csv)", config.RUNS_DIR / "log.png")


def retrieval_only(label):
    """Recall@k: share of the expected clauses that search returned. No LLM, no cost."""
    from claimsense_hw.retrieval import get_retriever

    r = get_retriever()
    found = total = 0
    for q in trace.read_jsonl(config.RETRIEVAL_GOLD):
        got = {h.doc_id for h in r.search(q["query"])}
        found += len(set(q["clauses"]) & got)
        total += len(q["clauses"])
    recall = found / total
    print(
        f"recall@{r.top_k} mode={r.mode} chunks={config.CHUNK_STRATEGY}: "
        f"{found}/{total} = {recall:.3f}"
    )
    log_and_plot(label, "recall", round(recall, 3))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="run", help="name this run in the log and plots")
    ap.add_argument(
        "--redteam", action="store_true", help="add the 30 red-team claims (eval/redteam)"
    )
    ap.add_argument("--retrieval-only", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--show", type=int, default=8)
    a = ap.parse_args()
    if a.retrieval_only:
        return retrieval_only(a.label)

    from claimsense_hw.agent import ClaimAgent

    claims = {c["claim_id"]: c for c in trace.read_jsonl(config.DEV_CLAIMS)}
    golds = {g["claim_id"]: g for g in trace.read_jsonl(config.DEV_GOLD)}
    for cid, g in golds.items():  # the category is for the scorer only, never the agent
        g["category"] = claims[cid]["scenario_label"]
    cases = [(claims[cid], golds[cid]) for cid in claims]
    if a.redteam:  # 30 attacked claims; gold already carries its category
        rt_claims = {c["claim_id"]: c for c in trace.read_jsonl(config.REDTEAM_CLAIMS)}
        cases += [(rt_claims[g["claim_id"]], g) for g in trace.read_jsonl(config.REDTEAM_GOLD)]

    agent = ClaimAgent()
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        preds = list(pool.map(lambda c: agent.resolve(c[0]), cases))
    config.RUNS_DIR.mkdir(exist_ok=True)
    trace.write_jsonl(config.RUNS_DIR / f"{a.label}.jsonl", preds)

    policy_ids = {r["clause_id"] for r in kb.load_records() if r["record_type"] == "policy_clause"}
    report = metrics.score_all(preds, [g for _, g in cases], policy_ids)
    print(metrics.format_report(report, a.show))
    tokens = sum(p["meta"].get("tokens", 0) for p in preds)
    cost = sum(p["meta"].get("cost_usd", 0) for p in preds)
    secs = sum(p["meta"].get("latency_s", 0) for p in preds)
    print(f"\ncost: {tokens} tokens, ${cost:.4f}, {secs:.0f}s total")
    (config.RUNS_DIR / f"{a.label}.report.json").write_text(json.dumps(report, indent=1))
    plot_bars(
        report["per_category"], f"{a.label}: score per category", config.RUNS_DIR / f"{a.label}.png"
    )
    log_and_plot(a.label, "score", report["score"], f"{tokens} tokens ${cost:.4f}")


if __name__ == "__main__":
    main()
