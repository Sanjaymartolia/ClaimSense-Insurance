"""E3: did the lessons help? A thin, metered wrapper around the two Reflexion scripts.

    # 1. learn on the development claims; a PERSON approves each lesson at the terminal
    python -X utf8 -m eval.experiments.e3 learn --reviewer "<name>" \
        --out docs/experiments/reflexion/run-04
    # 2. held-out, before and after the frozen playbook, 3 repeats (Eval & Red-Team only)
    python -X utf8 -m eval.experiments.e3 heldout --heldout ../claimsense-heldout \
        --out ../claimsense-heldout-results/run-03

Settings come from `configs/E3_reflexion.yaml`, so both steps use the same tolerance, executor and
calculator. What this adds to the scripts:

- **Lesson cost.** Every call to `reflexion.loop.reflect` (the only place lessons are generated)
  runs inside the harness's model-usage counter. `learn` writes `<out>/lesson_cost.json`: calls,
  lessons drafted, tokens, dollars, dollars per lesson. In stub mode it is 0.
- **Lessons that made results worse.** The script's ablation (leave one lesson out at a time)
  already finds them; `learn` copies them from `<out>/report.json` into `lesson_cost.json`.

The held-out step only passes arguments through: the script refuses a held-out or output folder
inside the repository, an unfrozen or changed playbook, and any overlap with the dev set. This
wrapper never reads held-out files.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest import mock

import yaml

from eval.harness.claimsense_adapter import count_llm_usage
from eval.harness.loader import REPO_ROOT

from .config import CONFIG_DIR, ConfigError

CONFIG = CONFIG_DIR / "E3_reflexion.yaml"
KEYS = ("dev_cases", "playbook", "after_runs", "repeat", "tolerance_rs", "executor", "calculator")


def load_e3(path: Path = CONFIG) -> dict[str, Any]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    missing = [k for k in KEYS if k not in raw]
    if missing:
        raise ConfigError(f"{Path(path).name}: missing {missing}")
    if int(raw["repeat"]) < 3:
        raise ConfigError("the brief asks for at least 3 held-out repeats")
    if raw["executor"] not in ("local", "langgraph") or raw["calculator"] not in (
        "reference",
        "team",
    ):
        raise ConfigError("executor is local|langgraph, calculator is reference|team")
    return raw


def _script(name: str) -> ModuleType:
    path = REPO_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_e3_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


class LessonMeter:
    """Wraps `reflect`: counts calls, drafted lessons, tokens and dollars."""

    def __init__(self, reflect: Any, metered: bool) -> None:
        self.reflect = reflect
        self.metered = metered
        self.calls = 0
        self.drafted = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.cost_usd = 0.0

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        with count_llm_usage(self.metered) as spent:
            draft = self.reflect(*args, **kwargs)
        self.drafted += draft is not None
        self.prompt_tokens += int(spent["prompt_tokens"])
        self.completion_tokens += int(spent["completion_tokens"])
        self.cost_usd += float(spent["cost_usd"])
        return draft

    def summary(self) -> dict[str, Any]:
        return {
            "reflect_calls": self.calls,
            "lessons_drafted": self.drafted,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "cost_usd_per_lesson": round(self.cost_usd / self.drafted, 6) if self.drafted else 0.0,
            "metered": self.metered,
        }


def harmful_lessons(report_json: Path) -> list[dict[str, Any]]:
    """Lessons the ablation found made results worse (`harmful`), from the script's report."""
    if not report_json.exists():
        return []
    report = json.loads(report_json.read_text(encoding="utf-8"))
    return [
        {k: row.get(k) for k in ("lesson_id", "error_increase_rs", "harmful")}
        for row in report.get("ablation") or []
        if row.get("harmful")
    ]


def learn(args: argparse.Namespace, cfg: dict[str, Any]) -> int:
    from claimsense.agents.llm import stub_mode
    from claimsense.reflexion import loop

    argv = [
        "experiment",
        "--cases", str(cfg["dev_cases"]),
        "--out", args.out,
        "--reviewer", args.reviewer,
        "--approve", args.approve,
        "--after-runs", str(cfg["after_runs"]),
        "--executor", str(cfg["executor"]),
        "--calculator", str(cfg["calculator"]),
        "--tolerance-rs", str(cfg["tolerance_rs"]),
    ]  # fmt: skip
    meter = LessonMeter(loop.reflect, metered=not stub_mode())
    with mock.patch.object(loop, "reflect", meter):
        _script("run_reflexion_experiment").main(argv)
    out = Path(args.out)
    result = {
        "lesson_cost": meter.summary(),
        "harmful_lessons": harmful_lessons(out / "report.json"),
        "approve": args.approve,
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "lesson_cost.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"\nE3 lesson cost: {json.dumps(result['lesson_cost'])}")
    print(f"E3 lessons that made results worse: {result['harmful_lessons'] or 'none'}")
    print(f"written to {out / 'lesson_cost.json'}")
    return 0


def heldout(args: argparse.Namespace, cfg: dict[str, Any]) -> int:
    argv = [
        "--playbook", str(cfg["playbook"]),
        "--heldout", args.heldout,
        "--dev", str(cfg["dev_cases"]),
        "--out", args.out,
        "--repeat", str(cfg["repeat"]),
        "--executor", str(cfg["executor"]),
        "--calculator", str(cfg["calculator"]),
        "--tolerance-rs", str(cfg["tolerance_rs"]),
    ]  # fmt: skip
    _script("run_reflexion_heldout").main(argv)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--config", default=str(CONFIG))
    sub = p.add_subparsers(dest="step", required=True)
    le = sub.add_parser("learn", help="learn on dev with a person approving each lesson")
    le.add_argument("--out", required=True)
    le.add_argument("--reviewer", required=True, help="the person approving lessons")
    le.add_argument(
        "--approve",
        choices=["console", "auto"],
        default="console",
        help="auto is a harness check only, never a result",
    )
    ho = sub.add_parser("heldout", help="held-out before/after (Eval & Red-Team only)")
    ho.add_argument("--heldout", required=True, help="held-out folder, OUTSIDE the repository")
    ho.add_argument("--out", required=True, help="results folder, OUTSIDE the repository")
    args = p.parse_args(argv)
    cfg = load_e3(Path(args.config))
    return learn(args, cfg) if args.step == "learn" else heldout(args, cfg)


if __name__ == "__main__":
    sys.exit(main())
