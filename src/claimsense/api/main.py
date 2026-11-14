"""FastAPI service (Deploy & Ops, L16): health, Prometheus metrics and the claim cases.

Endpoints, stream events, settings and examples: `src/claimsense/api/README.md`.
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import AsyncIterator

from fastapi import FastAPI
from prometheus_client import make_asgi_app

from claimsense import __version__

from .cases import router
from .runner import CaseService, Settings


@contextlib.asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """With MCP tools the servers start before any request: policy-kb takes minutes to open its
    index. On shutdown every server process is stopped."""
    if app.state.settings.tools == "mcp":
        app.state.cases = CaseService(app.state.settings)
    yield
    if app.state.cases is not None:
        app.state.cases.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    """The app for these settings (default: from the environment). With stub or real tools the
    case service starts on the first case request, so `/health` and `/metrics/` work without the
    `agents` extra."""
    app = FastAPI(title="ClaimSense", version=__version__, lifespan=_lifespan)
    app.state.settings = settings or Settings.from_env()
    app.state.cases = None
    app.state.cases_lock = threading.Lock()
    app.mount("/metrics", make_asgi_app())
    app.include_router(router)

    @app.get("/health")
    def health() -> dict[str, str]:
        """Up, and how claims run: agents `stub` or `real` models, tools stub, real or mcp."""
        return {
            "status": "ok",
            "version": __version__,
            "llm": _llm_mode(),
            "tools": app.state.settings.tools,
        }

    return app


def _llm_mode() -> str:
    try:
        from claimsense.agents.llm import stub_mode
    except ImportError:  # no .[agents]: the case routes answer 503 anyway
        return "unavailable"
    return "stub" if stub_mode() else "real"


app = create_app()
