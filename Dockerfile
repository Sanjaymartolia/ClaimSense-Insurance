FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
COPY config ./config
# The synthetic claims behind /demo/claims (dev and red-team only, never the held-out set).
COPY eval/golden_dev/claims.jsonl eval/golden_dev/claims.jsonl
COPY eval/redteam/claims.jsonl eval/redteam/claims.jsonl
# observability: tracing works when .env sets CLAIMSENSE_OTEL=otlp and OTEL_EXPORTER_OTLP_ENDPOINT
RUN pip install --no-cache-dir ".[agents,mcp,observability]"
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"
CMD ["uvicorn", "claimsense.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
