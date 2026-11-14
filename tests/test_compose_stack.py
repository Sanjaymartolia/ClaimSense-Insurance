"""The one-command stack, `docker compose up --build`: what a fresh clone gets, and the monitoring
files it mounts, kept equal to their sources in `eval/monitoring/`. No Docker needed here: the
CI `compose` job starts the containers."""

import json
from pathlib import Path

import yaml

from eval.monitoring import ops

ROOT = Path(__file__).resolve().parents[1]
SERVICES = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))["services"]


def bind_mounts(service: str) -> dict[str, Path]:
    """Container path -> host path, for the service's bind mounts (not its named volumes)."""
    mounts = {}
    for volume in SERVICES[service].get("volumes", []):
        host, container, *_ = volume.split(":")
        if host.startswith("./"):
            mounts[container] = ROOT / host
    return mounts


def host_path(service: str, container_path: str) -> Path:
    """Where a path inside the container comes from on the host, through a bind mount."""
    for container, host in bind_mounts(service).items():
        if container_path == container or container_path.startswith(container + "/"):
            return host / container_path[len(container) :].lstrip("/")
    raise AssertionError(f"{container_path} is not mounted into {service}")


def test_a_fresh_clone_gets_demo_reviewers_so_the_case_ui_can_sign_in():
    reviewers = SERVICES["api"]["environment"]["CLAIMSENSE_REVIEWERS"]
    assert reviewers.startswith("${CLAIMSENSE_REVIEWERS:-")  # a value in .env or the shell wins
    assert "local-alice=alice:adjudicator" in reviewers
    assert "local-bob=bob:senior" in reviewers


def test_every_port_listens_on_this_machine_only():
    for name, service in SERVICES.items():
        for port in service.get("ports", []):
            assert port.startswith("127.0.0.1:"), (name, port)


def test_every_mounted_monitoring_file_exists():
    for service in ("prometheus", "grafana"):
        for container, host in bind_mounts(service).items():
            assert host.exists(), f"{service} mounts {host} at {container}, which is missing"


def test_prometheus_scrapes_the_api_and_loads_the_edit_rate_alert():
    config = yaml.safe_load(host_path("prometheus", "/etc/prometheus/prometheus.yml").read_text())
    job = config["scrape_configs"][0]
    assert (job["metrics_path"], job["static_configs"][0]["targets"]) == ("/metrics/", ["api:8000"])
    rules = [host_path("prometheus", path) for path in config["rule_files"]]
    names = [
        rule["alert"]
        for path in rules
        for group in yaml.safe_load(path.read_text(encoding="utf-8"))["groups"]
        for rule in group["rules"]
        if "alert" in rule
    ]
    assert "AdjudicatorEditRateRising" in names


def test_grafana_opens_on_the_operations_dashboard_from_the_prometheus_container():
    grafana = SERVICES["grafana"]
    home = host_path("grafana", grafana["environment"]["GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH"])
    assert json.loads(home.read_text(encoding="utf-8"))["uid"] == ops.OPS_UID
    provisioning = "/etc/grafana/provisioning"
    source = yaml.safe_load(
        host_path("grafana", f"{provisioning}/datasources/prometheus.yml").read_text()
    )["datasources"][0]
    assert source["url"] == "http://prometheus:9090"
    provider = yaml.safe_load(
        host_path("grafana", f"{provisioning}/dashboards/claimsense.yml").read_text()
    )["providers"][0]
    assert host_path("grafana", provider["options"]["path"]) == home.parent


def test_the_mounted_alert_and_dashboard_equal_their_sources_in_eval_monitoring():
    rules = ROOT / "monitoring" / "rules"
    assert (rules / ops.OPS_RULES_FILE.name).read_bytes() == ops.OPS_RULES_FILE.read_bytes()
    assert (rules / ops.OPS_RULES_TEST.name).read_bytes() == ops.OPS_RULES_TEST.read_bytes()
    board = ROOT / "monitoring" / "grafana" / "dashboards" / f"{ops.OPS_UID}.json"
    assert json.loads(board.read_text(encoding="utf-8")) == ops.build_ops_dashboard()
