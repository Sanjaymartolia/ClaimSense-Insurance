# eval/monitoring: live monitoring for ClaimSense (L13 section 8)

Owner: Eval & Red-Team. The full write-up, with results, is
[docs/MONITORING_REPORT_CARD.md](../../docs/MONITORING_REPORT_CARD.md).

The agent suite (`eval/agent_suite`) grades the pipeline **before** a change ships, on fixed claims.
This package watches it **after** it ships: fresh claims keep arriving, metrics go to Prometheus,
Grafana draws them, and alert rules page a person when a tool breaks or an injection burst arrives.
It runs a real Prometheus and a real Grafana on this machine, without Docker.

## Run it

```bash
# once: download and verify Prometheus 3.13.4 and Grafana 12.4.12 (about 400 MB of downloads,
# 1.5 GB unpacked, in ~/.claimsense/monitoring_stack, outside the repo)
python -m eval.monitoring setup

# the four-minute incident drill, free (stub agents); about 6 minutes with start-up
python -m eval.monitoring run --stub --label my-drill --open

# leave the stack up afterwards to explore the dashboard (Ctrl+C stops it)
python -m eval.monitoring run --stub --label my-drill --keep

# stop servers that an interrupted run left behind
python -m eval.monitoring down

# config files for Deploy & Ops (alert rules, Prometheus example, Grafana dashboard + provisioning)
python -m eval.monitoring export --out runs/monitoring/export
```

A label that already exists is overwritten. The reports quote `drill-2`, `drill-3` and
`real-drill`: never reuse those labels (a reused label already lost the first drill's evidence).

`run` options: `--arms v1,guarded` (the two variants of the A/B test; any two from the agent
suite's `VARIANTS`), `--scale 0.5` (shorter phases; alerts may not have time to fire), `--workers 5`,
`--seed 0`, `--judge --judge-limit 20` (LLM judge on a sample of payloads; needs a key, costs money).

Without `--stub`, an `OPENROUTER_API_KEY` in the environment switches the agents to real models.
That costs money for every claim of the four minutes, so use `--stub` unless you mean it.

Exit code of `run`:

- **0:** the drill went as designed.
- **1:** an expected alert stayed silent, or an alert fired during normal traffic.
- **2:** the stack could not start, or another run is in progress.
- **3:** the run is inconclusive and must be rerun: the traffic generator stalled, or Prometheus
  could not be read back. `live.csv` and the A/B results are still written.

The drill is enforced only for the run it was designed on (stub mode, full length, arms
`v1,guarded`); other runs report it. Only one run at a time: a lock in the stack folder makes a
second `run`, or `down`, refuse while one is in progress.

## What it does

| Notebook | Here | File |
|---|---|---|
| 8.1 metrics from traces | `Metrics.export_trace(trace, correct)` on its own registry | `metrics.py` |
| 8.2 Prometheus, PromQL, alert rules | pinned, checksum-verified binaries; 6 rules | `stack.py`, `alert_rules.yml` |
| 8.3 / 8.4 dashboard as code, provisioned | 17 panels, opened at `/d/claimsense-live/...&kiosk` | `dashboard.py`, `stack.py` |
| 8.5 live traffic, A/B by user | fresh dev claims under new ids and synthetic members; A = `v1`, B = `guarded` | `live.py` |
| 8.6 the incident | normal 75 s, tariff tool outage 60 s, injection burst 45 s, recovered 45 s | `live.py` |
| 8.7 read the dashboard back | the same PromQL, saved as `panels.json` and drawn as `panels.png` | `readback.py` |
| 8.8 which alerts fired | `ALERTS` over the run, with each runbook line, and the drill check | `readback.py` |
| 8.9 A/B on live traffic | Fisher's exact (handled correctly), Mann-Whitney U (seconds, cost) | `abtest.py` |
| 8.10 clean up | servers stopped in `finally`; `down` for leftovers | `__main__.py`, `stack.py` |

Outputs go to `runs/monitoring/<label>/`: `summary.json` (everything the report quotes),
`live.csv` (one row per claim: no claim text, no member id), `panels.json`, `panels.png`.

## Rules this package keeps

- Fresh claims are built in memory from the 20 dev claims. Their gold is the human dev gold, plus
  the one change an attack makes when one is planted (as `eval/redteam/build_cases.py` does). No
  calculator output is used as gold, and `scenario_label` / `fixture_notes` are stripped.
- No claim id, member id or claim text is a metric label or a log line; errors are logged by
  exception type only.
- Prometheus, Grafana and the metrics page listen on 127.0.0.1 only. The servers get the
  environment without any variable that looks like a key, secret, token or password. Grafana's
  admin password is random per run and never written down.
- `monitoring/` and `docker-compose.yml` belong to Deploy & Ops and are not touched. `export`
  writes files for them to review, and refuses an `--out` inside `monitoring/`.
- Ports already answering (for example `docker compose up` on 9090 and 3000) are skipped, not
  shared.

## Remove it

Delete `~/.claimsense/monitoring_stack` (or `$CLAIMSENSE_MONITORING_HOME` if set). Nothing else
is installed. Run `python -m eval.monitoring down` first if a run was interrupted.

## Tests

`pytest eval/tests/test_monitoring.py -q`: no network, no binaries. The stack is checked through
the files it writes, the read-back through a fake Prometheus.
