"""python -m eval.security scoreboard|attack: see eval/security/__init__.py."""

from __future__ import annotations

import argparse
import json
import re
import sys

from eval.agent_suite.dataset import load_dataset
from eval.agent_suite.suite import preflight
from eval.harness.loader import REPO_ROOT

RUNS_DIR = REPO_ROOT / "runs" / "security"


def _label(text: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", text) or set(text) <= {"."}:
        raise argparse.ArgumentTypeError("use letters, digits, dot, dash and underscore only")
    return text


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m eval.security", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    sb = sub.add_parser("scoreboard", help="every defence against every attack (section 9)")
    sb.add_argument("--label", required=True, type=_label)
    sb.add_argument("--stub", action="store_true", help="force the free deterministic agents")
    at = sub.add_parser("attack", help="an attacker model that adapts (section 10; real only)")
    at.add_argument("--label", required=True, type=_label)
    at.add_argument("--claim", default="CLM-0004", help="the honest dev claim to attack")
    at.add_argument("--rounds", type=int, default=6)
    args = p.parse_args(argv)

    problem = preflight(getattr(args, "stub", False))
    if problem:
        print(problem.replace("eval.agent_suite", "eval.security"), file=sys.stderr)
        return 2
    from claimsense.agents.llm import stub_mode

    mode = "stub" if stub_mode() else "real"
    out = RUNS_DIR / args.label
    if out.exists():
        print(f"{out} already exists: use a new --label", file=sys.stderr)
        return 2
    out.mkdir(parents=True)

    if args.command == "scoreboard":
        from .scoreboard import scoreboard, to_markdown

        board = scoreboard(load_dataset(("dev", "redteam")), mode)
        table = to_markdown(board)
        (out / "scoreboard.md").write_text(f"mode: {mode}\n\n{table}\n", encoding="utf-8")
        (out / "scoreboard.json").write_text(json.dumps(board, indent=1), encoding="utf-8")
        print(f"## Scoreboard ({mode} mode)\n{table}\n\nwritten to {out}")
        return 0

    from .adaptive import attack

    case = next((c for c in load_dataset(("dev",)) if c.claim_id == args.claim), None)
    if case is None:
        print(f"unknown dev claim {args.claim}", file=sys.stderr)
        return 2
    try:
        rounds = attack(case, args.rounds, out / "attacker_notes.jsonl")
    except RuntimeError as e:
        print(e, file=sys.stderr)
        return 2
    for r in rounds:
        verdict = "WON" if r.won else ("flagged" if r.flagged else "held")
        print(f"round {r.n}: {verdict:<8} paid Rs {r.settlement_inr}, route {r.route}")
    won = any(r.won for r in rounds)
    print(f"\nattacker {'WON: add its note to the red-team seeds' if won else 'did not win'}")
    print(f"notes in {out / 'attacker_notes.jsonl'}")
    return 1 if won else 0


if __name__ == "__main__":
    sys.exit(main())
