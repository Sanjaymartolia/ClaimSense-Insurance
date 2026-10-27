"""FastAPI service. Owner: Deploy & Ops. Streaming case endpoints come in T37."""

from fastapi import FastAPI
from prometheus_client import Counter, make_asgi_app

from claimsense import __version__

app = FastAPI(title="ClaimSense", version=__version__)
app.mount("/metrics", make_asgi_app())

CLAIMS_PROCESSED = Counter("claimsense_claims_processed_total", "Claims processed", ["outcome"])


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}
