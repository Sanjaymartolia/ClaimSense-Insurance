"""Observability for the ClaimSense pipeline: OpenTelemetry traces (L14 / AAI-14).

    python -m eval.observability show [CLAIM_ID ...] --stub   the simple way: spans in memory, one
                                                             trace printed as a tree, no server
    python -m eval.observability setup                       download and verify Jaeger (once)
    python -m eval.observability run --stub --label NAME     the production way: spans to Jaeger
                                                             over OTLP, a normal batch and a tool
                                                             outage, read back and analysed
    python -m eval.observability down                        stop a Jaeger an interrupted run left

Without --stub, an OPENROUTER_API_KEY in the environment switches the agents to real models (it
costs money). `run` exits 0 when every check holds, 1 when one fails, 2 when it cannot start.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import json
import os
import random
import re
import sys
import time
import webbrowser
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

from eval.agent_suite.dataset import Case, load_dataset
from eval.agent_suite.suite import VARIANTS, preflight
from eval.harness.loader import REPO_ROOT
from eval.monitoring.live import Fault

from . import analysis, jaeger, otel

RUNS_DIR = REPO_ROOT / "runs" / "observability"
OK, CHECK_FAILED, CANNOT_START = 0, 1, 2

#: The notebook's claim #4 is Kabir's dinner; ClaimSense's CLM-0004 is the first claim with a
#: procedure, so its trace shows every agent, the tariff check and the review.
DEFAULT_CLAIM = "CLM-0004"


def _label(text: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", text) or set(text) <= {"."}:
        raise argparse.ArgumentTypeError("use letters, digits, dot, dash and underscore only")
    return text


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="python -m eval.observability", description=__doc__.split("\n")[0]
    )
    sub = p.add_subparsers(dest="command", required=True)

    show = sub.add_parser("show", help="simple way: trace claims in memory and print the tree")
    show.add_argument("claims", nargs="*", default=[DEFAULT_CLAIM], help="claim ids (CLM-0004)")
    show.add_argument("--stub", action="store_true", help="force the free deterministic agents")
    show.add_argument("--variant", default="v1", choices=sorted(VARIANTS))
    show.add_argument("--json", action="store_true", help="also print two spans as OTLP JSON")

    sub.add_parser("setup", help="download, verify and unpack Jaeger (once)")
    sub.add_parser("down", help="stop a Jaeger an interrupted run left behind")

    run = sub.add_parser("run", help="production way: spans to a backend, normal + outage")
    run.add_argument("--label", required=True, type=_label, help="outputs: runs/observability/<l>")
    run.add_argument("--stub", action="store_true", help="force the free deterministic agents")
    run.add_argument(
        "--backend",
        choices=("jaeger", "otlp-env", "memory"),
        default="jaeger",
        help="jaeger: local viewer (default). otlp-env: the OTEL_EXPORTER_OTLP_* variables "
        "(Langfuse, Phoenix, a Collector). memory: no export",
    )
    run.add_argument("--split", default="dev", choices=("dev", "redteam"), help="claims to send")
    run.add_argument("--workers", type=int, default=4, help="claims run at once (notebook: 8)")
    run.add_argument("--error-rate", type=float, default=0.7, help="outage: share of tool calls")
    run.add_argument("--delay", type=float, default=1.5, help="outage: seconds per tool call")
    run.add_argument("--seed", type=int, default=0)
    run.add_argument("--open", action="store_true", help="open the Jaeger UI in the browser")
    run.add_argument("--keep", action="store_true", help="leave Jaeger up after the run")
    return p.parse_args(argv)


# ---------------------------------------------------------------------------------- helpers
def _start(force_stub: bool) -> tuple[str, str | None]:
    """Stub or real, decided once. Returns (mode, problem)."""
    problem = preflight(force_stub)
    if problem:
        return "", problem.replace("eval.agent_suite", "eval.observability")
    problem = otel.langsmith_problem()
    if problem:
        return "", problem
    from claimsense.agents.llm import stub_mode

    return ("stub" if stub_mode() else "real"), None


def _cases(split: str) -> list[Case]:
    return load_dataset((split,))


def _instrument(tel: otel.Telemetry, mode: str) -> bool:
    """Real mode only: model-call spans from the LangChain instrumentation, content off."""
    if mode != "real":
        return False
    on = otel.instrument_langchain(tel)
    print(
        "model calls: traced by the LangChain instrumentation (prompts and replies NOT recorded)"
        if on
        else 'model calls: not traced (pip install -e ".[observability]")'
    )
    return on


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=UTC).isoformat(timespec="seconds")


# ------------------------------------------------------------------------------------- show
def cmd_show(args: argparse.Namespace) -> int:
    mode, problem = _start(args.stub)
    if problem:
        print(problem, file=sys.stderr)
        return CANNOT_START
    by_id = {c.claim_id: c for c in load_dataset(("dev", "redteam"))}
    unknown = [c for c in args.claims if c not in by_id]
    if unknown:
        print(
            f"unknown claim id(s): {', '.join(unknown)} (try CLM-0004 or CLM-9001)", file=sys.stderr
        )
        return CANNOT_START
    tel = otel.telemetry()
    _instrument(tel, mode)
    try:
        for cid in args.claims:
            t, trace_id = otel.run_claim(
                tel, by_id[cid].eval_case, variant=args.variant, **VARIANTS[args.variant]
            )
            spans = analysis.by_trace(tel.rows())[trace_id]
            print(f"\n## {cid} ({mode}, {args.variant}): trace {trace_id}, {len(spans)} spans")
            print(analysis.tree(spans))
        if args.json:
            finished = tel.memory.get_finished_spans()
            root = next(s for s in finished if s.name == otel.ROOT_SPAN)
            tool = next((s for s in finished if s.name.startswith("execute_tool")), None)
            print("\n## Two spans exactly as an exporter sends them (after redaction)")
            print(root.to_json())
            if tool is not None:
                print(tool.to_json())
        _traceparent(tel)
        u = analysis.usage(tel.rows())
        if mode == "real":
            print(
                f"\nmodel-call spans {u['model_call_spans']}, tokens {u['input_tokens']} in / "
                f"{u['output_tokens']} out, ${u['cost_usd']:.5f}"
            )
    finally:
        otel.uninstrument_langchain()
        tel.shutdown()
    return OK


def _traceparent(tel: otel.Telemetry) -> None:
    """Notebook 4.2: the header that would carry this trace into another service (or MCP)."""
    from opentelemetry.propagate import inject

    with tel.tracer.start_as_current_span("execute_tool tariff_range (remote call)") as span:
        headers: dict[str, str] = {}
        inject(headers)
    print("\n## 4.2 One trace across services: the header an MCP or HTTP tool call would carry")
    print(f"  traceparent: {headers.get('traceparent')}")
    print(f"  trace id:    {span.get_span_context().trace_id:032x}")


# -------------------------------------------------------------------------------------- run
def _batch(
    tel: otel.Telemetry,
    cases: list[Case],
    phase: str,
    workers: int,
    prepare_for: Callable[[int], Any] | None = None,
) -> list[tuple[str, str]]:
    """Run every case in one phase, `workers` at a time. Returns [(claim_id, trace_id)]."""

    def one(i_case: tuple[int, Case]) -> tuple[str, str]:
        i, case = i_case
        prepare = prepare_for(i) if prepare_for else None
        _, trace_id = otel.run_claim(
            tel, case.eval_case, phase=phase, prepare=prepare, **VARIANTS["v1"]
        )
        return case.claim_id, trace_id

    with ThreadPoolExecutor(workers) as pool:
        return list(pool.map(one, enumerate(cases)))


def _read_back(
    j: jaeger.Jaeger, rows: list[analysis.SpanRow], start: float, end: float, wait_s: float = 30
) -> dict:
    """Ask Jaeger for what it stored: the service, every trace of the run, one full trace."""
    expected = {r.trace_id for r in analysis.roots(rows)}
    out: dict[str, Any] = {"expected_traces": len(expected)}
    deadline = time.monotonic() + wait_s
    found: set[str] = set()
    while True:  # the batch processor and Jaeger both buffer: ask again until all are there
        stored = analysis.from_otlp(j.find_traces(start, end, depth=max(1000, 4 * len(expected))))
        found = {r.trace_id for r in stored} & expected
        if found == expected or time.monotonic() >= deadline:
            break
        time.sleep(1)
    out["services"] = j.services()
    out["traces_found"] = len(found)
    out["spans_checked"] = len(stored)
    keys_off = {k for r in stored for k in r.attrs if not otel.keep(k)}
    example = min(expected) if expected else None
    if example:
        back = analysis.from_otlp(j.get_trace(example))
        out["example_trace"] = example
        out["example_spans_stored"] = len(back)
        out["example_spans_sent"] = sum(r.trace_id == example for r in rows)
        keys_off |= {k for r in back for k in r.attrs if not otel.keep(k)}
    out["unredacted_keys_stored"] = sorted(keys_off)  # over every span Jaeger gave back
    out["ok"] = (
        jaeger.SERVICE in out["services"]
        and found == expected
        and out.get("example_spans_stored") == out.get("example_spans_sent")
        and not keys_off
    )
    return out


def _write_outputs(out: Path, summary: dict, rows: list[analysis.SpanRow], trees: str) -> bool:
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    (out / "trees.txt").write_text(trees, encoding="utf-8")
    phase_of = {r.trace_id: r.attrs.get("claimsense.phase", "") for r in analysis.roots(rows)}
    claim_of = {r.trace_id: r.attrs.get("claim.id", "") for r in analysis.roots(rows)}
    t0 = min((r.start_ns for r in rows), default=0)
    with (out / "spans.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["phase", "claim_id", "trace_id", "span_id", "parent_id", "name",
                    "start_ms", "ms", "error", "status", "error_type"])  # fmt: skip
        for r in sorted(rows, key=lambda r: r.start_ns):
            w.writerow(
                [
                    phase_of.get(r.trace_id, ""),
                    claim_of.get(r.trace_id, ""),
                    r.trace_id,
                    r.span_id,
                    r.parent_id or "",
                    r.name,
                    round((r.start_ns - t0) / 1e6, 3),
                    round(r.ms, 3),
                    r.error,
                    r.attrs.get("claimsense.status", ""),
                    r.attrs.get("error.type", ""),
                ]
            )
    title = (
        f"ClaimSense spans per name, run '{summary['label']}' ({summary['mode']} agents, "
        f"{summary['claims_per_phase']} claims per phase)"
    )
    return analysis.plot_red(summary["red"], out / "red.png", title)


def cmd_run(args: argparse.Namespace) -> int:
    out = RUNS_DIR / args.label
    if out.exists():
        print(
            f"{out} already exists. Use a new --label: reports may quote this run, and a rerun "
            "would overwrite its evidence.",
            file=sys.stderr,
        )
        return CANNOT_START
    if args.workers < 1 or not 0 <= args.error_rate <= 1 or args.delay < 0:
        print("--workers >= 1, --error-rate in [0, 1], --delay >= 0", file=sys.stderr)
        return CANNOT_START
    mode, problem = _start(args.stub)
    if problem:
        print(problem, file=sys.stderr)
        return CANNOT_START
    if args.backend == "otlp-env" and not (
        _env("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or _env("OTEL_EXPORTER_OTLP_ENDPOINT")
    ):
        print(
            "--backend otlp-env needs OTEL_EXPORTER_OTLP_TRACES_ENDPOINT (and usually "
            "OTEL_EXPORTER_OTLP_TRACES_HEADERS). See eval/observability/README.md for Langfuse.",
            file=sys.stderr,
        )
        return CANNOT_START
    try:
        # The lock guards Jaeger's folder and ports; the other backends use neither.
        with jaeger.run_lock() if args.backend == "jaeger" else contextlib.nullcontext():
            return _run(args, mode, out)
    except jaeger.JaegerError as e:
        print(f"observability: {e}", file=sys.stderr)
        return CANNOT_START


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


#: Headers the OTLP exporter reads from the environment even when `headers=` is given.
_HEADER_VARS = ("OTEL_EXPORTER_OTLP_HEADERS", "OTEL_EXPORTER_OTLP_TRACES_HEADERS")


def _local_exporter(endpoint: str) -> Any:
    """An OTLP exporter for the local Jaeger that never carries a Langfuse or LangSmith
    credential from the environment."""
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    saved = {k: os.environ.pop(k) for k in _HEADER_VARS if k in os.environ}
    try:
        return OTLPSpanExporter(endpoint=endpoint, timeout=5)
    finally:
        os.environ.update(saved)


#: One span with an attribute off the allowlist, sent with the run: proof that redaction is in
#: the export path (the check fails if it ever comes out with the attribute still on).
CANARY = "redaction canary"
_CANARY_KEY, _CANARY_VALUE = "canary.prompt", "CANARY-TEXT-must-not-leave-the-process"


def _canary(tel: otel.Telemetry) -> None:
    with tel.tracer.start_as_current_span(CANARY) as span:
        span.set_attribute(_CANARY_KEY, _CANARY_VALUE)


def _redacted(canary: list[analysis.SpanRow]) -> bool:
    return len(canary) == 1 and canary[0].attrs == {"claimsense.redacted_attributes": 1}


def _run(args: argparse.Namespace, mode: str, out: Path) -> int:
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    j: jaeger.Jaeger | None = None
    tel: otel.Telemetry | None = None
    try:
        exporter = None
        if args.backend == "jaeger":
            j = jaeger.start()
            exporter = _local_exporter(j.otlp_endpoint)
        elif args.backend == "otlp-env":
            exporter = OTLPSpanExporter(timeout=10)  # endpoint and headers from the environment
        tel = otel.telemetry(exporter)
        _instrument(tel, mode)
        cases = _cases(args.split)
        fault = Fault(error_rate=args.error_rate, delay_s=args.delay)

        print(f"\n## Normal: {len(cases)} {args.split} claims, {args.workers} at a time")
        t_start = time.time()
        normal = _batch(tel, cases, "normal", args.workers)
        print(f"## Outage: the same claims while {fault.tool} fails {fault.error_rate:.0%} of the "
              f"time after {fault.delay_s:.1f} s")  # fmt: skip
        outage = _batch(
            tel,
            cases,
            "outage",
            args.workers,
            lambda i: fault.hook(random.Random(args.seed * 1000 + i)),  # noqa: S311 - simulation
        )
        t_end = time.time()
        _canary(tel)
        flushed = tel.flush()

        every = tel.rows()
        rows = [r for r in every if r.name != CANARY]
        delivered = (
            {"sent": tel.otlp.sent, "failed": tel.otlp.failed, "spans": len(every)}
            if tel.otlp is not None
            else None
        )
        phase_traces = {"normal": {t for _, t in normal}, "outage": {t for _, t in outage}}
        by_phase = {p: [r for r in rows if r.trace_id in ids] for p, ids in phase_traces.items()}
        red = {p: analysis.red(rs) for p, rs in by_phase.items()}
        paths = analysis.error_paths(by_phase["outage"])
        readback = _read_back(j, rows, t_start, t_end) if j else None

        tariff = "execute_tool tariff_range"
        checks = {
            "every_claim_traced": len(analysis.roots(rows)) == 2 * len(cases),
            "one_trace_per_claim": all(len(v) == len(cases) for v in phase_traces.values()),
            "normal_has_no_tool_errors": all(
                v["errors"] == 0 for k, v in red["normal"].items() if k.startswith("execute_tool")
            ),
            "outage_visible_in_spans": red["outage"].get(tariff, {}).get("errors", 0) > 0,
            "exported_spans_redacted": _redacted([r for r in every if r.name == CANARY]),
            # force_flush returns True even when the backend refused every batch: count instead
            "backend_accepted_every_span": delivered is None
            or (bool(flushed) and delivered["failed"] == 0 and delivered["sent"] == len(every)),
        }
        if readback is not None:
            checks["jaeger_read_back"] = bool(readback["ok"])

        trees = _example_trees(rows, normal, outage)
        summary = {
            "label": args.label,
            "mode": mode,
            "backend": args.backend,
            "versions": {
                "opentelemetry-sdk": metadata.version("opentelemetry-sdk"),
                "jaeger": jaeger.VERSION if j else None,
            },
            "started": _iso(t_start),
            "ended": _iso(t_end),
            "split": args.split,
            "claims_per_phase": len(cases),
            "workers": args.workers,
            "fault": {"tool": fault.tool, "error_rate": fault.error_rate, "delay_s": fault.delay_s},
            "spans": {p: len(rs) for p, rs in by_phase.items()},
            "red": red,
            "error_paths": paths,
            "gate": {p: analysis.gate(rs) for p, rs in by_phase.items()},
            "usage": {p: analysis.usage(rs) for p, rs in by_phase.items()},
            "delivered": delivered,
            "readback": readback,
            "checks": checks,
            "ok": all(checks.values()),
        }
        drawn = _write_outputs(out, summary, rows, trees)
        _report(summary, j, normal, outage, out, drawn)

        if args.open and j:
            webbrowser.open(f"{j.ui_url}/search?service={jaeger.SERVICE}")
        if args.keep and j:
            print(f"\nJaeger left up: {j.ui_url}  (Ctrl+C to stop it)")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\nstopping")
        return OK if summary["ok"] else CHECK_FAILED
    except KeyboardInterrupt:
        print("\nstopped")
        return 130
    finally:
        otel.uninstrument_langchain()
        if tel is not None:
            tel.shutdown()
        if j is not None:
            j.stop()


def _example_trees(rows: list[analysis.SpanRow], normal: list, outage: list) -> str:
    """One trace per phase: CLM-0004 when normal, the first claim with an error in the outage."""
    traces = analysis.by_trace(rows)
    pick_normal = next((t for c, t in normal if c == DEFAULT_CLAIM), normal[0][1] if normal else "")
    failed = {t for t, spans in traces.items() if any(r.error for r in spans)}
    pick_outage = next((t for _, t in outage if t in failed), outage[0][1] if outage else "")
    parts = []
    for phase, tid in (("normal", pick_normal), ("outage", pick_outage)):
        if tid in traces:
            claim = next((r.attrs.get("claim.id") for r in analysis.roots(traces[tid])), "?")
            parts.append(f"## {phase}: {claim}, trace {tid}\n{analysis.tree(traces[tid])}\n")
    return "\n".join(parts)


def _report(summary: dict, j, normal: list, outage: list, out: Path, drawn: bool) -> None:
    print("\n## 6.1 Rate, errors and duration per span name")
    print(analysis.red_table(summary["red"]))
    print("\n## 6.2 What each claim did after the tool failed")
    for p in summary["error_paths"] or []:
        print(f"  {p['claim_id']:<10} {p['status']:<9} {p['error_type'] or '-':<14} {p['path']}")
    if not summary["error_paths"]:
        print("  (no claim hit an error)")
    print("\n## 8 The approval gate, read from the human_review spans")
    for phase, g in summary["gate"].items():
        print(
            f"  {phase:<7} {g['sent_to_person']}/{g['claims']} claims sent to a person, "
            f"decisions {g['decisions']}, median wait {g['median_wait_s']} s"
        )
    print("\n## 9 Model calls and cost, from the spans")
    for phase, u in summary["usage"].items():
        print(
            f"  {phase:<7} {u['model_call_spans']} model-call spans, {u['input_tokens']} tokens in"
            f" / {u['output_tokens']} out, ${u['cost_usd']:.5f}"
        )
    d = summary["delivered"]
    if d is not None:
        print(f"\n## Export: the backend accepted {d['sent']} of {d['spans']} spans, refused "
              f"{d['failed']}")  # fmt: skip
    rb = summary["readback"]
    if rb is not None:
        print("\n## 4 What Jaeger stored (read back through its API v3)")
        print(f"  services: {', '.join(rb['services']) or '-'}")
        print(f"  traces found: {rb['traces_found']} of {rb['expected_traces']}")
        if rb.get("example_trace"):
            print(
                f"  trace {rb['example_trace']}: {rb['example_spans_stored']} spans stored, "
                f"{rb['example_spans_sent']} sent"
            )
        print(
            f"  keys off the allowlist in the {rb['spans_checked']} spans read back: "
            f"{rb['unredacted_keys_stored'] or 'none'}"
        )
        if j is not None:
            pick = dict(normal).get(DEFAULT_CLAIM)
            print(f"  open:   {j.ui_url}/search?service={jaeger.SERVICE}")
            if pick:
                print(f"  CLM-0004 (normal): {j.trace_url(pick)}")
    print("\n## Checks")
    for name, ok in summary["checks"].items():
        print(f"  {'ok  ' if ok else 'FAIL'} {name}")
    print(f"\nwritten to {out}")
    if not drawn:
        print('no chart: matplotlib is missing (pip install -e ".[docs]")')


# ------------------------------------------------------------------------------- setup, down
def cmd_setup() -> int:
    try:
        binary = jaeger.ensure_binary()
    except jaeger.JaegerError as e:
        print(f"setup failed: {e}", file=sys.stderr)
        return CANNOT_START
    print(f"Jaeger {jaeger.VERSION}: {binary}")
    print(f"Everything is in {jaeger.home()}. Delete that folder to remove it.")
    return OK


def cmd_down() -> int:
    try:
        with jaeger.run_lock():
            stopped = jaeger.stop_leftovers()
    except jaeger.JaegerError as e:
        print(e, file=sys.stderr)
        return CANNOT_START
    print("stopped a leftover Jaeger" if stopped else "nothing was running")
    return OK


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "show":
        return cmd_show(args)
    if args.command == "setup":
        return cmd_setup()
    if args.command == "down":
        return cmd_down()
    return cmd_run(args)


if __name__ == "__main__":
    sys.exit(main())
