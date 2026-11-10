"""Print the framework rubric scorecard in the terminal.

    python -m eval.tools.rubric_score                 # the scorecard and the total
    python -m eval.tools.rubric_score --plan          # also what would move the score
    python -m eval.tools.rubric_score --insurance     # also the regulated-domain weighting
    python -m eval.tools.rubric_score --json          # machine-readable

The scores are **read from `docs/FRAMEWORK_RUBRIC_SCORE.md`**, never stored here. That is
deliberate. A copy of the scores in Python would drift from the report the first time somebody
edited one and not the other, and then two commands would disagree about the same project. Defect
RET-03 in `docs/CLAIMS_AND_GOLD_SET_FIXES.md` records what that costs. The report is the source of
truth; this file is a reader.

The arithmetic is recomputed here from the parsed scores and weights. It is not taken from the
report's total. So if the report's own sum were ever wrong, this command would disagree with it,
and `eval/tests/test_rubric_report.py` would fail. Two independent checks on the same number.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORT = REPO_ROOT / "docs" / "FRAMEWORK_RUBRIC_SCORE.md"

#: The book's weights, Table 3.2. Used only to warn if the report has drifted from them.
BOOK_WEIGHTS = {
    "D1": 15,
    "D2": 10,
    "D3": 15,
    "D4": 15,
    "D5": 5,
    "D6": 10,
    "D7": 15,
    "D8": 10,
    "D9": 5,
}

#: One way to follow the book's "up-weight D3 and D7 for a regulated unit" tip, keeping the sum
#: at 100. Shown by `--insurance`; it is not the headline score.
INSURANCE_WEIGHTS = {**BOOK_WEIGHTS, "D3": 20, "D7": 20, "D1": 10, "D4": 10}


def section(text: str, number: int) -> str:
    """One top-level section, `## <number>. ...` up to the next `## `."""
    match = re.search(rf"^## {number}\. .*?(?=^## |\Z)", text, re.M | re.S)
    if not match:
        raise ValueError(f"section {number} not found in {REPORT.name}")
    return match.group(0)


def parse_scorecard(text: str) -> list[dict]:
    """Rows of Section 3: dimension id, name, weight, score, weighted, reason.

    Scoped to Section 3 because the weight-comparison table in Section 6 has the same shape.
    """
    pattern = re.compile(
        r"^\|\s*(D\d)\s+([^|]+?)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*([^|]*?)\s*\|",
        re.M,
    )
    rows = [
        {
            "dim": m.group(1),
            "name": m.group(2).strip(),
            "weight": int(m.group(3)),
            "score": int(m.group(4)),
            "weighted": int(m.group(5)),
            "reason": m.group(6).strip(),
        }
        for m in pattern.finditer(section(text, 3))
    ]
    if len(rows) != 9:
        raise ValueError(f"expected 9 scorecard rows, parsed {len(rows)}")
    return rows


def parse_plan(text: str) -> list[tuple[str, str, float]]:
    """Rows of the Section 7 table: (work, dimensions it moves, gain)."""
    out: list[tuple[str, str, float]] = []
    for line in section(text, 7).splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3:
            continue
        gain = re.search(r"\+(\d\.\d\d)", cells[2])
        if gain:
            out.append((_plain(cells[0]), _plain(cells[1]), float(gain.group(1))))
    return out


#: Characters the report uses that a cp1252 Windows console cannot print. Replaced rather than
#: escaped, because `python -m eval.tools.rubric_score` must not crash on the default terminal.
NON_ASCII = {"→": "->", "—": "--", "–": "-", "‘": "'", "’": "'", "“": '"', "”": '"'}


def _plain(cell: str) -> str:
    """Strip Markdown emphasis, and make the text safe for a cp1252 console.

    The report is UTF-8 and uses an arrow in "D4 2->4". Printing that raw raises
    UnicodeEncodeError on a default Windows terminal, so the tool would crash on the very
    platform this project is developed on.
    """
    text = cell.replace("**", "").replace("`", "")
    for bad, good in NON_ASCII.items():
        text = text.replace(bad, good)
    return text.encode("ascii", "replace").decode("ascii")


def bar(score: int, width: int = 5) -> str:
    return "#" * score + "." * (width - score)


def render(rows: list[dict], plan: list, *, show_plan: bool, show_insurance: bool) -> str:
    total = sum(r["weighted"] for r in rows)
    lines = [
        "",
        "  ClaimSense - framework rubric (Table 3.2, book weights)",
        "",
        f"  {'dim':<4}{'dimension':<26}{'wt':>4}{'score':>7}  {'':<6}{'weighted':>9}",
        f"  {'-' * 4}{'-' * 26}{'-' * 4}{'-' * 7}  {'-' * 6}{'-' * 9}",
    ]
    for r in rows:
        lines.append(
            f"  {r['dim']:<4}{r['name'][:25]:<26}{r['weight']:>4}{r['score']:>5}/5  "
            f"{bar(r['score']):<6}{r['weighted']:>9}"
        )
    lines += [
        f"  {'-' * 4}{'-' * 26}{'-' * 4}{'-' * 7}  {'-' * 6}{'-' * 9}",
        f"  {'':<4}{'TOTAL':<26}{sum(r['weight'] for r in rows):>4}{'':>7}  {'':<6}{total:>9}",
        "",
        f"  SCORE: {total / 100:.2f} out of 5",
        "",
    ]

    drift = [r["dim"] for r in rows if r["weight"] != BOOK_WEIGHTS[r["dim"]]]
    if drift:
        lines += [f"  WARNING: weights differ from the book's for {', '.join(drift)}", ""]

    if show_insurance:
        adjusted = sum(r["score"] * INSURANCE_WEIGHTS[r["dim"]] for r in rows) / 100
        lines += [
            "  Regulated-domain weighting (the book's tip: up-weight D3 and D7)",
            "    D3 and D7 -> 20 each, D1 and D4 -> 10 each, sum still 100",
            f"    score: {adjusted:.2f}  "
            f"({adjusted - total / 100:+.2f} against the book's weights)",
            "    It is lower because compliance and safety hold the most unconnected work.",
            "",
        ]

    if show_plan and plan:
        lines += ["  What would move the score", ""]
        for work, dims, gain in plan:
            lines.append(f"    +{gain:.2f}  {work[:58]:<58}  {dims}")
        connection = sum(g for _, _, g in sorted(plan, key=lambda t: -t[2])[:4])
        lines += [
            "",
            f"    Connecting what is already written: +{connection:.2f} "
            f"-> {total / 100 + connection:.2f}",
            "",
        ]

    lines += [f"  Full evidence for every score: docs/{REPORT.name}", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m eval.tools.rubric_score",
        description="Print the ClaimSense framework rubric scorecard.",
        epilog="Scores are read from docs/FRAMEWORK_RUBRIC_SCORE.md, which is the source of truth.",
    )
    parser.add_argument("--plan", action="store_true", help="also show what would move the score")
    parser.add_argument(
        "--insurance", action="store_true", help="also show the regulated-domain weighting"
    )
    parser.add_argument("--json", action="store_true", help="print JSON instead of a table")
    args = parser.parse_args(argv)

    if not REPORT.exists():
        print(f"{REPORT} not found", file=sys.stderr)
        return 1
    text = REPORT.read_text(encoding="utf-8")
    rows = parse_scorecard(text)
    plan = parse_plan(text)
    total = sum(r["weighted"] for r in rows)

    if args.json:
        print(
            json.dumps(
                {
                    "score": round(total / 100, 2),
                    "weighted_sum": total,
                    "weights_sum": sum(r["weight"] for r in rows),
                    "dimensions": rows,
                    "improvements": [{"work": w, "dimensions": d, "gain": g} for w, d, g in plan],
                    "source": str(REPORT.relative_to(REPO_ROOT)).replace("\\", "/"),
                },
                indent=2,
            )
        )
    else:
        print(render(rows, plan, show_plan=args.plan, show_insurance=args.insurance))
    return 0


if __name__ == "__main__":
    sys.exit(main())
