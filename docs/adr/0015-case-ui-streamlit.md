# ADR-0015: The case UI is a Streamlit client of the case API

**Status:** proposed (review by Deploy & Ops)
**Owner / layers:** Deploy & Ops (`src/claimsense/ui/`, compose, CI); written by Eval & Red-Team in
Phase 3. L14, L16
**Date:** 2026-11-14

## Context
The capstone guide (pp. 9-10) puts a case UI in front of the claims adjudicator ("upload packet ·
stream worksheet") and demos three scenes through it: the proportional cut explained line by
line, the injected note and the duplicate bill flagged, and an edit that voids the earlier
approval. L16 adds a dashboard (edit rate, rupees deducted by reason, fraud flags, turnaround,
cost per claim) and Docker Compose. The case API (Phase 2) already streams runs and takes
decisions; `src/claimsense/ui/` was an empty package. The brief allows Streamlit, Chainlit or
Gradio.

## Options considered
- **A. Streamlit.** Tables, forms, metrics and charts are built in; per-session state holds two
  signed-in reviewers; `streamlit.testing.v1.AppTest` drives the screens from pytest. A second
  process (port 8501) and an optional extra.
- **B. Chainlit.** Built around a chat. The adjudicator's work is a worksheet table, line edits and
  a two-level approval, not a conversation.
- **C. Gradio.** Fits one-model demos; a multi-step case with two reviewers and a dashboard takes
  more custom state, and its pages are harder to test from pytest.
- **D. A static page served by FastAPI.** No new dependency, but the JavaScript (stream parsing,
  forms) would have no automated test without a browser test tool.

## Decision
- **A.** `python -m claimsense.ui` runs `src/claimsense/ui/app.py` on 127.0.0.1:8501 with usage
  statistics off. The UI calls the case API only (`ui/client.py`), server to server, so the
  browser never holds a reviewer token.
- What it shows is built by plain functions (`ui/views.py`) with their own tests. Every string
  from the API is shown as text or in a table, never as markdown: fraud flags quote the claim's
  documents (rule 2).
- The API gained `GET /me` (who a token is) and the run mode on `/health` (`llm`, `tools`).
- Docker: `Dockerfile.ui` (core dependencies and Streamlit only) and a `ui` service in compose.
  The compose file now runs the agents in stub mode unless `CLAIMSENSE_LLM` says otherwise, takes
  reviewers from the environment, keeps checkpoints on a volume and publishes ports on 127.0.0.1;
  `.dockerignore` keeps `.env` and the course notebooks (real keys) out of every build.
- CI: the `test` job installs `.[ui]` and runs `tests/ui`; a new `compose` job builds both images,
  starts them healthy, serves a demo claim through the API container, and calls the API from the
  UI container.

## Consequences
- Tests drive the three demo scenes, the four-eyes refusal and the dashboard through AppTest
  against the API app in memory (stub agents, no model call); a live smoke runs the same over
  real HTTP.
- Two processes to run instead of one; `.[ui]` adds Streamlit and its dependencies (pandas,
  pyarrow), installed only where the UI runs.
- Approvals given on an earlier worksheet are shown void from what the session saw; the API's
  audit trail keeps the record either way.
- Open, for Deploy & Ops: Grafana provisioning and the edit-rate alert (`monitoring/`), real sign-in
  instead of static tokens, and the MCP servers as compose services over HTTP (ADR-0012).

## Links
`src/claimsense/ui/README.md` (run and demo script), `src/claimsense/api/README.md`,
`tests/ui/`, `docker-compose.yml`, `Dockerfile.ui`, `.github/workflows/ci.yml`.
