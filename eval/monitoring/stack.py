"""L13 section 8.2 and 8.3: a real Prometheus and a real Grafana on this machine, without Docker.

The notebook downloads both servers and starts them as plain processes. This module does the same
for ClaimSense, with four changes that matter outside a notebook:

- **Pinned checksums.** Each archive's SHA-256 is written below (taken from the publishers' own
  checksum files on 10 November 2026) and checked before anything is unpacked. A download that does
  not match is deleted and the run stops.
- **Outside the repository.** Binaries and run data live in `~/.claimsense/monitoring_stack`
  (override with `CLAIMSENSE_MONITORING_HOME`), about 1.5 GB. Nothing is written into the repo, and
  the folder is not inside OneDrive. Delete the folder to remove everything.
- **Local only.** Prometheus, Grafana and the metrics page bind to 127.0.0.1. Grafana lets an
  anonymous visitor *view*; the admin password is random per start and kept in memory.
- **No secrets handed to the servers.** The child processes get the environment without any
  variable whose name looks like a key, secret, token or password (rule 4).

The file in `monitoring/prometheus.yml` belongs to Deploy & Ops and is not touched: this stack
writes its own config under the run folder. `python -m eval.monitoring export` writes the same
files out for them to adopt.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import re
import secrets
import shutil
import signal
import socket
import subprocess  # noqa: S404 - starts the two pinned, checksum-verified servers; no shell
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

PROM_VERSION = "3.13.4"
GRAFANA_VERSION = "12.4.12"

#: SHA-256 of each release archive, by platform. Sources: `sha256sums.txt` on the Prometheus
#: GitHub release, and `<archive>.sha256` on dl.grafana.com. To move to a new version, change the
#: version above and every hash here together.
SHA256: dict[str, dict[str, str]] = {
    "prometheus": {
        "windows-amd64": "9f8950c9c5092366368b674b098250c82e998f62b90e2fbe16e1a3bf773a1a0e",
        "linux-amd64": "87f21a66f96c597a189cef8d640e8921b621fc17a9feff707c332c4f3b3ddd56",
        "linux-arm64": "ffa86c7d6e7f7e7dc8a79c81c5c2a6c9164464b79335f25613f4327c863b8489",
        "darwin-amd64": "87d99101a4dfdcbc750a17a85fbfdf3068f8b1e2d71ececa08b168a8f15d6319",
        "darwin-arm64": "0714a2812b2880078eeb10244d684981905fda568b50351ad6eea29397e55996",
    },
    "grafana": {
        "windows-amd64": "7e7c979015240f188a122400421cfe0c33d3ba5fc46d899376bb78bff2d65b31",
        "linux-amd64": "4d6d433f61a18710b4e1c2bd40709e63b220ab5b13c59328be313f56b5b83e55",
        "linux-arm64": "51e7abe19266dab73a5948b6856b5bb43bd350f6e1c7359f4ef9a8e532443d4b",
        "darwin-amd64": "066f6a1a16bfadddc20295abaa02271c0977ed9c0fae18ad41e6cebce92727d8",
        "darwin-arm64": "f8dcf60aae5a66e4d0f48c5ba9dab1685396c6e4e85c03d4c3cc6b30dbec0754",
    },
}

HOST = "127.0.0.1"
SCRAPE_JOB = "claimsense-live"
USER_AGENT = "claimsense-eval-monitoring"
Log = Callable[[str], None]

#: Environment variable names that are never passed to Prometheus or Grafana.
_SECRET_NAME = re.compile(r"KEY|SECRET|TOKEN|PASSWORD|PASSWD|CREDENTIAL", re.IGNORECASE)

#: Requests to this machine must not go through a configured HTTP proxy.
_LOCAL = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class StackError(RuntimeError):
    """The monitoring stack could not be downloaded, verified, started or queried."""


# ------------------------------------------------------------------------------ where it lives
def home() -> Path:
    override = os.environ.get("CLAIMSENSE_MONITORING_HOME")
    return Path(override) if override else Path.home() / ".claimsense" / "monitoring_stack"


def platform_tag() -> str:
    system = {"Windows": "windows", "Linux": "linux", "Darwin": "darwin"}.get(platform.system())
    arch = {"amd64": "amd64", "x86_64": "amd64", "arm64": "arm64", "aarch64": "arm64"}.get(
        platform.machine().lower()
    )
    tag = f"{system}-{arch}"
    if tag not in SHA256["prometheus"]:
        raise StackError(
            f"no pinned Prometheus/Grafana build for {platform.system()} {platform.machine()}. "
            f"Supported: {', '.join(sorted(SHA256['prometheus']))}."
        )
    return tag


@dataclass(frozen=True)
class Archive:
    tool: str
    filename: str
    url: str
    sha256: str


def archives(tag: str | None = None) -> dict[str, Archive]:
    """The two downloads for this platform."""
    tag = tag or platform_tag()
    ext = "zip" if tag.startswith("windows") else "tar.gz"
    prom = f"prometheus-{PROM_VERSION}.{tag}.{ext}"
    graf = f"grafana-{GRAFANA_VERSION}.{tag}.{ext}"
    return {
        "prometheus": Archive(
            "prometheus",
            prom,
            f"https://github.com/prometheus/prometheus/releases/download/v{PROM_VERSION}/{prom}",
            SHA256["prometheus"][tag],
        ),
        "grafana": Archive(
            "grafana",
            graf,
            f"https://dl.grafana.com/oss/release/{graf}",
            SHA256["grafana"][tag],
        ),
    }


# ------------------------------------------------------------------- download, verify, unpack
def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch(archive: Archive, directory: Path, log: Log = print) -> Path:
    """Download once to `<name>.part`, check the SHA-256, then rename. Returns the archive path.

    A file that is already there and matches is reused. A download that does not match the pinned
    hash is deleted and never unpacked.
    """
    dest = directory / archive.filename
    if dest.exists():
        if sha256_of(dest) == archive.sha256:
            return dest
        dest.unlink()
    directory.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    request = urllib.request.Request(archive.url, headers={"User-Agent": USER_AGENT})  # noqa: S310
    log(f"downloading {archive.filename} ...")
    try:
        with urllib.request.urlopen(request, timeout=60) as response, part.open("wb") as out:  # noqa: S310 - fixed https URL built from the pinned version
            total = int(response.headers.get("Content-Length") or 0)
            done, next_mark = 0, 0.25
            while block := response.read(1 << 20):
                out.write(block)
                done += len(block)
                if total and done / total >= next_mark:
                    log(f"  {archive.tool}: {done / total:.0%} of {total / 1e6:.0f} MB")
                    next_mark += 0.25
    except (urllib.error.URLError, OSError) as e:
        part.unlink(missing_ok=True)
        raise StackError(f"could not download {archive.url}: {e}") from e
    got = sha256_of(part)
    if got != archive.sha256:
        part.unlink()
        raise StackError(
            f"{archive.filename}: SHA-256 is {got}, expected {archive.sha256}. "
            "The download was deleted and nothing was unpacked."
        )
    part.replace(dest)
    return dest


def unpack(archive_path: Path, into: Path, sha256: str) -> None:
    """Unpack into an empty folder of its own. A marker file records which archive is in it."""
    marker = into / ".unpacked"
    if marker.exists() and marker.read_text(encoding="utf-8").strip() == sha256:
        return
    if into.exists():
        _rmtree(into)
    into.mkdir(parents=True)
    if archive_path.name.endswith(".zip"):
        with zipfile.ZipFile(archive_path) as z:
            z.extractall(into)  # noqa: S202 - checksum verified; zipfile strips unsafe paths
    else:
        with tarfile.open(archive_path) as tar:
            tar.extractall(into, filter="data")  # noqa: S202 - checksum verified; data filter
    marker.write_text(sha256, encoding="utf-8")


@dataclass(frozen=True)
class Binaries:
    prometheus: Path
    grafana: Path
    grafana_home: Path


def _one(root: Path, pattern: str, what: str) -> Path:
    hits = sorted(p for p in root.glob(pattern) if p.is_file())
    if not hits:
        raise StackError(f"{what} not found under {root} (looked for {pattern})")
    return hits[0]


def ensure_binaries(log: Log = print) -> Binaries:
    """Download, verify and unpack both servers if they are not already there."""
    exe = ".exe" if os.name == "nt" else ""
    found: dict[str, Path] = {}
    for tool, archive in archives().items():
        folder = home() / tool
        unpacked = folder / "unpacked"
        marker = unpacked / ".unpacked"
        if not (marker.exists() and marker.read_text(encoding="utf-8").strip() == archive.sha256):
            path = fetch(archive, folder, log)
            log(f"unpacking {archive.filename} ...")
            unpack(path, unpacked, archive.sha256)
        pattern = f"*/prometheus{exe}" if tool == "prometheus" else f"*/bin/grafana{exe}"
        found[tool] = _one(unpacked, pattern, tool)
    return Binaries(found["prometheus"], found["grafana"], found["grafana"].parent.parent)


# ------------------------------------------------------------------------------- small helpers
def _answers(host: str, port: int) -> bool:
    """Something already accepts connections there (for example `docker compose up`, which
    listens on 0.0.0.0: Windows still lets 127.0.0.1 bind the same port and steal its traffic)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex((host, port)) == 0


def pick_port(preferred: int, host: str = HOST, tries: int = 50) -> int:
    """The first free port at or above `preferred`."""
    for port in range(preferred, preferred + tries):
        if _answers(host, port):
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, port))
            except OSError:
                continue
            return port
    raise StackError(f"no free port in {preferred}-{preferred + tries - 1}")


@contextmanager
def run_lock() -> Iterator[None]:
    """One run at a time on this machine. A second `run` (or `down`) would otherwise kill this
    run's servers and delete its folder. The OS drops the lock if the process dies."""
    home().mkdir(parents=True, exist_ok=True)
    with (home() / "run.lock").open("a+b") as f:
        try:
            if os.name == "nt":
                import msvcrt

                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            raise StackError(
                "another monitoring run is in progress on this machine. Wait for it to end, "
                "or press Ctrl+C in its terminal."
            ) from e
        try:
            yield
        finally:
            if os.name == "nt":
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)


def child_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """This process's environment for a child: no secrets, no stray Grafana settings."""
    env = {
        k: v
        for k, v in os.environ.items()
        if not _SECRET_NAME.search(k) and not k.upper().startswith("GF_")
    }
    env.update(extra or {})
    return env


def _get(url: str, timeout: float = 5.0, headers: dict[str, str] | None = None) -> Any:
    request = urllib.request.Request(url, headers=headers or {})  # noqa: S310 - 127.0.0.1 only
    with _LOCAL.open(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def wait_for(
    url: str,
    what: str,
    timeout: float = 240.0,
    proc: subprocess.Popen | None = None,
    log_path: Path | None = None,
) -> None:
    """Poll once a second until `url` answers 200. Fails early if the process has died."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc is not None and proc.poll() is not None:
            raise StackError(
                f"{what} exited with code {proc.returncode}.\n{_tail(log_path)}".rstrip()
            )
        try:
            with _LOCAL.open(url, timeout=2) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(1)
    raise StackError(f"{what} was not ready after {timeout:.0f} s.\n{_tail(log_path)}".rstrip())


def _tail(path: Path | None, lines: int = 15) -> str:
    if path is None or not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
    return f"last lines of {path}:\n" + "\n".join(text)


def _rmtree(path: Path) -> None:
    """Remove a folder. Windows releases a killed process's files a moment late, so retry."""
    for attempt in range(10):
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except OSError:
            if attempt == 9:
                raise
            time.sleep(0.5)


# -------------------------------------------------------------------------- processes and pids
def _spawn(cmd: list[str], cwd: Path, env: dict[str, str], log_path: Path) -> subprocess.Popen:
    """Start a server in its own process group, so Ctrl+C reaches this program first."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    kwargs: dict[str, Any] = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    else:
        kwargs["start_new_session"] = True
    with log_path.open("ab") as log_file:
        return subprocess.Popen(  # noqa: S603 - fixed argument list, binary verified by checksum
            cmd,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            **kwargs,
        )


def _image_name(pid: int) -> str:
    """The executable name of a running process, or "" if there is none with that pid."""
    try:
        if os.name == "nt":
            out = subprocess.run(  # noqa: S603
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],  # noqa: S607
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            ).stdout
            first = out.strip().splitlines()[0] if out.strip() else ""
            return first.split(",")[0].strip('"').lower() if first.startswith('"') else ""
        out = subprocess.run(  # noqa: S603
            ["ps", "-p", str(pid), "-o", "comm="],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        ).stdout
        return Path(out.strip()).name.lower()
    except (OSError, subprocess.SubprocessError):
        return ""


def _kill(pid: int) -> None:
    try:
        if os.name == "nt":
            subprocess.run(  # noqa: S603
                ["taskkill", "/PID", str(pid), "/T", "/F"],  # noqa: S607
                capture_output=True,
                timeout=30,
                check=False,
            )
        else:
            os.kill(pid, signal.SIGTERM)
    except (OSError, subprocess.SubprocessError):
        pass


def _pid_file() -> Path:
    return home() / "pids.json"


def _record_pids(pids: dict[str, int]) -> None:
    home().mkdir(parents=True, exist_ok=True)
    _pid_file().write_text(json.dumps(pids), encoding="utf-8")


def stop_leftovers(log: Log = print) -> int:
    """Stop servers a previous run left behind. Only kills a pid that is still the same program."""
    path = _pid_file()
    if not path.exists():
        return 0
    try:
        pids = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pids = {}
    stopped = 0
    for name, pid in pids.items():
        if isinstance(pid, int) and _image_name(pid).startswith(name):
            _kill(pid)
            stopped += 1
            log(f"stopped a leftover {name} (pid {pid})")
    path.unlink(missing_ok=True)
    if stopped:
        time.sleep(1.0)
    return stopped


# ------------------------------------------------------------------------------- config files
def prometheus_config(metrics_target: str, rules_file: str = "alert_rules.yml") -> dict:
    """8.2: scrape the metrics page every 5 s and evaluate the alert rules every 5 s."""
    return {
        "global": {"scrape_interval": "5s", "evaluation_interval": "5s"},
        "rule_files": [rules_file],
        "scrape_configs": [
            {"job_name": SCRAPE_JOB, "static_configs": [{"targets": [metrics_target]}]}
        ],
    }


def datasource_config(prometheus_url: str) -> dict:
    return {
        "apiVersion": 1,
        "datasources": [
            {
                "name": "Prometheus",
                "uid": "prom",
                "type": "prometheus",
                "access": "proxy",
                "url": prometheus_url,
                "isDefault": True,
                "jsonData": {"timeInterval": "5s"},
            }
        ],
    }


def dashboard_provider_config(dashboards_dir: str) -> dict:
    return {
        "apiVersion": 1,
        "providers": [{"name": "claimsense", "type": "file", "options": {"path": dashboards_dir}}],
    }


def write_provisioning(
    root: Path, dashboard: dict, prometheus_url: str, dashboards_dir: str | None = None
) -> Path:
    """8.3: Grafana's provisioning folder. Returns the dashboard JSON path.

    `dashboards_dir` is the path Grafana will read the dashboards from, if it differs from where
    they are written now (the `export` command writes files for a container to mount).
    """
    for sub in ("datasources", "dashboards", "plugins", "alerting"):
        (root / "provisioning" / sub).mkdir(parents=True, exist_ok=True)
    dash_dir = root / "dashboards"
    dash_dir.mkdir(parents=True, exist_ok=True)
    (root / "provisioning" / "datasources" / "prometheus.yml").write_text(
        yaml.safe_dump(datasource_config(prometheus_url), sort_keys=False), encoding="utf-8"
    )
    (root / "provisioning" / "dashboards" / "claimsense.yml").write_text(
        yaml.safe_dump(
            dashboard_provider_config(dashboards_dir or dash_dir.as_posix()), sort_keys=False
        ),
        encoding="utf-8",
    )
    dash_file = dash_dir / f"{dashboard['uid']}.json"
    dash_file.write_text(json.dumps(dashboard, indent=2), encoding="utf-8")
    return dash_file


# ----------------------------------------------------------------------------------- the stack
@dataclass
class Stack:
    """A running Prometheus and Grafana, and the three calls the rest of the package needs."""

    run_dir: Path
    metrics_port: int
    prom_port: int
    grafana_port: int
    dashboard_uid: str
    dashboard_title: str
    _password: str = field(default="", repr=False)
    procs: dict[str, subprocess.Popen] = field(default_factory=dict, repr=False)

    @property
    def prom_url(self) -> str:
        return f"http://{HOST}:{self.prom_port}"

    @property
    def grafana_url(self) -> str:
        return f"http://{HOST}:{self.grafana_port}"

    @property
    def dashboard_url(self) -> str:
        """8.4: the dashboard, refreshing every 5 s, without Grafana's menus."""
        slug = re.sub(r"[^a-z0-9]+", "-", self.dashboard_title.lower()).strip("-")
        return f"{self.grafana_url}/d/{self.dashboard_uid}/{slug}?orgId=1&refresh=5s&kiosk"

    # ------------------------------------------------------------------ Prometheus
    def prom(
        self, expr: str, start: float | None = None, end: float | None = None, step: int = 5
    ) -> list[dict]:
        """Run PromQL. No `start`: an instant query. With `start` and `end`: a range query."""
        if start is None:
            path, params = "query", {"query": expr}
        else:
            path = "query_range"
            params = {"query": expr, "start": start, "end": end or time.time(), "step": step}
        try:
            body = _get(
                f"{self.prom_url}/api/v1/{path}?{urllib.parse.urlencode(params)}", timeout=30
            )
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:300]
            raise StackError(f"Prometheus rejected {expr!r}: {detail}") from e
        except (urllib.error.URLError, OSError) as e:
            raise StackError(f"Prometheus did not answer: {e}") from e
        if body.get("status") != "success":
            raise StackError(f"Prometheus query failed for {expr!r}: {body}")
        return body["data"]["result"]

    def targets(self) -> list[dict]:
        """Each scrape target's URL and health (`up` once the first scrape succeeded)."""
        active = _get(f"{self.prom_url}/api/v1/targets")["data"]["activeTargets"]
        return [{"url": t["scrapeUrl"], "health": t["health"]} for t in active]

    def rules(self) -> list[dict]:
        """Every loaded alert rule with its annotations (summary, runbook)."""
        groups = _get(f"{self.prom_url}/api/v1/rules")["data"]["groups"]
        return [
            {"name": r["name"], "annotations": r.get("annotations") or {}, "query": r["query"]}
            for g in groups
            for r in g["rules"]
            if r.get("type") == "alerting"
        ]

    # --------------------------------------------------------------------- Grafana
    def _admin(self) -> dict[str, str]:
        token = base64.b64encode(f"admin:{self._password}".encode()).decode()
        return {"Authorization": f"Basic {token}"}

    def annotate(self, text: str) -> bool:
        """8.5: mark a moment on the dashboard. Never raises: a lost note must not stop traffic."""
        body = {
            "dashboardUID": self.dashboard_uid,
            "time": int(time.time() * 1000),
            "text": text,
            "tags": ["phase"],
        }
        request = urllib.request.Request(  # noqa: S310 - 127.0.0.1 only
            f"{self.grafana_url}/api/annotations",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", **self._admin()},
            method="POST",
        )
        try:
            with _LOCAL.open(request, timeout=5) as response:
                return response.status == 200
        except (urllib.error.URLError, OSError):
            return False

    def grafana_check(self) -> dict:
        """Proof that the dashboard is really served: health, dashboard found, a live query."""
        out: dict[str, Any] = {"health": None, "dashboard_found": False, "datasource_query": None}
        try:
            out["health"] = _get(f"{self.grafana_url}/api/health").get("database")
            query = urllib.parse.urlencode({"query": self.dashboard_title})
            hits = _get(f"{self.grafana_url}/api/search?{query}")
            out["dashboard_found"] = any(h.get("uid") == self.dashboard_uid for h in hits)
            board = _get(f"{self.grafana_url}/api/dashboards/uid/{self.dashboard_uid}")
            out["panels"] = len((board.get("dashboard") or {}).get("panels") or [])
            up = urllib.parse.urlencode({"query": f'up{{job="{SCRAPE_JOB}"}}'})
            proxied = _get(
                f"{self.grafana_url}/api/datasources/proxy/uid/prom/api/v1/query?{up}",
                headers=self._admin(),
            )
            result = proxied.get("data", {}).get("result") or []
            out["datasource_query"] = result[0]["value"][1] if result else "no data"
        except (urllib.error.URLError, OSError, KeyError, ValueError) as e:
            out["error"] = f"{type(e).__name__}: {e}"
        return out

    # ------------------------------------------------------------------------ stop
    def stop(self) -> None:
        for proc in self.procs.values():
            if proc.poll() is None:
                _kill(proc.pid)
        for proc in self.procs.values():
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
        self.procs.clear()
        _pid_file().unlink(missing_ok=True)


def start(
    dashboard: dict, rules_file: Path, metrics_port: int, log: Log = print, settle_s: float = 6.0
) -> Stack:
    """Start Prometheus and Grafana for one run. The metrics page must already be serving.

    Returns once Prometheus is ready, its rules are loaded, the scrape target is up, and Grafana
    has loaded the dashboard. Raises `StackError`, with the server's last log lines, otherwise.
    """
    stop_leftovers(log)
    binaries = ensure_binaries(log)
    run = home() / "run"
    try:
        if run.exists():
            _rmtree(run)
        run.mkdir(parents=True)
    except OSError as e:  # a file still held open by a server that would not stop
        raise StackError(
            f"could not reset {run}: {e}. Run `python -m eval.monitoring down`."
        ) from e

    stack = Stack(
        run_dir=run,
        metrics_port=metrics_port,
        prom_port=pick_port(9090),
        grafana_port=pick_port(3000),
        dashboard_uid=dashboard["uid"],
        dashboard_title=dashboard["title"],
        _password=secrets.token_urlsafe(24),
    )
    try:
        # --- Prometheus
        (run / "prometheus.yml").write_text(
            yaml.safe_dump(prometheus_config(f"{HOST}:{metrics_port}"), sort_keys=False),
            encoding="utf-8",
        )
        shutil.copyfile(rules_file, run / "alert_rules.yml")
        prom_log = run / "prometheus.log"
        stack.procs["prometheus"] = _spawn(
            [
                str(binaries.prometheus),
                f"--config.file={run / 'prometheus.yml'}",
                f"--storage.tsdb.path={run / 'tsdb'}",
                f"--web.listen-address={HOST}:{stack.prom_port}",
                "--log.level=warn",
            ],
            cwd=run,
            env=child_env(),
            log_path=prom_log,
        )
        _record_pids({k: p.pid for k, p in stack.procs.items()})
        wait_for(
            f"{stack.prom_url}/-/ready", "Prometheus", 120, stack.procs["prometheus"], prom_log
        )
        log(f"Prometheus {PROM_VERSION} ready at {stack.prom_url}")

        # --- Grafana
        graf = run / "grafana"
        dash_file = write_provisioning(graf, dashboard, stack.prom_url)
        for sub in ("data", "logs", "plugins"):  # Grafana does not create its data folder itself
            (graf / sub).mkdir(parents=True, exist_ok=True)
        graf_log = run / "grafana.log"
        stack.procs["grafana"] = _spawn(
            [str(binaries.grafana), "server", "--homepath", str(binaries.grafana_home)],
            cwd=binaries.grafana_home,
            env=child_env(
                {
                    "GF_SERVER_HTTP_ADDR": HOST,
                    "GF_SERVER_HTTP_PORT": str(stack.grafana_port),
                    "GF_PATHS_PROVISIONING": str(graf / "provisioning"),
                    "GF_PATHS_DATA": str(graf / "data"),
                    "GF_PATHS_LOGS": str(graf / "logs"),
                    "GF_PATHS_PLUGINS": str(graf / "plugins"),
                    "GF_AUTH_ANONYMOUS_ENABLED": "true",
                    "GF_AUTH_ANONYMOUS_ORG_ROLE": "Viewer",
                    "GF_AUTH_DISABLE_LOGIN_FORM": "true",
                    "GF_SECURITY_ADMIN_PASSWORD": stack._password,
                    "GF_USERS_DEFAULT_THEME": "light",
                    "GF_ANALYTICS_REPORTING_ENABLED": "false",
                    "GF_ANALYTICS_CHECK_FOR_UPDATES": "false",
                    "GF_ANALYTICS_CHECK_FOR_PLUGIN_UPDATES": "false",
                    "GF_NEWS_NEWS_FEED_ENABLED": "false",
                    "GF_PLUGINS_PREINSTALL_DISABLED": "true",
                    "GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH": str(dash_file),
                }
            ),
            log_path=graf_log,
        )
        _record_pids({k: p.pid for k, p in stack.procs.items()})
        wait_for(
            f"{stack.grafana_url}/api/health", "Grafana", 240, stack.procs["grafana"], graf_log
        )
        deadline = time.monotonic() + 30
        while not stack.grafana_check()["dashboard_found"]:
            if time.monotonic() > deadline:
                raise StackError(f"Grafana did not load the dashboard.\n{_tail(graf_log)}")
            time.sleep(1)
        log(f"Grafana {GRAFANA_VERSION} ready at {stack.grafana_url}")

        # --- what Prometheus actually loaded (8.2)
        time.sleep(settle_s)  # one scrape interval, so the target has a health
        wanted = {
            r["alert"]
            for g in yaml.safe_load(rules_file.read_text(encoding="utf-8"))["groups"]
            for r in g["rules"]
        }
        loaded = {r["name"] for r in stack.rules()}
        if wanted - loaded:
            raise StackError(f"Prometheus did not load these rules: {sorted(wanted - loaded)}")
        down = [t for t in stack.targets() if t["health"] != "up"]
        if down:
            raise StackError(f"the scrape target is not up: {down}. Is the metrics page serving?")
        return stack
    except BaseException:
        stack.stop()
        raise
