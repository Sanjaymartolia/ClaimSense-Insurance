"""Recall@k and MRR for each search stage and kind of query, with a chart in runs/ (L5-L6).

Run from the repository root: ``python -m claimsense.retrieval.evaluate --label <name>``.
The chart needs matplotlib: ``pip install -e ".[retrieval,docs]"``.
"""

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from claimsense.retrieval.index import DEFAULT_INDEX_DIR, REPO_ROOT, open_retriever
from claimsense.retrieval.search import RERANK_POOL, HybridRetriever

DEFAULT_QUERIES = REPO_ROOT / "eval/golden_dev/retrieval_queries.jsonl"
K = 5
# bill_line_other terms are never used to write the rewrite glossary, so overfitting shows there.
KINDS = ("question", "bill_line_dev", "bill_line_other")

# Each stage returns clause IDs, best first, so a split clause counts once.
STAGES = {
    "Dense": lambda retriever, query: retriever.clause_ids(retriever.dense(query)),
    "BM25": lambda retriever, query: retriever.clause_ids(retriever.lexical(query)),
    "RRF": lambda retriever, query: retriever.clause_ids(retriever.fused(query)),
    "RRF + reranker": lambda retriever, query: [
        hit.clause_id for hit in retriever.search(query, k=RERANK_POOL)
    ],
}


def load_queries(path: Path = DEFAULT_QUERIES) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def first_hit_rank(expected: Sequence[str], ranked: Sequence[str]) -> int | None:
    """1-based rank of the first listed clause. Any listed clause answers the query."""
    return next((i for i, clause in enumerate(ranked, start=1) if clause in expected), None)


def recall_at_k(ranks: Sequence[int | None], k: int = K) -> float:
    return sum(rank is not None and rank <= k for rank in ranks) / len(ranks)


def mean_reciprocal_rank(ranks: Sequence[int | None]) -> float:
    return sum(1 / rank for rank in ranks if rank is not None) / len(ranks)


def rank_by_stage(
    retriever: HybridRetriever, queries: Sequence[dict[str, Any]]
) -> dict[str, list[int | None]]:
    return {
        stage: [first_hit_rank(q["clauses"], run(retriever, q["query"])) for q in queries]
        for stage, run in STAGES.items()
    }


def summarise(
    ranks: dict[str, list[int | None]], queries: Sequence[dict[str, Any]]
) -> dict[str, dict[str, dict[str, float]]]:
    """Scores per stage, for each kind of query and for the whole set ("all")."""
    groups: dict[str, list[int]] = {"all": list(range(len(queries)))}
    for i, query in enumerate(queries):
        groups.setdefault(query["kind"], []).append(i)
    return {
        kind: {
            stage: {
                "recall": recall_at_k([stage_ranks[i] for i in indices]),
                "mrr": mean_reciprocal_rank([stage_ranks[i] for i in indices]),
            }
            for stage, stage_ranks in ranks.items()
        }
        for kind, indices in groups.items()
    }


def plot_stages(
    ranks: dict[str, list[int | None]], queries: Sequence[dict[str, Any]], out: Path
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    summary = summarise(ranks, queries)
    kinds = [kind for kind in summary if kind != "all"]
    stages = list(ranks)
    metrics = (("recall", f"Recall@{K}"), ("mrr", "MRR"))
    fig, axes = plt.subplots(
        len(metrics),
        len(kinds),
        figsize=(0.8 + 3.7 * len(kinds), 5.8),
        dpi=160,
        sharey=True,
        squeeze=False,
        facecolor="#fcfcfb",
    )
    for row, (metric, metric_name) in enumerate(metrics):
        for column, kind in enumerate(kinds):
            ax = axes[row][column]
            ax.set_facecolor("#fcfcfb")
            values = [summary[kind][stage][metric] for stage in stages]
            bars = ax.bar(range(len(stages)), values, 0.62, color="#2a78d6")
            for bar, value in zip(bars, values, strict=True):
                ax.annotate(
                    f"{value:.2f}",
                    (bar.get_x() + bar.get_width() / 2, value),
                    xytext=(0, 3),
                    textcoords="offset points",
                    ha="center",
                    fontsize=8,
                    color="#0b0b0b",
                )
            labels = [stage.replace(" + ", " +\n") for stage in stages]
            ax.set_xticks(range(len(stages)), labels, color="#52514e", fontsize=7.5)
            ax.set_ylim(0, 1.15)
            ax.set_yticks([0, 0.25, 0.5, 0.75, 1])
            ax.tick_params(axis="y", labelcolor="#52514e", labelsize=8)
            ax.tick_params(length=0)
            ax.grid(axis="y", color="#e6e5e0", linewidth=0.8)
            ax.set_axisbelow(True)
            for spine in ("top", "right", "left"):
                ax.spines[spine].set_visible(False)
            ax.spines["bottom"].set_color("#b5b4ad")
            if row == 0:
                count = sum(query["kind"] == kind for query in queries)
                ax.set_title(f"{kind} ({count})", loc="left", fontsize=10, color="#0b0b0b")
            if column == 0:
                ax.set_ylabel(metric_name, color="#52514e", fontsize=9)
    fig.suptitle(
        "Search quality by stage and kind of query (draft labels)",
        x=0.012,
        ha="left",
        fontsize=11,
        color="#0b0b0b",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--label", required=True, help="names the chart: runs/retrieval_<label>.png"
    )
    parser.add_argument("--queries", type=Path, default=DEFAULT_QUERIES)
    parser.add_argument("--index-dir", type=Path, default=DEFAULT_INDEX_DIR)
    args = parser.parse_args()

    queries = load_queries(args.queries)
    ranks = rank_by_stage(open_retriever(index_dir=args.index_dir), queries)

    print(f"{'query':<7}{'kind':<17}" + "".join(f"{stage:>16}" for stage in ranks) + "  term")
    for i, query in enumerate(queries):
        row = "".join(f"{str(ranks[stage][i] or '-'):>16}" for stage in ranks)
        print(f"{query['qid']:<7}{query['kind']:<17}{row}  {query['query'][:48]}")
    print()
    for kind, scores in summarise(ranks, queries).items():
        for metric, name in (("recall", f"Recall@{K}"), ("mrr", "MRR")):
            row = "".join(f"{scores[stage][metric]:>16.3f}" for stage in ranks)
            print(f"{name:<9}{kind:<15}{row}")

    out = REPO_ROOT / "runs" / f"retrieval_{args.label}.png"
    plot_stages(ranks, queries, out)
    print(f"Chart: {out.relative_to(REPO_ROOT).as_posix()}")


if __name__ == "__main__":
    main()
