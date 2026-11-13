"""Build the judge calibration set from real agent output, then score the judge against it.

    python -m eval.calibration.collect collect [--n 24] [--splits dev,redteam] [--real-retrieval]
    #   two people label every row independently (rater_a, rater_b: 1 supported, 0 not)
    python -m eval.calibration.collect sheets                      # one CSV per rater, for Excel
    python -m eval.calibration.collect import --a sheet_rater_a.csv --b sheet_rater_b.csv
    python -m eval.calibration.collect score

`collect` runs the real coverage agent (needs OPENROUTER_API_KEY, costs a little) and writes
`calibration_set.jsonl` with unlabelled rows. Each row holds the model's one-sentence reason for one
bill line and exactly the context the judge sees for it: the clause wording the agent was shown,
plus the claim's facts (`attach_clause_contexts`). Rows are picked round-robin across claims so no
claim dominates. Synthetic claims only; the file stays local until the labels are done.

`score` runs the same RAGAS faithfulness judge on every labelled row and prints Cohen's kappa
between the raters and between the judge and the raters (`judge_calibration.report`).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .judge_calibration import (
    CALIBRATION_SET,
    inter_rater_reliability,
    load_calibration_set,
    report,
)

RATERS = ("rater_a", "rater_b")
SCORES_FILE = CALIBRATION_SET.with_name("judge_scores.json")
SHEET_COLUMNS = (
    "item_id",
    "claim_and_line",
    "model_explanation",
    "policy_text_shown",
    "claim_facts_shown",
    "label_1_or_0",
    "note",
)
SEPARATOR = "\n---\n"  # between texts in one spreadsheet cell


def candidates(outputs: Iterable[Any]) -> list[list[dict[str, Any]]]:
    """Per claim, the lines that carry a real model reason and a context to judge it against."""
    from eval.harness.llm_judge_metrics import is_placeholder

    per_claim = []
    for out in outputs:
        lines = [
            {
                "claim_id": out.claim_id,
                "line_id": line_id,
                "rationale": rationale,
                "contexts": list(out.retrieved_contexts.get(line_id) or []),
            }
            for line_id, rationale in sorted(out.rationales.items())
            if rationale.strip()
            and not is_placeholder(rationale)
            and out.retrieved_contexts.get(line_id)
        ]
        if lines:
            per_claim.append(lines)
    return per_claim


def pick(per_claim: list[list[dict[str, Any]]], n: int) -> list[dict[str, Any]]:
    """Round-robin across claims, so 24 items come from many claims, not three long bills.

    Claim k starts at its line k (mod its length), so 24 claims do not all give their first line,
    and an explanation already chosen word for word (a red-team copy of a dev claim) is skipped.
    """
    rotated = []
    for k, lines in enumerate(per_claim):
        start = k % len(lines)
        rotated.append(lines[start:] + lines[:start])
    chosen: list[dict[str, Any]] = []
    seen: set[str] = set()
    depth = 0
    while len(chosen) < n and any(depth < len(lines) for lines in rotated):
        for lines in rotated:
            if depth < len(lines) and len(chosen) < n:
                key = " ".join(lines[depth]["rationale"].lower().split())
                if key not in seen:
                    seen.add(key)
                    chosen.append(lines[depth])
        depth += 1
    return [
        {"item_id": f"CAL-{i:03d}", **row, "labels": dict.fromkeys(RATERS)}
        for i, row in enumerate(chosen, 1)
    ]


def _real_outputs(splits: list[str], retrieval: str) -> list[Any]:
    from eval.harness.claimsense_adapter import ClaimSenseAdapter
    from eval.harness.llm_judge_metrics import attach_clause_contexts
    from eval.harness.loader import load_split

    adapter = ClaimSenseAdapter(calculator="real", retrieval=retrieval)
    cases = [case for split in splits for case in load_split(split)]
    outputs = []
    for i, case in enumerate(cases, 1):
        print(f"  [{i}/{len(cases)}] {case.claim_id}", flush=True)
        outputs.append(adapter.run(case.claim))
    attach_clause_contexts(outputs, cases)  # the claim's facts, as the judge gets them
    return outputs


def collect(args: argparse.Namespace) -> int:
    from claimsense.agents.llm import stub_mode

    out = Path(args.out)
    if out.exists():
        print(f"{out} exists. Labels may be in it: move it away first.", file=sys.stderr)
        return 2
    if stub_mode():
        print(
            "stub mode: the agents give no model reasons, so there is nothing to calibrate on. "
            "Load OPENROUTER_API_KEY and unset CLAIMSENSE_LLM.",
            file=sys.stderr,
        )
        return 2
    splits = [s.strip() for s in args.splits.split(",") if s.strip()]
    outputs = _real_outputs(splits, "real" if args.real_retrieval else "stub")
    rows = pick(candidates(outputs), args.n)
    if len(rows) < args.n:
        print(f"only {len(rows)} lines had a model reason; wanted {args.n}", file=sys.stderr)
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8")
    print(f"wrote {len(rows)} unlabelled items from {len({r['claim_id'] for r in rows})} claims")
    print(f"to {out}. Next: two people fill labels.rater_a and labels.rater_b (1 or 0).")
    return 0 if len(rows) >= 20 else 1


def score(args: argparse.Namespace) -> int:
    import asyncio

    from eval.harness.llm_judge_metrics import _build_scorer

    items = load_calibration_set(args.out)  # refuses unlabelled rows
    if not inter_rater_reliability(items)["passed"]:
        print(report(items))  # people disagree: do not pay for a judge run
        return 1
    lines = {
        row["item_id"]: row.get("line_id", "")
        for row in (json.loads(t) for t in Path(args.out).read_text("utf-8").splitlines() if t)
    }
    scorer, model = _build_scorer()

    async def run() -> dict[str, float]:
        scores = {}
        for item in items:
            result = await scorer.ascore(
                # the harness judge's own question (llm_judge_metrics._score_output)
                user_input=f"Is line {lines[item.item_id]} payable, and under which clause?",
                response=item.rationale,
                retrieved_contexts=item.contexts,
            )
            scores[item.item_id] = float(getattr(result, "value", result))
        return scores

    scores = asyncio.run(run())
    SCORES_FILE.write_text(json.dumps({"judge_model": model, "scores": scores}, indent=1), "utf-8")
    print(report(items, scores))
    return 0


def _rows(path: Path | str) -> list[dict[str, Any]]:
    return [json.loads(t) for t in Path(path).read_text("utf-8").splitlines() if t.strip()]


def sheet_row(row: dict[str, Any]) -> dict[str, str]:
    """One spreadsheet row: what the model said, beside exactly what it was shown."""
    facts_prefix = f"Claim {row['claim_id']} facts"
    facts = [c for c in row["contexts"] if c.startswith(facts_prefix)]
    policy = [c for c in row["contexts"] if not c.startswith(facts_prefix)]
    return {
        "item_id": row["item_id"],
        "claim_and_line": row.get("line_id", row["claim_id"]),
        "model_explanation": row["rationale"],
        "policy_text_shown": SEPARATOR.join(policy),
        "claim_facts_shown": SEPARATOR.join(facts),
        "label_1_or_0": "",
        "note": "",
    }


def read_sheet(path: Path | str) -> dict[str, int]:
    """item_id -> label from a filled sheet. Refuses a blank or anything other than 0 or 1."""
    labels: dict[str, int] = {}
    with Path(path).open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            value = (row.get("label_1_or_0") or "").strip()
            if value not in ("0", "1"):
                raise ValueError(f"{path}: {row['item_id']} has label {value!r}; use 1 or 0")
            labels[row["item_id"]] = int(value)
    return labels


def sheets(args: argparse.Namespace) -> int:
    rows = _rows(args.out)
    folder = Path(args.out).parent
    paths = [folder / f"sheet_{rater}.csv" for rater in RATERS]
    if any(p.exists() for p in paths):
        print("a rater sheet exists; move it away first (it may hold labels)", file=sys.stderr)
        return 2
    for path in paths:
        with path.open("w", encoding="utf-8-sig", newline="") as fh:  # utf-8-sig: Excel reads it
            writer = csv.DictWriter(fh, fieldnames=SHEET_COLUMNS)
            writer.writeheader()
            writer.writerows(sheet_row(r) for r in rows)
        print(f"wrote {path}")
    print("Give one sheet to each rater. Label independently; do not compare until both are done.")
    return 0


def import_labels(args: argparse.Namespace) -> int:
    rows = _rows(args.out)
    sheets_by_rater = {"rater_a": read_sheet(args.a), "rater_b": read_sheet(args.b)}
    ids = {r["item_id"] for r in rows}
    for rater, labels in sheets_by_rater.items():
        if set(labels) != ids:
            missing, extra = sorted(ids - set(labels)), sorted(set(labels) - ids)
            print(f"{rater}: missing {missing}, unknown {extra}", file=sys.stderr)
            return 2
    for r in rows:
        r["labels"] = {rater: labels[r["item_id"]] for rater, labels in sheets_by_rater.items()}
    text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    Path(args.out).write_text(text, "utf-8")
    print(f"imported labels for {len(rows)} items into {args.out}. Next: ... collect score")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    c = sub.add_parser("collect", help="run the real agents, write unlabelled items")
    c.add_argument("--n", type=int, default=24, help="items to write (20 are required)")
    c.add_argument("--splits", default="dev,redteam")
    c.add_argument("--real-retrieval", action="store_true", help="hybrid retriever, as RAGAS uses")
    c.add_argument("--out", default=str(CALIBRATION_SET))
    s = sub.add_parser("score", help="judge the labelled items and report Cohen's kappa")
    s.add_argument("--out", default=str(CALIBRATION_SET))
    sh = sub.add_parser("sheets", help="write one CSV per rater, for Excel")
    sh.add_argument("--out", default=str(CALIBRATION_SET))
    im = sub.add_parser("import", help="copy both raters' labels into the set")
    im.add_argument("--a", required=True, help="rater A's filled sheet")
    im.add_argument("--b", required=True, help="rater B's filled sheet")
    im.add_argument("--out", default=str(CALIBRATION_SET))
    args = p.parse_args(argv)
    commands = {"collect": collect, "score": score, "sheets": sheets, "import": import_labels}
    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
