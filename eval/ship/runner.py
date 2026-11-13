"""Every evaluation in one command, one verdict: is this commit safe to ship?

    python -m eval.ship --label ss-1113            # real models: the ship decision (costs money)
    python -m eval.ship --label ss-1113 --stub     # free rehearsal: same stages, stub agents

Each stage is an existing tool, run as its own process with its own gates; nothing is rescored
here. Every stage's output is saved to `runs/ship/<label>/logs/<stage>.log`, and its own results
stay where that tool always writes them (`runs/full/`, `runs/agentic/`, `runs/security/`, ...).

Blocking stages decide the verdict. Report-only stages are run and linked, but cannot block:
the RAGAS judge is uncalibrated (weight 0.00 in the scorecard), and the security scoreboard and
retrieval evaluation report numbers without a pass mark.

Verdict and exit code:
    0  SHIP                every blocking stage ran and passed, real mode
    0  REHEARSAL PASSED    the same, in stub mode: not a ship decision (models were not called)
    1  DO NOT SHIP         a blocking stage failed
    2  NOT VERIFIED        a blocking stage could not run (missing package, index, key)
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = REPO_ROOT / "runs" / "ship"
PY = sys.executable

PASSED, FAILED, SKIPPED, ERROR = "passed", "failed", "skipped", "could not run"
SHIP, REHEARSAL, NO_SHIP, NOT_VERIFIED = "SHIP", "REHEARSAL PASSED", "DO NOT SHIP", "NOT VERIFIED"


@dataclass(frozen=True)
class Stage:
    name: str
    what: str
    blocking: bool
    cmd: tuple[str, ...]
    needs: tuple[str, ...] = ()  # importable packages
    needs_paths: tuple[str, ...] = ()  # repo paths that must exist
    real_only: bool = False  # needs a real model (skipped in stub mode)
    opt_in: bool = False  # runs only when asked for (--attack)
    offline: bool = False  # always stub, even in a real run (CI runs these with no key)
    env: tuple[tuple[str, str], ...] = ()
    error_codes: tuple[int, ...] = (2,)  # exit codes meaning "could not run", not "failed"
    outputs: str = ""


@dataclass
class Result:
    name: str
    what: str
    blocking: bool
    status: str
    exit_code: int | None
    seconds: float
    log: str
    note: str = ""
    outputs: str = ""
    cmd: list[str] = field(default_factory=list)


def stages(label: str, stub: bool, workers: int, judge_limit: int, variant: str) -> list[Stage]:
    stub_flag = ("--stub",) if stub else ()
    deepeval_env = (("DEEPEVAL_DISABLE_DOTENV", "1"), ("DEEPEVAL_TELEMETRY_OPT_OUT", "1"))
    return [
        Stage("tests", "Product tests (CI)", True, (PY, "-m", "pytest", "-q"), offline=True),
        Stage("lint", "ruff check (CI)", True, (PY, "-m", "ruff", "check", "."), needs=("ruff",)),
        Stage(
            "format",
            "ruff format --check (CI)",
            True,
            (PY, "-m", "ruff", "format", "--check", "."),
            needs=("ruff",),
        ),
        Stage(
            "tool-pins",
            "Tools unchanged since review",
            True,
            (PY, "-m", "claimsense.hooks.pins"),
        ),
        Stage(
            "release-gate",
            "Harness self-check + dev and red-team claims + agent suite + combined gate",
            True,
            (
                PY,
                "-X",
                "utf8",
                "-m",
                "eval.full",
                "--label",
                f"{label}-full",
                "--splits",
                "dev,redteam",
                "--variant",
                variant,
                "--workers",
                str(workers),
                "--quiet",
                *stub_flag,
            ),
            outputs=f"runs/full/{label}-full/",
        ),
        Stage(
            "tool-use",
            "Tool calls, tools, hooks, guardrails (offline)",
            True,
            (PY, "-X", "utf8", "-m", "eval.agentic.run", "--label", f"{label}-agentic"),
            needs=("matplotlib",),
            outputs=f"runs/agentic/{label}-agentic.*",
        ),
        Stage(
            "deepeval",
            "DeepEval trajectory tests (code checks, no judge)",
            True,
            (PY, "-X", "utf8", "-m", "pytest", "eval/deepeval_suite", "-q", "-p", "no:warnings"),
            needs=("deepeval",),
            env=deepeval_env,
            error_codes=(2, 3, 4),  # pytest: interrupted, internal error, usage error
        ),
        Stage(
            "deepeval-judge",
            "DeepEval payload judge, GEval + faithfulness (report only; uncalibrated)",
            False,
            (
                PY,
                "-X",
                "utf8",
                "-m",
                "pytest",
                "eval/deepeval_suite/test_payload_quality.py",
                "-q",
                "-p",
                "no:warnings",
            ),
            needs=("deepeval",),
            env=(*deepeval_env, ("CLAIMSENSE_DEEPEVAL_JUDGE", "1")),
            real_only=True,
            error_codes=(2, 3, 4),
        ),
        Stage(
            "security",
            "Security scoreboard: each defence against the attacks (report only)",
            False,
            (PY, "-X", "utf8", "-m", "eval.security", "scoreboard", "--label", f"{label}-sec")
            + stub_flag,
            outputs=f"runs/security/{label}-sec/",
        ),
        Stage(
            "retrieval",
            "Policy search recall on 47 queries (report only, about 12 min)",
            False,
            (PY, "-X", "utf8", "-m", "claimsense.retrieval.evaluate", "--label", label),
            needs=("chromadb", "rank_bm25", "sentence_transformers", "matplotlib"),
            needs_paths=("chroma-data",),
            outputs=f"runs/retrieval_{label}.png",
        ),
        Stage(
            "ragas",
            "RAGAS rationale groundedness (report only; uncalibrated, weight 0.00)",
            False,
            (
                PY,
                "-X",
                "utf8",
                "-m",
                "eval.harness.run",
                "--adapter",
                "claimsense-real-retrieval",
                "--split",
                "dev",
                "--judge",
                "--judge-limit",
                str(judge_limit),
                "--label",
                f"{label}-ragas",
            ),
            needs=("ragas", "chromadb"),
            needs_paths=("chroma-data",),
            real_only=True,
            outputs=f"runs/{label}-ragas.scorecard.json",
        ),
        Stage(
            "attacker",
            "Adaptive attacker (report only; exit 1 = it won)",
            False,
            (PY, "-X", "utf8", "-m", "eval.security", "attack", "--label", f"{label}-attack"),
            real_only=True,
            opt_in=True,
            outputs=f"runs/security/{label}-attack/",
        ),
    ]


def missing(stage: Stage) -> str:
    """Why a stage cannot run here, or '' if it can."""
    gone = [p for p in stage.needs if importlib.util.find_spec(p) is None]
    if gone:
        return f"package missing: {', '.join(gone)} (pip install -r requirements.txt)"
    absent = [p for p in stage.needs_paths if not (REPO_ROOT / p).exists()]
    if absent:
        return f"not found: {', '.join(absent)} (python -m claimsense.retrieval.index)"
    return ""


def child_env(stub: bool, extra: tuple[tuple[str, str], ...]) -> dict[str, str]:
    env = dict(os.environ, PYTHONUTF8="1", **dict(extra))
    if stub:
        env["CLAIMSENSE_LLM"] = "stub"
    return env


def run_stage(stage: Stage, stub: bool, log_dir: Path) -> Result:
    log = log_dir / f"{stage.name}.log"
    base = {
        "name": stage.name,
        "what": stage.what,
        "blocking": stage.blocking,
        "log": log.relative_to(REPO_ROOT).as_posix() if log.is_relative_to(REPO_ROOT) else str(log),
        "outputs": stage.outputs,
        "cmd": [Path(c).name if c == PY else c for c in stage.cmd],
    }
    if stage.real_only and stub:
        return Result(**base, status=SKIPPED, exit_code=None, seconds=0.0, note="needs real model")
    why = missing(stage)
    if why:
        status = ERROR if stage.blocking else SKIPPED
        return Result(**base, status=status, exit_code=None, seconds=0.0, note=why)
    start = time.monotonic()
    with log.open("w", encoding="utf-8") as fh:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            stage.cmd,
            cwd=REPO_ROOT,
            env=child_env(stub or stage.offline, stage.env),
            stdout=fh,
            stderr=subprocess.STDOUT,
            check=False,
        )
    seconds = round(time.monotonic() - start, 1)
    code = proc.returncode
    if code == 0:
        status = PASSED
    elif code in stage.error_codes:
        status = ERROR
    else:
        status = FAILED
    return Result(**base, status=status, exit_code=code, seconds=seconds)


def verdict(results: list[Result], stub: bool) -> tuple[str, int]:
    blocking = [r for r in results if r.blocking]
    if any(r.status == FAILED for r in blocking):
        return NO_SHIP, 1
    if any(r.status != PASSED for r in blocking):
        return NOT_VERIFIED, 2
    return (REHEARSAL if stub else SHIP), 0


def summary_md(label: str, mode: str, results: list[Result], word: str) -> str:
    lines = [
        f"# Ship check `{label}`",
        "",
        f"**Mode:** {mode} · **Verdict:** {word}",
        "",
        "| Stage | Blocks? | Result | Exit | Seconds | Outputs | Note |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        code = "" if r.exit_code is None else r.exit_code
        lines.append(
            f"| {r.name}: {r.what} | {'yes' if r.blocking else 'no'} | {r.status} | {code} | "
            f"{r.seconds} | {r.outputs} | {r.note} |"
        )
    lines += ["", "Logs: `logs/<stage>.log` in this folder."]
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--label", required=True, help="run name; output in runs/ship/<label>/")
    p.add_argument("--stub", action="store_true", help="free rehearsal: stub agents, no key")
    p.add_argument("--skip", default="", help="comma list of stages to leave out")
    p.add_argument("--only", default="", help="comma list: run just these stages")
    p.add_argument("--attack", action="store_true", help="also run the adaptive attacker (paid)")
    p.add_argument("--workers", type=int, default=4, help="claims in parallel in the release gate")
    p.add_argument("--judge-limit", type=int, default=5, help="claims the RAGAS judge scores")
    p.add_argument(
        "--variant", default="v1", help="release-gate variant (v1, guarded, real-retrieval...)"
    )
    p.add_argument("--list", action="store_true", help="print the stages and exit")
    return p.parse_args(argv)


def select(all_stages: list[Stage], args: argparse.Namespace) -> list[Stage]:
    names = {s.name for s in all_stages}
    only = {n.strip() for n in args.only.split(",") if n.strip()}
    skip = {n.strip() for n in args.skip.split(",") if n.strip()}
    unknown = (only | skip) - names
    if unknown:
        raise SystemExit(f"unknown stage(s): {', '.join(sorted(unknown))}; see --list")
    chosen = [s for s in all_stages if (not only or s.name in only) and s.name not in skip]
    return [s for s in chosen if not s.opt_in or args.attack or s.name in only]


def mode_problem(stub: bool) -> str:
    """Refuse a real run that would silently be a stub run, or fail on its first model call."""
    if stub:
        return ""
    if os.environ.get("CLAIMSENSE_LLM") == "stub":
        return "CLAIMSENSE_LLM=stub is set: pass --stub, or remove it for a real run."
    if not os.environ.get("OPENROUTER_API_KEY"):
        return "OPENROUTER_API_KEY is not set: load it for a real run, or pass --stub (free)."
    return ""


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    planned = select(
        stages(args.label, args.stub, args.workers, args.judge_limit, args.variant), args
    )
    if args.list:
        for s in planned:
            print(f"{s.name:<16}{'blocks' if s.blocking else 'report':<8}{s.what}")
        return 0
    problem = mode_problem(args.stub)
    if problem:
        print(f"eval.ship: {problem}", file=sys.stderr)
        return 2
    out = RUNS_DIR / args.label
    if out.exists():
        print(f"eval.ship: {out} exists; pick a new --label", file=sys.stderr)
        return 2
    (out / "logs").mkdir(parents=True)
    mode = "stub" if args.stub else "real"
    if not args.stub and os.environ.get("CLAIMSENSE_GUARD_LLM") == "1":
        print("note: CLAIMSENSE_GUARD_LLM=1 is set; the guard model slows every claim.")

    print(f"Ship check {args.label} ({mode} mode): {len(planned)} stages\n")
    results: list[Result] = []
    for i, stage in enumerate(planned, 1):
        tag = "blocks" if stage.blocking else "report"
        print(f"[{i}/{len(planned)}] {stage.name:<16}{tag:<8}{stage.what} ...", flush=True)
        res = run_stage(stage, args.stub, out / "logs")
        results.append(res)
        extra = f" ({res.note})" if res.note else ""
        print(f"      -> {res.status} in {res.seconds}s{extra}", flush=True)

    word, code = verdict(results, args.stub)
    text = summary_md(args.label, mode, results, word)
    (out / "summary.md").write_text(text, encoding="utf-8")
    (out / "summary.json").write_text(
        json.dumps(
            {
                "label": args.label,
                "mode": mode,
                "verdict": word,
                "exit_code": code,
                "stages": [asdict(r) for r in results],
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    print("\n" + text)
    print(f"VERDICT: {word}   (written to {out.relative_to(REPO_ROOT).as_posix()}/)")
    return code
