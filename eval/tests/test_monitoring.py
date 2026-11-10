"""Live monitoring (L13 section 8): metrics, alert rules, dashboard, live traffic, read-back, A/B.

No network and no Prometheus or Grafana binaries: the stack is checked through the config it
writes, and the read-back through a fake `prom` function that returns what Prometheus would.
"""

from __future__ import annotations

import json
import math
import random
import threading
from collections import Counter

import pytest
import yaml

pytest.importorskip("claimsense.agents", reason="needs pip install -e '.[dev]'")

from eval.agent_suite.suite import VARIANTS  # noqa: E402
from eval.agent_suite.trace import Span, Trace, run_traced  # noqa: E402
from eval.harness.loader import DEV_DIR, read_jsonl  # noqa: E402
from eval.harness.models import EVAL_ONLY_FIELDS  # noqa: E402
from eval.harness.suite import stub_llm  # noqa: E402
from eval.monitoring import __main__ as cli  # noqa: E402
from eval.monitoring import abtest, dashboard, readback, stack  # noqa: E402
from eval.monitoring import live as live_module  # noqa: E402
from eval.monitoring.live import (  # noqa: E402
    ARMS,
    RECORD_FIELDS,
    SCENARIO,
    ClaimSource,
    Fault,
    LiveRun,
    Phase,
    phase_counts,
    run_scenario,
    variant_for,
)
from eval.monitoring.metrics import Metrics, outcome_of  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _stub():
    with stub_llm():
        yield


@pytest.fixture(scope="module")
def source():
    return ClaimSource()


def _value(m: Metrics, name: str, **labels: str) -> float:
    return m.registry.get_sample_value(name, labels) or 0.0


# ------------------------------------------------------------------------------ 8.1 metrics
def test_export_trace_counts_outcome_tools_and_score():
    m = Metrics()
    t = Trace("C", "dev", variant="A", status="rejected", route="needs_review", seconds=0.2)
    t.spans = [
        Span("tool", "tariff_range", status="error"),
        Span("tool", "get_clause"),
        Span("tool", "settle_claim", status="blocked"),
    ]
    m.export_trace(t, correct=True)
    assert _value(m, "claimsense_claims_total", variant="A", outcome="needs_review") == 1
    assert _value(m, "claimsense_scored_total", variant="A") == 1
    assert _value(m, "claimsense_correct_total", variant="A") == 1
    assert _value(m, "claimsense_tool_calls_total", tool="tariff_range", status="error") == 1
    assert _value(m, "claimsense_tool_calls_total", tool="get_clause", status="ok") == 1
    assert _value(m, "claimsense_guardrail_trips_total", rule="tool_acl") == 1
    assert _value(m, "claimsense_latency_seconds_count", variant="A") == 1


def test_a_blocked_claim_trips_the_guardrail_and_has_no_latency():
    m = Metrics()
    t = Trace("C", "dev", variant="B", status="blocked", route="needs_review")
    t.flags = ["prompt_injection"]
    m.export_trace(t, correct=False)
    assert _value(m, "claimsense_claims_total", variant="B", outcome="blocked") == 1
    assert _value(m, "claimsense_guardrail_trips_total", rule="prompt_injection") == 1
    assert _value(m, "claimsense_scored_total", variant="B") == 1
    assert _value(m, "claimsense_correct_total", variant="B") == 0
    assert _value(m, "claimsense_latency_seconds_count", variant="B") == 0


def test_unscored_claims_are_not_counted_as_scored():
    m = Metrics()
    m.export_trace(Trace("C", "dev", variant="A", status="rejected", route="ready_for_approval"))
    assert _value(m, "claimsense_scored_total", variant="A") == 0


@pytest.mark.parametrize(
    ("status", "route", "expected"),
    [
        ("blocked", "needs_review", "blocked"),
        ("error", None, "error"),
        ("rejected", None, "error"),
        ("rejected", "ready_for_approval", "ready_for_approval"),
    ],
)
def test_outcome_of(status, route, expected):
    assert outcome_of(Trace("C", "dev", status=status, route=route)) == expected


def test_every_series_exists_at_zero_before_any_claim():
    """A rate() or ratio has data from the first scrape, so a panel shows 0, not "No data"."""
    m = Metrics()
    assert m.registry.get_sample_value(
        "claimsense_claims_total", {"variant": "B", "outcome": "error"}
    ) == pytest.approx(0)
    assert m.registry.get_sample_value(
        "claimsense_tool_calls_total", {"tool": "tariff_range", "status": "error"}
    ) == pytest.approx(0)


def test_no_claim_or_member_id_is_ever_a_label():
    m = Metrics()
    labels = {k for fam in m.registry.collect() for s in fam.samples for k in s.labels}
    assert labels <= {"variant", "outcome", "kind", "tool", "status", "rule", "le"}


# -------------------------------------------------------------- 8.2 rules and 8.3 dashboard
def test_every_metric_in_a_rule_or_query_is_exported():
    exported = Metrics().names()
    used = set()
    for rule in dashboard.load_rules():
        used |= dashboard.metric_names(rule["expr"])
    for expr in dashboard.QUERIES.values():
        used |= dashboard.metric_names(expr)
    assert used and used <= exported, sorted(used - exported)


def test_every_rule_has_a_wait_a_summary_and_a_runbook():
    rules = dashboard.load_rules()
    assert {r["alert"] for r in rules} == set(dashboard.thresholds())
    for rule in rules:
        assert rule["for"].endswith("s"), rule["alert"]
        assert rule["annotations"]["summary"] and rule["annotations"]["runbook"], rule["alert"]


def test_thresholds_are_read_from_the_rule_expressions():
    limits = dashboard.thresholds()
    assert limits["ToolErrorRateHigh"] == 0.2
    assert limits["HandledCorrectlyDrop"] == 0.40
    assert len(limits) == 6


def test_stat_tile_colours_change_exactly_at_the_alert_threshold():
    limits = dashboard.thresholds()
    board = dashboard.build_dashboard()
    steps = {
        p["title"]: [s["value"] for s in p["fieldConfig"]["defaults"]["thresholds"]["steps"]]
        for p in board["panels"]
        if "thresholds" in p["fieldConfig"]["defaults"]
    }
    assert steps["Handled correctly (1 min)"] == [None, limits["HandledCorrectlyDrop"]]
    assert steps["P95 latency"] == [None, limits["LatencyP95High"]]
    assert steps["Cost per claim"] == [None, limits["CostPerClaimHigh"]]


def test_dashboard_shape_and_url():
    board = dashboard.build_dashboard()
    assert board["uid"] == dashboard.DASHBOARD_UID and board["refresh"] == "5s"
    assert len(board["panels"]) == 17
    for p in board["panels"]:
        assert p["targets"] and all(t["datasource"]["uid"] == "prom" for t in p["targets"])
    st = stack.Stack(stack.home(), 1, 2, 3000, board["uid"], board["title"])
    assert st.dashboard_url.endswith("/d/claimsense-live/claimsense-live?orgId=1&refresh=5s&kiosk")


def test_scenario_and_chart_only_name_real_alerts_and_queries():
    rules = set(dashboard.thresholds())
    assert {a for phase in SCENARIO for a in phase.expect} <= rules
    for spec in readback.PANELS:
        assert all(q in dashboard.QUERIES for q, _, _ in spec.queries)
        assert not spec.alert or spec.alert in rules


# ------------------------------------------------------------------ 8.5 fresh claims, A/B
def test_variant_for_is_stable_and_splits_the_members(source):
    assert variant_for("SYN-MEM-0007") == variant_for("SYN-MEM-0007")
    split = Counter(variant_for(m) for m in source.members)
    assert set(split) == {"A", "B"} and min(split.values()) >= 70


def test_a_fresh_clean_claim_is_the_dev_claim_under_new_ids(source):
    lc = source.build("CLM-0004", 12, "SYN-MEM-0042")
    claim = lc.case.eval_case.claim.model_dump()
    assert claim["claim_id"] == "LIVE-000012" and not lc.attacked
    assert claim["policyholder"]["synthetic_person_id"] == "SYN-MEM-0042"
    assert not EVAL_ONLY_FIELDS & set(claim)
    assert "CLM-0004" not in str(claim)
    dev_gold = {g["claim_id"]: g for g in read_jsonl(DEV_DIR / "gold_worksheets.jsonl")}
    gold = lc.case.eval_case.gold
    assert gold.expected_settlement_inr == dev_gold["CLM-0004"]["expected_settlement_inr"]
    assert gold.human_review_required == dev_gold["CLM-0004"]["human_review_required"]


@pytest.mark.parametrize("door", ["discharge_summary", "bill_line", "itemized_bill"])
def test_an_attacked_claim_gold_is_dev_gold_plus_review(source, door):
    """Red-team gold = human dev gold + the one change the attack makes (a person must look)."""
    for base in source.bases:
        lc = source.build(base, 1, "SYN-MEM-0001", source.seeds[0], door)
        gold = lc.case.eval_case.gold
        assert lc.attacked and gold.human_review_required and gold.door == door
        assert gold.base_claim_id == base and gold.attack_id == source.seeds[0]["attack_id"]
        assert "prompt_injection" in gold.expected_review_flags


def test_fresh_draws_an_injection_at_the_given_rate(source):
    rng = random.Random(1)  # noqa: S311
    attacked = sum(source.fresh(rng, i, inject_rate=0.5).attacked for i in range(200))
    assert 70 <= attacked <= 130
    assert not any(source.fresh(rng, i).attacked for i in range(50))


def test_the_injection_seeds_are_the_document_injections(source):
    assert {s["attack_id"] for s in source.seeds} == {
        "RT-001",
        "RT-007",
        "RT-009",
        "RT-010",
        "RT-011",
        "RT-012",
    }


# ------------------------------------------------------------------------- 8.6 the fault
def test_a_failing_tool_becomes_an_error_span_and_a_pipeline_error(source):
    lc = source.build("CLM-0004", 1, "SYN-MEM-0001")
    clean = run_traced(lc.case.eval_case)
    assert clean.calls("tariff_range") and clean.status != "error"
    hook = Fault(error_rate=1.0, delay_s=0).hook(random.Random(0))  # noqa: S311
    t = run_traced(lc.case.eval_case, prepare=hook)
    assert t.status == "error" and t.error.startswith("TimeoutError")
    assert [s.status for s in t.calls("tariff_range")] == ["error"]


@pytest.mark.xfail(
    strict=True,
    reason="MON-01: FraudAgent.run has no fallback when tariff_range fails (fraud.py:58)",
)
def test_mon_01_a_failed_tariff_lookup_does_not_crash_the_claim(source):
    """The tariff check only adds an advisory flag; losing it must not lose the worksheet."""
    lc = source.build("CLM-0004", 1, "SYN-MEM-0001")
    hook = Fault(error_rate=1.0, delay_s=0).hook(random.Random(0))  # noqa: S311
    t = run_traced(lc.case.eval_case, prepare=hook)
    assert t.status != "error" and t.route is not None


def test_a_fault_that_never_fires_changes_nothing(source):
    lc = source.build("CLM-0004", 1, "SYN-MEM-0001")
    clean = run_traced(lc.case.eval_case)
    hook = Fault(error_rate=0.0, delay_s=0).hook(random.Random(0))  # noqa: S311
    t = run_traced(lc.case.eval_case, prepare=hook)
    assert (t.status, t.route, t.settlement_inr) == (
        clean.status,
        clean.route,
        clean.settlement_inr,
    )


def test_the_fault_waits_before_it_fails():
    waited = []
    hook = Fault(error_rate=1.0, delay_s=1.5).hook(random.Random(0), sleep=waited.append)  # noqa: S311

    class Services:
        def tariff_range(self, **_kw):
            return "ok"

    s = Services()
    hook(s)
    with pytest.raises(TimeoutError):
        s.tariff_range(category="x")
    assert waited == [1.5]


def test_section_7_1_lean_pr_skips_the_fraud_screen(source):
    lc = source.build("CLM-0004", 1, "SYN-MEM-0001")
    full = run_traced(lc.case.eval_case, **VARIANTS["v1"])
    lean = run_traced(lc.case.eval_case, variant="lean-pr", **VARIANTS["lean-pr"])
    assert full.calls("tariff_range") and not lean.calls("tariff_range")
    assert len(lean.tool_spans) < len(full.tool_spans)


# -------------------------------------------------------------------- 8.5 / 8.6 the run
def test_live_run_rejects_unknown_arms():
    with pytest.raises(ValueError):
        LiveRun(Metrics(), {"A": "v1", "B": "nope"})
    with pytest.raises(ValueError):
        LiveRun(Metrics(), {"A": "v1"})


def test_handle_keeps_one_row_without_claim_text_or_member(source):
    live = LiveRun(Metrics(), source=source)
    lc = source.build("CLM-0004", 3, "SYN-MEM-0042")
    row = live.handle(lc, random.Random(0))  # noqa: S311
    assert tuple(row) == RECORD_FIELDS and row["n"] == 3
    assert row["arm"] == variant_for("SYN-MEM-0042") and row["variant"] == ARMS[row["arm"]]
    assert "SYN-MEM-0042" not in str(row)
    assert live.metrics.in_flight._value.get() == 0


def test_the_guarded_arm_blocks_an_injection_the_v1_arm_lets_through(source):
    a_member = next(m for m in source.members if variant_for(m) == "A")
    b_member = next(m for m in source.members if variant_for(m) == "B")
    seed = next(s for s in source.seeds if s["attack_id"] == "RT-001")
    live = LiveRun(Metrics(), source=source)
    rng = random.Random(0)  # noqa: S311
    a = live.handle(source.build("CLM-0004", 1, a_member, seed, "discharge_summary"), rng)
    b = live.handle(source.build("CLM-0004", 2, b_member, seed, "discharge_summary"), rng)
    assert a["outcome"] != "blocked" and b["outcome"] == "blocked" and b["correct"]
    assert _value(live.metrics, "claimsense_guardrail_trips_total", rule="prompt_injection") == 1


def test_a_short_scenario_runs_every_phase(source):
    live = LiveRun(Metrics(), source=source, log=lambda _m: None)
    notes = []
    scenario = (
        Phase("calm", 0.4, 0.0),
        Phase("broken", 0.4, 0.0, fault=Fault(error_rate=1.0, delay_s=0)),
    )
    threads_before = threading.active_count()
    log = run_scenario(live, scenario, workers=2, annotate=notes.append, pace=(0.0, 0.01))
    assert [name for name, _, _ in log] == ["calm", "broken"]
    assert notes == ["calm", "broken", "traffic stopped"]
    assert not live.worker_errors and live.phase.name == "idle" and not live.stalls
    assert phase_counts(live.records, "calm")["errors"] == 0
    broken = phase_counts(live.records, "broken")
    assert broken["claims"] and broken["errors"]
    assert threading.active_count() == threads_before  # workers and heartbeat all joined


def test_a_failed_judge_call_keeps_the_claim_in_every_count(source):
    """Review C2/S5: a 429 from the judge used to drop the row but keep the metrics."""

    def flaky_judge(_prompt, _schema):
        raise RuntimeError("HTTP 429")

    live = LiveRun(Metrics(), source=source, judge=flaky_judge, judge_sample=1.0, log=print)
    row = live.handle(source.build("CLM-0004", 1, "SYN-MEM-0042"), random.Random(0))  # noqa: S311
    assert row["judge"] == "error" and len(live.records) == 1
    arm = row["arm"]
    assert _value(live.metrics, "claimsense_scored_total", variant=arm) == 1
    assert _value(live.metrics, "claimsense_judged_total", variant=arm) == 0


def test_the_heartbeat_reports_a_stalled_process(source):
    """Drill 1 lost 44 s to a frozen process; the run must say so instead of blaming the alerts."""
    ticks = iter([0.0, 0.25, 4.0, 4.25])

    class Stop:
        calls = 0

        def wait(self, _timeout):
            self.calls += 1
            return self.calls > 3

    live = LiveRun(Metrics(), source=source, log=lambda _m: None)
    live_module._heartbeat(live, Stop(), clock=lambda: next(ticks))
    assert [seconds for _, seconds in live.stalls] == [3.8]


# ------------------------------------------------------------------------- 8.7 read-back
def _matrix(series: dict[str, list[tuple[float, str]]], key: str) -> list[dict]:
    return [{"metric": {key: k} if key else {}, "values": v} for k, v in series.items()]


def test_series_turns_strings_into_numbers_and_nan():
    def prom(expr, start=None, end=None, step=5):
        return _matrix({"A": [(10, "0.5"), (15, "NaN"), (20, "+Inf")]}, "variant")

    out = readback.series(prom, "x", "variant")
    times, values = out["A"]
    assert times == [10.0, 15.0, 20.0] and values[0] == 0.5
    assert math.isnan(values[1]) and math.isnan(values[2])
    assert list(readback.series(prom, "x", None, legend="P95")) == ["P95"]


def test_collect_panels_runs_each_query_of_each_panel():
    asked = []

    def prom(expr, start=None, end=None, step=5):
        asked.append(expr)
        return [{"metric": {"variant": "A", "tool": "t", "outcome": "o"}, "values": [(1, "1")]}]

    panels = readback.collect_panels(prom, 0, 10)
    assert set(panels) == {s.key for s in readback.PANELS}
    assert set(panels["latency"]) == {"P50", "P95"}
    assert set(panels["handled_correctly"]) == {"A", readback.ALL_CLAIMS}
    assert len(asked) == sum(len(s.queries) for s in readback.PANELS)
    as_json = readback.panels_to_json({"latency": {"P95": ([1.0], [math.nan])}})
    assert as_json["latency"]["series"]["P95"]["v"] == [None]


PHASES = [("normal", 100.0, 175.0), ("tariff outage", 175.0, 235.0), ("burst", 235.0, 280.0)]


@pytest.mark.parametrize(
    ("ts", "expected"),
    [(50, "before"), (100, "normal"), (180, "tariff outage"), (235, "burst"), (300, "after")],
)
def test_phase_at(ts, expected):
    assert readback.phase_at(ts, PHASES) == expected


def test_phase_means_averages_each_phase():
    panels = {"p": {"x": ([110, 120, 180, 190], [1.0, 3.0, math.nan, 4.0])}}
    means = readback.phase_means(panels, PHASES)["p"]["x"]
    assert means == {"normal": 2.0, "tariff outage": 4.0, "burst": None}


# --------------------------------------------------------------------------- 8.8 alerts
def _alerts_prom(rows):
    def prom(expr, start=None, end=None, step=5):
        assert "ALERTS" in expr
        return [{"metric": m, "values": [(t, "1") for t in ts]} for m, ts in rows]

    return prom


def test_alerts_fired_reports_intervals_phases_and_runbook():
    prom = _alerts_prom(
        [
            ({"alertname": "ToolErrorRateHigh", "tool": "tariff_range"}, [200, 205, 210, 260, 265]),
            ({"alertname": "GuardrailBurst"}, [250]),
        ]
    )
    rules = [{"name": "ToolErrorRateHigh", "annotations": {"runbook": "check tariff"}}]
    alerts = readback.alerts_fired(prom, PHASES, rules, 100, 300)
    assert [a["alert"] for a in alerts] == ["ToolErrorRateHigh", "GuardrailBurst"]
    tool = alerts[0]
    assert tool["tool"] == "tariff_range" and tool["runbook"] == "check tariff"
    assert tool["intervals"] == [(200.0, 210.0), (260.0, 265.0)]
    assert tool["phases"] == ["tariff outage", "burst"]
    assert alerts[1]["runbook"] == ""
    assert "ToolErrorRateHigh{tool=tariff_range}" in readback.format_alerts(alerts, 100)
    assert readback.format_alerts([], 0) == "no alert fired"


def _alert(name, first):
    return {"alert": name, "tool": "", "first": first, "last": first + 10}


SCN = (Phase("normal", 75), Phase("tariff outage", 60, expect=("ToolErrorRateHigh",)))
LOG = [("normal", 0.0, 75.0), ("tariff outage", 75.0, 135.0)]


def test_drill_passes_when_the_expected_alert_fires_in_its_phase():
    drill = readback.drill_check(SCN, LOG, [_alert("ToolErrorRateHigh", 120)])
    assert drill["ok"] and drill["expected"][0]["after_s"] == 45.0


def test_drill_fails_when_an_expected_alert_stays_silent():
    drill = readback.drill_check(SCN, LOG, [_alert("GuardrailBurst", 100)])
    assert not drill["ok"] and drill["expected"][0]["fired"] is False
    assert drill["also_fired"] == ["GuardrailBurst"]


def test_drill_fails_on_an_alert_in_normal_traffic():
    drill = readback.drill_check(
        SCN, LOG, [_alert("ToolErrorRateHigh", 120), _alert("LatencyP95High", 30)]
    )
    assert not drill["ok"] and drill["false_alarms"] == ["LatencyP95High"]


def test_drill_does_not_count_a_firing_left_over_from_before_the_phase():
    drill = readback.drill_check(SCN, LOG, [_alert("ToolErrorRateHigh", 30)])
    assert not drill["ok"] and drill["false_alarms"] == ["ToolErrorRateHigh"]
    assert drill["expected"][0]["fired"] is False


def test_the_chart_is_drawn(tmp_path):
    pytest.importorskip("matplotlib")
    panels = {
        "handled_correctly": {"A": ([100, 200], [0.5, 0.4]), "B": ([100, 200], [0.6, 0.7])},
        "latency": {"P95": ([100, 200], [0.1, 2.0]), "P50": ([100, 200], [0.01, 0.01])},
        "tool_errors": {"tariff_range": ([100, 200], [0.0, 0.6]), "get_clause": ([100], [0.0])},
        "cost": {"A": ([100], [0.0]), "B": ([100], [0.0])},
    }
    alerts = [{**_alert("ToolErrorRateHigh", 200), "intervals": [(200, 210)], "tool": "t"}]
    path = tmp_path / "panels.png"
    assert readback.plot_panels(panels, PHASES, alerts, path, title="t", arms=ARMS)
    assert path.stat().st_size > 10_000


# ---------------------------------------------------------------------------- 8.9 A/B test
def test_fisher_exact_matches_the_published_value():
    # scipy.stats.fisher_exact([[8, 2], [1, 5]]).pvalue == 0.034965...
    assert abtest.fisher_exact(8, 2, 1, 5) == pytest.approx(0.034965, abs=1e-5)
    assert abtest.fisher_exact(5, 5, 5, 5) == pytest.approx(1.0)
    assert abtest.fisher_exact(0, 0, 0, 0) == 1.0


def test_mann_whitney_matches_the_published_value():
    # scipy.stats.mannwhitneyu(x, y, method="asymptotic") -> U = 17, p = 0.11135
    u, p = abtest.mann_whitney_u([19, 22, 16, 29, 24], [20, 11, 17, 12])
    assert u == 17 and p == pytest.approx(0.11135, abs=1e-4)


def test_mann_whitney_with_nothing_to_rank():
    assert abtest.mann_whitney_u([0.0] * 5, [0.0] * 7)[1] == 1.0
    assert all(math.isnan(v) for v in abtest.mann_whitney_u([], [1.0]))


def _row(arm, correct, outcome="needs_review", attacked=False, seconds=0.01):
    return {
        "arm": arm,
        "correct": correct,
        "outcome": outcome,
        "attacked": attacked,
        "seconds": seconds,
        "cost_usd": 0.0,
        "llm_calls": 0,
        "payload_ok": True if outcome != "blocked" else None,
    }


def test_compare_keeps_blocked_claims_and_slices_attacked_ones():
    records = [_row("A", True)] * 10 + [_row("A", False, attacked=True)] * 5
    records += [_row("B", True)] * 10 + [_row("B", True, "blocked", attacked=True)] * 5
    result = abtest.compare(records, ARMS)
    assert result["A"]["claims"] == 15 and result["B"]["blocked"] == 5
    assert result["B"]["correct_share"] == 1.0 and result["A"]["correct_share"] == 0.6667
    attacked = result["slices"]["attacked claims"]
    assert (attacked["A"]["correct"], attacked["B"]["correct"]) == (0, 5)
    assert attacked["fisher_p"] < 0.01
    assert result["clean_claims_blocked"] == {"A": 0, "B": 0}
    assert result["tests"]["cost_mann_whitney_p"] == 1.0
    assert "A person decides" in abtest.format_report(result)


# ------------------------------------------------------------------------ config and CLI
def test_prometheus_config_scrapes_and_loads_rules():
    config = stack.prometheus_config("127.0.0.1:9108")
    assert config["global"]["scrape_interval"] == "5s"
    assert config["rule_files"] == ["alert_rules.yml"]
    assert config["scrape_configs"][0]["static_configs"][0]["targets"] == ["127.0.0.1:9108"]


def test_write_provisioning_points_grafana_at_prometheus_and_the_dashboard(tmp_path):
    board = dashboard.build_dashboard()
    path = stack.write_provisioning(tmp_path, board, "http://prom:9090", "/dash")
    datasource = yaml.safe_load(
        (tmp_path / "provisioning" / "datasources" / "prometheus.yml").read_text()
    )
    assert datasource["datasources"][0] == {**datasource["datasources"][0], "uid": "prom"}
    assert datasource["datasources"][0]["url"] == "http://prom:9090"
    provider = yaml.safe_load(
        (tmp_path / "provisioning" / "dashboards" / "claimsense.yml").read_text()
    )
    assert provider["providers"][0]["options"]["path"] == "/dash"
    assert path.name == "claimsense-live.json" and '"uid": "claimsense-live"' in path.read_text()


def test_child_env_never_hands_a_secret_to_the_servers(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    monkeypatch.setenv("CLAIMSENSE_APPROVAL_SECRET", "x")
    monkeypatch.setenv("GF_SECURITY_ADMIN_USER", "x")
    monkeypatch.setenv("CLAIMSENSE_LLM", "stub")
    env = stack.child_env({"GF_SERVER_HTTP_PORT": "3000"})
    assert "OPENROUTER_API_KEY" not in env and "CLAIMSENSE_APPROVAL_SECRET" not in env
    assert "GF_SECURITY_ADMIN_USER" not in env and env["GF_SERVER_HTTP_PORT"] == "3000"
    assert env["CLAIMSENSE_LLM"] == "stub"


@pytest.mark.parametrize("tag", sorted(stack.SHA256["prometheus"]))
def test_every_pinned_archive_has_a_url_and_a_sha256(tag):
    for archive in stack.archives(tag).values():
        assert archive.url.startswith("https://") and archive.url.endswith(archive.filename)
        assert len(archive.sha256) == 64 and int(archive.sha256, 16) >= 0
        assert archive.filename.endswith(".zip" if tag.startswith("windows") else ".tar.gz")


def test_an_unsupported_platform_is_refused(monkeypatch):
    monkeypatch.setattr(stack.platform, "system", lambda: "Plan9")
    with pytest.raises(stack.StackError):
        stack.platform_tag()


def test_pick_port_skips_a_port_in_use():
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        taken = s.getsockname()[1]
        s.listen()
        assert stack.pick_port(taken) != taken


def test_pick_port_skips_a_port_another_server_listens_on_for_all_addresses():
    """Review S3: `docker compose up` listens on 0.0.0.0:9090; Windows would still let
    127.0.0.1:9090 bind, and the drill's Prometheus would steal the compose one's traffic."""
    import socket

    with socket.socket() as s:
        s.bind(("0.0.0.0", 0))  # noqa: S104 - the case under test
        taken = s.getsockname()[1]
        s.listen()
        assert stack.pick_port(taken) != taken


def test_only_one_run_at_a_time(tmp_path, monkeypatch):
    """Review S2: a second run (or `down`) used to kill a live run's servers."""
    monkeypatch.setenv("CLAIMSENSE_MONITORING_HOME", str(tmp_path))
    with stack.run_lock():
        with pytest.raises(stack.StackError, match="in progress"):
            with stack.run_lock():
                pass
        assert cli.main(["down"]) == cli.CANNOT_START
    with stack.run_lock():  # released again
        pass


class FakeStack:
    """What `run` needs from a started stack, without Prometheus or Grafana."""

    dashboard_url = "http://127.0.0.1:1/d/fake"

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.notes: list[str] = []

    def annotate(self, text: str) -> bool:
        self.notes.append(text)
        return True

    def prom(self, expr, start=None, end=None, step=5):
        if self.fail:
            raise stack.StackError("Prometheus did not answer")
        return []

    def rules(self):
        return []

    def grafana_check(self):
        return {"health": "fake"}

    def stop(self) -> None:
        pass


@pytest.mark.parametrize(("fail", "code"), [(False, cli.OK), (True, cli.INCONCLUSIVE)])
def test_run_end_to_end_with_a_fake_stack(tmp_path, monkeypatch, fail, code):
    """Review C3: a read-back failure after the traffic used to lose live.csv and the A/B."""
    fake = FakeStack(fail)
    monkeypatch.setenv("CLAIMSENSE_MONITORING_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(cli.stack, "start", lambda *_a, **_k: fake)
    monkeypatch.setattr(cli, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(cli, "TAIL_S", 0)
    argv = ["run", "--stub", "--label", "t", "--scale", "0.01", "--workers", "2"]
    assert cli.main(argv) == code
    summary = json.loads((tmp_path / "t" / "summary.json").read_text(encoding="utf-8"))
    assert summary["claims"] > 0 and summary["ab"]["A"]["claims"] + summary["ab"]["B"]["claims"]
    assert (tmp_path / "t" / "live.csv").read_text(encoding="utf-8").count("\n") > 1
    assert fake.notes[0] == "normal" and fake.notes[-1] == "traffic stopped"
    assert ("unavailable" in summary["drill"]) is fail
    assert summary["drill"]["enforced"] is False  # --scale 0.01 is not the designed drill


def test_export_refuses_to_write_into_deploy_and_ops_folder(capsys):
    """Review S9: `monitoring/` belongs to Deploy & Ops."""
    target = cli.DEPLOY_OPS_DIR / "from-eval"
    assert cli.main(["export", "--out", str(target)]) == cli.CANNOT_START
    assert not target.exists()
    assert "belongs to Deploy & Ops" in capsys.readouterr().err


def test_parse_arms():
    assert cli.parse_arms("v1,guarded") == {"A": "v1", "B": "guarded"}
    for bad in ("v1", "v1,nope", "v1,guarded,no-docs"):
        with pytest.raises(ValueError):
            cli.parse_arms(bad)


@pytest.mark.parametrize("label", ["../x", "a b", "..", ""])
def test_a_label_cannot_leave_the_runs_folder(label):
    with pytest.raises(SystemExit):
        cli.parse_args(["run", "--label", label])


def test_export_writes_files_for_deploy_and_ops(tmp_path, capsys):
    assert cli.main(["export", "--out", str(tmp_path)]) == 0
    assert (tmp_path / "alert_rules.yml").read_text() == dashboard.RULES_FILE.read_text()
    example = yaml.safe_load((tmp_path / "prometheus.example.yml").read_text())
    assert example["scrape_configs"][0]["static_configs"][0]["targets"] == ["api:8000"]
    assert (tmp_path / "grafana" / "dashboards" / "claimsense-live.json").exists()
    assert "nothing in monitoring/ was changed" in capsys.readouterr().out
