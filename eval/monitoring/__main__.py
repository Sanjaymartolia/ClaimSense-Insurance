"""Live monitoring for the ClaimSense pipeline (L13 section 8).

    python -m eval.monitoring setup                     download and verify Prometheus and Grafana
    python -m eval.monitoring run --stub --label demo   the four-minute incident drill
    python -m eval.monitoring down                      stop servers an interrupted run left behind
    python -m eval.monitoring export --out DIR          config files for Deploy & Ops to adopt

`run` exits 0 when the alerts did what the scenario was built to show, 1 when an expected alert
stayed silent or one fired in normal traffic, 2 when the run could not start, and 3 when the run
is inconclusive (the traffic generator stalled, or Prometheus could not be read back): rerun.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sys
import time
import urllib.error
import webbrowser
from collections import Counter
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

import yaml

from eval.agent_suite.judge import openrouter_structured
from eval.agent_suite.suite import VARIANTS, preflight
from eval.harness.loader import REPO_ROOT

from . import abtest, ops, readback, stack
from .dashboard import RULES_FILE, build_dashboard, thresholds
from .live import (
    ARMS,
    RECORD_FIELDS,
    SCENARIO,
    LiveRun,
    phase_counts,
    run_scenario,
    variant_for,
)
from .metrics import Metrics

RUNS_DIR = REPO_ROOT / "runs" / "monitoring"
METRICS_PORT = 9108

#: Seconds to wait after the traffic stops: two scrapes and two rule evaluations (5 s each).
TAIL_S = 12.0

#: `run` exit codes.
OK, DRILL_FAILED, CANNOT_START, INCONCLUSIVE = 0, 1, 2, 3

#: Deploy & Ops' folder; `export` never writes into it.
DEPLOY_OPS_DIR = REPO_ROOT / "monitoring"


def _label(text: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", text) or set(text) <= {"."}:
        raise argparse.ArgumentTypeError("use letters, digits, dot, dash and underscore only")
    return text


def parse_arms(text: str) -> dict[str, str]:
    """`v1,guarded` -> {"A": "v1", "B": "guarded"}."""
    names = [v.strip() for v in text.split(",") if v.strip()]
    if len(names) != 2 or any(v not in VARIANTS for v in names):
        raise ValueError(f"--arms takes two variants from {sorted(VARIANTS)}, such as v1,guarded")
    return {"A": names[0], "B": names[1]}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="python -m eval.monitoring", description=__doc__.split("\n")[0]
    )
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("setup", help="download, verify and unpack Prometheus and Grafana (once)")
    sub.add_parser("down", help="stop servers an interrupted run left behind")

    run = sub.add_parser("run", help="start the stack, send live traffic through an incident")
    run.add_argument(
        "--label",
        required=True,
        type=_label,
        help="run name; outputs go to runs/monitoring/<label>",
    )
    run.add_argument(
        "--stub", action="store_true", help="force the free deterministic agents, even with a key"
    )
    run.add_argument("--arms", default=",".join(ARMS.values()), help="A,B variants (v1,guarded)")
    run.add_argument("--scale", type=float, default=1.0, help="phase length factor (0.5 = half)")
    run.add_argument("--workers", type=int, default=5, help="traffic threads")
    run.add_argument("--seed", type=int, default=0, help="seed of the traffic")
    run.add_argument("--open", action="store_true", help="open the dashboard in the browser")
    run.add_argument("--keep", action="store_true", help="leave the stack up after the run")
    run.add_argument(
        "--judge", action="store_true", help="LLM judge on a sample of payloads (costs money)"
    )
    run.add_argument("--judge-limit", type=int, default=20, help="judge at most this many claims")

    exp = sub.add_parser("export", help="write alert rules, dashboard and provisioning to a folder")
    exp.add_argument("--out", required=True, type=Path, help="folder to write into")
    exp.add_argument(
        "--prometheus-url", default="http://prometheus:9090", help="how Grafana reaches Prometheus"
    )
    exp.add_argument(
        "--dashboards-dir",
        default="/var/lib/grafana/dashboards",
        help="where Grafana will find the dashboard JSON (the path inside its container)",
    )
    exp.add_argument("--metrics-target", default="api:8000", help="host:port Prometheus scrapes")
    return p.parse_args(argv)


# ------------------------------------------------------------------------------- the commands
def cmd_setup() -> int:
    try:
        binaries = stack.ensure_binaries()
    except stack.StackError as e:
        print(f"setup failed: {e}", file=sys.stderr)
        return 2
    print(f"Prometheus {stack.PROM_VERSION}:  {binaries.prometheus}")
    print(f"Grafana {stack.GRAFANA_VERSION}:    {binaries.grafana}")
    print(f"Everything is in {stack.home()}. Delete that folder to remove it.")
    return 0


def cmd_down() -> int:
    try:
        with stack.run_lock():  # never pull the servers out from under a live run
            stopped = stack.stop_leftovers()
    except stack.StackError as e:
        print(e, file=sys.stderr)
        return CANNOT_START
    print(f"stopped {stopped} server(s)" if stopped else "nothing was running")
    return OK


def cmd_export(args: argparse.Namespace) -> int:
    out: Path = args.out
    if out.resolve().is_relative_to(DEPLOY_OPS_DIR.resolve()):
        print(
            f"refusing to write into {DEPLOY_OPS_DIR}: it belongs to Deploy & Ops. "
            "Export somewhere else (such as runs/monitoring/export) and hand the files over.",
            file=sys.stderr,
        )
        return CANNOT_START
    out.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(RULES_FILE, out / "alert_rules.yml")
    # L16, production windows: the edit-rate alert on the case API's metrics, and its unit test.
    shutil.copyfile(ops.OPS_RULES_FILE, out / ops.OPS_RULES_FILE.name)
    shutil.copyfile(ops.OPS_RULES_TEST, out / ops.OPS_RULES_TEST.name)
    config = stack.prometheus_config(args.metrics_target)
    config["rule_files"].append(ops.OPS_RULES_FILE.name)
    (out / "prometheus.example.yml").write_text(
        "# Example only: written by `python -m eval.monitoring export`.\n"
        "# The 5 s intervals suit a demo. In production use 15 s or more, and lengthen the\n"
        "# `for:` times and rate windows in alert_rules.yml to minutes.\n"
        + yaml.safe_dump(config, sort_keys=False),
        encoding="utf-8",
    )
    dash = stack.write_provisioning(
        out / "grafana", build_dashboard(), args.prometheus_url, args.dashboards_dir
    )
    ops_dash = dash.with_name(f"{ops.OPS_UID}.json")  # same folder: Grafana loads both
    ops_dash.write_text(json.dumps(ops.build_ops_dashboard(), indent=2), encoding="utf-8")
    print(f"alert rules        {out / 'alert_rules.yml'}")
    print(f"ops alert (L16)    {out / ops.OPS_RULES_FILE.name} (+ {ops.OPS_RULES_TEST.name})")
    print(f"Prometheus example {out / 'prometheus.example.yml'}")
    print(f"Grafana dashboard  {dash}")
    print(f"ops dashboard      {ops_dash}")
    print(f"Grafana provision  {out / 'grafana' / 'provisioning'}")
    print("These are for Deploy & Ops to review and mount; nothing in monitoring/ was changed.")
    return 0


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=UTC).isoformat(timespec="seconds")


def build_summary(
    *,
    label: str,
    mode: str,
    arms: dict[str, str],
    args: argparse.Namespace,
    live: LiveRun,
    phase_log: list[tuple[str, float, float]],
    panels: dict[str, readback.Series],
    alerts: list[dict],
    drill: dict,
    grafana: dict,
) -> dict:
    """Everything the report quotes, in one file."""
    t0 = phase_log[0][1]
    spec = {p.name: p for p in SCENARIO}
    return {
        "label": label,
        "mode": mode,
        "versions": {
            "prometheus": stack.PROM_VERSION,
            "grafana": stack.GRAFANA_VERSION,
            "prometheus_client": metadata.version("prometheus-client"),
        },
        "arms": arms,
        "members_per_arm": dict(sorted(Counter(map(variant_for, live.source.members)).items())),
        "workers": args.workers,
        "seed": args.seed,
        "scale": args.scale,
        "started": _iso(t0),
        "ended": _iso(phase_log[-1][2]),
        "claims": len(live.records),
        "phases": [
            {
                "name": name,
                "start_s": round(start - t0, 1),
                "end_s": round(end - t0, 1),
                "inject_rate": spec[name].inject_rate,
                "fault": (
                    {
                        "tool": spec[name].fault.tool,
                        "error_rate": spec[name].fault.error_rate,
                        "delay_s": spec[name].fault.delay_s,
                    }
                    if spec[name].fault
                    else None
                ),
                "expect": list(spec[name].expect),
                **phase_counts(live.records, name),
            }
            for name, start, end in phase_log
        ],
        "alert_thresholds": thresholds(),
        "phase_means": readback.phase_means(panels, phase_log),
        "alerts": [
            {
                "alert": a["alert"],
                "tool": a["tool"],
                "first_s": round(a["first"] - t0, 1),
                "last_s": round(a["last"] - t0, 1),
                "intervals_s": [[round(s - t0, 1), round(e - t0, 1)] for s, e in a["intervals"]],
                "phases": a["phases"],
                "runbook": a["runbook"],
            }
            for a in alerts
        ],
        "drill": drill,
        "grafana": grafana,
        "ab": abtest.compare(live.records, arms),
        "worker_errors": dict(live.worker_errors),
    }


def write_outputs(
    out: Path,
    summary: dict,
    live: LiveRun,
    panels: dict[str, readback.Series],
    phase_log: list[tuple[str, float, float]],
    alerts: list[dict],
) -> bool:
    """summary.json, live.csv, panels.json and panels.png. Returns whether the chart was drawn."""
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    with (out / "live.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=RECORD_FIELDS)
        writer.writeheader()
        writer.writerows(sorted(live.records, key=lambda r: r["n"]))
    readback.write_panels_json(panels, out / "panels.json")
    arms = summary["arms"]
    return readback.plot_panels(
        panels,
        phase_log,
        alerts,
        out / "panels.png",
        title=(
            f"ClaimSense live run '{summary['label']}' ({summary['mode']} agents, "
            f"{summary['claims']} claims).  A = {arms['A']},  B = {arms['B']}"
        ),
        arms=arms,
    )


def cmd_run(args: argparse.Namespace) -> int:
    problem = preflight(args.stub)
    if problem:
        print(problem.replace("eval.agent_suite", "eval.monitoring run"), file=sys.stderr)
        return 2
    from claimsense.agents.llm import stub_mode

    mode = "stub" if stub_mode() else "real"
    try:
        arms = parse_arms(args.arms)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    if args.scale <= 0 or args.workers < 1:
        print("--scale must be above 0 and --workers at least 1", file=sys.stderr)
        return 2

    try:
        with stack.run_lock():
            return _drill(args, mode, arms)
    except stack.StackError as e:  # the lock: another run is in progress
        print(f"monitoring stack: {e}", file=sys.stderr)
        return CANNOT_START


def _read_back(running: stack.Stack, phase_log: list, start: float, end: float) -> tuple:
    """8.7 and 8.8. Returns (panels, alerts, drill); if Prometheus cannot be read, the drill
    says why and the panels and alerts are empty: the claims' own rows are still good."""
    try:
        panels = readback.collect_panels(running.prom, start, end)
        alerts = readback.alerts_fired(running.prom, phase_log, running.rules(), start, end)
    except (stack.StackError, urllib.error.URLError, OSError) as e:
        unavailable = {"ok": False, "unavailable": f"{type(e).__name__}: {e}"}
        return {}, [], {"expected": [], "false_alarms": [], "also_fired": [], **unavailable}
    return panels, alerts, readback.drill_check(SCENARIO, phase_log, alerts)


def _drill(args: argparse.Namespace, mode: str, arms: dict[str, str]) -> int:
    metrics = Metrics(variants=arms)
    live = LiveRun(
        metrics,
        arms,
        judge=openrouter_structured if args.judge else None,
        judge_limit=args.judge_limit,
    )
    server, _thread = metrics.serve(stack.pick_port(METRICS_PORT))
    running: stack.Stack | None = None
    try:
        running = stack.start(build_dashboard(arms), RULES_FILE, server.server_port)
        print(f"\ndashboard: {running.dashboard_url}\n")
        if args.open:
            webbrowser.open(running.dashboard_url)

        total = sum(p.seconds for p in SCENARIO) * args.scale
        print(f"## 8.6 The incident ({total:.0f} s, {args.workers} workers)")
        phase_log = run_scenario(
            live,
            SCENARIO,
            workers=args.workers,
            seed=args.seed,
            annotate=running.annotate,
            scale=args.scale,
        )
        time.sleep(TAIL_S)

        start, end = phase_log[0][1], time.time()
        panels, alerts, drill = _read_back(running, phase_log, start, end)
        # While the process is stalled no claim moves; alert times then measure the stall.
        drill["generator_stalls"] = [
            {"at_s": round(t - start, 1), "seconds": s} for t, s in live.stalls
        ]
        # The drill is a fixed test only for the run it was designed on, with traffic flowing.
        designed = mode == "stub" and args.scale >= 1.0 and arms == ARMS
        inconclusive = "unavailable" in drill or (designed and bool(live.stalls))
        drill["enforced"] = designed and not inconclusive
        summary = build_summary(
            label=args.label,
            mode=mode,
            arms=arms,
            args=args,
            live=live,
            phase_log=phase_log,
            panels=panels,
            alerts=alerts,
            drill=drill,
            grafana=running.grafana_check(),
        )
        out = RUNS_DIR / args.label
        drawn = write_outputs(out, summary, live, panels, phase_log, alerts)

        print("\n## 8.8 Alerts that fired (seconds into the run)")
        print(readback.format_alerts(alerts, start))
        print("\n## The drill: did each alert fire when the scenario says it should?")
        for row in drill["expected"]:
            when = (
                f"fired {row['after_s']:.0f} s into the phase" if row["fired"] else "DID NOT FIRE"
            )
            print(f"  {row['phase']:<16} {row['alert']:<24} {when}")
        print(f"  false alarms in normal traffic: {', '.join(drill['false_alarms']) or 'none'}")
        print(f"  also fired (not required):      {', '.join(drill['also_fired']) or 'none'}")
        if not designed:
            print(
                "  (not enforced: the drill is a test only in stub mode, full length, v1,guarded)"
            )
        for stall in drill["generator_stalls"]:
            print(
                f"  WARNING: the traffic generator stalled {stall['seconds']:.0f} s at "
                f"{stall['at_s']:.0f} s; alert times after it are late by that much."
            )
        if "unavailable" in drill:
            print(f"  WARNING: Prometheus could not be read back ({drill['unavailable']}).")
        if inconclusive:
            print("  INCONCLUSIVE: rerun. live.csv and the A/B below are still valid.")
        print("\n## 8.9 A/B on the live claims")
        print(abtest.format_report(summary["ab"]))
        if live.worker_errors:
            print(f"\nworker errors: {dict(live.worker_errors)}")
        print(f"\nwritten to {out}")
        if not drawn:
            print('no chart: matplotlib is missing (pip install -e ".[docs]")')

        if args.keep:
            print(f"\nstack left up: {running.dashboard_url}\nCtrl+C to stop it.")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\nstopping")
        if inconclusive:
            return INCONCLUSIVE
        return OK if drill["ok"] or not drill["enforced"] else DRILL_FAILED
    except stack.StackError as e:
        print(f"monitoring stack: {e}", file=sys.stderr)
        return CANNOT_START
    except KeyboardInterrupt:
        print("\nstopped")
        return 130
    finally:
        if running is not None:
            running.stop()
        server.shutdown()
        server.server_close()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "setup":
        return cmd_setup()
    if args.command == "down":
        return cmd_down()
    if args.command == "export":
        return cmd_export(args)
    return cmd_run(args)


if __name__ == "__main__":
    sys.exit(main())
