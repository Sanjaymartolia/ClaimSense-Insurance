FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
COPY config ./config
RUN pip install --no-cache-dir ".[agents,mcp]"
EXPOSE 8000
CMD ["uvicorn", "claimsense.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
