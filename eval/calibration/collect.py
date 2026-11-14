"""Build the judge calibration set from real agent output, then score the judge against it.

    python -m eval.calibration.collect collect [--n 24] [--splits dev,redteam] [--real-retrieval]
                                               [--out SET] [--exclude EARLIER_SET]
    #   two people label every row independently (rater_a, rater_b: 1 supported, 0 not)
    python -m eval.calibration.collect sheets                      # one CSV per rater, for Excel
    python -m eval.calibration.collect import --a sheet_rater_a.csv --b sheet_rater_b.csv
    python -m eval.calibration.collect score [--judge ragas|rubric]

`collect` runs the real coverage agent (needs OPENROUTER_API_KEY, costs a little) and writes
`calibration_set.jsonl` with unlabelled rows. Each row holds the model's one-sentence reason for one
bill line and exactly the context the judge sees for it: the clause wording the agent was shown,
plus the claim's facts (`attach_clause_contexts`). Rows are picked round-robin across claims so no
claim dominates. Synthetic claims only; the file stays local until the labels are done. A later
round goes in its own folder, with `--exclude` naming the earlier set: its explanations are
skipped, and the item ids continue after its ids.

`score` runs a judge on every labelled row and prints Cohen's kappa between the raters and between
the judge and the raters (`judge_calibration.report`). `--judge ragas` (the default) is the
harness's RAGAS faithfulness judge; `--judge rubric` is the judge with the raters' written rule
(`rubric_judge`). The scores go beside the set, one file per judge (`scores_path`), with the
freeze hash when the judge passes.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .judge_calibration import (
    CALIBRATION_SET,
    CalibrationItem,
    freeze,
    inter_rater_reliability,
    judge_agreement,
    load_calibration_set,
    report,
)
from .rubric_judge import judge_item, prompt_path, split_contexts

RATERS = ("rater_a", "rater_b")
JUDGES = ("ragas", "rubric")
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


def scores_path(calibration_set: Path | str, judge: str) -> Path:
    """Beside its set, one file per judge, so no run overwrites another set's or judge's scores.
    RAGAS keeps the name of the first file, `judge_scores.json`."""
    name = "judge_scores.json" if judge == "ragas" else f"judge_scores_{judge}.json"
    return Path(calibration_set).with_name(name)


def explanation_key(text: str) -> str:
    """Two explanations are one item when they match word for word, whatever the case or spacing."""
    return " ".join(text.lower().split())


def excluded(path: Path | str) -> tuple[set[str], int]:
    """An earlier set's explanations, to skip, and the first item number after its ids."""
    rows = _rows(path)
    numbers = [int(m.group()) for r in rows if (m := re.search(r"\d+$", str(r["item_id"])))]
    return {explanation_key(r["rationale"]) for r in rows}, max(numbers, default=0) + 1


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


def pick(
    per_claim: list[list[dict[str, Any]]],
    n: int,
    seen: set[str] | None = None,
    first: int = 1,
) -> list[dict[str, Any]]:
    """Round-robin across claims, so 24 items come from many claims, not three long bills.

    Claim k starts at its line k (mod its length), so 24 claims do not all give their first line,
    and an explanation already chosen word for word (a red-team copy of a dev claim) is skipped,
    as is one in `seen` (an earlier set's). Item numbers start at `first`.
    """
    rotated = []
    for k, lines in enumerate(per_claim):
        start = k % len(lines)
        rotated.append(lines[start:] + lines[:start])
    chosen: list[dict[str, Any]] = []
    taken = set(seen or ())
    depth = 0
    while len(chosen) < n and any(depth < len(lines) for lines in rotated):
        for lines in rotated:
            if depth < len(lines) and len(chosen) < n:
                key = explanation_key(lines[depth]["rationale"])
                if key not in taken:
                    taken.add(key)
                    chosen.append(lines[depth])
        depth += 1
    return [
        {"item_id": f"CAL-{i:03d}", **row, "labels": dict.fromkeys(RATERS)}
        for i, row in enumerate(chosen, first)
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
    seen: set[str] = set()
    first = 1
    if args.exclude:
        if not Path(args.exclude).exists():  # checked before the paid run
            print(f"{args.exclude} does not exist; nothing was run", file=sys.stderr)
            return 2
        seen, first = excluded(args.exclude)
    splits = [s.strip() for s in args.splits.split(",") if s.strip()]
    outputs = _real_outputs(splits, "real" if args.real_retrieval else "stub")
    rows = pick(candidates(outputs), args.n, seen=seen, first=first)
    if len(rows) < args.n:
        print(f"only {len(rows)} new lines had a model reason; wanted {args.n}", file=sys.stderr)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8")
    print(f"wrote {len(rows)} unlabelled items from {len({r['claim_id'] for r in rows})} claims")
    print(f"to {out}. Next: two people fill labels.rater_a and labels.rater_b (1 or 0).")
    return 0 if len(rows) >= 20 else 1


def score(args: argparse.Namespace) -> int:
    items = load_calibration_set(args.out)  # refuses unlabelled rows
    if not inter_rater_reliability(items)["passed"]:
        print(report(items))  # people disagree: do not pay for a judge run
        return 1
    rows = {r["item_id"]: r for r in _rows(args.out)}
    checks: dict[str, dict[str, bool]] | None = None
    rubric_file: Path | None = None
    if args.judge == "rubric":
        rubric_file = prompt_path()
        model, scores, checks = _rubric_scores(items, rows, rubric_file)
    else:
        model, scores = _ragas_scores(items, rows)
    result: dict[str, Any] = {"judge": args.judge, "judge_model": model, "scores": scores}
    if checks is not None:
        result["checks"] = checks  # true/false per check; the judge's reasoning is never saved
    if judge_agreement(items, scores)["passed"]:
        result["freeze"] = freeze(items, model, rubric_file)
    path = scores_path(args.out, args.judge)
    path.write_text(json.dumps(result, indent=1), "utf-8")
    print(report(items, scores))
    if "freeze" in result:
        print(f"  frozen as {result['freeze']['frozen_hash']}: record it in the report")
    print(f"  scores written to {path}")
    return 0


def _ragas_scores(
    items: list[CalibrationItem], rows: dict[str, dict[str, Any]]
) -> tuple[str, dict[str, float]]:
    import asyncio

    from eval.harness.llm_judge_metrics import _build_scorer

    scorer, model = _build_scorer()

    async def run() -> dict[str, float]:
        scores = {}
        for item in items:
            line = rows[item.item_id].get("line_id", "")
            result = await scorer.ascore(
                # the harness judge's own question (llm_judge_metrics._score_output)
                user_input=f"Is line {line} payable, and under which clause?",
                response=item.rationale,
                retrieved_contexts=item.contexts,
            )
            scores[item.item_id] = float(getattr(result, "value", result))
        return scores

    return model, asyncio.run(run())


def _rubric_scores(
    items: list[CalibrationItem], rows: dict[str, dict[str, Any]], rubric_file: Path
) -> tuple[str, dict[str, float], dict[str, dict[str, bool]]]:
    from claimsense.config import model_for

    rubric = rubric_file.read_text("utf-8")
    scores: dict[str, float] = {}
    checks: dict[str, dict[str, bool]] = {}
    for item in items:
        row = rows[item.item_id]
        policy, facts = split_contexts(row["claim_id"], item.contexts)
        scores[item.item_id], checks[item.item_id] = judge_item(
            rubric, row.get("line_id", ""), item.rationale, policy, facts
        )
        failed = [name for name, ok in checks[item.item_id].items() if not ok]
        verdict = f"not supported ({', '.join(failed)})" if failed else "supported"
        print(f"  {item.item_id}: {verdict}", flush=True)  # ids and check names only (rule 4)
    return model_for("judge"), scores, checks


def _rows(path: Path | str) -> list[dict[str, Any]]:
    return [json.loads(t) for t in Path(path).read_text("utf-8").splitlines() if t.strip()]


def sheet_row(row: dict[str, Any]) -> dict[str, str]:
    """One spreadsheet row: what the model said, beside exactly what it was shown."""
    policy, facts = split_contexts(row["claim_id"], row["contexts"])
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
    c.add_argument(
        "--exclude", help="an earlier set: skip its explanations, number new items after its ids"
    )
    s = sub.add_parser("score", help="judge the labelled items and report Cohen's kappa")
    s.add_argument("--out", default=str(CALIBRATION_SET))
    s.add_argument(
        "--judge",
        choices=JUDGES,
        default="ragas",
        help="ragas: the harness judge; rubric: the raters' rule in config/prompts/judge.md",
    )
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
