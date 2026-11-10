"""Live monitoring for the ClaimSense pipeline (L13 section 8). Owner: Eval & Red-Team.

`eval.harness` and `eval.agent_suite` are offline: a fixed set of claims, scored once. This package
is the online half of the same lesson. It sends a stream of fresh synthetic claims through the real
pipeline, exports what every trace shows as Prometheus metrics, and runs a real Prometheus and a
real Grafana next to it, so alerts fire and a dashboard moves while an incident plays out.

    metrics.py       8.1  trace -> counters, histograms and a gauge on a /metrics page
    alert_rules.yml  8.2  six alert rules, each with a summary and a runbook line
    stack.py         8.2  download (checksum pinned), start and stop Prometheus and Grafana
    dashboard.py     8.3  the dashboard and Grafana's provisioning, as code
    live.py          8.5  fresh claims with a known answer, A/B routing by member, live traffic
                     8.6  the incident: normal -> tariff outage -> injection burst -> recovered
    readback.py      8.7  the same panels read back through PromQL, and a chart
                     8.8  which alerts fired, in which phase, with their runbook
    abtest.py        8.9  A/B on live traffic: Mann-Whitney U and Fisher's exact test

Run it with `python -m eval.monitoring run --stub --label <name>`. It only observes the product:
nothing under `src/` is edited, and nothing here settles a claim. See `README.md` next to this file
and `docs/MONITORING_REPORT_CARD.md`.
"""
