"""Notebook section 4: Jaeger, a trace viewer, on this machine without Docker.

The notebook downloads Jaeger v2 and starts it as one process: spans in over OTLP, a web UI and a
query API out. This module does the same, with the safeguards of `eval.monitoring.stack` (whose
download, checksum, unpack and process helpers it reuses):

- **Pinned checksums.** The SHA-256 of each archive below is the one Jaeger publishes in
  `jaeger-2.22.0.sha256sum.txt` on the v2.22.0 release; GitHub's asset digests agree (checked on
  11 November 2026). A download that does not match is deleted and never unpacked.
- **Outside the repository.** `~/.claimsense/observability_stack` (override with
  `CLAIMSENSE_OBSERVABILITY_HOME`), about 250 MB unpacked. Delete it to remove everything.
- **Local only, and less than the default.** Jaeger's stock config also opens gRPC, Jaeger-thrift
  and Zipkin receivers, a sampling server, an MCP endpoint and a metrics port. `config()` keeps
  only OTLP over HTTP in, and the UI and query API out, all on 127.0.0.1, with storage in memory.
- **No secrets handed over.** The child gets the environment without any key-like variable and
  without any `OTEL_*` variable (those can hold a Langfuse or LangSmith credential).
"""

from __future__ import annotations

import json
import os
import platform
import subprocess  # noqa: S404 - starts the pinned, checksum-verified Jaeger binary; no shell
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import yaml

from eval.monitoring import stack as _stack

VERSION = "2.22.0"
HOST = "127.0.0.1"
SERVICE = "claimsense"

#: SHA-256 of each release archive, from the publisher's checksum file (see the module docstring).
SHA256: dict[str, str] = {
    "windows-amd64": "0fe3343c49e44e3c1e86846767286a3d7d16c8f89fff6e285e7e5a8bd34442c8",
    "linux-amd64": "cb0c0be9a4b8fba424bbbc6217b0feb0adeea3bca5b73a83db1af31bb7d34389",
    "linux-arm64": "c3dbcd54a8b16cdd277445923a7f79b1144cbdbbfd55e473dc0f32a45bd94e73",
    "darwin-amd64": "6cdeeee5cb98d0f0d071be1848351d97405d85ab3dfa9fe46e08e216aeed0861",
    "darwin-arm64": "856f82c353833d85d144e2bb59ecf1156bb431d62748d62e59360b5bdc00fc63",
}

Log = Callable[[str], None]


class JaegerError(RuntimeError):
    """Jaeger could not be downloaded, verified, started or queried."""


# ------------------------------------------------------------------------------ where it lives
def home() -> Path:
    override = os.environ.get("CLAIMSENSE_OBSERVABILITY_HOME")
    return Path(override) if override else Path.home() / ".claimsense" / "observability_stack"


def platform_tag() -> str:
    system = {"Windows": "windows", "Linux": "linux", "Darwin": "darwin"}.get(platform.system())
    arch = {"amd64": "amd64", "x86_64": "amd64", "arm64": "arm64", "aarch64": "arm64"}.get(
        platform.machine().lower()
    )
    tag = f"{system}-{arch}"
    if tag not in SHA256:
        raise JaegerError(
            f"no pinned Jaeger build for {platform.system()} {platform.machine()}. "
            f"Supported: {', '.join(sorted(SHA256))}."
        )
    return tag


def archive(tag: str | None = None) -> _stack.Archive:
    tag = tag or platform_tag()
    ext = "zip" if tag.startswith("windows") else "tar.gz"
    name = f"jaeger-{VERSION}-{tag}.{ext}"
    return _stack.Archive(
        "jaeger",
        name,
        f"https://github.com/jaegertracing/jaeger/releases/download/v{VERSION}/{name}",
        SHA256[tag],
    )


def ensure_binary(log: Log = print) -> Path:
    """Download, verify and unpack Jaeger if it is not already there. Returns the executable."""
    arc = archive()
    folder = home() / "jaeger"
    unpacked = folder / "unpacked"
    marker = unpacked / ".unpacked"
    try:
        if not (marker.exists() and marker.read_text(encoding="utf-8").strip() == arc.sha256):
            path = _stack.fetch(arc, folder, log)
            log(f"unpacking {arc.filename} ...")
            _stack.unpack(path, unpacked, arc.sha256)
        exe = ".exe" if os.name == "nt" else ""
        hits = sorted(p for p in unpacked.rglob(f"jaeger{exe}") if p.is_file())
    except _stack.StackError as e:
        raise JaegerError(str(e)) from e
    if not hits:
        raise JaegerError(f"the jaeger executable was not found under {unpacked}")
    return hits[0]


# ---------------------------------------------------------------------------------- config
def config(otlp_port: int, ui_port: int, grpc_port: int) -> dict:
    """Jaeger v2 config: OTLP/HTTP in, query UI and API out, memory storage, 127.0.0.1 only."""
    return {
        "service": {
            "extensions": ["jaeger_storage", "jaeger_query"],
            "pipelines": {
                "traces": {
                    "receivers": ["otlp"],
                    "processors": ["batch"],
                    "exporters": ["jaeger_storage_exporter"],
                }
            },
            "telemetry": {
                "resource": {"service.name": "jaeger"},
                "metrics": {"level": "none"},  # no metrics server on 0.0.0.0:8888
                "logs": {"level": "warn"},
            },
        },
        "extensions": {
            "jaeger_storage": {"backends": {"memstore": {"memory": {"max_traces": 100000}}}},
            "jaeger_query": {
                "storage": {"traces": "memstore"},
                "enable_tracing": False,  # Jaeger's own spans would crowd the service list
                "http": {"endpoint": f"{HOST}:{ui_port}"},
                "grpc": {"endpoint": f"{HOST}:{grpc_port}"},
            },
        },
        "receivers": {"otlp": {"protocols": {"http": {"endpoint": f"{HOST}:{otlp_port}"}}}},
        "processors": {"batch": {}},
        "exporters": {"jaeger_storage_exporter": {"trace_storage": "memstore"}},
    }


# --------------------------------------------------------------------------------- lock, pids
@contextmanager
def run_lock() -> Iterator[None]:
    """One `run` at a time on this machine; `down` refuses while one is in progress."""
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
            raise JaegerError(
                "another observability run is in progress on this machine. Wait for it, "
                "or press Ctrl+C in its terminal."
            ) from e
        try:
            yield
        finally:
            if os.name == "nt":
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)


def _pid_file() -> Path:
    return home() / "pids.json"


def stop_leftovers(log: Log = print) -> int:
    """Stop a Jaeger an earlier run left behind. Only kills a pid that is still Jaeger."""
    path = _pid_file()
    if not path.exists():
        return 0
    try:
        pid = int(json.loads(path.read_text(encoding="utf-8")).get("jaeger", 0))
    except (OSError, ValueError, json.JSONDecodeError):
        pid = 0
    stopped = 0
    if pid and _stack._image_name(pid).startswith("jaeger"):
        _stack._kill(pid)
        stopped = 1
        log(f"stopped a leftover jaeger (pid {pid})")
        time.sleep(1.0)
    path.unlink(missing_ok=True)
    return stopped


# ---------------------------------------------------------------------------------- running
def parse_traces(text: str) -> dict:
    """Jaeger API v3 answers `{"result": {"resourceSpans": [...]}}`; a streamed answer is several
    such objects one after another. Returns one OTLP body with every resourceSpans entry."""
    decoder, pos, spans = json.JSONDecoder(), 0, []
    text = text.strip()
    while pos < len(text):
        obj, end = decoder.raw_decode(text, pos)
        result = obj.get("result", obj) if isinstance(obj, dict) else {}
        spans.extend(result.get("resourceSpans") or [])
        pos = end
        while pos < len(text) and text[pos].isspace():
            pos += 1
    return {"resourceSpans": spans}


def _rfc3339(ts: float) -> str:
    return (
        datetime.fromtimestamp(ts, tz=UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    )


@dataclass
class Jaeger:
    """A running Jaeger and the three reads the CLI needs (notebook backup slide 2)."""

    run_dir: Path
    otlp_port: int
    ui_port: int
    grpc_port: int
    proc: subprocess.Popen | None = field(default=None, repr=False)

    @property
    def otlp_endpoint(self) -> str:
        return f"http://{HOST}:{self.otlp_port}/v1/traces"

    @property
    def ui_url(self) -> str:
        return f"http://{HOST}:{self.ui_port}"

    def trace_url(self, trace_id: str) -> str:
        return f"{self.ui_url}/trace/{trace_id}"

    def _read(
        self, path: str, params: dict | None = None, timeout: float = 30.0, missing_ok: bool = False
    ) -> str:
        query = f"?{urllib.parse.urlencode(params)}" if params else ""
        request = urllib.request.Request(f"{self.ui_url}{path}{query}")  # noqa: S310 - 127.0.0.1
        try:
            with _stack._LOCAL.open(request, timeout=timeout) as response:
                return response.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            if missing_ok and e.code == 404:  # API v3 answers 404 "No traces found"
                return ""
            raise JaegerError(f"Jaeger did not answer {path}: {e}") from e
        except (urllib.error.URLError, OSError) as e:
            raise JaegerError(f"Jaeger did not answer {path}: {e}") from e

    def services(self) -> list[str]:
        body = json.loads(self._read("/api/v3/services"))
        return list(body.get("services") or [])

    def get_trace(self, trace_id: str) -> dict:
        return parse_traces(self._read(f"/api/v3/traces/{trace_id}", missing_ok=True))

    def find_traces(self, start: float, end: float, depth: int = 1000) -> dict:
        """Every trace of the ClaimSense service that started in [start, end] (unix seconds)."""
        return parse_traces(
            self._read(
                "/api/v3/traces",
                {
                    "query.service_name": SERVICE,
                    "query.start_time_min": _rfc3339(start - 1),
                    "query.start_time_max": _rfc3339(end + 1),
                    "query.search_depth": depth,
                },
                missing_ok=True,
            )
        )

    def stop(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            _stack._kill(self.proc.pid)
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None
        _pid_file().unlink(missing_ok=True)


def pick_ports() -> tuple[int, int, int]:
    """(OTLP, UI, gRPC). The UI and gRPC searches overlap (16686.. and 16685..), so the gRPC port
    is moved above the UI port when both land on the same one."""
    try:
        otlp, ui, grpc = _stack.pick_port(4318), _stack.pick_port(16686), _stack.pick_port(16685)
        if grpc == ui:
            grpc = _stack.pick_port(ui + 1)
    except _stack.StackError as e:
        raise JaegerError(str(e)) from e
    return otlp, ui, grpc


def child_env() -> dict[str, str]:
    """The monitoring stack's key-free environment, without OTEL_* (exporter credentials)."""
    return {k: v for k, v in _stack.child_env().items() if not k.upper().startswith("OTEL_")}


def start(log: Log = print) -> Jaeger:
    """Start Jaeger for one run. Returns once its query API answers."""
    stop_leftovers(log)
    binary = ensure_binary(log)
    run = home() / "run"
    try:
        if run.exists():
            _stack._rmtree(run)
        run.mkdir(parents=True)
    except OSError as e:
        raise JaegerError(
            f"could not reset {run}: {e}. Run `python -m eval.observability down`."
        ) from e
    ports = pick_ports()
    jaeger = Jaeger(run, *ports)
    cfg = run / "jaeger.yaml"
    cfg.write_text(yaml.safe_dump(config(*ports), sort_keys=False), encoding="utf-8")
    log_path = run / "jaeger.log"
    # `file:` names the config provider; without it a Windows path's drive letter ("C:") would be
    # read as a provider name.
    jaeger.proc = _stack._spawn(
        [str(binary), f"--config=file:{cfg}"], cwd=run, env=child_env(), log_path=log_path
    )
    _pid_file().write_text(json.dumps({"jaeger": jaeger.proc.pid}), encoding="utf-8")
    try:
        _stack.wait_for(f"{jaeger.ui_url}/api/v3/services", "Jaeger", 120, jaeger.proc, log_path)
    except _stack.StackError as e:
        jaeger.stop()
        raise JaegerError(str(e)) from e
    except BaseException:  # Ctrl+C: Jaeger is in its own process group and would stay up
        jaeger.stop()
        raise
    log(f"Jaeger {VERSION} ready: UI {jaeger.ui_url}, OTLP {jaeger.otlp_endpoint}")
    return jaeger
